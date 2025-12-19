"""
=====================================================
ZEUS - Python Executor Tool
Executa código Python em container Docker isolado
=====================================================
"""

from typing import Dict, Any
import docker
import tempfile
import os
import uuid

from .base import BaseTool, ToolParameter
from .docker_helper import get_docker_client
from config import get_settings, get_logger

logger = get_logger(__name__)
settings = get_settings()


class PythonExecutorTool(BaseTool):
    """
    Executa código Python em um container Docker isolado.
    
    Cria um container efêmero, executa o código e retorna o resultado.
    O container é automaticamente removido após a execução.
    """
    
    name = "execute_python"
    description = """Executa código Python em um ambiente isolado e seguro.
Use para: cálculos matemáticos, processamento de dados, manipulação de arquivos,
automações, e qualquer tarefa que requeira programação Python.
Bibliotecas disponíveis: numpy, pandas, requests, pillow, beautifulsoup4, matplotlib, scipy."""
    
    parameters = [
        ToolParameter(
            name="code",
            type="string",
            description="Código Python a ser executado. Use print() para exibir resultados."
        ),
        ToolParameter(
            name="timeout",
            type="integer",
            description="Tempo máximo de execução em segundos (padrão: 60)",
            required=False
        )
    ]
    
    @property
    def docker_client(self):
        """Obtém cliente Docker sob demanda"""
        return get_docker_client()
    
    async def execute(self, code: str, timeout: int = 60, **kwargs) -> Dict[str, Any]:
        """
        Executa código Python em container isolado.
        
        Args:
            code: Código Python a executar
            timeout: Timeout em segundos
            kwargs: Argumentos extras (websocket)
            
        Returns:
            Resultado da execução
        """
        websocket = kwargs.get('websocket')
        
        if not self.docker_client:
            return self._error("Docker não disponível")
        
        # Limitar timeout ao máximo configurado
        timeout = min(timeout, settings.max_execution_time)
        
        logger.info(
            "Executando Python",
            code_length=len(code),
            timeout=timeout
        )
        
        try:
            # Nome único para o container
            container_name = f"zeus-python-{uuid.uuid4().hex[:8]}"
            
            # Tentar usar imagem sandbox otimizada, fallback para python:3.11-slim
            image = "python:3.11-slim"
            
            # 1. Iniciar container
            container = self.docker_client.containers.run(
                image=image,
                command="tail -f /dev/null", 
                name=container_name,
                working_dir="/code",
                mem_limit=f"{settings.max_memory_mb}m",
                network_disabled=False,
                detach=True,
                remove=True
            )
            
            try:
                # 2. Injetar código
                encoded_code = code.encode('utf-8').hex()
                setup_cmd = f"/bin/bash -c 'if ! command -v xxd &> /dev/null; then apt-get update && apt-get install -y xxd; fi; echo {encoded_code} | xxd -r -p > /code/script.py'"
                container.exec_run(setup_cmd)
                
                # REFATORANDO para rodar stream em thread para não bloquear loop e permitir websocket send
                
                return await self._run_with_streaming(container, websocket)
                    
            finally:
                # Parar container (auto-remove fará a limpeza)
                try:
                    container.stop()
                except:
                    pass
        
        except Exception as e:
            logger.error("Erro ao executar Python", error=str(e))
            return self._error(f"Erro interno: {str(e)}")

    async def _run_with_streaming(self, container, websocket):
        """Executa script e faz streaming do output em background"""
        import asyncio
        import threading
        
        output_buffer = []
        
        def stream_generator():
            # Executa comando unbuffered
            return container.exec_run("python -u /code/script.py", stream=True, demux=True)

        # Rodar generator em thread para não bloquear o async loop
        # Iterar sobre o generator é bloqueante IO
        
        q = asyncio.Queue()
        
        def producer():
            try:
                gen = stream_generator()
                for stdout, stderr in gen:
                    chunk = ""
                    is_err = False
                    if stdout: chunk = stdout.decode('utf-8', errors='replace')
                    if stderr: 
                        chunk = stderr.decode('utf-8', errors='replace')
                        is_err = True
                    if chunk:
                        # Colocar na queue thread-safe
                        asyncio.run_coroutine_threadsafe(q.put((chunk, is_err)), loop)
            except Exception as e:
                asyncio.run_coroutine_threadsafe(q.put(None), loop) # Sinal de fim
            finally:
                asyncio.run_coroutine_threadsafe(q.put(None), loop)

        loop = asyncio.get_running_loop()
        t = threading.Thread(target=producer, daemon=True)
        t.start()
        
        # Consumir fila
        while True:
            item = await q.get()
            if item is None:
                break
            
            chunk, is_err = item
            output_buffer.append(chunk)
            
            if websocket:
                try:
                    await websocket.send_json({
                        "type": "tool_log",
                        "tool": "execute_python",
                        "output": chunk,
                        "is_error": is_err
                    })
                except:
                    pass
        
        full_output = "".join(output_buffer)
        return self._success(full_output)

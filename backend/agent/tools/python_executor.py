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
import asyncio

from .base import BaseTool, ToolParameter
from .docker_helper import get_docker_client
from config import get_settings, get_logger
from agent.container_session_manager import ContainerSessionManager

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
        ),
        ToolParameter(
            name="session_id",
            type="string",
            description="ID da sessão atual (injetado automaticamente)",
            required=False
        )
    ]
    
    @property
    def docker_client(self):
        """Obtém cliente Docker sob demanda"""
        return get_docker_client()
    
    async def execute(self, code: str, timeout: int = 60, session_id: str = None, **kwargs) -> Dict[str, Any]:
        """
        Executa código Python em container isolado (persistente por sessão).
        
        Args:
            code: Código Python a executar
            timeout: Timeout em segundos
            session_id: ID da sessão
            kwargs: Argumentos extras (websocket)
            
        Returns:
            Resultado da execução
        """
        websocket = kwargs.get('websocket')
        
        if not session_id:
             session_id = kwargs.get('session_id')
        
        if not session_id:
             # Fallback para execução sem sessão (cria container novo se não houver ID?)
             # Melhor exigir ID ou gerar um temporário
             session_id = "temp-" + uuid.uuid4().hex[:8]
        
        if not self.docker_client:
            return self._error("Docker não disponível")
        
        # Limitar timeout ao máximo configurado
        timeout = min(timeout, settings.max_execution_time)
        
        logger.info(
            "Executando Python",
            code_length=len(code),
            timeout=timeout,
            session_id=session_id
        )
        
        try:
            # Obter container da sessão (inicia se parado, cria se não existe)
            container = ContainerSessionManager.get_or_create_container(session_id)
            if not container:
                return self._error("Falha ao obter container de execução")

            # Nome único para o script
            script_name = f"script_{uuid.uuid4().hex[:8]}.py"
            
            # Preparar o script no container
            # Usando xxd como no ContainerSessionManager
            encoded_code = code.encode('utf-8').hex()
            setup_cmd = f"/bin/bash -c 'if ! command -v xxd &> /dev/null; then apt-get update && apt-get install -y xxd; fi; echo {encoded_code} | xxd -r -p > /app/data/{script_name}'"
            
            exit_code, out = container.exec_run(setup_cmd)
            if exit_code != 0:
                return self._error(f"Erro ao preparar ambiente: {out.decode('utf-8')}")

            try:
                # Executar com streaming
                # O script está em /app/data/{script_name}
                # O workdir do container de sessão é /app/data                
                return await self._run_with_streaming(container, script_name, websocket, timeout)
                    
            finally:
                # Limpar script
                try:
                    container.exec_run(f"rm /app/data/{script_name}")
                except:
                    pass
        
        except Exception as e:
            logger.error("Erro ao executar Python", error=str(e))
            return self._error(f"Erro interno: {str(e)}")

    async def _run_with_streaming(self, container, script_name, websocket, timeout):
        """Executa script e faz streaming do output em background"""
        import threading
        
        output_buffer = []
        
        # Generator original do docker-py
        def stream_generator():
            # Executa python unbuffered
            # Usamos exec_run com stream=True
            return container.exec_run(f"python3 /app/data/{script_name}", stream=True, demux=True)

        # Queue para comunicação thread -> async
        q = asyncio.Queue()
        
        def producer():
            try:
                # Executa
                gen = stream_generator()
                for stdout, stderr in gen:
                    chunk = ""
                    is_err = False
                    if stdout: chunk = stdout.decode('utf-8', errors='replace')
                    if stderr: 
                        chunk = stderr.decode('utf-8', errors='replace')
                        is_err = True
                    if chunk:
                        asyncio.run_coroutine_threadsafe(q.put((chunk, is_err)), loop)
            except Exception as e:
                pass # Erro no stream
            finally:
                asyncio.run_coroutine_threadsafe(q.put(None), loop)

        loop = asyncio.get_running_loop()
        t = threading.Thread(target=producer, daemon=True)
        t.start()
        
        # Consumir fila com timeout
        try:
            start_time = asyncio.get_event_loop().time()
            while True:
                # Verificar timeout
                if (asyncio.get_event_loop().time() - start_time) > timeout:
                    output_buffer.append("\n[Tempo limite de execução excedido]")
                    break
                
                try:
                    # Wait for item com timeout curto para checar loop timeout
                    item = await asyncio.wait_for(q.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                
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
        except Exception as e:
            output_buffer.append(f"\n[Erro na leitura de saída: {str(e)}]")
        
        full_output = "".join(output_buffer)
        return self._success(full_output)


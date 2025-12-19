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
            
        Returns:
            Resultado da execução
        """
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
            image = "zeus-sandbox-python:latest"
            try:
                self.docker_client.images.get(image)
            except:
                image = "python:3.11-slim"
                logger.info("Usando imagem fallback", image=image)
            
            # Executar container sem montar volume, passando código via stdin
            
            # 1. Criar container mantendo-o rodando (tail -f /dev/null)
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
                # 2. Escrever o código em um arquivo dentro do container
                # Usamos xxd para evitar problemas de escaping de bash com aspas/quebras de linha
                # Encode para hex no Python -> echo hex | xxd -r -p > script.py no container
                encoded_code = code.encode('utf-8').hex()
                
                # Install xxd if not present (python slim might not have it, but we can try pure bash fallback if needed)
                # Fallback simples usando printf se xxd falhar (menos robusto para binários, mas ok para texto)
                setup_cmd = f"/bin/bash -c 'if ! command -v xxd &> /dev/null; then apt-get update && apt-get install -y xxd; fi; echo {encoded_code} | xxd -r -p > /code/script.py'"
                
                # Executar comando de setup (pode demorar um pouco se instalar xxd)
                container.exec_run(setup_cmd)
                
                # 3. Executar o script Python
                result = container.exec_run("python /code/script.py")
                
                # 4. Capturar output
                output = result.output.decode('utf-8')
                
                logger.info(
                    "Python executado com sucesso",
                    output_length=len(output)
                )
                
                return self._success(output)
                    
            finally:
                # Parar container (auto-remove fará a limpeza)
                try:
                    container.stop()
                except:
                    pass

                

        
        except Exception as e:
            logger.error("Erro ao executar Python", error=str(e))
            return self._error(f"Erro interno: {str(e)}")

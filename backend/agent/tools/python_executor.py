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
            # Criar arquivo temporário com o código
            with tempfile.NamedTemporaryFile(
                mode='w',
                suffix='.py',
                delete=False,
                encoding='utf-8'
            ) as f:
                f.write(code)
                temp_file = f.name
            
            # Nome único para o container
            container_name = f"zeus-python-{uuid.uuid4().hex[:8]}"
            
            # Diretório temporário para compartilhar
            temp_dir = os.path.dirname(temp_file)
            
            # Tentar usar imagem sandbox otimizada, fallback para python:3.11-slim
            image = "zeus-sandbox-python:latest"
            try:
                self.docker_client.images.get(image)
            except:
                image = "python:3.11-slim"
                logger.info("Usando imagem fallback", image=image)
            
            # Executar container
            try:
                container = self.docker_client.containers.run(
                    image=image,
                    command=f"python /code/{os.path.basename(temp_file)}",
                    name=container_name,
                    volumes={
                        temp_dir: {'bind': '/code', 'mode': 'ro'}
                    },
                    working_dir="/code",
                    mem_limit=f"{settings.max_memory_mb}m",
                    network_disabled=False,  # Rede habilitada para downloads
                    remove=True,  # Auto-remove após execução
                    detach=False,  # Aguardar conclusão
                    stdout=True,
                    stderr=True
                )
                
                # Decodificar output
                output = container.decode('utf-8') if isinstance(container, bytes) else str(container)
                
                logger.info(
                    "Python executado com sucesso",
                    output_length=len(output)
                )
                
                return self._success(output)
                
            except docker.errors.ContainerError as e:
                # Container retornou erro (código Python falhou)
                stderr = e.stderr.decode('utf-8') if e.stderr else str(e)
                logger.warning("Python retornou erro", error=stderr)
                return self._error(f"Erro na execução:\n{stderr}")
                
            except docker.errors.ImageNotFound:
                # Imagem não existe - tentar pull
                logger.info("Baixando imagem python:3.11-slim")
                self.docker_client.images.pull("python:3.11-slim")
                return self._error("Imagem Python baixada. Tente novamente.")
                
            finally:
                # Limpar arquivo temporário
                try:
                    os.unlink(temp_file)
                except:
                    pass
        
        except Exception as e:
            logger.error("Erro ao executar Python", error=str(e))
            return self._error(f"Erro interno: {str(e)}")

"""
=====================================================
ZEUS - Container Session Manager
Gerencia containers Docker efêmeros por sessão
=====================================================
"""

import docker
import asyncio
from typing import Optional
from config import get_settings, get_logger
from agent.tools.docker_helper import get_docker_client

logger = get_logger(__name__)
settings = get_settings()

class ContainerSessionManager:
    """
    Gerencia o ciclo de vida de containers isolados por sessão.
    Cria containers sob demanda e os remove quando solicitados.
    """
    
    IMAGE_NAME = "python:3.11" # Imagem base
    @classmethod
    def get_container_name(cls, session_id: str) -> str:
        from datetime import datetime
        date_str = datetime.now().strftime("%d-%m-%Y")
        return f"{date_str}-{session_id}"

    @classmethod
    def get_or_create_container(cls, session_id: str) -> Optional[docker.models.containers.Container]:
        """
        Obtém um container existente para a sessão ou cria um novo.
        """
        client = get_docker_client()
        if not client:
            logger.error("Docker client não disponível")
            return None
            
        container_name = cls.get_container_name(session_id)
        
        try:
            # Tentar obter existente
            container = client.containers.get(container_name)
            if container.status != 'running':
                logger.info("Container da sessão parado, iniciando...", session_id=session_id)
                container.start()
            return container
        except docker.errors.NotFound:
            # Criar novo
            logger.info("Criando novo container para sessão", session_id=session_id)
            try:
                # Montar volume de dados para persistência durante a sessão
                # Montamos o diretório de dados do host para o container ter acesso aos arquivos
                # IMPORTANTE: Isso dá acesso aos arquivos do usuário, mas isola a execução do processo system host
                volumes = {
                    settings.data_dir: {'bind': '/app/data', 'mode': 'rw'}
                }
                
                container = client.containers.run(
                    image=cls.IMAGE_NAME,
                    name=container_name,
                    command="tail -f /dev/null", # Manter rodando
                    detach=True,
                    volumes=volumes,
                    working_dir="/app/data",
                    restart_policy={"Name": "no"}, # Não reiniciar automaticamente
                    network_mode="bridge" # Rede padrão
                )
                logger.info("Container criado com sucesso", id=container.short_id)
                return container
            except Exception as e:
                logger.error("Erro ao criar container de sessão", error=str(e))
                raise e
        except Exception as e:
            logger.error("Erro ao obter container de sessão", error=str(e))
            raise e

    @classmethod
    def cleanup_container(cls, session_id: str):
        """
        Remove o container da sessão (kill & remove).
        """
        client = get_docker_client()
        if not client:
            return

        container_name = cls.get_container_name(session_id)
        
        try:
            container = client.containers.get(container_name)
            logger.info("Removendo container de sessão", session_id=session_id)
            container.remove(force=True)
            logger.info("Container removido")
        except docker.errors.NotFound:
            pass # Já removido
        except Exception as e:
            logger.error("Erro ao limpar container de sessão", error=str(e))

    @classmethod
    async def execute_command(cls, session_id: str, command: str, timeout: int = 30) -> tuple[int, str, str]:
        """
        Executa comando no container da sessão.
        Retorna (exit_code, stdout, stderr)
        """
        container = cls.get_or_create_container(session_id)
        if not container:
            raise Exception("Não foi possível obter container para execução")

        # Usar exec_run do docker SDK
        # Nota: exec_run não suporta timeout nativo facilmente de forma async sem bloquear, 
        # mas vamos envolver em asyncio.to_thread
        
        try:
            # exec_run retorna (exit_code, output) onde output é bytes combinados ou tupla se demux=True
            # Para separar stdout/stderr, usamos demux=True
            
            def _run():
                return container.exec_run(
                    cmd=f"bash -c {shlex.quote(command)}", 
                    demux=True,
                    workdir="/app/data"
                )
            
            import shlex
            
            # Executar em thread para não bloquear loop
            exec_result = await asyncio.to_thread(_run)
            
            exit_code = exec_result.exit_code
            stdout_bytes, stderr_bytes = exec_result.output
            
            stdout_str = stdout_bytes.decode('utf-8', errors='replace') if stdout_bytes else ""
            stderr_str = stderr_bytes.decode('utf-8', errors='replace') if stderr_bytes else ""
            
            return exit_code, stdout_str, stderr_str
            
        except Exception as e:
            logger.error("Erro na execução do comando docker", error=str(e))
            raise e

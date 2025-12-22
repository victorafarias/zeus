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
    
    IMAGE_NAME = "zeus-sandbox:latest" # Imagem customizada com dependências

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
                # IMPORTANTE: Usar HOST_DATA_DIR (caminho real no host da VPS)
                # e não settings.data_dir (que é /app/data, interno ao container principal)
                # Isso garante que arquivos baixados no sandbox persistam no host
                import os
                host_data_dir = os.environ.get('HOST_DATA_DIR', settings.data_dir)
                
                # Se for caminho relativo (./data), converter para absoluto baseado no diretório do compose
                # Na VPS, isso seria algo como /root/zeus/data
                if host_data_dir.startswith('./') or host_data_dir.startswith('.\\'):
                    # Assumimos que o compose roda em /root/zeus ou similar
                    # Precisamos do caminho absoluto do host
                    compose_dir = os.environ.get('COMPOSE_PROJECT_DIR', '/root/zeus')
                    host_data_dir = os.path.join(compose_dir, host_data_dir[2:])
                    
                logger.info("Montando volume de dados", host_path=host_data_dir, container_path='/app/data')
                
                # Montar volume de dados para persistência durante a sessão
                volumes = {
                    host_data_dir: {'bind': '/app/data', 'mode': 'rw'}
                }
                
                # Verificar se a imagem existe, se não, construir
                try:
                    client.images.get(cls.IMAGE_NAME)
                except docker.errors.ImageNotFound:
                    logger.info(f"Imagem {cls.IMAGE_NAME} não encontrada. Iniciando build...")
                    try:
                        # Build usando SDK
                        # Contexto é a raiz do projeto (onde o app roda, backend ou root?)
                        # Assumindo que Dockerfile.sandbox está em ./docker/Dockerfile.sandbox relativo ao working dir
                        import os
                        dockerfile_path = os.path.join("docker", "Dockerfile.sandbox")
                        
                        # Se não achar o arquivo, tenta ajustar path (se rodando de dentro de backend/)
                        if not os.path.exists(dockerfile_path) and os.path.exists(os.path.join("..", "docker", "Dockerfile.sandbox")):
                             dockerfile_path = os.path.join("..", "docker", "Dockerfile.sandbox")
                             build_context = ".."
                        else:
                             build_context = "."
                             
                        logger.info(f"Construindo imagem a partir de {dockerfile_path} context context {build_context}")
                        
                        image, build_logs = client.images.build(
                            path=build_context,
                            dockerfile=dockerfile_path,
                            tag=cls.IMAGE_NAME,
                            rm=True
                        )
                        for chunk in build_logs:
                            if 'stream' in chunk:
                                logger.debug(chunk['stream'].strip())
                                
                        logger.info(f"Imagem {cls.IMAGE_NAME} construída com sucesso!")
                        
                    except Exception as build_err:
                        logger.error(f"Erro ao buildar imagem: {build_err}")
                        logger.warning("Tentando usar python:3.11-slim como fallback...")
                        # Fallback se build falhar
                        cls.IMAGE_NAME = "python:3.11-slim"
                
                container = client.containers.run(
                    image=cls.IMAGE_NAME,
                    name=container_name,
                    command="tail -f /dev/null", # Manter rodando
                    detach=True,
                    volumes=volumes,
                    working_dir="/app/data",
                    restart_policy={"Name": "no"}, # Não reiniciar automaticamente
                    network_mode="bridge",
                    # Importante: aumentar shm_size para multiprocessamento (whisper/pl)
                    shm_size="512m" 
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
        
        try:
            import shlex
            
            def _run():
                return container.exec_run(
                    cmd=f"bash -c {shlex.quote(command)}", 
                    demux=True,
                    workdir="/app/data"
                )
            
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

    @classmethod
    async def execute_python_in_container(cls, session_id: str, code: str, timeout: int = 60) -> tuple[bool, str]:
        """
        Executa código Python dentro do container persistente da sessão.
        
        Args:
            session_id: ID da sessão
            code: Código Python a executar
            timeout: Tempo limite
            
        Returns:
            (success, output)
        """
        container = cls.get_or_create_container(session_id)
        if not container:
            return False, "Docker não disponível ou erro ao criar container"

        try:
            # Criar arquivo script temporário dentro do container via echo/bash
            # Usando xxd para evitar problemas com aspas e escapes complexos
            encoded_code = code.encode('utf-8').hex()
            
            # Comando para decodificar e salvar script.py
            # Nota: usamos um nome aleatório para evitar colisão se rodar paralelo (embora session seja serial geralmente)
            import uuid
            script_name = f"script_{uuid.uuid4().hex[:8]}.py"
            setup_cmd = f"/bin/bash -c 'echo {encoded_code} | xxd -r -p > /attr/data/{script_name}'"
            
            # ATENÇÃO: working_dir é /app/data, e volume montado também.
            # Vamos salvar direto lá.
            setup_cmd = f"/bin/bash -c 'if ! command -v xxd &> /dev/null; then apt-get update && apt-get install -y xxd; fi; echo {encoded_code} | xxd -r -p > {script_name}'"
            
            # Executar setup (criação do arquivo)
            exit_code, out, err = await cls.execute_command(session_id, setup_cmd, timeout=10)
            if exit_code != 0:
                return False, f"Erro ao preparar script: {err}"
            
            # Executar python
            run_cmd = f"python3 {script_name}"
            exit_code, stdout, stderr = await cls.execute_command(session_id, run_cmd, timeout=timeout)
            
            # Limpar script
            await cls.execute_command(session_id, f"rm {script_name}")
            
            output = stdout
            if stderr:
                output += f"\n[STDERR]\n{stderr}"
            
            if exit_code != 0:
                return False, f"Erro na execução (Exit Code {exit_code}):\n{output}"
                
            return True, output

        except Exception as e:
            return False, f"Erro interno ao executar Python: {str(e)}"


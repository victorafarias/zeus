"""
=====================================================
ZEUS - Docker Helper
Utilitários para conexão Docker cross-platform
=====================================================
"""

import docker
from config import get_logger

logger = get_logger(__name__)

# Cliente Docker singleton
_docker_client = None


def get_docker_client():
    """
    Retorna cliente Docker com suporte cross-platform.
    
    Tenta múltiplos métodos de conexão:
    1. Variável de ambiente DOCKER_HOST (padrão)
    2. Unix socket (Linux/macOS)
    3. Named pipe (Windows)
    
    Returns:
        docker.DockerClient ou None se não disponível
    """
    global _docker_client
    
    if _docker_client is not None:
        try:
            _docker_client.ping()
            return _docker_client
        except:
            _docker_client = None
    
    # Tentar conexão padrão (usa DOCKER_HOST ou socket padrão)
    try:
        client = docker.from_env()
        client.ping()
        logger.info("Docker conectado via ambiente")
        _docker_client = client
        return client
    except Exception as e:
        logger.debug("Conexão padrão falhou", error=str(e))
    
    # Tentar named pipe do Windows
    try:
        client = docker.DockerClient(base_url='npipe:////./pipe/docker_engine')
        client.ping()
        logger.info("Docker conectado via named pipe (Windows)")
        _docker_client = client
        return client
    except Exception as e:
        logger.debug("Named pipe falhou", error=str(e))
    
    # Tentar TCP localhost (Docker Toolbox ou WSL2)
    try:
        client = docker.DockerClient(base_url='tcp://localhost:2375')
        client.ping()
        logger.info("Docker conectado via TCP localhost")
        _docker_client = client
        return client
    except Exception as e:
        logger.debug("TCP localhost falhou", error=str(e))
    
    # Tentar unix socket explícito
    try:
        client = docker.DockerClient(base_url='unix:///var/run/docker.sock')
        client.ping()
        logger.info("Docker conectado via unix socket")
        _docker_client = client
        return client
    except Exception as e:
        logger.debug("Unix socket falhou", error=str(e))
    
    logger.error("Não foi possível conectar ao Docker")
    return None


def is_docker_available() -> bool:
    """Verifica se Docker está disponível"""
    client = get_docker_client()
    return client is not None

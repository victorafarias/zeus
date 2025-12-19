"""
=====================================================
ZEUS - Configurações do Sistema
Carrega variáveis de ambiente e define configurações
=====================================================
"""

import os
from pydantic_settings import BaseSettings
from functools import lru_cache
import structlog
import logging

# Configurar nível de log do Python padrão
logging.basicConfig(
    format="%(message)s",
    level=logging.INFO,  # Mudar para DEBUG para mais detalhes
)

# Configurar logging estruturado
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.dev.ConsoleRenderer()
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)


class Settings(BaseSettings):
    """
    Configurações do sistema Zeus.
    Valores são carregados do arquivo .env ou variáveis de ambiente.
    """
    
    # -------------------------------------------------
    # OpenRouter API
    # -------------------------------------------------
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    
    # -------------------------------------------------
    # Autenticação
    # -------------------------------------------------
    auth_username: str = "victor"
    auth_password: str = "V!ct0rf@"
    secret_key: str = "development-secret-key-change-in-production"
    
    # Configurações JWT
    jwt_algorithm: str = "HS256"
    jwt_expire_hours: int = 24
    
    # -------------------------------------------------
    # Ambiente
    # -------------------------------------------------
    environment: str = "development"
    
    # -------------------------------------------------
    # Execução de Código
    # -------------------------------------------------
    max_execution_time: int = 300  # segundos
    max_memory_mb: int = 512       # MB
    
    # -------------------------------------------------
    # Caminhos
    # -------------------------------------------------
    data_dir: str = "/app/data"
    uploads_dir: str = "/app/data/uploads"
    outputs_dir: str = "/app/data/outputs"
    conversations_dir: str = "/app/data/conversations"
    chromadb_dir: str = "/app/data/chromadb"
    
    class Config:
        """Configuração do Pydantic para carregar do .env"""
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


@lru_cache()
def get_settings() -> Settings:
    """
    Retorna instância cacheada das configurações.
    O cache evita recarregar o .env a cada requisição.
    """
    return Settings()


def get_logger(name: str):
    """
    Retorna um logger estruturado para o módulo especificado.
    
    Uso:
        logger = get_logger(__name__)
        logger.info("Mensagem", variavel="valor")
    """
    return structlog.get_logger(name)

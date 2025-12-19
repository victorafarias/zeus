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
    # OpenRouter API (usado como fallback ou para tarefas complexas)
    # -------------------------------------------------
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    
    # -------------------------------------------------
    # Modelos de IA (via OpenRouter)
    # -------------------------------------------------
    
    # Modelo Primário: Google Gemma 3 27B (3 minutos timeout)
    primary_model: str = "openai/gpt-5-nano"
    primary_model_timeout: int = 180  # segundos (3 minutos)
    
    # Modelo Secundário: OpenAI GPT-4o-mini (5 minutos timeout)
    # Fallback caso o primário falhe
    secondary_model: str = "openai/gpt-4.1-nano"
    secondary_model_timeout: int = 300  # segundos (5 minutos)
    
    # -------------------------------------------------
    # Autenticação (valores devem vir do .env)
    # -------------------------------------------------
    auth_username: str = ""
    auth_password: str = ""
    secret_key: str = ""
    
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

"""
=====================================================
ZEUS - API de Modelos OpenRouter
Endpoints para listar modelos disponíveis
=====================================================
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
import httpx

from config import get_settings, get_logger
from api.auth import get_current_user, UserInfo

# -------------------------------------------------
# Configuração
# -------------------------------------------------
router = APIRouter()
logger = get_logger(__name__)
settings = get_settings()


# -------------------------------------------------
# Modelos Pydantic
# -------------------------------------------------
class ModelPricing(BaseModel):
    """Informações de preço do modelo"""
    prompt: str        # Preço por token de entrada (string com valor)
    completion: str    # Preço por token de saída


class ModelInfo(BaseModel):
    """Informações de um modelo"""
    id: str                           # ID do modelo (ex: openai/gpt-4)
    name: str                         # Nome legível
    description: Optional[str] = None
    context_length: int               # Tamanho do contexto em tokens
    pricing: Optional[ModelPricing] = None
    supports_tools: bool = False      # Suporta function calling


class ModelsResponse(BaseModel):
    """Resposta da listagem de modelos"""
    models: List[ModelInfo]
    total: int


# -------------------------------------------------
# Cache de modelos
# -------------------------------------------------
_models_cache: List[ModelInfo] = []
_cache_timestamp: float = 0
CACHE_TTL = 300  # 5 minutos


# -------------------------------------------------
# Funções auxiliares
# -------------------------------------------------
async def fetch_openrouter_models() -> List[ModelInfo]:
    """
    Busca lista de modelos da API OpenRouter.
    
    Retorna apenas modelos que suportam function calling (tools).
    """
    global _models_cache, _cache_timestamp
    import time
    
    # Verificar cache
    current_time = time.time()
    if _models_cache and (current_time - _cache_timestamp) < CACHE_TTL:
        logger.debug("Retornando modelos do cache")
        return _models_cache
    
    logger.info("Buscando modelos do OpenRouter")
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://openrouter.ai/api/v1/models",
                headers={
                    "Authorization": f"Bearer {settings.openrouter_api_key}",
                    "HTTP-Referer": "https://zeus.ovictorfarias.com.br",
                    "X-Title": "Zeus AI Agent"
                },
                timeout=30.0
            )
            
            if response.status_code != 200:
                logger.error(
                    "Erro ao buscar modelos",
                    status_code=response.status_code,
                    response=response.text[:200]
                )
                raise HTTPException(
                    status_code=502,
                    detail="Erro ao comunicar com OpenRouter"
                )
            
            data = response.json()
            models_data = data.get("data", [])
            
            # Processar e filtrar modelos
            models: List[ModelInfo] = []
            
            for m in models_data:
                # Verificar se suporta tools (function calling)
                supported_params = m.get("supported_parameters", [])
                supports_tools = "tools" in supported_params
                
                # Extrair preços
                pricing = None
                if m.get("pricing"):
                    pricing = ModelPricing(
                        prompt=m["pricing"].get("prompt", "0"),
                        completion=m["pricing"].get("completion", "0")
                    )
                
                model_info = ModelInfo(
                    id=m.get("id", ""),
                    name=m.get("name", m.get("id", "")),
                    description=m.get("description"),
                    context_length=m.get("context_length", 4096),
                    pricing=pricing,
                    supports_tools=supports_tools
                )
                
                models.append(model_info)
            
            # Ordenar: modelos com tools primeiro, depois por nome
            models.sort(key=lambda x: (not x.supports_tools, x.name))
            
            # Atualizar cache
            _models_cache = models
            _cache_timestamp = current_time
            
            logger.info(
                "Modelos carregados",
                total=len(models),
                with_tools=sum(1 for m in models if m.supports_tools)
            )
            
            return models
            
    except httpx.RequestError as e:
        logger.error("Erro de conexão com OpenRouter", error=str(e))
        raise HTTPException(
            status_code=502,
            detail="Não foi possível conectar ao OpenRouter"
        )


# -------------------------------------------------
# Endpoints
# -------------------------------------------------
@router.get("", response_model=ModelsResponse)
async def list_models(
    tools_only: bool = True,
    user: UserInfo = Depends(get_current_user)
):
    """
    Lista modelos disponíveis no OpenRouter.
    
    Args:
        tools_only: Se True, retorna apenas modelos com suporte a tools
    """
    logger.info(
        "Listando modelos",
        username=user.username,
        tools_only=tools_only
    )
    
    models = await fetch_openrouter_models()
    
    # Filtrar por suporte a tools se solicitado
    if tools_only:
        models = [m for m in models if m.supports_tools]
    
    return ModelsResponse(
        models=models,
        total=len(models)
    )


@router.get("/{model_id:path}", response_model=ModelInfo)
async def get_model(
    model_id: str,
    user: UserInfo = Depends(get_current_user)
):
    """
    Retorna informações de um modelo específico.
    
    Args:
        model_id: ID do modelo (ex: openai/gpt-4)
    """
    models = await fetch_openrouter_models()
    
    for model in models:
        if model.id == model_id:
            return model
    
    raise HTTPException(
        status_code=404,
        detail=f"Modelo não encontrado: {model_id}"
    )

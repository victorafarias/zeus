"""
=====================================================
ZEUS - API de Conversas
CRUD para gerenciar conversas do chat
=====================================================
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
import uuid
import json
import os

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
class Message(BaseModel):
    """Uma mensagem do chat"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: str  # "user", "assistant", "system"
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    # Campos opcionais para tool calls
    tool_calls: Optional[List[dict]] = None
    tool_call_id: Optional[str] = None
    
    # Arquivos anexados à mensagem (lista de IDs de arquivos)
    attached_files: Optional[List[str]] = None


class Conversation(BaseModel):
    """Uma conversa completa"""
    # Configuração para permitir campo model_id sem conflito
    model_config = {"protected_namespaces": ()}
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str = "Nova Conversa"
    model_id: str = "openai/gpt-4"
    messages: List[Message] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    

class ConversationSummary(BaseModel):
    """Resumo de uma conversa para listagem"""
    model_config = {"protected_namespaces": ()}
    
    id: str
    title: str
    model_id: str
    message_count: int
    created_at: datetime
    updated_at: datetime


class CreateConversationRequest(BaseModel):
    """Dados para criar nova conversa"""
    model_config = {"protected_namespaces": ()}
    
    title: Optional[str] = "Nova Conversa"
    model_id: Optional[str] = "openai/gpt-4"


class UpdateConversationRequest(BaseModel):
    """Dados para atualizar conversa"""
    model_config = {"protected_namespaces": ()}
    
    title: Optional[str] = None
    model_id: Optional[str] = None


class ConversationsListResponse(BaseModel):
    """Lista de conversas"""
    conversations: List[ConversationSummary]
    total: int


# -------------------------------------------------
# Funções de Persistência
# -------------------------------------------------
def get_conversation_path(conversation_id: str) -> str:
    """Retorna o caminho do arquivo de uma conversa"""
    return os.path.join(settings.conversations_dir, f"{conversation_id}.json")


def load_conversation(conversation_id: str) -> Optional[Conversation]:
    """
    Carrega uma conversa do arquivo JSON.
    
    Args:
        conversation_id: ID da conversa
        
    Returns:
        Conversa ou None se não existir
    """
    path = get_conversation_path(conversation_id)
    
    if not os.path.exists(path):
        return None
    
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Conversation(**data)
    except Exception as e:
        logger.error("Erro ao carregar conversa", id=conversation_id, error=str(e))
        return None


def save_conversation(conversation: Conversation) -> bool:
    """
    Salva uma conversa em arquivo JSON.
    
    Args:
        conversation: Conversa a salvar
        
    Returns:
        True se sucesso
    """
    path = get_conversation_path(conversation.id)
    
    try:
        # Garantir que diretório existe
        os.makedirs(os.path.dirname(path), exist_ok=True)
        
        # Converter para dict e salvar
        data = conversation.model_dump(mode="json")
        
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        
        logger.debug("Conversa salva", id=conversation.id)
        return True
        
    except Exception as e:
        logger.error("Erro ao salvar conversa", id=conversation.id, error=str(e))
        return False


def delete_conversation_file(conversation_id: str) -> bool:
    """
    Remove arquivo de uma conversa.
    
    Args:
        conversation_id: ID da conversa
        
    Returns:
        True se sucesso
    """
    path = get_conversation_path(conversation_id)
    
    if os.path.exists(path):
        try:
            os.remove(path)
            logger.info("Conversa removida", id=conversation_id)
            return True
        except Exception as e:
            logger.error("Erro ao remover conversa", id=conversation_id, error=str(e))
            return False
    
    return False


def list_all_conversations() -> List[ConversationSummary]:
    """
    Lista todas as conversas salvas.
    
    Returns:
        Lista de resumos de conversas ordenados por data
    """
    conversations = []
    
    if not os.path.exists(settings.conversations_dir):
        return conversations
    
    for filename in os.listdir(settings.conversations_dir):
        if filename.endswith(".json"):
            conversation_id = filename[:-5]  # Remove .json
            conv = load_conversation(conversation_id)
            
            if conv:
                conversations.append(
                    ConversationSummary(
                        id=conv.id,
                        title=conv.title,
                        model_id=conv.model_id,
                        message_count=len(conv.messages),
                        created_at=conv.created_at,
                        updated_at=conv.updated_at
                    )
                )
    
    # Ordenar por data de atualização (mais recente primeiro)
    conversations.sort(key=lambda x: x.updated_at, reverse=True)
    
    return conversations


# -------------------------------------------------
# Endpoints
# -------------------------------------------------
@router.get("", response_model=ConversationsListResponse)
async def list_conversations(
    user: UserInfo = Depends(get_current_user)
):
    """
    Lista todas as conversas do usuário.
    """
    logger.info("Listando conversas", username=user.username)
    
    conversations = list_all_conversations()
    
    return ConversationsListResponse(
        conversations=conversations,
        total=len(conversations)
    )


@router.post("", response_model=Conversation)
async def create_conversation(
    request: CreateConversationRequest,
    user: UserInfo = Depends(get_current_user)
):
    """
    Cria uma nova conversa.
    """
    logger.info(
        "Criando conversa",
        username=user.username,
        title=request.title
    )
    
    conversation = Conversation(
        title=request.title or "Nova Conversa",
        model_id=request.model_id or "openai/gpt-4"
    )
    
    if not save_conversation(conversation):
        raise HTTPException(
            status_code=500,
            detail="Erro ao salvar conversa"
        )
    
    return conversation


@router.get("/{conversation_id}", response_model=Conversation)
async def get_conversation(
    conversation_id: str,
    user: UserInfo = Depends(get_current_user)
):
    """
    Retorna uma conversa específica.
    """
    conversation = load_conversation(conversation_id)
    
    if not conversation:
        raise HTTPException(
            status_code=404,
            detail="Conversa não encontrada"
        )
    
    return conversation


@router.put("/{conversation_id}", response_model=Conversation)
async def update_conversation(
    conversation_id: str,
    request: UpdateConversationRequest,
    user: UserInfo = Depends(get_current_user)
):
    """
    Atualiza título ou modelo de uma conversa.
    """
    conversation = load_conversation(conversation_id)
    
    if not conversation:
        raise HTTPException(
            status_code=404,
            detail="Conversa não encontrada"
        )
    
    # Atualizar campos
    if request.title is not None:
        conversation.title = request.title
    if request.model_id is not None:
        conversation.model_id = request.model_id
    
    conversation.updated_at = datetime.utcnow()
    
    if not save_conversation(conversation):
        raise HTTPException(
            status_code=500,
            detail="Erro ao salvar conversa"
        )
    
    logger.info("Conversa atualizada", id=conversation_id)
    
    return conversation


@router.delete("/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    user: UserInfo = Depends(get_current_user)
):
    """
    Remove uma conversa.
    """
    if not delete_conversation_file(conversation_id):
        raise HTTPException(
            status_code=404,
            detail="Conversa não encontrada"
        )
    
    return {"message": "Conversa removida com sucesso"}

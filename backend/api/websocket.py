"""
=====================================================
ZEUS - WebSocket Handler
Gerencia conexões WebSocket para chat em tempo real
=====================================================
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from typing import Optional
import json

from config import get_settings, get_logger
from api.auth import verify_token
from api.conversations import (
    load_conversation, 
    save_conversation, 
    Message,
    Conversation
)
from agent.orchestrator import AgentOrchestrator
from services.rate_limiter import get_rate_limiter

# -------------------------------------------------
# Configuração
# -------------------------------------------------
router = APIRouter()
logger = get_logger(__name__)
settings = get_settings()


# -------------------------------------------------
# WebSocket Endpoint
# -------------------------------------------------
@router.websocket("/ws/chat")
async def websocket_chat(
    websocket: WebSocket,
    token: Optional[str] = Query(None),
    conversation_id: Optional[str] = Query(None)
):
    """
    WebSocket para chat em tempo real com o agente.
    
    Query params:
        token: JWT de autenticação
        conversation_id: ID da conversa (opcional, cria nova se não existir)
    
    Mensagens do cliente (JSON):
        {
            "type": "message",
            "content": "texto da mensagem",
            "model_id": "openai/gpt-4" (opcional)
        }
    
    Mensagens do servidor (JSON):
        {
            "type": "message" | "chunk" | "error" | "status",
            "content": "...",
            "role": "assistant",
            ...
        }
    """
    # Verificar autenticação
    if not token:
        await websocket.close(code=4001, reason="Token não fornecido")
        return
    
    try:
        token_data = verify_token(token)
        username = token_data.username
    except Exception as e:
        logger.warning("WebSocket: token inválido", error=str(e))
        await websocket.close(code=4001, reason="Token inválido")
        return
    
    # Aceitar conexão
    await websocket.accept()
    logger.info(
        "WebSocket conectado",
        username=username,
        conversation_id=conversation_id
    )
    
    # Obter rate limiter
    rate_limiter = get_rate_limiter()
    
    # Carregar ou criar conversa
    conversation: Optional[Conversation] = None
    if conversation_id:
        conversation = load_conversation(conversation_id)
    
    if not conversation:
        from datetime import datetime
        import uuid
        conversation = Conversation(
            id=conversation_id or str(uuid.uuid4()),
            title="Nova Conversa"
        )
        # NÃO salvar imediatamente para evitar conversas vazias
        # save_conversation(conversation)
        
        # Notificar cliente sobre nova conversa apenas se foi criada explicitamente
        # Se veio sem ID, é uma nova sessão temporária até primeira mensagem
        await websocket.send_json({
            "type": "conversation_created",
            "conversation_id": conversation.id
        })
    
    # Criar orquestrador do agente
    orchestrator = AgentOrchestrator()
    
    # Estado de cancelamento compartilhado entre WebSocket e orquestrador
    # Usado para sinalizar ao processamento que deve ser cancelado
    cancel_state = {
        "cancelled": False,
        "active_process": None  # Armazena processo shell ativo (se houver)
    }
    
    try:
        while True:
            # Receber mensagem do cliente
            data = await websocket.receive_text()
            
            try:
                message_data = json.loads(data)
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "content": "Formato de mensagem inválido"
                })
                continue
            
            msg_type = message_data.get("type", "message")
            
            # -------------------------------------------------
            # Handler para mensagem de CANCELAMENTO
            # -------------------------------------------------
            if msg_type == "cancel":
                logger.info(
                    "Solicitação de cancelamento recebida",
                    username=username,
                    conversation_id=conversation.id if conversation else None
                )
                
                # Sinalizar cancelamento
                cancel_state["cancelled"] = True
                
                # Se houver processo shell ativo, tentar matar
                if cancel_state.get("active_process"):
                    try:
                        cancel_state["active_process"].kill()
                        logger.info("Processo shell ativo cancelado")
                    except Exception as e:
                        logger.warning("Erro ao matar processo", error=str(e))
                
                # Notificar cliente
                await websocket.send_json({
                    "type": "cancelled",
                    "content": "Processamento cancelado pelo usuário."
                })
                
                # Reset do flag para próxima mensagem
                cancel_state["cancelled"] = False
                cancel_state["active_process"] = None
                continue
            
            if msg_type == "message":
                content = message_data.get("content", "").strip()
                
                # Extrair modelos customizados do frontend (1ª, 2ª e 3ª Instância)
                # Se não fornecidos, usa os valores padrão do config
                models_data = message_data.get("models", {})
                custom_models = {
                    "primary": models_data.get("primary", settings.primary_model),
                    "secondary": models_data.get("secondary", settings.secondary_model),
                    "tertiary": models_data.get("tertiary", settings.secondary_model)
                }
                
                if not content:
                    continue
                
                # Reset do estado de cancelamento para nova mensagem
                cancel_state["cancelled"] = False
                cancel_state["active_process"] = None
                
                logger.info(
                    "Mensagem recebida",
                    username=username,
                    content_length=len(content),
                    primary_model=custom_models["primary"],
                    secondary_model=custom_models["secondary"],
                    tertiary_model=custom_models["tertiary"]
                )
                
                # Verificar rate limit
                allowed, error_msg = await rate_limiter.check_request(username)
                if not allowed:
                    await websocket.send_json({
                        "type": "error",
                        "content": f"⏱️ {error_msg}"
                    })
                    continue
                
                # Adicionar mensagem do usuário à conversa
                user_message = Message(
                    role="user",
                    content=content
                )
                conversation.messages.append(user_message)
                conversation.model_id = custom_models["primary"]  # Guardar modelo primário
                
                # Atualizar título se for primeira mensagem
                if len(conversation.messages) == 1:
                    # Usar primeiras palavras como título
                    title_words = content.split()[:6]
                    conversation.title = " ".join(title_words)
                    if len(content.split()) > 6:
                        conversation.title += "..."
                
                # Notificar que está processando
                await websocket.send_json({
                    "type": "status",
                    "status": "processing"
                })
                
                try:
                    logger.info(
                        "Iniciando processamento com agente",
                        primary=custom_models["primary"],
                        secondary=custom_models["secondary"],
                        tertiary=custom_models["tertiary"]
                    )
                    print(f"[DEBUG] Processando mensagem: {content[:50]}...")
                    
                    # Processar com o agente, passando modelos customizados e cancel_state
                    response = await orchestrator.process_message(
                        conversation=conversation,
                        websocket=websocket,
                        custom_models=custom_models,
                        cancel_state=cancel_state
                    )
                    
                    print(f"[DEBUG] Resposta recebida: {str(response)[:100]}...")
                    
                    # Adicionar resposta à conversa
                    assistant_message = Message(
                        role="assistant",
                        content=response.get("content", ""),
                        tool_calls=response.get("tool_calls")
                    )
                    conversation.messages.append(assistant_message)
                    
                    # Atualizar timestamp
                    from datetime import datetime
                    conversation.updated_at = datetime.utcnow()
                    
                    # Salvar conversa
                    save_conversation(conversation)
                    
                    # Enviar resposta final
                    await websocket.send_json({
                        "type": "message",
                        "role": "assistant",
                        "content": response.get("content", ""),
                        "message_id": assistant_message.id,
                        "tool_calls": response.get("tool_calls")
                    })
                    
                except Exception as e:
                    logger.error(
                        "Erro ao processar mensagem",
                        error=str(e)
                    )
                    await websocket.send_json({
                        "type": "error",
                        "content": f"Erro ao processar: {str(e)}"
                    })
                
                finally:
                    # Notificar que terminou
                    await websocket.send_json({
                        "type": "status",
                        "status": "idle"
                    })
            
            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})
    
    except WebSocketDisconnect:
        logger.info(
            "WebSocket desconectado",
            username=username,
            conversation_id=conversation.id if conversation else None
        )
    
    except Exception as e:
        logger.error("Erro no WebSocket", error=str(e))
        try:
            await websocket.send_json({
                "type": "error",
                "content": f"Erro interno: {str(e)}"
            })
        except:
            pass

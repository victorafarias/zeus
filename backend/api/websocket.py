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
            
            if msg_type == "message":
                content = message_data.get("content", "").strip()
                model_id = message_data.get("model_id", conversation.model_id)
                
                if not content:
                    continue
                
                logger.info(
                    "Mensagem recebida",
                    username=username,
                    content_length=len(content),
                    model_id=model_id
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
                conversation.model_id = model_id
                
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
                    logger.info("Iniciando processamento com agente", model=model_id)
                    print(f"[DEBUG] Processando mensagem: {content[:50]}...")
                    
                    # Processar com o agente
                    response = await orchestrator.process_message(
                        conversation=conversation,
                        websocket=websocket
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

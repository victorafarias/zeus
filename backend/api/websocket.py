"""
=====================================================
ZEUS - WebSocket Handler
Gerencia conexões WebSocket para chat em tempo real
=====================================================
"""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from starlette.websockets import WebSocketState
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
from api.uploads import load_file_content
from api.ws_manager import get_ws_manager
from agent.orchestrator import AgentOrchestrator
from services.rate_limiter import get_rate_limiter
from services.task_queue import get_task_queue, TaskStatus

# -------------------------------------------------
# Configuração
# -------------------------------------------------
router = APIRouter()
logger = get_logger(__name__)
settings = get_settings()


# -------------------------------------------------
# Função auxiliar para envio seguro via WebSocket
# -------------------------------------------------
async def safe_send_json(websocket: WebSocket, data: dict) -> bool:
    """
    Envia JSON via WebSocket apenas se a conexão ainda estiver aberta.
    
    Args:
        websocket: Conexão WebSocket
        data: Dicionário a ser enviado como JSON
        
    Returns:
        True se enviou com sucesso, False se a conexão estava fechada
    """
    try:
        # Verifica se o WebSocket ainda está conectado
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.send_json(data)
            return True
        else:
            logger.warning(
                "Tentativa de envio para WebSocket fechado ignorada",
                data_type=data.get("type", "unknown")
            )
            return False
    except Exception as e:
        logger.warning(
            "Erro ao enviar via WebSocket (conexão possivelmente fechada)",
            error=str(e),
            data_type=data.get("type", "unknown")
        )
        return False


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
    
    # Obter gerenciadores
    ws_manager = get_ws_manager()
    task_queue = get_task_queue()
    
    # Registrar conexão no gerenciador (para receber broadcasts)
    await ws_manager.connect(websocket, conversation.id)
    
    # Estado de cancelamento compartilhado entre WebSocket e orquestrador
    # Usado para sinalizar ao processamento que deve ser cancelado
    cancel_state = {
        "cancelled": False,
        "active_process": None  # Armazena processo shell ativo (se houver)
    }
    
    # Enviar tarefas ativas da conversa ao conectar
    try:
        active_tasks = await task_queue.list_tasks_by_conversation(conversation.id, limit=10)
        for task in active_tasks:
            if task.status in [TaskStatus.PENDING, TaskStatus.PROCESSING]:
                await websocket.send_json({
                    "type": "task_status",
                    "task_id": task.id,
                    "status": task.status.value,
                    "user_message": task.user_message[:100]
                })
    except Exception as e:
        logger.warning("Erro ao enviar tarefas ativas", error=str(e))
    
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
                
                # Extrair arquivos anexados
                attached_files = message_data.get("attached_files", [])
                
                # Extrair modelos customizados do frontend (1ª, 2ª Instância e Mago)
                # Se não fornecidos, usa os valores padrão do config
                models_data = message_data.get("models", {})
                custom_models = {
                    "primary": models_data.get("primary", settings.primary_model),
                    "secondary": models_data.get("secondary", settings.secondary_model),
                    "mago": models_data.get("mago", settings.secondary_model)
                }
                
                if not content and not attached_files:
                    continue
                
                # -------------------------------------------------
                # Processar arquivos anexados
                # -------------------------------------------------
                file_context = ""
                image_attachments = []  # Para imagens, enviaremos separadamente
                
                if attached_files:
                    logger.info(
                        "Processando arquivos anexados",
                        count=len(attached_files)
                    )
                    
                    for file_id in attached_files:
                        file_data = await load_file_content(file_id)
                        
                        if file_data:
                            if file_data["type"] == "text":
                                # Arquivo de texto/código: incluir no contexto
                                file_context += f"\n\n--- Arquivo: {file_data['name']} ---\n"
                                file_context += file_data["content"]
                                file_context += "\n--- Fim do arquivo ---\n"
                                
                            elif file_data["type"] == "image":
                                # Imagem: adicionar referência (modelos podem não suportar)
                                image_attachments.append(file_data)
                                file_context += f"\n[Imagem anexada: {file_data['name']}]\n"
                                
                            else:
                                # PDFs, Word, binários: incluir indicação
                                file_context += f"\n{file_data['content']}\n"
                        else:
                            file_context += f"\n[Erro: arquivo {file_id} não encontrado]\n"
                    
                    logger.info(
                        "Contexto de arquivos construído",
                        context_length=len(file_context),
                        images_count=len(image_attachments)
                    )
                
                # Combinar conteúdo da mensagem com contexto dos arquivos
                full_content = content
                if file_context:
                    full_content = content + file_context
                
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
                # IMPORTANTE: Usamos 'full_content' (com arquivos) para enviar ao agente
                # Depois, restauramos para 'content' antes de salvar
                user_message = Message(
                    role="user",
                    content=full_content  # Inclui contexto dos arquivos para o agente
                )
                # Guardar referência aos arquivos anexados (se houver)
                if attached_files:
                    user_message.attached_files = attached_files
                    
                conversation.messages.append(user_message)
                conversation.model_id = custom_models["primary"]  # Guardar modelo primário
                
                # Atualizar título se for primeira mensagem
                if len(conversation.messages) == 1:
                    # Usar primeiras palavras como título
                    title_words = content.split()[:6]
                    conversation.title = " ".join(title_words)
                    if len(content.split()) > 6:
                        conversation.title += "..."
                
                # Verificar se deve usar processamento em background
                # O cliente pode solicitar explicitamente, ou pode ser automatic se detectado
                use_background = message_data.get("background", False)
                
                if use_background:
                    # -------------------------------------------------
                    # MODO BACKGROUND: Criar tarefa na fila
                    # -------------------------------------------------
                    try:
                        # Salvar conversa primeiro (para o worker encontrar)
                        user_message.content = content  # Restaurar conteúdo original
                        save_conversation(conversation)
                        
                        # Criar tarefa na fila
                        task = await task_queue.create_task(
                            conversation_id=conversation.id,
                            user_message=full_content,  # Inclui contexto de arquivos
                            models=custom_models,
                            attached_files=attached_files
                        )
                        
                        logger.info(
                            "Tarefa criada para processamento em background",
                            task_id=task.id,
                            conversation_id=conversation.id
                        )
                        
                        # Notificar cliente sobre a tarefa criada
                        await websocket.send_json({
                            "type": "task_created",
                            "task_id": task.id,
                            "status": "pending",
                            "message": "Sua mensagem foi enfileirada para processamento. Você pode fechar esta janela e a resposta será processada em background."
                        })
                        
                    except Exception as e:
                        logger.error("Erro ao criar tarefa", error=str(e))
                        await websocket.send_json({
                            "type": "error",
                            "content": f"Erro ao criar tarefa: {str(e)}"
                        })
                else:
                    # -------------------------------------------------
                    # MODO SÍNCRONO: Processar diretamente via WebSocket
                    # -------------------------------------------------
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
                        
                        # Restaurar conteúdo original (sem arquivos) antes de salvar
                        # Isso evita persistir o contexto grande dos arquivos
                        user_message.content = content  # Volta para o texto original
                        
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
                        # Usar envio seguro - conexão pode ter sido fechada
                        await safe_send_json(websocket, {
                            "type": "error",
                            "content": f"Erro ao processar: {str(e)}"
                        })
                    
                    finally:
                        # Notificar que terminou (usando envio seguro)
                        await safe_send_json(websocket, {
                            "type": "status",
                            "status": "idle"
                        })
            
            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})
    
    except WebSocketDisconnect:
        # Desregistrar do gerenciador
        await ws_manager.disconnect(websocket)
        logger.info(
            "WebSocket desconectado",
            username=username,
            conversation_id=conversation.id if conversation else None
        )
    
    except Exception as e:
        # Desregistrar do gerenciador
        await ws_manager.disconnect(websocket)
        logger.error("Erro no WebSocket", error=str(e))
        # Envio seguro - não precisa de try/except adicional
        await safe_send_json(websocket, {
            "type": "error",
            "content": f"Erro interno: {str(e)}"
        })

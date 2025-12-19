"""
=====================================================
ZEUS - Orquestrador do Agente
Gerencia o ciclo de vida do agente e execução de tools
=====================================================
"""

from typing import Dict, Any, List, Optional
from fastapi import WebSocket
import json

from config import get_settings, get_logger
from agent.openrouter_client import get_openrouter_client
from agent.prompts import SYSTEM_PROMPT, RAG_CONTEXT_TEMPLATE
from agent.tools import get_all_tools, execute_tool

# -------------------------------------------------
# Configuração
# -------------------------------------------------
logger = get_logger(__name__)
settings = get_settings()

# RAG Service (lazy import para evitar circular)
_rag_service = None

def get_rag():
    """Obtém RAG service com lazy loading"""
    global _rag_service
    if _rag_service is None:
        try:
            from services.rag_service import get_rag_service
            _rag_service = get_rag_service()
        except Exception as e:
            logger.warning("RAG não disponível", error=str(e))
            _rag_service = False  # Marca como indisponível
    return _rag_service if _rag_service else None


class AgentOrchestrator:
    """
    Orquestrador principal do agente Zeus.
    
    Gerencia:
    - Comunicação com OpenRouter
    - Execução de tools
    - Ciclo de tool calling (múltiplas iterações)
    - Streaming de respostas
    """
    
    def __init__(self):
        """Inicializa o orquestrador"""
        self.client = get_openrouter_client()
        self.tools = get_all_tools()
        
        logger.info(
            "Orquestrador inicializado",
            tools_count=len(self.tools)
        )
    
    def _build_messages(
        self,
        conversation_messages: List[Dict[str, Any]],
        rag_context: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Constrói lista de mensagens para enviar ao modelo.
        
        Args:
            conversation_messages: Mensagens da conversa
            rag_context: Contexto adicional do RAG (opcional)
            
        Returns:
            Lista de mensagens formatadas para API
        """
        messages = []
        
        # System prompt com contexto RAG se disponível
        system_content = SYSTEM_PROMPT
        if rag_context:
            system_content += "\n\n" + RAG_CONTEXT_TEMPLATE.format(
                procedures=rag_context
            )
        
        messages.append({
            "role": "system",
            "content": system_content
        })
        
        # Adicionar mensagens da conversa
        for msg in conversation_messages:
            msg_dict = {
                "role": msg.role if hasattr(msg, 'role') else msg.get('role'),
                "content": msg.content if hasattr(msg, 'content') else msg.get('content', '')
            }
            
            # Adicionar tool_calls se existirem
            tool_calls = msg.tool_calls if hasattr(msg, 'tool_calls') else msg.get('tool_calls')
            if tool_calls:
                msg_dict["tool_calls"] = tool_calls
            
            # Adicionar tool_call_id se for resposta de tool
            tool_call_id = msg.tool_call_id if hasattr(msg, 'tool_call_id') else msg.get('tool_call_id')
            if tool_call_id:
                msg_dict["role"] = "tool"
                msg_dict["tool_call_id"] = tool_call_id
            
            messages.append(msg_dict)
        
        return messages
    
    async def process_message(
        self,
        conversation,
        websocket: Optional[WebSocket] = None
    ) -> Dict[str, Any]:
        """
        Processa uma mensagem do usuário e retorna resposta.
        
        Implementa o ciclo de tool calling:
        1. Envia mensagem para o modelo
        2. Se modelo solicitar tool, executa e envia resultado
        3. Repete até resposta final
        
        Args:
            conversation: Objeto Conversation com mensagens
            websocket: WebSocket para enviar atualizações em tempo real
            
        Returns:
            Dicionário com resposta final
        """
        logger.info(
            "Processando mensagem",
            conversation_id=conversation.id,
            model_id=conversation.model_id
        )
        
        # Buscar contexto do RAG
        rag_context = None
        rag = get_rag()
        if rag:
            try:
                # Pegar última mensagem do usuário para buscar contexto
                last_user_msg = None
                for msg in reversed(conversation.messages):
                    role = msg.role if hasattr(msg, 'role') else msg.get('role')
                    if role == 'user':
                        last_user_msg = msg.content if hasattr(msg, 'content') else msg.get('content', '')
                        break
                
                if last_user_msg:
                    rag_context = await rag.get_context_for_query(last_user_msg)
                    if rag_context:
                        logger.debug("Contexto RAG encontrado", length=len(rag_context))
            except Exception as e:
                logger.warning("Erro ao buscar contexto RAG", error=str(e))
        
        # Construir mensagens
        messages = self._build_messages(
            conversation.messages,
            rag_context
        )
        
        # Armazenar procedimentos executados para salvar no RAG
        executed_procedures = []
        
        # Limitar número de iterações para evitar loops infinitos
        max_iterations = 10
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            
            logger.info(
                "Iteração do agente",
                iteration=iteration,
                messages_count=len(messages)
            )
            
            # Enviar para o modelo
            response = await self.client.chat_completion(
                messages=messages,
                model=conversation.model_id,
                tools=self.tools if self.tools else None
            )
            
            # Verificar se há tool calls
            tool_calls = response.get("tool_calls", [])
            
            if not tool_calls:
                # Resposta final - sem mais tools a executar
                logger.info(
                    "Resposta final",
                    content_length=len(response.get("content", ""))
                )
                return response
            
            # Executar cada tool call
            logger.info(
                "Executando tools",
                count=len(tool_calls)
            )
            
            # Adicionar resposta do assistente com tool_calls às mensagens
            messages.append({
                "role": "assistant",
                "content": response.get("content") or "",
                "tool_calls": tool_calls
            })
            
            for tool_call in tool_calls:
                tool_name = tool_call["function"]["name"]
                tool_args_str = tool_call["function"]["arguments"]
                tool_id = tool_call["id"]
                
                # Notificar via WebSocket
                if websocket:
                    await websocket.send_json({
                        "type": "tool_start",
                        "tool": tool_name,
                        "tool_id": tool_id
                    })
                
                try:
                    # Parse dos argumentos
                    tool_args = json.loads(tool_args_str)
                    
                    logger.info(
                        "Executando tool",
                        name=tool_name,
                        args=list(tool_args.keys())
                    )
                    
                    tool_args["websocket"] = websocket

                    # Heartbeat task para feedback constante
                    async def heartbeat(ws):
                        import asyncio
                        import random
                        messages = [
                            "Ainda processando sua solicitação...",
                            "O processo continua em execução, aguarde...",
                            "Executando tarefa complexa...",
                            "Trabalhando nisso..."
                        ]
                        try:
                            while True:
                                await asyncio.sleep(15) # A cada 15s
                                if ws:
                                    await ws.send_json({
                                        "type": "status",
                                        "status": "processing",
                                        "content": random.choice(messages)
                                    })
                        except asyncio.CancelledError:
                            pass

                    # Iniciar heartbeat
                    heartbeat_task = asyncio.create_task(heartbeat(websocket)) if websocket else None

                    # Executar a tool
                    try:
                        result = await execute_tool(tool_name, tool_args)
                    finally:
                        # Cancelar heartbeat ao terminar
                        if heartbeat_task:
                            heartbeat_task.cancel()
                            try:
                                await heartbeat_task
                            except asyncio.CancelledError:
                                pass
                    
                    logger.info(
                        "Tool executada",
                        name=tool_name,
                        success=result.get("success", False)
                    )
                    
                    # Formatar resultado
                    if result.get("success"):
                        tool_result = result.get("output", "Executado com sucesso")
                    else:
                        tool_result = f"Erro: {result.get('error', 'Erro desconhecido')}"
                    
                except json.JSONDecodeError as e:
                    tool_result = f"Erro ao parsear argumentos: {str(e)}"
                    logger.error("Erro ao parsear args da tool", error=str(e))
                    
                except Exception as e:
                    tool_result = f"Erro ao executar: {str(e)}"
                    logger.error("Erro ao executar tool", error=str(e))
                
                # Notificar resultado via WebSocket
                if websocket:
                    await websocket.send_json({
                        "type": "tool_result",
                        "tool": tool_name,
                        "tool_id": tool_id,
                        "result": tool_result[:500]  # Limitar tamanho
                    })
                
                # Adicionar resultado às mensagens
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_id,
                    "content": tool_result
                })
                
                # Guardar procedimento para salvar no RAG depois
                if result.get("success"):
                    executed_procedures.append({
                        "tool": tool_name,
                        "args": tool_args,
                        "result": tool_result[:500]
                    })
        
        # Salvar procedimentos executados no RAG (após loop)
        if executed_procedures and rag:
            try:
                for proc in executed_procedures:
                    # Criar descrição do procedimento
                    description = f"Executou {proc['tool']} com argumentos: {list(proc['args'].keys())}"
                    await rag.add_procedure(
                        description=description,
                        solution=proc['result'],
                        tool_used=proc['tool']
                    )
            except Exception as e:
                logger.warning("Erro ao salvar procedimentos no RAG", error=str(e))
        
        # Se chegou aqui, excedeu iterações
        logger.warning(
            "Máximo de iterações excedido",
            iterations=max_iterations
        )
        
        return {
            "content": "Desculpe, a operação excedeu o limite de iterações. Por favor, tente novamente com uma tarefa mais simples.",
            "role": "assistant"
        }

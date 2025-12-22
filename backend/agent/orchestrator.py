"""
=====================================================
ZEUS - Orquestrador do Agente
Gerencia o ciclo de vida do agente e execução de tools
=====================================================
"""

from typing import Dict, Any, List, Optional, Callable
from fastapi import WebSocket
import json
import asyncio

from config import get_settings, get_logger
from agent.openrouter_client import get_openrouter_client
from agent.prompts import SYSTEM_PROMPT, RAG_CONTEXT_TEMPLATE
from agent.tools import get_all_tools, execute_tool
from agent.container_session_manager import ContainerSessionManager

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
    - Comunicação com OpenRouter (modelos 1ª, 2ª e 3ª Instância)
    - Fallback automático entre modelos: 1ª → 2ª → 3ª Instância
    - Execução de tools
    - Ciclo de tool calling (múltiplas iterações)
    """
    
    def __init__(self):
        """Inicializa o orquestrador com cliente OpenRouter"""
        self.client = get_openrouter_client()
        self.tools = get_all_tools()
        
        # Modelos padrão (usados se não fornecidos via frontend)
        self.default_primary_model = settings.primary_model
        self.default_secondary_model = settings.secondary_model
        self.default_tertiary_model = settings.secondary_model  # Usar secundário como fallback
        
        # Timeouts para cada nível
        self.primary_timeout = settings.primary_model_timeout
        self.secondary_timeout = settings.secondary_model_timeout
        self.tertiary_timeout = settings.secondary_model_timeout  # Mesmo timeout do secundário
        
        logger.info(
            "Orquestrador inicializado",
            default_primary=self.default_primary_model,
            default_secondary=self.default_secondary_model,
            default_tertiary=self.default_tertiary_model,
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
    
    async def _send_log_feedback(
        self, 
        websocket: Optional[WebSocket], 
        message: str,
        progress_callback: Optional[Callable] = None,
        step_type: str = "info"
    ):
        """
        Envia feedback de log para o frontend via WebSocket ou callback.
        Exibe a descrição do log no indicador de digitação.
        
        Args:
            websocket: Conexão WebSocket (pode ser None)
            message: Mensagem de log a exibir
            progress_callback: Callback alternativo para envio de progresso
            step_type: Tipo do passo (info, tool_start, tool_end, error)
        """
        # Primeiro, tentar callback (para background worker)
        if progress_callback:
            try:
                await progress_callback(message, step_type)
            except Exception:
                pass
        
        # Depois, tentar WebSocket direto
        if websocket:
            try:
                await websocket.send_json({
                    "type": "backend_log",
                    "message": message
                })
            except Exception:
                pass  # Ignorar erros de envio
    
    async def _call_model_with_retry(self, model, messages, tools, timeout):
        """
        Tenta chamar o modelo, com retry se a resposta for vazia/erro de modelo vazio.
        Retorna a resposta ou None se falhar todas tentativas.
        """
        max_attempts = 2
        
        for attempt in range(max_attempts):
            try:
                is_last_attempt = (attempt == max_attempts - 1)
                
                # Tentar chamar o modelo
                response = await asyncio.wait_for(
                    self.client.chat_completion(
                        messages=messages,
                        model=model,
                        tools=tools
                    ),
                    timeout=timeout
                )
                
                # Verificar se resposta é válida
                content = response.get("content", "")
                tool_calls = response.get("tool_calls")
                
                # Erros específicos retornados pelo client que devem acionar fallback
                is_empty_error = isinstance(content, str) and "Erro: O modelo retornou uma resposta vazia" in content
                is_malformed_tool_error = isinstance(content, str) and "Erro: O modelo gerou tool calls malformados" in content
                
                has_error = is_empty_error or is_malformed_tool_error
                
                if (content or tool_calls) and not has_error:
                    # Sucesso! Resposta válida
                    return response
                
                # Se chegou aqui, é resposta vazia/ruim
                logger.warning(
                    f"Resposta inválida/vazia do modelo {model}",
                    attempt=attempt+1,
                    content_preview=str(content)[:100]
                )
                
                if not is_last_attempt:
                    logger.info(f"Tentando novamente {model} em 1s...")
                    await asyncio.sleep(1)
                    continue
                
            except asyncio.TimeoutError:
                logger.warning(f"Timeout no modelo {model} (tentativa {attempt+1})")
                if attempt < max_attempts - 1:
                    await asyncio.sleep(1)
                    
            except Exception as e:
                logger.error(f"Erro no modelo {model} (tentativa {attempt+1}): {e}")
                if attempt < max_attempts - 1:
                    await asyncio.sleep(1)
        
        return None # Falhou todas as tentativas

    async def process_message(
        self,
        conversation,
        websocket: Optional[WebSocket] = None,
        custom_models: Optional[Dict[str, str]] = None,
        cancel_state: Optional[Dict[str, Any]] = None,
        progress_callback: Optional[Callable[[str, str], Any]] = None
    ) -> Dict[str, Any]:
        """
        Processa uma mensagem do usuário e retorna resposta.
        
        Implementa o ciclo de tool calling com fallback 1ª → 2ª → 3ª Instância:
        1. Envia mensagem para o modelo da 1ª Instância
        2. Se falhar, tenta 2ª Instância
        3. Se falhar, tenta 3ª Instância
        4. Se modelo solicitar tool, executa e envia resultado
        5. Repete até resposta final
        
        Args:
            conversation: Objeto Conversation com mensagens
            websocket: WebSocket para enviar atualizações em tempo real
            custom_models: Modelos customizados {primary, secondary, tertiary}
            cancel_state: Estado de cancelamento compartilhado {cancelled: bool, active_process: processo}
            progress_callback: Callback para enviar progresso (para background worker)
                               Assinatura: async def callback(message: str, step_type: str)
            
        Returns:
            Dicionário com resposta final
        """
        # Determinar modelos a usar (customizados ou padrão)
        models = custom_models or {}
        primary_model = models.get("primary", self.default_primary_model)
        secondary_model = models.get("secondary", self.default_secondary_model)
        tertiary_model = models.get("tertiary", self.default_tertiary_model)
        
        logger.info(
            "Processando mensagem",
            conversation_id=conversation.id,
            primary_model=primary_model,
            secondary_model=secondary_model,
            tertiary_model=tertiary_model
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
        max_iterations = 200
        iteration = 0
        
        while iteration < max_iterations:
            iteration += 1
            
            # -------------------------------------------------
            # VERIFICAÇÃO DE CANCELAMENTO
            # -------------------------------------------------
            if cancel_state and cancel_state.get("cancelled"):
                logger.info(
                    "Processamento cancelado pelo usuário",
                    iteration=iteration
                )
                await self.cleanup_resources(conversation.id)
                return {
                    "content": "Processamento cancelado pelo usuário.",
                    "role": "assistant",
                    "cancelled": True
                }
            
            logger.info(
                "Iteração do agente",
                iteration=iteration,
                messages_count=len(messages)
            )
            await self._send_log_feedback(websocket, f"Iteração do agente ({iteration})", progress_callback)
            
            await self._send_log_feedback(
                websocket, 
                f"Enviando para 1ª Instância ({primary_model})",
                progress_callback
            )
            
            # Tentar 1ª Instância (modelo primário)
            response = await self._call_model_with_retry(
                model=primary_model,
                messages=messages,
                tools=self.tools if self.tools else None,
                timeout=self.primary_timeout
            )
            
            if response:
                logger.info("Resposta da 1ª Instância recebida", model=primary_model)
            else:
                # Falha na 1ª Instância → Tentar 2ª Instância
                logger.warning(
                    "Falha na 1ª Instância, tentando 2ª Instância",
                    primary_model=primary_model,
                    secondary_model=secondary_model
                )
                await self._send_log_feedback(
                    websocket,
                    f"Erro em {primary_model}, tentando 2ª Instância ({secondary_model})",
                    progress_callback
                )
                
                response = await self._call_model_with_retry(
                    model=secondary_model,
                    messages=messages,
                    tools=self.tools if self.tools else None,
                    timeout=self.secondary_timeout
                )
                
                if response:
                    logger.info("Resposta da 2ª Instância recebida", model=secondary_model)
                else:
                    # Falha na 2ª Instância → Tentar 3ª Instância
                    logger.warning(
                        "Falha na 2ª Instância, tentando 3ª Instância",
                        secondary_model=secondary_model,
                        tertiary_model=tertiary_model
                    )
                    await self._send_log_feedback(
                        websocket,
                        f"Erro em {secondary_model}, tentando 3ª Instância ({tertiary_model})",
                        progress_callback
                    )
                    
                    response = await self._call_model_with_retry(
                        model=tertiary_model,
                        messages=messages,
                        tools=self.tools if self.tools else None,
                        timeout=self.tertiary_timeout
                    )
                    
                    if response:
                        logger.info("Resposta da 3ª Instância recebida", model=tertiary_model)
                    else:
                        # Falha total em todas as instâncias
                        error_msg = f"Erro: Todos os modelos falharam (1ª: {primary_model}, 2ª: {secondary_model}, 3ª: {tertiary_model})"
                        logger.error("Falha em todas as instâncias")
                        await self._send_log_feedback(websocket, "Erro: Falha em todas as instâncias", progress_callback, "error")
                        await self.cleanup_resources(conversation.id)
                        return {
                            "content": error_msg,
                            "role": "assistant"
                        }
            
            # Resposta recebida
            await self._send_log_feedback(websocket, "Resposta recebida", progress_callback)
            
            # Verificar se há tool calls
            tool_calls = response.get("tool_calls", [])
            
            if not tool_calls:
                # Resposta final - sem mais tools a executar
                logger.info(
                    "Resposta final",
                    content_length=len(response.get("content", ""))
                )
                await self._send_log_feedback(websocket, "Resposta final gerada", progress_callback)
                await self.cleanup_resources(conversation.id)
                return response
            
            # Executar cada tool call
            logger.info(
                "Executando tools",
                count=len(tool_calls)
            )
            await self._send_log_feedback(websocket, f"Executando {len(tool_calls)} ferramenta(s)", progress_callback)
            
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
                
                # Inicializar variáveis antes do try para evitar erro de variável não definida
                # se houver exceção antes de serem atribuídas
                result = None
                tool_args = {}
                
                try:
                    # Parse dos argumentos com sanitização de escapes inválidos
                    # Alguns modelos LLM retornam \t, \n literais que são inválidos em JSON
                    def sanitize_json_string(s: str) -> str:
                        """
                        Corrige sequências de escape inválidas em JSON.
                        Modelos LLM às vezes geram \\t, \\n literais (não escapados como \\\\t)
                        que causam erro no json.loads.
                        """
                        import re
                        # Substituir escapes inválidos por escapes válidos
                        # Primeiro, duplicar barras antes de caracteres de escape inválidos
                        # Isso transforma \t em \\t (escape válido)
                        
                        # Lista de caracteres que precisam de escape duplo
                        # Excluímos os já válidos em JSON: \\, \", \n, \r, \t, \b, \f, \uXXXX
                        # O problema é que \t dentro de uma string JSON deveria ser um tab,
                        # mas se o modelo gerou literalmente "\t" (barra+t), precisamos escapar a barra
                        
                        # Detectar se a string tem escapes malformados tentando parsear
                        try:
                            json.loads(s)
                            return s  # Já é válido
                        except json.JSONDecodeError:
                            pass
                        
                        # Tentar corrigir escapes inválidos
                        # Substituir sequências de escape problemáticas dentro de strings JSON
                        # Pattern: captura uma barra seguida de caractere que NÃO é escape válido
                        # Escapes válidos em JSON: \\ \" \/ \b \f \n \r \t \uXXXX
                        
                        # Abordagem: substituir \\ por placeholder, corrigir, restaurar
                        placeholder = "\x00ESCAPED_BACKSLASH\x00"
                        s = s.replace("\\\\", placeholder)
                        
                        # Agora, barras simples restantes que precedem caracteres inválidos
                        # devem ser escapadas. Mas primeiro, vamos tratar os casos comuns:
                        # \t \n \r são válidos em JSON, o problema é quando o modelo
                        # gera uma string literal com barra+t que não está dentro de aspas
                        
                        # Restaurar
                        s = s.replace(placeholder, "\\\\")
                        
                        return s
                    
                    # Tentar parse direto primeiro
                    try:
                        tool_args = json.loads(tool_args_str)
                    except json.JSONDecodeError:
                        # Se falhar, tentar com sanitização mais agressiva
                        # Usar ast.literal_eval como fallback para strings Python escapadas
                        import ast
                        try:
                            # Tentar interpretar como string Python (que aceita mais escapes)
                            # e depois converter para JSON
                            sanitized = tool_args_str.encode('utf-8').decode('unicode_escape')
                            tool_args = json.loads(sanitized)
                        except Exception:
                            # Última tentativa: substituir escapes problemáticos manualmente
                            fixed = tool_args_str.replace('\\t', '\\\\t').replace('\\n', '\\\\n').replace('\\r', '\\\\r')
                            tool_args = json.loads(fixed)
                    
                    logger.info(
                        "Executando tool",
                        name=tool_name,
                        args=list(tool_args.keys())
                    )
                    await self._send_log_feedback(websocket, f"Executando: {tool_name}", progress_callback, "tool_start")
                    
                    tool_args["websocket"] = websocket
                    
                    tool_args["websocket"] = websocket
                    
                    # Passar cancel_state para tools que precisam verificar cancelamento
                    tool_args["cancel_state"] = cancel_state

                    # INJETAR SESSION_ID para isolamento
                    if conversation.id:
                        tool_args["session_id"] = conversation.id

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
                        await self._send_log_feedback(websocket, f"Tool {tool_name} executada com sucesso", progress_callback, "tool_end")
                    else:
                        tool_result = f"Erro: {result.get('error', 'Erro desconhecido')}"
                        await self._send_log_feedback(websocket, f"Erro na tool {tool_name}", progress_callback, "error")
                    
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
                # Verificar se result foi definido (pode não ter sido se houve erro de parsing)
                if result and result.get("success"):
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
        
            except Exception as e:
                logger.warning("Erro ao salvar procedimentos no RAG", error=str(e))
        
        # Se chegou aqui, excedeu iterações
        logger.warning(
            "Máximo de iterações excedido",
            iterations=max_iterations
        )
        
        await self.cleanup_resources(conversation.id)
        return {
            "content": "Desculpe, a operação excedeu o limite de iterações. Por favor, tente novamente com uma tarefa mais simples.",
            "role": "assistant"
        }
    
    async def cleanup_resources(self, session_id: str):
        """Limpa recursos da sessão"""
        if session_id:
            logger.info("Limpando recursos da sessão", session_id=session_id)
            try:
                ContainerSessionManager.cleanup_container(session_id)
            except Exception as e:
                logger.error("Erro ao limpar container", error=str(e))

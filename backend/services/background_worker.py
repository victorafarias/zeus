"""
=====================================================
ZEUS - Background Worker
Processa tarefas em background independente do WebSocket
=====================================================
"""

import asyncio
from typing import Optional, Dict, Any, Callable
from datetime import datetime

from config import get_settings, get_logger
from services.task_queue import (
    get_task_queue, 
    Task, 
    TaskStatus, 
    TaskQueue
)
from api.ws_manager import get_ws_manager, WebSocketManager
from api.conversations import load_conversation, save_conversation, Message
from agent.orchestrator import AgentOrchestrator

# -------------------------------------------------
# Configuração
# -------------------------------------------------
logger = get_logger(__name__)
settings = get_settings()


class BackgroundWorker:
    """
    Worker que processa tarefas em background.
    
    Características:
    - Processa múltiplas tarefas em paralelo (configurável)
    - Independente de conexões WebSocket
    - Envia atualizações via broadcast para clientes conectados
    - Resiliente a falhas - continua processando outras tarefas
    """
    
    def __init__(
        self,
        max_concurrent_tasks: int = 3,
        poll_interval: float = 1.0,
        cleanup_interval: float = 3600.0  # 1 hora
    ):
        """
        Inicializa o worker.
        
        Args:
            max_concurrent_tasks: Máximo de tarefas processadas simultaneamente
            poll_interval: Intervalo em segundos entre verificações de novas tarefas
            cleanup_interval: Intervalo em segundos entre limpezas de tarefas antigas
        """
        self.max_concurrent_tasks = max_concurrent_tasks
        self.poll_interval = poll_interval
        self.cleanup_interval = cleanup_interval
        
        self._running = False
        self._active_tasks: Dict[str, asyncio.Task] = {}
        self._main_task: Optional[asyncio.Task] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        
        # Dependências
        self._task_queue: Optional[TaskQueue] = None
        self._ws_manager: Optional[WebSocketManager] = None
        
        logger.info(
            "BackgroundWorker inicializado",
            max_concurrent=max_concurrent_tasks,
            poll_interval=poll_interval
        )
    
    async def start(self) -> None:
        """Inicia o worker"""
        if self._running:
            logger.warning("Worker já está em execução")
            return
        
        self._running = True
        self._task_queue = get_task_queue()
        self._ws_manager = get_ws_manager()
        
        # Recuperação de falhas: Resetar tarefas que ficaram presas em 'processing'
        try:
            reset_count = await self._task_queue.reset_stuck_tasks()
            if reset_count > 0:
                logger.warning(f"Worker recuperou {reset_count} tarefas interrompidas")
        except Exception as e:
            logger.error("Erro ao resetar tarefas travadas", error=str(e))
        
        # Inicia loop principal
        self._main_task = asyncio.create_task(self._main_loop())
        
        # Inicia loop de limpeza
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        
        logger.info("BackgroundWorker iniciado")
    
    async def stop(self) -> None:
        """Para o worker graciosamente"""
        self._running = False
        
        # Cancela loop principal
        if self._main_task:
            self._main_task.cancel()
            try:
                await self._main_task
            except asyncio.CancelledError:
                pass
        
        # Cancela loop de limpeza
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # Aguarda tarefas ativas terminarem (com timeout)
        if self._active_tasks:
            logger.info(
                "Aguardando tarefas ativas terminarem",
                count=len(self._active_tasks)
            )
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._active_tasks.values(), return_exceptions=True),
                    timeout=30.0
                )
            except asyncio.TimeoutError:
                logger.warning("Timeout aguardando tarefas, cancelando...")
                for task in self._active_tasks.values():
                    task.cancel()
        
        logger.info("BackgroundWorker parado")
    
    async def _main_loop(self) -> None:
        """Loop principal que verifica e processa tarefas"""
        while self._running:
            try:
                # Verifica se pode processar mais tarefas
                available_slots = self.max_concurrent_tasks - len(self._active_tasks)
                
                if available_slots > 0:
                    # Obtém tarefas pendentes
                    pending_tasks = await self._task_queue.get_pending_tasks(
                        limit=available_slots
                    )
                    
                    for task in pending_tasks:
                        # Tenta claim a tarefa (evita race condition)
                        if await self._task_queue.claim_task(task.id):
                            # Cria task de processamento
                            async_task = asyncio.create_task(
                                self._process_task(task)
                            )
                            self._active_tasks[task.id] = async_task
                            
                            # Callback para remover quando terminar
                            async_task.add_done_callback(
                                lambda t, tid=task.id: self._on_task_done(tid)
                            )
                
                # Aguarda antes de verificar novamente
                await asyncio.sleep(self.poll_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(
                    "Erro no loop principal do worker",
                    error=str(e)
                )
                await asyncio.sleep(self.poll_interval)
    
    def _on_task_done(self, task_id: str) -> None:
        """Callback quando uma tarefa termina"""
        self._active_tasks.pop(task_id, None)
    
    async def _cleanup_loop(self) -> None:
        """Loop que limpa tarefas antigas periodicamente"""
        while self._running:
            try:
                await asyncio.sleep(self.cleanup_interval)
                
                # Remove tarefas com mais de 24 horas
                deleted = await self._task_queue.cleanup_old_tasks(hours=24)
                
                if deleted > 0:
                    logger.info(f"Limpeza: {deleted} tarefas antigas removidas")
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Erro na limpeza de tarefas", error=str(e))
    
    async def _process_task(self, task: Task) -> None:
        """
        Processa uma tarefa individual.
        
        Args:
            task: Tarefa a processar
        """
        logger.info(
            "Iniciando processamento de tarefa",
            task_id=task.id,
            conversation_id=task.conversation_id
        )
        
        try:
            # Notifica clientes conectados
            await self._ws_manager.send_task_status(
                task.conversation_id,
                task.id,
                TaskStatus.PROCESSING.value
            )
            
            # Carrega conversa
            conversation = load_conversation(task.conversation_id)
            
            if not conversation:
                raise ValueError(f"Conversa não encontrada: {task.conversation_id}")
            
            # Adiciona mensagem do usuário à conversa
            user_message = Message(
                role="user",
                content=task.user_message,
                attached_files=task.attached_files if task.attached_files else None
            )
            conversation.messages.append(user_message)
            
            # Cria orquestrador
            orchestrator = AgentOrchestrator()
            
            # Cria callback de progresso
            async def progress_callback(message: str, step_type: str = "info"):
                # Salva no banco
                await self._task_queue.add_progress(task.id, message, step_type)
                
                # Envia para clientes conectados
                await self._ws_manager.send_task_progress(
                    task.conversation_id,
                    task.id,
                    message,
                    step_type
                )
            
            # Processa mensagem
            # NOTA: O orquestrador precisa ser modificado para aceitar progress_callback
            # Por enquanto, passamos None para websocket
            response = await orchestrator.process_message(
                conversation=conversation,
                websocket=None,  # Não há WebSocket direto
                custom_models=task.models,
                cancel_state={"cancelled": False, "active_process": None},
                progress_callback=progress_callback,  # Novo parâmetro
                require_completion_tool=True  # EXIGIR finish_task para background tasks
            )
            
            # Adiciona resposta à conversa
            assistant_message = Message(
                role="assistant",
                content=response.get("content", ""),
                tool_calls=response.get("tool_calls")
            )
            conversation.messages.append(assistant_message)
            
            # Atualiza timestamp
            conversation.updated_at = datetime.utcnow()
            
            # Salva conversa
            save_conversation(conversation)
            
            # Marca tarefa como concluída
            await self._task_queue.update_task_status(
                task.id,
                TaskStatus.COMPLETED,
                result=response.get("content", ""),
                tool_calls=response.get("tool_calls")
            )
            
            # Notifica clientes
            await self._ws_manager.send_task_status(
                task.conversation_id,
                task.id,
                TaskStatus.COMPLETED.value,
                result=response.get("content", ""),
                tool_calls=response.get("tool_calls")
            )
            
            logger.info(
                "Tarefa processada com sucesso",
                task_id=task.id
            )
            
        except Exception as e:
            error_msg = str(e)
            logger.error(
                "Erro ao processar tarefa",
                task_id=task.id,
                error=error_msg
            )
            
            # Marca tarefa como falha
            await self._task_queue.update_task_status(
                task.id,
                TaskStatus.FAILED,
                error=error_msg
            )
            
            # Notifica clientes
            await self._ws_manager.send_task_status(
                task.conversation_id,
                task.id,
                TaskStatus.FAILED.value,
                error=error_msg
            )


# -------------------------------------------------
# Singleton para uso global
# -------------------------------------------------
_worker: Optional[BackgroundWorker] = None


def get_background_worker() -> BackgroundWorker:
    """
    Obtém instância singleton do BackgroundWorker.
    
    Returns:
        Instância do BackgroundWorker
    """
    global _worker
    if _worker is None:
        _worker = BackgroundWorker(
            # Aumentado para 5 tarefas paralelas para suportar múltiplos chats simultaneamente
            max_concurrent_tasks=5,
            poll_interval=1.0,  # Verifica novas tarefas a cada 1 segundo
            cleanup_interval=3600.0  # Limpa tarefas antigas a cada 1 hora
        )
    return _worker


async def start_background_worker() -> None:
    """Inicia o worker em background"""
    worker = get_background_worker()
    await worker.start()


async def stop_background_worker() -> None:
    """Para o worker"""
    worker = get_background_worker()
    await worker.stop()

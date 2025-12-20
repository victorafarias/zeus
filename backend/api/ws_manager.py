"""
=====================================================
ZEUS - WebSocket Connection Manager
Gerencia múltiplas conexões WebSocket para broadcast
=====================================================
"""

import asyncio
from typing import Dict, Set, Optional, Any, List
from fastapi import WebSocket
from starlette.websockets import WebSocketState
from collections import defaultdict

from config import get_logger

# -------------------------------------------------
# Configuração
# -------------------------------------------------
logger = get_logger(__name__)


class WebSocketManager:
    """
    Gerenciador de conexões WebSocket.
    
    Permite:
    - Registrar conexões por conversa
    - Broadcast de mensagens para todos conectados em uma conversa
    - Gerenciamento automático de desconexões
    """
    
    def __init__(self):
        """Inicializa o gerenciador"""
        # Mapa de conversation_id -> set de WebSockets
        self._connections: Dict[str, Set[WebSocket]] = defaultdict(set)
        
        # Mapa de WebSocket -> conversation_id (para cleanup rápido)
        self._ws_to_conversation: Dict[WebSocket, str] = {}
        
        # Lock para operações thread-safe
        self._lock = asyncio.Lock()
        
        logger.info("WebSocketManager inicializado")
    
    async def connect(
        self,
        websocket: WebSocket,
        conversation_id: str
    ) -> None:
        """
        Registra uma nova conexão WebSocket para uma conversa.
        
        Args:
            websocket: Conexão WebSocket
            conversation_id: ID da conversa
        """
        async with self._lock:
            # Remove de conversa anterior se existir
            if websocket in self._ws_to_conversation:
                old_conv_id = self._ws_to_conversation[websocket]
                self._connections[old_conv_id].discard(websocket)
            
            # Registra na nova conversa
            self._connections[conversation_id].add(websocket)
            self._ws_to_conversation[websocket] = conversation_id
        
        logger.debug(
            "WebSocket conectado à conversa",
            conversation_id=conversation_id,
            total_connections=len(self._connections[conversation_id])
        )
    
    async def disconnect(self, websocket: WebSocket) -> None:
        """
        Remove uma conexão WebSocket.
        
        Args:
            websocket: Conexão WebSocket a remover
        """
        async with self._lock:
            if websocket in self._ws_to_conversation:
                conversation_id = self._ws_to_conversation[websocket]
                self._connections[conversation_id].discard(websocket)
                del self._ws_to_conversation[websocket]
                
                # Remove conversa do mapa se não tiver mais conexões
                if not self._connections[conversation_id]:
                    del self._connections[conversation_id]
                
                logger.debug(
                    "WebSocket desconectado da conversa",
                    conversation_id=conversation_id
                )
    
    async def switch_conversation(
        self,
        websocket: WebSocket,
        new_conversation_id: str
    ) -> None:
        """
        Move uma conexão para uma conversa diferente.
        
        Útil quando o usuário muda de conversa sem reconectar.
        
        Args:
            websocket: Conexão WebSocket
            new_conversation_id: ID da nova conversa
        """
        await self.connect(websocket, new_conversation_id)
    
    async def broadcast_to_conversation(
        self,
        conversation_id: str,
        message: Dict[str, Any]
    ) -> int:
        """
        Envia mensagem para todas as conexões de uma conversa.
        
        Args:
            conversation_id: ID da conversa
            message: Mensagem a enviar (será convertida para JSON)
            
        Returns:
            Número de conexões que receberam a mensagem
        """
        connections = self._connections.get(conversation_id, set()).copy()
        
        if not connections:
            logger.debug(
                "Nenhuma conexão ativa para broadcast",
                conversation_id=conversation_id
            )
            return 0
        
        # Função auxiliar para envio individual seguro
        async def send_to_socket(websocket: WebSocket) -> bool:
            try:
                if websocket.client_state == WebSocketState.CONNECTED:
                    await websocket.send_json(message)
                    return True
                return False
            except Exception as e:
                logger.warning(
                    "Erro ao enviar broadcast",
                    conversation_id=conversation_id,
                    error=str(e)
                )
                return False
        
        # Enviar para todos em paralelo
        results = await asyncio.gather(
            *[send_to_socket(ws) for ws in connections],
            return_exceptions=True
        )
        
        sent_count = 0
        failed_connections = []
        
        # Processar resultados
        for websocket, result in zip(connections, results):
            if isinstance(result, Exception) or result is False:
                failed_connections.append(websocket)
            else:
                sent_count += 1
        
        # Remove conexões que falharam de forma assíncrona (sem bloquear retorno)
        if failed_connections:
            asyncio.create_task(self._cleanup_failed(failed_connections))
            
        logger.debug(
            "Broadcast enviado",
            conversation_id=conversation_id,
            sent=sent_count,
            failed=len(failed_connections)
        )
        
        return sent_count
        
    async def _cleanup_failed(self, connections: List[WebSocket]):
        """Remove conexões falhas em background"""
        for ws in connections:
            await self.disconnect(ws)
    
    async def send_task_progress(
        self,
        conversation_id: str,
        task_id: str,
        message: str,
        step_type: str = "info"
    ) -> int:
        """
        Envia atualização de progresso de uma tarefa.
        
        Args:
            conversation_id: ID da conversa
            task_id: ID da tarefa
            message: Mensagem de progresso
            step_type: Tipo do passo
            
        Returns:
            Número de conexões que receberam
        """
        return await self.broadcast_to_conversation(
            conversation_id,
            {
                "type": "task_progress",
                "task_id": task_id,
                "message": message,
                "step_type": step_type
            }
        )
    
    async def send_task_status(
        self,
        conversation_id: str,
        task_id: str,
        status: str,
        result: Optional[str] = None,
        error: Optional[str] = None,
        tool_calls: Optional[list] = None
    ) -> int:
        """
        Envia atualização de status de uma tarefa.
        
        Args:
            conversation_id: ID da conversa
            task_id: ID da tarefa
            status: Novo status
            result: Resultado (se completed)
            error: Erro (se failed)
            tool_calls: Tool calls executadas
            
        Returns:
            Número de conexões que receberam
        """
        message = {
            "type": "task_status",
            "task_id": task_id,
            "status": status
        }
        
        if result is not None:
            message["result"] = result
        
        if error is not None:
            message["error"] = error
        
        if tool_calls is not None:
            message["tool_calls"] = tool_calls
        
        return await self.broadcast_to_conversation(conversation_id, message)
    
    def get_connection_count(self, conversation_id: str) -> int:
        """
        Retorna número de conexões ativas para uma conversa.
        
        Args:
            conversation_id: ID da conversa
            
        Returns:
            Número de conexões
        """
        return len(self._connections.get(conversation_id, set()))
    
    def get_total_connections(self) -> int:
        """
        Retorna total de conexões ativas.
        
        Returns:
            Total de conexões
        """
        return len(self._ws_to_conversation)
    
    def get_active_conversations(self) -> Set[str]:
        """
        Retorna IDs de conversas com conexões ativas.
        
        Returns:
            Set de conversation_ids
        """
        return set(self._connections.keys())


# -------------------------------------------------
# Singleton para uso global
# -------------------------------------------------
_ws_manager: Optional[WebSocketManager] = None


def get_ws_manager() -> WebSocketManager:
    """
    Obtém instância singleton do WebSocketManager.
    
    Returns:
        Instância do WebSocketManager
    """
    global _ws_manager
    if _ws_manager is None:
        _ws_manager = WebSocketManager()
    return _ws_manager

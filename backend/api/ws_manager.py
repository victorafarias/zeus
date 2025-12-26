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
    - Broadcast global para notificações de sistema
    - Gerenciamento automático de desconexões
    """
    
    def __init__(self):
        """Inicializa o gerenciador"""
        # Mapa de conversation_id -> set de WebSockets
        self._connections: Dict[str, Set[WebSocket]] = defaultdict(set)
        
        # Mapa de WebSocket -> conversation_id (para cleanup rápido)
        self._ws_to_conversation: Dict[WebSocket, str] = {}
        
        # Mapa para rastrear todos os sockets ativos (para broadcast global)
        self._all_sockets: Set[WebSocket] = set()
        
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
            # Remove de conversa anterior se existir (mas mantém no set global se já estiver)
            if websocket in self._ws_to_conversation:
                old_conv_id = self._ws_to_conversation[websocket]
                self._connections[old_conv_id].discard(websocket)
            
            # Registra na nova conversa
            self._connections[conversation_id].add(websocket)
            self._ws_to_conversation[websocket] = conversation_id
            self._all_sockets.add(websocket)
        
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
            
            # Remove do set global
            self._all_sockets.discard(websocket)
    
    async def switch_conversation(
        self,
        websocket: WebSocket,
        new_conversation_id: str
    ) -> None:
        """
        Muda a conversa associada a um WebSocket.
        
        Args:
            websocket: Conexão WebSocket
            new_conversation_id: Novo ID de conversa
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
            message: Mensagem a enviar
            
        Returns:
            Número de conexões que receberam
        """
        if conversation_id not in self._connections:
            return 0
            
        return await self._broadcast_to_sockets(self._connections[conversation_id], message)
        
    async def broadcast_globally(
        self,
        message: Dict[str, Any]
    ) -> int:
        """
        Envia mensagem para TODAS as conexões ativas.
        Útil para notificações de status que devem aparecer na sidebar independente da conversa atual.
        
        Args:
            message: Mensagem a enviar
            
        Returns:
            Número de conexões que receberam
        """
        if not self._all_sockets:
            return 0
            
        return await self._broadcast_to_sockets(self._all_sockets, message)

    async def _broadcast_to_sockets(
        self,
        sockets: Set[WebSocket],
        message: Dict[str, Any]
    ) -> int:
        """Helper para broadcast para um conjunto de sockets"""
        count = 0
        dead_connections = set()
        
        # Copia para evitar erro de modificação durante iteração
        connections = list(sockets)
        
        for websocket in connections:
            try:
                if websocket.client_state == WebSocketState.CONNECTED:
                    await websocket.send_json(message)
                    count += 1
                else:
                    dead_connections.add(websocket)
            except Exception as e:
                logger.warning(f"Erro no broadcast: {e}")
                dead_connections.add(websocket)
        
        # Limpa conexões mortas
        if dead_connections:
            async with self._lock:
                for ws in dead_connections:
                    await self.disconnect(ws)
                    
        return count
    
    async def send_task_progress(
        self,
        conversation_id: str,
        task_id: str,
        message: str,
        step_type: str = "info"
    ) -> int:
        """
        Envia atualização de progresso de uma tarefa.
        Usa broadcast global para garantir que loaders na sidebar sejam atualizados.
        
        Args:
            conversation_id: ID da conversa
            task_id: ID da tarefa
            message: Mensagem de progresso
            step_type: Tipo do passo
            
        Returns:
            Número de conexões que receberam
        """
        payload = {
            "type": "task_progress",
            "task_id": task_id,
            "conversation_id": conversation_id, # Importante para frontend filtrar
            "message": message,
            "step_type": step_type
        }
        
        # Broadcast global para atualizar sidebar em outras conversas
        return await self.broadcast_globally(payload)
    
    async def send_task_status(
        self,
        conversation_id: str,
        task_id: str,
        status: str,
        result: Optional[str] = None,
        error: Optional[str] = None,
        tool_calls: Optional[list] = None,
        execution_time: Optional[float] = None
    ) -> int:
        """
        Envia atualização de status de uma tarefa.
        Usa broadcast global.
        
        Args:
            conversation_id: ID da conversa
            task_id: ID da tarefa
            status: Novo status
            result: Resultado (se completed)
            error: Erro (se failed)
            tool_calls: Tool calls executadas
            execution_time: Tempo de execução em segundos
            
        Returns:
            Número de conexões que receberam
        """
        message = {
            "type": "task_status",
            "task_id": task_id,
            "conversation_id": conversation_id, # Importante para frontend filtrar
            "status": status
        }
        
        if result is not None:
            message["result"] = result
        
        if error is not None:
            message["error"] = error
        
        if tool_calls is not None:
            message["tool_calls"] = tool_calls
        
        # Tempo de execução: importante para exibir ao usuário
        if execution_time is not None:
            message["execution_time"] = round(execution_time, 2)
        
        # Broadcast global para atualizar sidebar em outras conversas
        return await self.broadcast_globally(message)

    
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
        return len(self._all_sockets)
    
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

"""
=====================================================
ZEUS - Rate Limiter
Controle de taxa de requisições por usuário
=====================================================
"""

from typing import Dict, Optional
from datetime import datetime, timedelta
from collections import defaultdict
import asyncio

from config import get_logger

logger = get_logger(__name__)


class RateLimiter:
    """
    Rate limiter simples baseado em janela deslizante.
    
    Controla:
    - Requisições por minuto por usuário
    - Requisições por hora por usuário
    - Execuções de tools por dia
    """
    
    def __init__(
        self,
        requests_per_minute: int = 30,
        requests_per_hour: int = 300,
        tool_executions_per_day: int = 100
    ):
        """
        Inicializa o rate limiter.
        
        Args:
            requests_per_minute: Máximo de requisições por minuto
            requests_per_hour: Máximo de requisições por hora
            tool_executions_per_day: Máximo de execuções de tools por dia
        """
        self.requests_per_minute = requests_per_minute
        self.requests_per_hour = requests_per_hour
        self.tool_executions_per_day = tool_executions_per_day
        
        # Armazenamento de requisições: {user: [timestamps]}
        self._requests: Dict[str, list] = defaultdict(list)
        self._tool_executions: Dict[str, list] = defaultdict(list)
        
        # Lock para operações thread-safe
        self._lock = asyncio.Lock()
        
        logger.info(
            "Rate limiter inicializado",
            rpm=requests_per_minute,
            rph=requests_per_hour,
            tpd=tool_executions_per_day
        )
    
    def _cleanup_old_entries(
        self,
        entries: list,
        max_age: timedelta
    ) -> list:
        """Remove entradas antigas da lista"""
        cutoff = datetime.utcnow() - max_age
        return [ts for ts in entries if ts > cutoff]
    
    async def check_request(self, user_id: str) -> tuple[bool, Optional[str]]:
        """
        Verifica se uma requisição é permitida.
        
        Args:
            user_id: Identificador do usuário
            
        Returns:
            Tupla (permitido, mensagem_erro)
        """
        async with self._lock:
            now = datetime.utcnow()
            
            # Limpar entradas antigas
            self._requests[user_id] = self._cleanup_old_entries(
                self._requests[user_id],
                timedelta(hours=1)
            )
            
            requests = self._requests[user_id]
            
            # Verificar limite por minuto
            minute_ago = now - timedelta(minutes=1)
            requests_last_minute = len([ts for ts in requests if ts > minute_ago])
            
            if requests_last_minute >= self.requests_per_minute:
                wait_time = 60 - (now - min(ts for ts in requests if ts > minute_ago)).seconds
                return False, f"Limite por minuto excedido. Aguarde {wait_time}s"
            
            # Verificar limite por hora
            if len(requests) >= self.requests_per_hour:
                return False, "Limite por hora excedido. Tente novamente mais tarde"
            
            # Registrar requisição
            requests.append(now)
            return True, None
    
    async def check_tool_execution(self, user_id: str) -> tuple[bool, Optional[str]]:
        """
        Verifica se uma execução de tool é permitida.
        
        Args:
            user_id: Identificador do usuário
            
        Returns:
            Tupla (permitido, mensagem_erro)
        """
        async with self._lock:
            now = datetime.utcnow()
            
            # Limpar entradas do dia anterior
            self._tool_executions[user_id] = self._cleanup_old_entries(
                self._tool_executions[user_id],
                timedelta(days=1)
            )
            
            executions = self._tool_executions[user_id]
            
            if len(executions) >= self.tool_executions_per_day:
                return False, "Limite diário de execuções atingido"
            
            executions.append(now)
            return True, None
    
    async def get_usage(self, user_id: str) -> Dict[str, int]:
        """
        Retorna estatísticas de uso do usuário.
        
        Args:
            user_id: Identificador do usuário
            
        Returns:
            Dicionário com contadores de uso
        """
        async with self._lock:
            now = datetime.utcnow()
            
            # Limpar entradas antigas
            self._requests[user_id] = self._cleanup_old_entries(
                self._requests[user_id],
                timedelta(hours=1)
            )
            self._tool_executions[user_id] = self._cleanup_old_entries(
                self._tool_executions[user_id],
                timedelta(days=1)
            )
            
            requests = self._requests[user_id]
            minute_ago = now - timedelta(minutes=1)
            
            return {
                "requests_last_minute": len([ts for ts in requests if ts > minute_ago]),
                "requests_last_hour": len(requests),
                "tool_executions_today": len(self._tool_executions[user_id]),
                "limits": {
                    "requests_per_minute": self.requests_per_minute,
                    "requests_per_hour": self.requests_per_hour,
                    "tool_executions_per_day": self.tool_executions_per_day
                }
            }


# Instância singleton
_rate_limiter: Optional[RateLimiter] = None


def get_rate_limiter() -> RateLimiter:
    """Retorna instância singleton do rate limiter"""
    global _rate_limiter
    
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    
    return _rate_limiter

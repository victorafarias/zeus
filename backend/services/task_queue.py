"""
=====================================================
ZEUS - Task Queue Service
Gerencia fila de tarefas com persistência SQLite
=====================================================
"""

import sqlite3
import asyncio
import uuid
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from contextlib import contextmanager
from enum import Enum

from config import get_settings, get_logger

# -------------------------------------------------
# Configuração
# -------------------------------------------------
logger = get_logger(__name__)
settings = get_settings()


class TaskStatus(str, Enum):
    """Status possíveis de uma tarefa"""
    PENDING = "pending"         # Aguardando processamento
    PROCESSING = "processing"   # Em execução
    COMPLETED = "completed"     # Finalizada com sucesso
    FAILED = "failed"           # Falhou
    CANCELLED = "cancelled"     # Cancelada pelo usuário


class TaskProgress(BaseModel):
    """Um passo de progresso de uma tarefa"""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    message: str
    step_type: str = "info"  # info, tool_start, tool_end, error


class Task(BaseModel):
    """Modelo de uma tarefa na fila"""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str
    user_message: str
    status: TaskStatus = TaskStatus.PENDING
    
    # Configuração de modelos para processamento
    models: Dict[str, str] = Field(default_factory=dict)
    
    # Arquivos anexados (lista de IDs)
    attached_files: List[str] = Field(default_factory=list)
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Resultado
    result: Optional[str] = None  # Resposta do agente
    error: Optional[str] = None   # Mensagem de erro se falhou
    tool_calls: Optional[List[dict]] = None  # Tool calls executadas
    
    # Progresso (para feedback em tempo real)
    progress: List[TaskProgress] = Field(default_factory=list)


class TaskQueue:
    """
    Gerenciador de fila de tarefas com SQLite.
    
    Utiliza thread pool para operações de I/O bloqueantes do SQLite,
    garantindo que o event loop assíncrono não seja travado.
    """
    
    def __init__(self, db_path: Optional[str] = None):
        """
        Inicializa o gerenciador de tarefas.
        
        Args:
            db_path: Caminho para o banco SQLite. Se None, usa o padrão.
        """
        self.db_path = db_path or f"{settings.data_dir}/tasks.db"
        self._init_database()
        
        logger.info("TaskQueue inicializado", db_path=self.db_path)
    
    @contextmanager
    def _get_connection(self):
        """
        Context manager para conexões SQLite.
        Garante que a conexão seja fechada após uso.
        """
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    async def _run_sync(self, func, *args):
        """Executa função síncrona em thread pool"""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, func, *args)
    
    def _init_database(self):
        """Cria tabelas se não existirem (Síncrono pois é chamado no init)"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # Tabela principal de tarefas
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    user_message TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    models TEXT,
                    attached_files TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    result TEXT,
                    error TEXT,
                    tool_calls TEXT,
                    progress TEXT
                )
            """)
            
            # Índices para consultas comuns
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_conversation 
                ON tasks(conversation_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_status 
                ON tasks(status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_created 
                ON tasks(created_at)
            """)
    
    def _task_to_row(self, task: Task) -> dict:
        """Converte Task para dict para inserção no banco"""
        return {
            "id": task.id,
            "conversation_id": task.conversation_id,
            "user_message": task.user_message,
            "status": task.status.value,
            "models": json.dumps(task.models),
            "attached_files": json.dumps(task.attached_files),
            "created_at": task.created_at.isoformat(),
            "started_at": task.started_at.isoformat() if task.started_at else None,
            "completed_at": task.completed_at.isoformat() if task.completed_at else None,
            "result": task.result,
            "error": task.error,
            "tool_calls": json.dumps(task.tool_calls) if task.tool_calls else None,
            "progress": json.dumps([p.model_dump() for p in task.progress])
        }
    
    def _row_to_task(self, row: sqlite3.Row) -> Task:
        """Converte linha do banco para Task"""
        progress_data = json.loads(row["progress"]) if row["progress"] else []
        progress_list = [TaskProgress(**p) for p in progress_data]
        
        return Task(
            id=row["id"],
            conversation_id=row["conversation_id"],
            user_message=row["user_message"],
            status=TaskStatus(row["status"]),
            models=json.loads(row["models"]) if row["models"] else {},
            attached_files=json.loads(row["attached_files"]) if row["attached_files"] else [],
            created_at=datetime.fromisoformat(row["created_at"]),
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            result=row["result"],
            error=row["error"],
            tool_calls=json.loads(row["tool_calls"]) if row["tool_calls"] else None,
            progress=progress_list
        )
    
    # -------------------------------------------------------------
    # Métodos Síncronos (Execução Real)
    # -------------------------------------------------------------
    
    def _create_task_sync(self, task: Task) -> None:
        row_data = self._task_to_row(task)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO tasks (
                    id, conversation_id, user_message, status, models,
                    attached_files, created_at, started_at, completed_at,
                    result, error, tool_calls, progress
                ) VALUES (
                    :id, :conversation_id, :user_message, :status, :models,
                    :attached_files, :created_at, :started_at, :completed_at,
                    :result, :error, :tool_calls, :progress
                )
            """, row_data)

    def _get_task_sync(self, task_id: str) -> Optional[Task]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_task(row)
            return None

    def _list_tasks_by_conversation_sync(self, conversation_id: str, limit: int) -> List[Task]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM tasks 
                WHERE conversation_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (conversation_id, limit))
            rows = cursor.fetchall()
            return [self._row_to_task(row) for row in rows]

    def _get_pending_tasks_sync(self, limit: int) -> List[Task]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM tasks 
                WHERE status = ?
                ORDER BY created_at ASC
                LIMIT ?
            """, (TaskStatus.PENDING.value, limit))
            rows = cursor.fetchall()
            return [self._row_to_task(row) for row in rows]

    def _claim_task_sync(self, task_id: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE tasks 
                SET status = ?, started_at = ?
                WHERE id = ? AND status = ?
            """, (
                TaskStatus.PROCESSING.value,
                datetime.utcnow().isoformat(),
                task_id,
                TaskStatus.PENDING.value
            ))
            return cursor.rowcount > 0

    def _update_task_status_sync(
        self, 
        task_id: str, 
        status: TaskStatus, 
        result: Optional[str], 
        error: Optional[str], 
        tool_calls: Optional[List[dict]]
    ) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            updates = ["status = ?"]
            params = [status.value]
            
            if status in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                updates.append("completed_at = ?")
                params.append(datetime.utcnow().isoformat())
            
            if result is not None:
                updates.append("result = ?")
                params.append(result)
            
            if error is not None:
                updates.append("error = ?")
                params.append(error)
            
            if tool_calls is not None:
                updates.append("tool_calls = ?")
                params.append(json.dumps(tool_calls))
            
            params.append(task_id)
            
            cursor.execute(f"""
                UPDATE tasks 
                SET {', '.join(updates)}
                WHERE id = ?
            """, params)
            return cursor.rowcount > 0

    def _add_progress_sync(self, task_id: str, message: str, step_type: str) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT progress FROM tasks WHERE id = ?", (task_id,))
            row = cursor.fetchone()
            if not row:
                return False
            
            current_progress = json.loads(row["progress"]) if row["progress"] else []
            current_progress.append({
                "timestamp": datetime.utcnow().isoformat(),
                "message": message,
                "step_type": step_type
            })
            
            cursor.execute("UPDATE tasks SET progress = ? WHERE id = ?", (json.dumps(current_progress), task_id))
            return cursor.rowcount > 0

    def _get_active_tasks_sync(self) -> List[Task]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM tasks 
                WHERE status IN (?, ?)
                ORDER BY created_at ASC
            """, (TaskStatus.PENDING.value, TaskStatus.PROCESSING.value))
            rows = cursor.fetchall()
            return [self._row_to_task(row) for row in rows]

    def _cleanup_old_tasks_sync(self, hours: int) -> int:
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM tasks 
                WHERE status IN (?, ?, ?)
                AND completed_at < ?
            """, (
                TaskStatus.COMPLETED.value,
                TaskStatus.FAILED.value,
                TaskStatus.CANCELLED.value,
                cutoff.isoformat()
            ))
            return cursor.rowcount
            
    def _reset_stuck_tasks_sync(self) -> int:
        """Reseta tarefas que ficaram presas em 'processing' (após crash)"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Marca como falha qualquer tarefa que estava 'processing'
            # Assumimos que se o servidor reiniciou, o processamento morreu
            cursor.execute("""
                UPDATE tasks 
                SET status = ?, error = ?, completed_at = ?
                WHERE status = ?
            """, (
                TaskStatus.FAILED.value,
                "Processamento interrompido (Servidor reiniciado)",
                datetime.utcnow().isoformat(),
                TaskStatus.PROCESSING.value
            ))
            if cursor.rowcount > 0:
                logger.warning(f"Resetadas {cursor.rowcount} tarefas presas em 'processing'")
            return cursor.rowcount

    # -------------------------------------------------------------
    # Wrappers Async (Não-bloqueantes)
    # -------------------------------------------------------------

    async def create_task(
        self,
        conversation_id: str,
        user_message: str,
        models: Dict[str, str],
        attached_files: Optional[List[str]] = None
    ) -> Task:
        task = Task(
            conversation_id=conversation_id,
            user_message=user_message,
            models=models,
            attached_files=attached_files or []
        )
        await self._run_sync(self._create_task_sync, task)
        logger.info("Tarefa criada", task_id=task.id)
        return task
    
    async def get_task(self, task_id: str) -> Optional[Task]:
        return await self._run_sync(self._get_task_sync, task_id)
    
    async def list_tasks_by_conversation(self, conversation_id: str, limit: int = 50) -> List[Task]:
        return await self._run_sync(self._list_tasks_by_conversation_sync, conversation_id, limit)
    
    async def get_pending_tasks(self, limit: int = 10) -> List[Task]:
        return await self._run_sync(self._get_pending_tasks_sync, limit)
    
    async def claim_task(self, task_id: str) -> bool:
        result = await self._run_sync(self._claim_task_sync, task_id)
        if result:
            logger.info("Tarefa claimed", task_id=task_id)
        return result
    
    async def update_task_status(
        self,
        task_id: str,
        status: TaskStatus,
        result: Optional[str] = None,
        error: Optional[str] = None,
        tool_calls: Optional[List[dict]] = None
    ) -> bool:
        updated = await self._run_sync(
            self._update_task_status_sync, 
            task_id, status, result, error, tool_calls
        )
        if updated:
            logger.info("Status atualizado", task_id=task_id, status=status.value)
        return updated
    
    async def add_progress(self, task_id: str, message: str, step_type: str = "info") -> bool:
        return await self._run_sync(self._add_progress_sync, task_id, message, step_type)
    
    async def get_active_tasks(self) -> List[Task]:
        return await self._run_sync(self._get_active_tasks_sync)
    
    async def cleanup_old_tasks(self, hours: int = 24) -> int:
        deleted = await self._run_sync(self._cleanup_old_tasks_sync, hours)
        if deleted > 0:
            logger.info("Limpeza efetuada", count=deleted)
        return deleted
        
    async def reset_stuck_tasks(self) -> int:
        return await self._run_sync(self._reset_stuck_tasks_sync)
    
    async def cancel_task(self, task_id: str) -> bool:
        return await self.update_task_status(
            task_id,
            TaskStatus.CANCELLED,
            error="Cancelada pelo usuário"
        )

# -------------------------------------------------
# Singleton para uso global
# -------------------------------------------------
_task_queue: Optional[TaskQueue] = None

def get_task_queue() -> TaskQueue:
    global _task_queue
    if _task_queue is None:
        _task_queue = TaskQueue()
    return _task_queue

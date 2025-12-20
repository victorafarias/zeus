"""
=====================================================
ZEUS - API de Tarefas
Endpoints REST para consultar status de tarefas
=====================================================
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

from config import get_logger
from api.auth import get_current_user, UserInfo
from services.task_queue import get_task_queue, Task, TaskStatus

# -------------------------------------------------
# Configuração
# -------------------------------------------------
router = APIRouter()
logger = get_logger(__name__)


# -------------------------------------------------
# Modelos de Resposta
# -------------------------------------------------
class TaskProgressResponse(BaseModel):
    """Progresso de uma tarefa"""
    timestamp: datetime
    message: str
    step_type: str


class TaskResponse(BaseModel):
    """Resposta de uma tarefa"""
    id: str
    conversation_id: str
    user_message: str
    status: str
    created_at: datetime
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    result: Optional[str]
    error: Optional[str]
    tool_calls: Optional[List[dict]]
    progress: List[TaskProgressResponse]


class TaskListResponse(BaseModel):
    """Lista de tarefas"""
    tasks: List[TaskResponse]
    total: int


class ActiveTasksResponse(BaseModel):
    """Tarefas ativas do sistema"""
    pending: int
    processing: int
    tasks: List[TaskResponse]


# -------------------------------------------------
# Funções auxiliares
# -------------------------------------------------
def task_to_response(task: Task) -> TaskResponse:
    """Converte Task para TaskResponse"""
    return TaskResponse(
        id=task.id,
        conversation_id=task.conversation_id,
        user_message=task.user_message[:200],  # Limitar tamanho
        status=task.status.value,
        created_at=task.created_at,
        started_at=task.started_at,
        completed_at=task.completed_at,
        result=task.result,
        error=task.error,
        tool_calls=task.tool_calls,
        progress=[
            TaskProgressResponse(
                timestamp=p.timestamp,
                message=p.message,
                step_type=p.step_type
            )
            for p in task.progress
        ]
    )


# -------------------------------------------------
# Endpoints
# -------------------------------------------------
@router.get("/{conversation_id}", response_model=TaskListResponse)
async def list_conversation_tasks(
    conversation_id: str,
    limit: int = 20,
    user: UserInfo = Depends(get_current_user)
):
    """
    Lista tarefas de uma conversa específica.
    
    Args:
        conversation_id: ID da conversa
        limit: Máximo de tarefas a retornar (padrão: 20)
        
    Returns:
        Lista de tarefas da conversa
    """
    task_queue = get_task_queue()
    tasks = await task_queue.list_tasks_by_conversation(conversation_id, limit)
    
    return TaskListResponse(
        tasks=[task_to_response(t) for t in tasks],
        total=len(tasks)
    )


@router.get("/{conversation_id}/{task_id}", response_model=TaskResponse)
async def get_task_status(
    conversation_id: str,
    task_id: str,
    user: UserInfo = Depends(get_current_user)
):
    """
    Obtém status detalhado de uma tarefa específica.
    
    Args:
        conversation_id: ID da conversa
        task_id: ID da tarefa
        
    Returns:
        Detalhes da tarefa
    """
    task_queue = get_task_queue()
    task = await task_queue.get_task(task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    
    if task.conversation_id != conversation_id:
        raise HTTPException(status_code=403, detail="Tarefa não pertence a esta conversa")
    
    return task_to_response(task)


@router.delete("/{conversation_id}/{task_id}")
async def cancel_task(
    conversation_id: str,
    task_id: str,
    user: UserInfo = Depends(get_current_user)
):
    """
    Cancela uma tarefa pendente.
    
    Só é possível cancelar tarefas com status 'pending'.
    Tarefas em processamento não podem ser canceladas por esta API.
    
    Args:
        conversation_id: ID da conversa
        task_id: ID da tarefa
        
    Returns:
        Mensagem de confirmação
    """
    task_queue = get_task_queue()
    task = await task_queue.get_task(task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    
    if task.conversation_id != conversation_id:
        raise HTTPException(status_code=403, detail="Tarefa não pertence a esta conversa")
    
    if task.status != TaskStatus.PENDING:
        raise HTTPException(
            status_code=400, 
            detail=f"Não é possível cancelar tarefa com status '{task.status.value}'"
        )
    
    success = await task_queue.cancel_task(task_id)
    
    if not success:
        raise HTTPException(status_code=500, detail="Erro ao cancelar tarefa")
    
    logger.info("Tarefa cancelada via API", task_id=task_id)
    
    return {"message": "Tarefa cancelada com sucesso"}


@router.get("/active/all", response_model=ActiveTasksResponse)
async def get_active_tasks(
    user: UserInfo = Depends(get_current_user)
):
    """
    Obtém todas as tarefas ativas do sistema.
    
    Útil para monitoramento e debug.
    
    Returns:
        Contagem e lista de tarefas ativas
    """
    task_queue = get_task_queue()
    tasks = await task_queue.get_active_tasks()
    
    pending = sum(1 for t in tasks if t.status == TaskStatus.PENDING)
    processing = sum(1 for t in tasks if t.status == TaskStatus.PROCESSING)
    
    return ActiveTasksResponse(
        pending=pending,
        processing=processing,
        tasks=[task_to_response(t) for t in tasks]
    )

from typing import Dict, Any
from .base import BaseTool, ToolParameter

class FinishTaskTool(BaseTool):
    """
    Tool para finalizar explicitamente uma tarefa.
    Deve ser usada quando o agente tiver concluído TODO o trabalho solicitado.
    """
    
    name = "finish_task"
    description = "Finaliza a tarefa atual. Use APENAS quando todo o trabalho estiver concluído e verificado."
    
    parameters = [
        ToolParameter(
            name="result",
            type="string",
            description="O resultado final da tarefa ou um resumo do que foi feito.",
            required=True
        )
    ]
        
    async def execute(self, result: str, **kwargs) -> Dict[str, Any]:
        """
        Executa a finalização da tarefa.
        
        Args:
            result: O resultado final
            
        Returns:
            Sucesso e o resultado
        """
        return {
            "success": True,
            "output": f"Tarefa finalizada: {result}",
            "task_completed": True  # Marcador especial para o orquestrador
        }

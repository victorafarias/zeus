"""

=====================================================
ZEUS - Tool para Chamar Modelos Externos (Mago)
Permite ao orquestrador local delegar tarefas complexas
ao modelo mais poderoso selecionado no "Mago"
=====================================================
"""

from typing import Dict, Any, Optional
from agent.tools.base import BaseTool, ToolParameter
from agent.openrouter_client import get_openrouter_client
from config import get_logger

logger = get_logger(__name__)


class ExternalModelTool(BaseTool):
    """
    Tool para chamar o modelo do Mago via OpenRouter.
    
    O Mago é o modelo mais poderoso selecionado pelo usuário,
    usado apenas quando tarefas requerem inteligência superior
    ou como última tentativa para resolver problemas complexos.
    """
    
    name = "call_external_model"
    description = """Chama o modelo do Mago (modelo mais poderoso configurado) para tarefas complexas.
Use APENAS quando a tarefa requer:
- Raciocínio lógico muito complexo ou matemática avançada
- Análise profunda de código ou debugging difícil
- Escrita criativa de alta qualidade
- Conhecimento técnico especializado que você não possui
- Última tentativa após outras abordagens falharem

NÃO use para:
- Tarefas simples que você pode resolver
- Execução de comandos ou operações com arquivos
- Busca em RAG ou operações locais

IMPORTANTE: Este modelo é o mais caro, use com moderação."""

    parameters = [
        ToolParameter(
            name="task_description",
            type="string",
            description="Descrição clara e detalhada da tarefa para o Mago",
            required=True
        ),
        ToolParameter(
            name="context",
            type="string",
            description="Contexto adicional relevante (código, dados, histórico)",
            required=False
        )
    ]
    
    # Modelo padrão de fallback caso não seja injetado pelo orquestrador
    DEFAULT_MODEL = "anthropic/claude-3.5-sonnet"
    
    async def execute(
        self,
        task_description: str,
        context: str = "",
        mago_model: str = None,  # Injetado pelo orquestrador
        **kwargs
    ) -> Dict[str, Any]:
        """
        Executa chamada para o modelo do Mago.
        
        Args:
            task_description: Descrição da tarefa
            context: Contexto adicional
            mago_model: Modelo do Mago (injetado pelo orquestrador)
            
        Returns:
            Resposta do modelo Mago
        """
        try:
            # Usar modelo injetado ou fallback para o padrão
            model = mago_model or self.DEFAULT_MODEL
            
            logger.info(
                "Chamando modelo do Mago",
                model=model,
                task_length=len(task_description)
            )
            
            # Construir prompt
            system_prompt = """Você é o Mago, um modelo de IA extremamente poderoso sendo consultado por outro agente de IA.
Sua expertise está sendo requisitada para uma tarefa complexa que requer inteligência superior.
Responda de forma direta e técnica. Forneça a resposta mais útil e completa possível.
Lembre-se: você foi chamado porque a tarefa é desafiadora - demonstre todo seu potencial."""

            user_prompt = task_description
            if context:
                user_prompt = f"{task_description}\n\n### Contexto:\n{context}"
            
            # Preparar mensagens
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
            
            # Chamar OpenRouter
            client = get_openrouter_client()
            response = await client.chat_completion(
                messages=messages,
                model=model,
                temperature=0.7,
                max_tokens=4096
            )
            
            result_content = response.get("content", "")
            
            logger.info(
                "Resposta do Mago recebida",
                model=model,
                response_length=len(result_content)
            )
            
            return {
                "success": True,
                "output": result_content,
                "model_used": model
            }
            
        except Exception as e:
            logger.error(
                "Erro ao chamar modelo do Mago",
                error=str(e)
            )
            return {
                "success": False,
                "error": f"Falha ao consultar o Mago: {str(e)}"
            }


# Função para registrar a tool
def get_external_model_tool() -> Dict[str, Any]:
    """Retorna definição da tool para registro"""
    tool = ExternalModelTool()
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters
        }
    }


# Instância singleton
_tool_instance: Optional[ExternalModelTool] = None


def get_tool_instance() -> ExternalModelTool:
    """Retorna instância singleton da tool"""
    global _tool_instance
    if _tool_instance is None:
        _tool_instance = ExternalModelTool()
    return _tool_instance

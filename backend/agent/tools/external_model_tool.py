"""

=====================================================
ZEUS - Tool para Chamar Modelos Externos (OpenRouter)
Permite ao orquestrador local delegar tarefas complexas
=====================================================
"""

from typing import Dict, Any, Optional
from agent.tools.base import BaseTool
from agent.openrouter_client import get_openrouter_client
from config import get_logger

logger = get_logger(__name__)


class ExternalModelTool(BaseTool):
    """
    Tool para chamar modelos externos via OpenRouter.
    
    Usada quando o orquestrador local (Llama 3.1) precisa de:
    - Raciocínio mais complexo
    - Conhecimento especializado
    - Tarefas criativas avançadas
    """
    
    name = "call_external_model"
    description = """Chama um modelo de IA externo mais poderoso (GPT-4, Claude, etc) para tarefas complexas.
Use APENAS quando a tarefa requer:
- Raciocínio lógico muito complexo ou matemática avançada
- Análise profunda de código ou debugging difícil
- Escrita criativa de alta qualidade
- Conhecimento técnico especializado que você não possui

NÃO use para:
- Tarefas simples que você pode resolver
- Execução de comandos ou operações com arquivos
- Busca em RAG ou operações locais"""

    parameters = {
        "type": "object",
        "properties": {
            "task_description": {
                "type": "string",
                "description": "Descrição clara e detalhada da tarefa para o modelo externo"
            },
            "context": {
                "type": "string",
                "description": "Contexto adicional relevante (código, dados, histórico)"
            },
            "model_preference": {
                "type": "string",
                "description": "Preferência de modelo: 'gpt4' para lógica/código, 'claude' para escrita/análise",
                "enum": ["gpt4", "claude", "auto"],
                "default": "auto"
            }
        },
        "required": ["task_description"]
    }
    
    # Mapeamento de preferências para modelos
    MODEL_MAP = {
        "gpt4": "openai/gpt-4o",
        "claude": "anthropic/claude-3.5-sonnet",
        "auto": "openai/gpt-4o"  # Padrão
    }
    
    async def execute(
        self,
        task_description: str,
        context: str = "",
        model_preference: str = "auto",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Executa chamada para modelo externo.
        
        Args:
            task_description: Descrição da tarefa
            context: Contexto adicional
            model_preference: Qual modelo preferir
            
        Returns:
            Resposta do modelo externo
        """
        try:
            logger.info(
                "Chamando modelo externo",
                preference=model_preference,
                task_length=len(task_description)
            )
            
            # Selecionar modelo
            model = self.MODEL_MAP.get(model_preference, self.MODEL_MAP["auto"])
            
            # Construir prompt
            system_prompt = """Você é um assistente especializado sendo consultado por outro agente de IA.
Responda de forma direta e técnica. O agente que te chamou precisa de ajuda com uma tarefa específica.
Forneça a resposta mais útil e completa possível."""

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
                "Resposta do modelo externo recebida",
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
                "Erro ao chamar modelo externo",
                error=str(e)
            )
            return {
                "success": False,
                "error": f"Falha ao consultar modelo externo: {str(e)}"
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

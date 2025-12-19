"""
=====================================================
ZEUS - Tools do Agente
Pacote com todas as ferramentas disponíveis
=====================================================
"""

from typing import Dict, Any, List, Optional
from .base import BaseTool
from .python_executor import PythonExecutorTool
from .shell_executor import ShellExecutorTool
from .docker_manager import DockerListTool, DockerCreateTool, DockerRemoveTool
from .file_manager import ReadFileTool, WriteFileTool
from .media_processor import TranscribeMediaTool
from .search_procedures import SearchProceduresTool
from .tts_tool import TextToSpeechTool

from config import get_logger

logger = get_logger(__name__)

# -------------------------------------------------
# Registro de Tools
# -------------------------------------------------

# Lista de todas as tools disponíveis
TOOLS: List[BaseTool] = [
    PythonExecutorTool(),
    ShellExecutorTool(),
    DockerListTool(),
    DockerCreateTool(),
    DockerRemoveTool(),
    ReadFileTool(),
    WriteFileTool(),
    TranscribeMediaTool(),
    SearchProceduresTool(),
    TextToSpeechTool(),
]

# Dicionário para acesso rápido por nome
TOOLS_BY_NAME: Dict[str, BaseTool] = {
    tool.name: tool for tool in TOOLS
}


def get_all_tools() -> List[Dict[str, Any]]:
    """
    Retorna definição de todas as tools no formato OpenAI.
    
    Returns:
        Lista de dicionários com definição das tools
    """
    return [tool.to_openai_tool() for tool in TOOLS]


async def execute_tool(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executa uma tool pelo nome.
    
    Args:
        name: Nome da tool
        args: Argumentos para a tool
        
    Returns:
        Resultado da execução
    """
    tool = TOOLS_BY_NAME.get(name)
    
    if not tool:
        logger.error("Tool não encontrada", name=name)
        return {
            "success": False,
            "error": f"Tool não encontrada: {name}"
        }
    
    try:
        return await tool.execute(**args)
    except Exception as e:
        logger.error("Erro ao executar tool", name=name, error=str(e))
        return {
            "success": False,
            "error": str(e)
        }

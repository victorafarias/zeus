"""
=====================================================
ZEUS - Search Procedures Tool
Busca procedimentos anteriores no RAG
=====================================================
"""

from typing import Dict, Any, List

from .base import BaseTool, ToolParameter
from config import get_logger

logger = get_logger(__name__)


class SearchProceduresTool(BaseTool):
    """Busca procedimentos anteriores no banco de conhecimento"""
    
    name = "search_procedures"
    description = """Busca procedimentos e soluções anteriores no banco de conhecimento.
Use para: encontrar soluções já aplicadas, recuperar comandos usados anteriormente,
buscar referências de tarefas similares."""
    
    parameters = [
        ToolParameter(
            name="query",
            type="string",
            description="Texto de busca descrevendo o que procura"
        ),
        ToolParameter(
            name="max_results",
            type="integer",
            description="Número máximo de resultados (padrão: 5)",
            required=False
        ),
        ToolParameter(
            name="tool_filter",
            type="string",
            description="Filtrar por ferramenta específica (ex: execute_python, execute_shell)",
            required=False
        )
    ]
    
    async def execute(
        self,
        query: str,
        max_results: int = 5,
        tool_filter: str = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Busca procedimentos no RAG"""
        try:
            from services.rag_service import get_rag_service
            
            rag = get_rag_service()
            procedures = await rag.search_procedures(
                query=query,
                n_results=max_results,
                tool_filter=tool_filter
            )
            
            if not procedures:
                return self._success(
                    "Nenhum procedimento encontrado para essa busca.\n"
                    "Tente termos diferentes ou mais genéricos."
                )
            
            # Formatar resultado
            lines = [f"Encontrados {len(procedures)} procedimentos relevantes:\n"]
            
            for i, proc in enumerate(procedures, 1):
                relevance = int(proc.get('relevance', 0) * 100)
                lines.append(f"### {i}. (Relevância: {relevance}%)")
                lines.append(proc['content'][:500])
                if proc.get('tool_used'):
                    lines.append(f"\n*Ferramenta usada: {proc['tool_used']}*")
                lines.append("\n---\n")
            
            logger.info("Busca de procedimentos", query=query[:50], results=len(procedures))
            return self._success("\n".join(lines))
            
        except Exception as e:
            logger.error("Erro na busca de procedimentos", error=str(e))
            return self._error(f"Erro na busca: {str(e)}")

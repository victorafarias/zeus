"""
=====================================================
ZEUS - RAG Manager Tool
Gerencia registros da base RAG (adicionar, listar, excluir)
=====================================================
"""

from typing import Dict, Any, List

from .base import BaseTool, ToolParameter
from config import get_logger

logger = get_logger(__name__)


class RAGManagerTool(BaseTool):
    """
    Gerencia registros da base de conhecimento RAG (ChromaDB).
    
    Permite adicionar, listar, excluir procedimentos e obter estatísticas.
    A busca semântica continua disponível via tool 'search_procedures'.
    """
    
    name = "manage_rag"
    description = """Gerencia a base de conhecimento RAG (memória de longo prazo).
Use para:
- Adicionar novos procedimentos e soluções ao banco
- Listar todos os procedimentos armazenados
- Excluir registros específicos por ID
- Obter estatísticas da base
NOTA: Para busca semântica, use a tool 'search_procedures'."""
    
    parameters = [
        ToolParameter(
            name="action",
            type="string",
            description="Ação a executar: 'add', 'list', 'delete', 'stats'",
            enum=["add", "list", "delete", "stats"]
        ),
        ToolParameter(
            name="id",
            type="string",
            description="ID do registro a excluir (apenas para action='delete')",
            required=False
        ),
        ToolParameter(
            name="description",
            type="string",
            description="Descrição do problema/tarefa (para action='add')",
            required=False
        ),
        ToolParameter(
            name="solution",
            type="string",
            description="Solução aplicada (para action='add')",
            required=False
        ),
        ToolParameter(
            name="tool_used",
            type="string",
            description="Nome da ferramenta usada (para action='add')",
            required=False
        ),
        ToolParameter(
            name="tags",
            type="array",
            description="Lista de tags para categorização (para action='add')",
            required=False,
            items={"type": "string"}  # Especifica que o array contém strings
        ),
        ToolParameter(
            name="limit",
            type="integer",
            description="Número máximo de resultados para listagem (padrão: 20)",
            required=False
        ),
        ToolParameter(
            name="collection",
            type="string",
            description="Coleção a gerenciar: 'procedures' ou 'conversations' (padrão: 'procedures')",
            required=False,
            enum=["procedures", "conversations"]
        )
    ]
    
    async def execute(
        self,
        action: str,
        id: str = None,
        description: str = None,
        solution: str = None,
        tool_used: str = None,
        tags: List[str] = None,
        limit: int = 20,
        collection: str = "procedures",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Executa ação de gerenciamento na base RAG.
        
        Args:
            action: Ação a executar
            id: ID do registro (para delete)
            description: Descrição do problema (para add)
            solution: Solução aplicada (para add)
            tool_used: Ferramenta usada (para add)
            tags: Tags de categorização (para add)
            limit: Limite de resultados (para list)
            collection: Coleção alvo (procedures ou conversations)
            
        Returns:
            Resultado da operação
        """
        try:
            # Importar serviço RAG
            from services.rag_service import get_rag_service
            rag = get_rag_service()
            
            # -------------------------------------------------
            # Action: ADD (adicionar procedimento)
            # -------------------------------------------------
            if action == "add":
                if not description:
                    return self._error("Parâmetro 'description' é obrigatório para adicionar")
                if not solution:
                    return self._error("Parâmetro 'solution' é obrigatório para adicionar")
                if not tool_used:
                    return self._error("Parâmetro 'tool_used' é obrigatório para adicionar")
                
                doc_id = await rag.add_procedure(
                    description=description,
                    solution=solution,
                    tool_used=tool_used,
                    tags=tags or []
                )
                
                logger.info(
                    "Procedimento adicionado via tool",
                    id=doc_id,
                    tool=tool_used
                )
                
                return self._success(
                    f"✅ Procedimento adicionado com sucesso!\n"
                    f"**ID:** `{doc_id}`\n"
                    f"**Ferramenta:** {tool_used}\n"
                    f"**Tags:** {', '.join(tags) if tags else 'Nenhuma'}"
                )
            
            # -------------------------------------------------
            # Action: LIST (listar registros)
            # -------------------------------------------------
            elif action == "list":
                if collection == "procedures":
                    items = await rag.list_procedures(limit=limit)
                    item_type = "procedimentos"
                else:
                    items = await rag.list_conversations(limit=limit)
                    item_type = "conversas"
                
                if not items:
                    return self._success(f"Nenhum(a) {item_type} encontrado(a) na base.")
                
                # Formatar saída
                lines = [f"📋 **{len(items)} {item_type} encontrado(s):**\n"]
                
                for i, item in enumerate(items, 1):
                    lines.append(f"### {i}. ID: `{item['id']}`")
                    
                    if collection == "procedures":
                        lines.append(f"**Ferramenta:** {item.get('tool_used', 'N/A')}")
                        if item.get('tags'):
                            lines.append(f"**Tags:** {', '.join(item['tags'])}")
                        lines.append(f"**Conteúdo:** {item.get('content', 'N/A')}")
                    else:
                        lines.append(f"**Resumo:** {item.get('summary', 'N/A')}")
                        if item.get('topics'):
                            lines.append(f"**Tópicos:** {', '.join(item['topics'])}")
                    
                    lines.append("---")
                
                logger.info(
                    "Listagem RAG via tool",
                    collection=collection,
                    count=len(items)
                )
                
                return self._success("\n".join(lines))
            
            # -------------------------------------------------
            # Action: DELETE (excluir registro)
            # -------------------------------------------------
            elif action == "delete":
                if not id:
                    return self._error("Parâmetro 'id' é obrigatório para excluir")
                
                if collection == "procedures":
                    success = await rag.delete_procedure(id)
                    item_type = "Procedimento"
                else:
                    success = await rag.delete_conversation(id)
                    item_type = "Conversa"
                
                if success:
                    logger.info(
                        "Registro RAG excluído via tool",
                        id=id,
                        collection=collection
                    )
                    return self._success(f"✅ {item_type} `{id}` excluído(a) com sucesso!")
                else:
                    return self._error(f"Falha ao excluir {item_type.lower()} `{id}`")
            
            # -------------------------------------------------
            # Action: STATS (estatísticas)
            # -------------------------------------------------
            elif action == "stats":
                stats = rag.get_stats()
                
                return self._success(
                    f"📊 **Estatísticas do RAG:**\n\n"
                    f"**Procedimentos:** {stats['procedures_count']}\n"
                    f"**Conversas:** {stats['conversations_count']}\n"
                    f"**Total de registros:** {stats['procedures_count'] + stats['conversations_count']}"
                )
            
            else:
                return self._error(f"Ação desconhecida: {action}")
        
        except Exception as e:
            logger.error("Erro no gerenciamento RAG", action=action, error=str(e))
            return self._error(f"Erro ao executar '{action}': {str(e)}")

"""
=====================================================
ZEUS - Serviço RAG (Retrieval Augmented Generation)
Memória de longo prazo usando ChromaDB
=====================================================
"""

from typing import List, Dict, Any, Optional
import chromadb
from chromadb.config import Settings
import hashlib
import json

from config import get_settings, get_logger

logger = get_logger(__name__)
settings = get_settings()

# Cliente ChromaDB singleton
_client: Optional[chromadb.PersistentClient] = None


def get_chroma_client() -> chromadb.PersistentClient:
    """
    Retorna cliente ChromaDB persistente.
    
    Returns:
        Cliente ChromaDB configurado
    """
    global _client
    
    if _client is None:
        _client = chromadb.PersistentClient(
            path=settings.chromadb_dir,
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )
        logger.info("ChromaDB inicializado", path=settings.chromadb_dir)
    
    return _client


class RAGService:
    """
    Serviço de RAG para recuperar contexto relevante.
    
    Armazena e recupera:
    - Procedimentos executados anteriormente
    - Soluções para problemas comuns
    - Histórico de conversas importantes
    """
    
    # Nome das coleções
    PROCEDURES_COLLECTION = "procedures"
    CONVERSATIONS_COLLECTION = "conversations"
    
    def __init__(self):
        """Inicializa o serviço RAG"""
        self.client = get_chroma_client()
        
        # Obter ou criar coleções
        self.procedures = self.client.get_or_create_collection(
            name=self.PROCEDURES_COLLECTION,
            metadata={"description": "Procedimentos e soluções executados"}
        )
        
        self.conversations = self.client.get_or_create_collection(
            name=self.CONVERSATIONS_COLLECTION,
            metadata={"description": "Histórico de conversas importantes"}
        )
        
        logger.info(
            "RAG Service inicializado",
            procedures_count=self.procedures.count(),
            conversations_count=self.conversations.count()
        )
    
    def _generate_id(self, content: str) -> str:
        """Gera ID único baseado no conteúdo"""
        return hashlib.md5(content.encode()).hexdigest()
    
    async def add_procedure(
        self,
        description: str,
        solution: str,
        tool_used: str,
        tags: List[str] = None,
        metadata: Dict[str, Any] = None
    ) -> str:
        """
        Adiciona um procedimento executado ao banco de conhecimento.
        
        Args:
            description: Descrição do problema/tarefa
            solution: Solução aplicada
            tool_used: Ferramenta usada
            tags: Tags para categorização
            metadata: Metadados adicionais
            
        Returns:
            ID do procedimento adicionado
        """
        # Texto combinado para embedding
        full_text = f"{description}\n\nSolução: {solution}\n\nFerramenta: {tool_used}"
        
        # Gerar ID único
        doc_id = self._generate_id(full_text)
        
        # Preparar metadados
        meta = {
            "tool_used": tool_used,
            "tags": json.dumps(tags or []),
            **(metadata or {})
        }
        
        try:
            # Adicionar ao ChromaDB
            self.procedures.add(
                documents=[full_text],
                metadatas=[meta],
                ids=[doc_id]
            )
            
            logger.info("Procedimento adicionado", id=doc_id, tool=tool_used)
            return doc_id
            
        except Exception as e:
            # Pode ser duplicado
            if "already exists" in str(e).lower():
                logger.debug("Procedimento já existe", id=doc_id)
                return doc_id
            raise
    
    async def search_procedures(
        self,
        query: str,
        n_results: int = 5,
        tool_filter: str = None
    ) -> List[Dict[str, Any]]:
        """
        Busca procedimentos similares à query.
        
        Args:
            query: Texto de busca
            n_results: Número máximo de resultados
            tool_filter: Filtrar por ferramenta específica
            
        Returns:
            Lista de procedimentos relevantes
        """
        try:
            # Preparar filtro
            where = None
            if tool_filter:
                where = {"tool_used": tool_filter}
            
            # Buscar
            results = self.procedures.query(
                query_texts=[query],
                n_results=n_results,
                where=where
            )
            
            # Formatar resultados
            procedures = []
            
            if results and results['documents']:
                for i, doc in enumerate(results['documents'][0]):
                    meta = results['metadatas'][0][i] if results['metadatas'] else {}
                    distance = results['distances'][0][i] if results['distances'] else 0
                    
                    procedures.append({
                        "id": results['ids'][0][i],
                        "content": doc,
                        "tool_used": meta.get("tool_used"),
                        "tags": json.loads(meta.get("tags", "[]")),
                        "relevance": 1 - distance  # Converter distância em relevância
                    })
            
            logger.debug(
                "Busca de procedimentos",
                query=query[:50],
                results=len(procedures)
            )
            
            return procedures
            
        except Exception as e:
            logger.error("Erro na busca de procedimentos", error=str(e))
            return []
    
    async def add_conversation_summary(
        self,
        conversation_id: str,
        summary: str,
        topics: List[str] = None
    ) -> str:
        """
        Adiciona resumo de conversa importante.
        
        Args:
            conversation_id: ID da conversa
            summary: Resumo da conversa
            topics: Tópicos abordados
            
        Returns:
            ID do documento
        """
        meta = {
            "conversation_id": conversation_id,
            "topics": json.dumps(topics or [])
        }
        
        try:
            self.conversations.add(
                documents=[summary],
                metadatas=[meta],
                ids=[conversation_id]
            )
            
            logger.info("Resumo de conversa adicionado", id=conversation_id)
            return conversation_id
            
        except Exception as e:
            if "already exists" in str(e).lower():
                # Atualizar existente
                self.conversations.update(
                    documents=[summary],
                    metadatas=[meta],
                    ids=[conversation_id]
                )
                return conversation_id
            raise
    
    async def search_conversations(
        self,
        query: str,
        n_results: int = 3
    ) -> List[Dict[str, Any]]:
        """
        Busca conversas relevantes.
        
        Args:
            query: Texto de busca
            n_results: Número máximo de resultados
            
        Returns:
            Lista de resumos de conversas
        """
        try:
            results = self.conversations.query(
                query_texts=[query],
                n_results=n_results
            )
            
            conversations = []
            
            if results and results['documents']:
                for i, doc in enumerate(results['documents'][0]):
                    meta = results['metadatas'][0][i] if results['metadatas'] else {}
                    
                    conversations.append({
                        "conversation_id": meta.get("conversation_id"),
                        "summary": doc,
                        "topics": json.loads(meta.get("topics", "[]"))
                    })
            
            return conversations
            
        except Exception as e:
            logger.error("Erro na busca de conversas", error=str(e))
            return []
    
    async def get_context_for_query(
        self,
        query: str,
        max_procedures: int = 3,
        max_conversations: int = 2
    ) -> str:
        """
        Obtém contexto completo para uma query.
        
        Combina procedimentos e conversas relevantes em um texto formatado.
        
        Args:
            query: Texto de busca
            max_procedures: Máximo de procedimentos
            max_conversations: Máximo de conversas
            
        Returns:
            Texto formatado com contexto
        """
        context_parts = []
        
        # Buscar procedimentos
        procedures = await self.search_procedures(query, max_procedures)
        if procedures:
            context_parts.append("### Procedimentos Anteriores Relevantes:\n")
            for i, proc in enumerate(procedures, 1):
                context_parts.append(f"{i}. {proc['content'][:500]}...")
                if proc['tool_used']:
                    context_parts.append(f"   *Ferramenta: {proc['tool_used']}*")
                context_parts.append("")
        
        # Buscar conversas
        convs = await self.search_conversations(query, max_conversations)
        if convs:
            context_parts.append("\n### Conversas Anteriores Relevantes:\n")
            for i, conv in enumerate(convs, 1):
                context_parts.append(f"{i}. {conv['summary'][:300]}...")
                context_parts.append("")
        
        if not context_parts:
            return ""
        
        return "\n".join(context_parts)
    
    async def list_procedures(
        self,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Lista todos os procedimentos armazenados.
        
        Args:
            limit: Número máximo de resultados
            
        Returns:
            Lista de todos os procedimentos
        """
        try:
            # ChromaDB get() retorna todos os documentos da coleção
            results = self.procedures.get(
                limit=limit,
                include=["documents", "metadatas"]
            )
            
            procedures = []
            if results and results['ids']:
                for i, doc_id in enumerate(results['ids']):
                    doc = results['documents'][i] if results['documents'] else ""
                    meta = results['metadatas'][i] if results['metadatas'] else {}
                    
                    procedures.append({
                        "id": doc_id,
                        "content": doc[:300] + "..." if len(doc) > 300 else doc,
                        "tool_used": meta.get("tool_used"),
                        "tags": json.loads(meta.get("tags", "[]"))
                    })
            
            logger.debug("Listagem de procedimentos", count=len(procedures))
            return procedures
            
        except Exception as e:
            logger.error("Erro ao listar procedimentos", error=str(e))
            return []
    
    async def delete_procedure(self, doc_id: str) -> bool:
        """
        Remove um procedimento pelo ID.
        
        Args:
            doc_id: ID do procedimento a remover
            
        Returns:
            True se removido com sucesso
        """
        try:
            self.procedures.delete(ids=[doc_id])
            logger.info("Procedimento removido", id=doc_id)
            return True
        except Exception as e:
            logger.error("Erro ao remover procedimento", id=doc_id, error=str(e))
            return False
    
    async def list_conversations(
        self,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Lista todas as conversas armazenadas.
        
        Args:
            limit: Número máximo de resultados
            
        Returns:
            Lista de todas as conversas
        """
        try:
            results = self.conversations.get(
                limit=limit,
                include=["documents", "metadatas"]
            )
            
            conversations = []
            if results and results['ids']:
                for i, doc_id in enumerate(results['ids']):
                    doc = results['documents'][i] if results['documents'] else ""
                    meta = results['metadatas'][i] if results['metadatas'] else {}
                    
                    conversations.append({
                        "id": doc_id,
                        "summary": doc[:300] + "..." if len(doc) > 300 else doc,
                        "conversation_id": meta.get("conversation_id"),
                        "topics": json.loads(meta.get("topics", "[]"))
                    })
            
            logger.debug("Listagem de conversas", count=len(conversations))
            return conversations
            
        except Exception as e:
            logger.error("Erro ao listar conversas", error=str(e))
            return []
    
    async def delete_conversation(self, conversation_id: str) -> bool:
        """
        Remove uma conversa pelo ID.
        
        Args:
            conversation_id: ID da conversa a remover
            
        Returns:
            True se removido com sucesso
        """
        try:
            self.conversations.delete(ids=[conversation_id])
            logger.info("Conversa removida", id=conversation_id)
            return True
        except Exception as e:
            logger.error("Erro ao remover conversa", id=conversation_id, error=str(e))
            return False
    
    def get_stats(self) -> Dict[str, int]:
        """Retorna estatísticas do RAG"""
        return {
            "procedures_count": self.procedures.count(),
            "conversations_count": self.conversations.count()
        }


# Singleton do serviço
_rag_service: Optional[RAGService] = None


def get_rag_service() -> RAGService:
    """Retorna instância singleton do RAGService"""
    global _rag_service
    
    if _rag_service is None:
        _rag_service = RAGService()
    
    return _rag_service

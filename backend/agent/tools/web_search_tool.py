"""
=====================================================
ZEUS - Tool de Busca na Web
Busca informações atuais na internet via OpenRouter
usando o modelo openai/gpt-4o-mini com web search
=====================================================
"""

from typing import Dict, Any
from agent.tools.base import BaseTool, ToolParameter
from agent.openrouter_client import get_openrouter_client
from config import get_logger

# -------------------------------------------------
# Configuração de Logger
# -------------------------------------------------
logger = get_logger(__name__)


class WebSearchTool(BaseTool):
    """
    Tool para buscar informações atuais na internet.
    
    Usa o modelo openai/gpt-4o-mini:online do OpenRouter,
    que ativa automaticamente a busca na web nativa do provedor.
    
    Ideal para:
    - Buscar notícias recentes
    - Verificar informações atualizadas
    - Pesquisar dados que mudam frequentemente
    - Obter informações sobre eventos recentes
    """
    
    # Nome da ferramenta (usado nas chamadas)
    name = "web_search"
    
    # Descrição para o modelo entender quando usar
    description = """Busca informações atuais e recentes na internet.
Use esta ferramenta quando precisar de:
- Notícias recentes ou atualizações
- Informações que mudam frequentemente (preços, cotações, etc)
- Dados sobre eventos recentes
- Verificar informações atualizadas (por ex,: últimas versões de softwares, bilbiotecas, aplicativos etc.)
- Pesquisar qualquer assunto que exija dados atuais

A ferramenta retorna informações com citação das fontes."""
    
    # Parâmetros aceitos pela ferramenta
    parameters = [
        ToolParameter(
            name="query",
            type="string",
            description="A consulta de busca para pesquisar na internet. Seja específico para obter melhores resultados.",
            required=True
        ),
        ToolParameter(
            name="context",
            type="string",
            description="Contexto adicional para refinar a busca (opcional). Ex: 'foco em fontes brasileiras' ou 'últimas 24 horas'",
            required=False
        )
    ]
    
    # Modelo usado para busca na web (com sufixo :online para ativar web search)
    # SEARCH_MODEL = "openai/gpt-4o-mini:online"
    SEARCH_MODEL = "deepseek/deepseek-chat-v3-0324:online"
    
    async def execute(
        self,
        query: str,
        context: str = "",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Executa uma busca na internet.
        
        Args:
            query: A consulta de busca
            context: Contexto adicional opcional
            
        Returns:
            Dicionário com resultado da busca ou erro
        """
        try:
            # Log inicial da operação
            logger.info(
                "Iniciando busca na web",
                query=query,
                context=context if context else "(sem contexto adicional)"
            )
            
            # Construir o prompt do sistema
            # Instruímos o modelo a buscar informações atuais e citar fontes
            system_prompt = """Você é um assistente de pesquisa especializado em buscar informações atuais na internet.

Importante: se na mensagem do usuário não houver um fuso horário especificado, use o fuso padrão UTC-3 de Brasília/DF no Brasil.

Suas responsabilidades:
1. Buscar informações recentes e relevantes sobre a consulta
2. Fornecer dados precisos e atualizados
3. SEMPRE citar as fontes das informações (URLs quando disponíveis)
4. Organizar a resposta de forma clara e estruturada
5. Indicar a data/período das informações quando relevante

Formato da resposta:
- Use markdown para formatação
- Liste as principais informações encontradas
- Inclua seção "Fontes:" ao final com os links utilizados"""

            # Construir o prompt do usuário
            user_prompt = f"Pesquise na internet: {query}"
            
            # Adicionar contexto se fornecido
            if context:
                user_prompt += f"\n\nContexto adicional: {context}"
            
            # Preparar mensagens para a API
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
            
            # Obter cliente OpenRouter
            client = get_openrouter_client()
            
            # Fazer chamada para o modelo com web search ativado
            # O sufixo :online ativa a busca na web nativa do OpenRouter
            logger.info(
                "Chamando OpenRouter com web search",
                model=self.SEARCH_MODEL
            )
            
            response = await client.chat_completion(
                messages=messages,
                model=self.SEARCH_MODEL,
                temperature=0.3,  # Temperatura baixa para respostas mais factuais
                max_tokens=4096
            )
            
            # Extrair conteúdo da resposta
            result_content = response.get("content", "")
            
            # Verificar se obtivemos resultado
            if not result_content:
                logger.warning(
                    "Busca na web retornou resultado vazio",
                    query=query
                )
                return self._error("A busca não retornou resultados. Tente reformular a consulta.")
            
            # Log de sucesso
            logger.info(
                "Busca na web concluída com sucesso",
                query=query,
                response_length=len(result_content)
            )
            
            # Retornar resultado formatado
            return {
                "success": True,
                "output": result_content,
                "model_used": self.SEARCH_MODEL,
                "query": query
            }
            
        except Exception as e:
            # Log do erro
            logger.error(
                "Erro na busca na web",
                query=query,
                error=str(e)
            )
            
            # Retornar erro formatado
            return self._error(f"Falha ao buscar na web: {str(e)}")

"""
=====================================================
ZEUS - Cliente OpenRouter
Wrapper para API OpenRouter usando SDK OpenAI
=====================================================
"""

from openai import AsyncOpenAI
from typing import List, Dict, Any, Optional, AsyncGenerator
import json

from config import get_settings, get_logger

# -------------------------------------------------
# Configuração
# -------------------------------------------------
logger = get_logger(__name__)
settings = get_settings()


class OpenRouterClient:
    """
    Cliente para API OpenRouter.
    
    Usa o SDK OpenAI que é compatível com OpenRouter.
    Suporta streaming e function calling.
    """
    
    def __init__(self):
        """Inicializa o cliente com configurações do .env"""
        self.client = AsyncOpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=settings.openrouter_api_key,
            default_headers={
                "HTTP-Referer": "https://zeus.ovictorfarias.com.br",
                "X-Title": "Zeus AI Agent"
            }
        )
        
        logger.info("Cliente OpenRouter inicializado")
    
    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        model: str = "openai/gpt-4",
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False,
        temperature: float = 0.7,
        max_tokens: int = 4096
    ) -> Dict[str, Any]:
        """
        Envia mensagens para o modelo e retorna resposta.
        
        Args:
            messages: Lista de mensagens no formato OpenAI
            model: ID do modelo (ex: openai/gpt-4)
            tools: Lista de ferramentas/funções disponíveis
            stream: Se True, retorna AsyncGenerator para streaming
            temperature: Criatividade da resposta (0-2)
            max_tokens: Máximo de tokens na resposta
            
        Returns:
            Resposta do modelo como dicionário
        """
        logger.info(
            "Enviando para OpenRouter",
            model=model,
            messages_count=len(messages),
            tools_count=len(tools) if tools else 0
        )
        
        try:
            # Preparar parâmetros
            params = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": stream
            }
            
            # Adicionar tools se fornecidas
            if tools:
                params["tools"] = tools
                params["tool_choice"] = "auto"
            
            # Fazer requisição
            response = await self.client.chat.completions.create(**params)
            
            # Processar resposta
            if stream:
                return response  # Retorna o generator para streaming
            
            # Resposta completa
            choice = response.choices[0]
            message = choice.message
            
            result = {
                "content": message.content or "",
                "role": message.role,
                "finish_reason": choice.finish_reason
            }
            
            # Adicionar tool_calls se existirem
            if message.tool_calls:
                result["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in message.tool_calls
                ]
            
            logger.info(
                "Resposta recebida",
                content_length=len(result["content"]),
                tool_calls_count=len(result.get("tool_calls", []))
            )
            
            return result
            
        except Exception as e:
            logger.error("Erro na requisição OpenRouter", error=str(e))
            raise
    
    async def chat_completion_stream(
        self,
        messages: List[Dict[str, Any]],
        model: str = "openai/gpt-4",
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Envia mensagens e retorna resposta em streaming.
        
        Yields:
            Chunks da resposta conforme são gerados
        """
        logger.info(
            "Iniciando streaming",
            model=model,
            messages_count=len(messages)
        )
        
        try:
            params = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True
            }
            
            if tools:
                params["tools"] = tools
                params["tool_choice"] = "auto"
            
            stream = await self.client.chat.completions.create(**params)
            
            async for chunk in stream:
                if chunk.choices:
                    delta = chunk.choices[0].delta
                    
                    yield {
                        "content": delta.content or "",
                        "tool_calls": delta.tool_calls if hasattr(delta, "tool_calls") else None,
                        "finish_reason": chunk.choices[0].finish_reason
                    }
            
            logger.info("Streaming concluído")
            
        except Exception as e:
            logger.error("Erro no streaming", error=str(e))
            raise


# Instância singleton do cliente
_client: Optional[OpenRouterClient] = None


def get_openrouter_client() -> OpenRouterClient:
    """Retorna instância singleton do cliente OpenRouter"""
    global _client
    
    if _client is None:
        _client = OpenRouterClient()
    
    return _client

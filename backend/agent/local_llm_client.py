"""
=====================================================
ZEUS - Cliente para LLM Local (Ollama)
Orquestrador principal usando modelo local
=====================================================
"""

from typing import Dict, Any, List, Optional
from openai import AsyncOpenAI
import asyncio

from config import get_settings, get_logger

# -------------------------------------------------
# Configuração
# -------------------------------------------------
logger = get_logger(__name__)
settings = get_settings()

# Cliente singleton
_local_client: Optional[AsyncOpenAI] = None


def get_local_llm_client() -> AsyncOpenAI:
    """
    Retorna cliente OpenAI configurado para LLM local (Ollama).
    
    Returns:
        Cliente AsyncOpenAI apontando para servidor local
    """
    global _local_client
    
    if _local_client is None:
        _local_client = AsyncOpenAI(
            base_url=settings.local_llm_base_url,
            api_key=settings.local_llm_api_key,
            timeout=settings.local_llm_timeout
        )
        logger.info(
            "Cliente LLM local inicializado",
            base_url=settings.local_llm_base_url,
            model=settings.local_llm_model
        )
    
    return _local_client


class LocalLLMClient:
    """
    Cliente para comunicação com LLM local (Ollama).
    
    Responsável por:
    - Enviar requisições para o modelo local
    - Gerenciar timeouts e retries
    - Formatar respostas no padrão esperado
    """
    
    def __init__(self):
        """Inicializa o cliente local"""
        self.client = get_local_llm_client()
        self.model = settings.local_llm_model
        self.timeout = settings.local_llm_timeout
        
        logger.info(
            "LocalLLMClient inicializado",
            model=self.model,
            timeout=self.timeout
        )
    
    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096
    ) -> Dict[str, Any]:
        """
        Envia requisição de chat completion para o LLM local.
        
        Args:
            messages: Lista de mensagens da conversa
            model: Modelo a usar (ignora, usa sempre o local)
            tools: Lista de tools disponíveis
            temperature: Temperatura de geração
            max_tokens: Máximo de tokens na resposta
            
        Returns:
            Dicionário com resposta formatada
        """
        try:
            logger.debug(
                "Enviando para LLM local",
                messages_count=len(messages),
                tools_count=len(tools) if tools else 0
            )
            
            # Preparar argumentos
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens
            }
            
            # Adicionar tools se fornecidas
            if tools:
                kwargs["tools"] = tools
                kwargs["tool_choice"] = "auto"
            
            # Fazer requisição com timeout
            response = await asyncio.wait_for(
                self.client.chat.completions.create(**kwargs),
                timeout=self.timeout
            )
            
            # Extrair resposta
            choice = response.choices[0]
            message = choice.message
            
            # Formatar resposta
            result = {
                "content": message.content or "",
                "role": "assistant"
            }
            
            # Processar tool calls se existirem
            if message.tool_calls:
                result["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in message.tool_calls
                ]
            
            logger.info(
                "Resposta do LLM local recebida",
                content_length=len(result["content"]),
                tool_calls=len(result.get("tool_calls", []))
            )
            
            return result
            
        except asyncio.TimeoutError:
            logger.error(
                "Timeout na comunicação com LLM local",
                timeout=self.timeout
            )
            raise Exception(f"LLM local não respondeu em {self.timeout}s")
            
        except Exception as e:
            logger.error(
                "Erro na comunicação com LLM local",
                error=str(e)
            )
            raise
    
    async def health_check(self) -> bool:
        """
        Verifica se o LLM local está disponível.
        
        Returns:
            True se disponível, False caso contrário
        """
        try:
            response = await asyncio.wait_for(
                self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=5
                ),
                timeout=10
            )
            return True
        except Exception as e:
            logger.warning("LLM local indisponível", error=str(e))
            return False

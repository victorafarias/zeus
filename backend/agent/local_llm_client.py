"""
=====================================================
ZEUS - Cliente para LLM Local (Ollama)
Orquestrador principal usando modelo local com fallback em cascata:
1. Gemma 3 4B (primário, 3 min timeout)
2. Llama3.2 (secundário, 5 min timeout)
3. OpenRouter (fallback final)
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

# Clientes singleton para cada modelo
_primary_client: Optional[AsyncOpenAI] = None
_secondary_client: Optional[AsyncOpenAI] = None


def get_primary_llm_client() -> AsyncOpenAI:
    """
    Retorna cliente OpenAI configurado para o modelo primário (Gemma 3 4B).
    
    Returns:
        Cliente AsyncOpenAI com timeout de 3 minutos
    """
    global _primary_client
    
    if _primary_client is None:
        _primary_client = AsyncOpenAI(
            base_url=settings.local_llm_base_url,
            api_key=settings.local_llm_api_key,
            timeout=settings.primary_llm_timeout
        )
        logger.info(
            "Cliente LLM primário inicializado",
            base_url=settings.local_llm_base_url,
            model=settings.primary_llm_model,
            timeout=settings.primary_llm_timeout
        )
    
    return _primary_client


def get_secondary_llm_client() -> AsyncOpenAI:
    """
    Retorna cliente OpenAI configurado para o modelo secundário (Llama3.2).
    
    Returns:
        Cliente AsyncOpenAI com timeout de 5 minutos
    """
    global _secondary_client
    
    if _secondary_client is None:
        _secondary_client = AsyncOpenAI(
            base_url=settings.local_llm_base_url,
            api_key=settings.local_llm_api_key,
            timeout=settings.secondary_llm_timeout
        )
        logger.info(
            "Cliente LLM secundário inicializado",
            base_url=settings.local_llm_base_url,
            model=settings.secondary_llm_model,
            timeout=settings.secondary_llm_timeout
        )
    
    return _secondary_client


# Manter compatibilidade com código antigo
def get_local_llm_client() -> AsyncOpenAI:
    """
    Retorna cliente do modelo primário (para compatibilidade).
    
    Returns:
        Cliente AsyncOpenAI do modelo primário
    """
    return get_primary_llm_client()


class LocalLLMClient:
    """
    Cliente para comunicação com LLM local (Ollama).
    
    Suporta múltiplos modelos com fallback em cascata:
    1. Modelo primário (Gemma 3 4B) - timeout de 3 minutos
    2. Modelo secundário (Llama3.2) - timeout de 5 minutos
    
    Responsável por:
    - Enviar requisições para os modelos locais
    - Gerenciar timeouts e retries
    - Formatar respostas no padrão esperado
    """
    
    def __init__(self, model: str = None, timeout: int = None):
        """
        Inicializa o cliente local.
        
        Args:
            model: Modelo específico a usar (opcional, usa primário por padrão)
            timeout: Timeout específico (opcional, usa do config)
        """
        # Configurações do modelo primário
        self.primary_client = get_primary_llm_client()
        self.primary_model = settings.primary_llm_model
        self.primary_timeout = settings.primary_llm_timeout
        
        # Configurações do modelo secundário
        self.secondary_client = get_secondary_llm_client()
        self.secondary_model = settings.secondary_llm_model
        self.secondary_timeout = settings.secondary_llm_timeout
        
        # Para manter compatibilidade com código antigo
        self.client = self.primary_client
        self.model = model or self.primary_model
        self.timeout = timeout or self.primary_timeout
        
        logger.info(
            "LocalLLMClient inicializado com fallback",
            primary_model=self.primary_model,
            primary_timeout=self.primary_timeout,
            secondary_model=self.secondary_model,
            secondary_timeout=self.secondary_timeout
        )
    
    async def _call_model(
        self,
        client: AsyncOpenAI,
        model: str,
        timeout: int,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096
    ) -> Dict[str, Any]:
        """
        Faz chamada para um modelo específico.
        
        Args:
            client: Cliente AsyncOpenAI configurado
            model: Nome do modelo
            timeout: Timeout em segundos
            messages: Lista de mensagens
            tools: Lista de tools disponíveis
            temperature: Temperatura de geração
            max_tokens: Máximo de tokens na resposta
            
        Returns:
            Dicionário com resposta formatada
            
        Raises:
            asyncio.TimeoutError: Se exceder timeout
            Exception: Para outros erros
        """
        # Preparar argumentos
        kwargs = {
            "model": model,
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
            client.chat.completions.create(**kwargs),
            timeout=timeout
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
        
        return result
    
    async def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
        max_tokens: int = 4096
    ) -> Dict[str, Any]:
        """
        Envia requisição de chat completion para o LLM local com fallback.
        
        Tenta primeiro o modelo primário (Gemma 3 4B).
        Se falhar, tenta o modelo secundário (Llama3.2).
        
        Args:
            messages: Lista de mensagens da conversa
            model: Modelo a usar (ignora, usa cascata local)
            tools: Lista de tools disponíveis
            temperature: Temperatura de geração
            max_tokens: Máximo de tokens na resposta
            
        Returns:
            Dicionário com resposta formatada
            
        Raises:
            Exception: Se ambos os modelos locais falharem
        """
        logger.debug(
            "Enviando para LLM local",
            messages_count=len(messages),
            tools_count=len(tools) if tools else 0
        )
        
        # Tentar modelo primário (Gemma 3 4B)
        try:
            logger.info(
                "Tentando modelo primário",
                model=self.primary_model,
                timeout=self.primary_timeout
            )
            
            result = await self._call_model(
                client=self.primary_client,
                model=self.primary_model,
                timeout=self.primary_timeout,
                messages=messages,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens
            )
            
            logger.info(
                "Resposta do modelo primário recebida",
                model=self.primary_model,
                content_length=len(result["content"]),
                tool_calls=len(result.get("tool_calls", []))
            )
            
            return result
            
        except asyncio.TimeoutError:
            logger.warning(
                "Timeout no modelo primário, tentando secundário",
                primary_model=self.primary_model,
                primary_timeout=self.primary_timeout
            )
            
        except Exception as e:
            logger.warning(
                "Erro no modelo primário, tentando secundário",
                primary_model=self.primary_model,
                error=str(e)
            )
        
        # Tentar modelo secundário (Llama3.2)
        try:
            logger.info(
                "Tentando modelo secundário",
                model=self.secondary_model,
                timeout=self.secondary_timeout
            )
            
            result = await self._call_model(
                client=self.secondary_client,
                model=self.secondary_model,
                timeout=self.secondary_timeout,
                messages=messages,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens
            )
            
            logger.info(
                "Resposta do modelo secundário recebida",
                model=self.secondary_model,
                content_length=len(result["content"]),
                tool_calls=len(result.get("tool_calls", []))
            )
            
            return result
            
        except asyncio.TimeoutError:
            logger.error(
                "Timeout no modelo secundário também",
                secondary_model=self.secondary_model,
                secondary_timeout=self.secondary_timeout
            )
            raise Exception(
                f"Modelos locais não responderam. "
                f"{self.primary_model} timeout após {self.primary_timeout}s, "
                f"{self.secondary_model} timeout após {self.secondary_timeout}s"
            )
            
        except Exception as e:
            logger.error(
                "Erro no modelo secundário também",
                secondary_model=self.secondary_model,
                error=str(e)
            )
            raise Exception(
                f"Modelos locais falharam. Erro: {str(e)}"
            )
    
    async def health_check(self) -> bool:
        """
        Verifica se pelo menos um LLM local está disponível.
        
        Returns:
            True se pelo menos um modelo responder, False caso contrário
        """
        # Testar modelo primário
        try:
            await asyncio.wait_for(
                self.primary_client.chat.completions.create(
                    model=self.primary_model,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=5
                ),
                timeout=10
            )
            logger.info("Modelo primário disponível", model=self.primary_model)
            return True
        except Exception as e:
            logger.warning(
                "Modelo primário indisponível",
                model=self.primary_model,
                error=str(e)
            )
        
        # Testar modelo secundário
        try:
            await asyncio.wait_for(
                self.secondary_client.chat.completions.create(
                    model=self.secondary_model,
                    messages=[{"role": "user", "content": "ping"}],
                    max_tokens=5
                ),
                timeout=10
            )
            logger.info("Modelo secundário disponível", model=self.secondary_model)
            return True
        except Exception as e:
            logger.warning(
                "Modelo secundário também indisponível",
                model=self.secondary_model,
                error=str(e)
            )
        
        return False

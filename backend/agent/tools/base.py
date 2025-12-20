"""
=====================================================
ZEUS - Classe Base de Tool
Define interface para todas as ferramentas do agente
=====================================================
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
from pydantic import BaseModel


class ToolParameter(BaseModel):
    """Define um parâmetro de uma tool"""
    name: str
    type: str  # "string", "integer", "boolean", "array", "object"
    description: str
    required: bool = True
    enum: Optional[List[str]] = None  # Valores permitidos
    items: Optional[Dict[str, str]] = None  # Tipo dos itens para arrays (ex: {"type": "string"})


class BaseTool(ABC):
    """
    Classe base para todas as tools do agente.
    
    Cada tool deve:
    1. Definir name, description e parameters
    2. Implementar o método execute()
    3. Retornar resultado no formato padrão
    """
    
    # Nome da tool (usado nas chamadas)
    name: str = "base_tool"
    
    # Descrição para o modelo entender quando usar
    description: str = "Descrição da ferramenta"
    
    # Parâmetros aceitos
    parameters: List[ToolParameter] = []
    
    def to_openai_tool(self) -> Dict[str, Any]:
        """
        Converte a tool para o formato OpenAI/OpenRouter.
        
        Returns:
            Dicionário no formato esperado pela API
        """
        # Construir schema dos parâmetros
        properties = {}
        required = []
        
        for param in self.parameters:
            prop = {
                "type": param.type,
                "description": param.description
            }
            
            if param.enum:
                prop["enum"] = param.enum
            
            # Adicionar 'items' para arrays (obrigatório pela API OpenAI)
            if param.type == "array":
                if param.items:
                    prop["items"] = param.items
                else:
                    # Padrão: array de strings se não especificado
                    prop["items"] = {"type": "string"}
            
            properties[param.name] = prop
            
            if param.required:
                required.append(param.name)
        
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required
                }
            }
        }
    
    @abstractmethod
    async def execute(self, **kwargs) -> Dict[str, Any]:
        """
        Executa a tool com os argumentos fornecidos.
        
        Returns:
            Dicionário com:
            - success: bool - se executou com sucesso
            - output: str - resultado da execução
            - error: str - mensagem de erro (se success=False)
        """
        pass
    
    def _success(self, output: str) -> Dict[str, Any]:
        """Helper para retornar sucesso"""
        return {
            "success": True,
            "output": output
        }
    
    def _error(self, error: str) -> Dict[str, Any]:
        """Helper para retornar erro"""
        return {
            "success": False,
            "error": error
        }

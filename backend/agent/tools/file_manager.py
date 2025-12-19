"""
=====================================================
ZEUS - File Manager Tools
Ferramentas para ler e escrever arquivos
=====================================================
"""

from typing import Dict, Any, Optional
import os
import aiofiles

from .base import BaseTool, ToolParameter
from config import get_settings, get_logger

logger = get_logger(__name__)
settings = get_settings()

# Diretórios permitidos para operações de arquivo
ALLOWED_DIRS = [
    "/app/data",
    settings.uploads_dir,
    settings.outputs_dir,
]


class ReadFileTool(BaseTool):
    """Lê o conteúdo de um arquivo"""
    
    name = "read_file"
    description = """Lê o conteúdo de um arquivo do sistema.
Por segurança, apenas arquivos nos diretórios de dados são acessíveis."""
    
    parameters = [
        ToolParameter(
            name="path",
            type="string",
            description="Caminho do arquivo a ler"
        ),
        ToolParameter(
            name="max_lines",
            type="integer",
            description="Máximo de linhas a retornar (padrão: 500)",
            required=False
        )
    ]
    
    async def execute(
        self,
        path: str,
        max_lines: int = 500,
        **kwargs
    ) -> Dict[str, Any]:
        """Lê conteúdo de arquivo"""
        # Resolver caminho absoluto
        if not os.path.isabs(path):
            path = os.path.join(settings.data_dir, path)
        
        # Verificar se está em diretório permitido
        is_allowed = any(
            path.startswith(allowed) 
            for allowed in ALLOWED_DIRS
        )
        
        if not is_allowed:
            logger.warning("Acesso negado a arquivo", path=path)
            return self._error(
                f"Acesso negado. Apenas arquivos em {settings.data_dir} são acessíveis."
            )
        
        # Verificar se arquivo existe
        if not os.path.exists(path):
            return self._error(f"Arquivo não encontrado: {path}")
        
        if not os.path.isfile(path):
            return self._error(f"Caminho não é um arquivo: {path}")
        
        logger.info("Lendo arquivo", path=path)
        
        try:
            async with aiofiles.open(path, 'r', encoding='utf-8') as f:
                lines = await f.readlines()
            
            # Limitar linhas
            total_lines = len(lines)
            if total_lines > max_lines:
                lines = lines[:max_lines]
                content = "".join(lines)
                content += f"\n...(truncado, mostrando {max_lines} de {total_lines} linhas)"
            else:
                content = "".join(lines)
            
            logger.info("Arquivo lido", path=path, lines=min(total_lines, max_lines))
            return self._success(content)
            
        except UnicodeDecodeError:
            return self._error("Arquivo não é texto legível (binário)")
        except Exception as e:
            logger.error("Erro ao ler arquivo", error=str(e))
            return self._error(f"Erro: {str(e)}")


class WriteFileTool(BaseTool):
    """Escreve/cria um arquivo"""
    
    name = "write_file"
    description = """Escreve conteúdo em um arquivo, criando-o se não existir.
Por segurança, apenas arquivos nos diretórios de dados podem ser criados/modificados."""
    
    parameters = [
        ToolParameter(
            name="path",
            type="string",
            description="Caminho do arquivo a criar/modificar"
        ),
        ToolParameter(
            name="content",
            type="string",
            description="Conteúdo a escrever no arquivo"
        ),
        ToolParameter(
            name="append",
            type="boolean",
            description="Se True, adiciona ao final em vez de sobrescrever (padrão: False)",
            required=False
        )
    ]
    
    async def execute(
        self,
        path: str,
        content: str,
        append: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """Escreve conteúdo em arquivo"""
        # Resolver caminho absoluto
        if not os.path.isabs(path):
            path = os.path.join(settings.data_dir, path)
        
        # Verificar se está em diretório permitido
        is_allowed = any(
            path.startswith(allowed) 
            for allowed in ALLOWED_DIRS
        )
        
        if not is_allowed:
            logger.warning("Escrita negada", path=path)
            return self._error(
                f"Acesso negado. Apenas arquivos em {settings.data_dir} podem ser escritos."
            )
        
        logger.info(
            "Escrevendo arquivo",
            path=path,
            append=append,
            content_length=len(content)
        )
        
        try:
            # Criar diretório se não existir
            os.makedirs(os.path.dirname(path), exist_ok=True)
            
            mode = 'a' if append else 'w'
            async with aiofiles.open(path, mode, encoding='utf-8') as f:
                await f.write(content)
            
            action = "adicionado a" if append else "escrito em"
            logger.info("Arquivo escrito", path=path)
            
            return self._success(f"Conteúdo {action} {path}")
            
        except Exception as e:
            logger.error("Erro ao escrever arquivo", error=str(e))
            return self._error(f"Erro: {str(e)}")

"""
=====================================================
ZEUS - API de Upload de Arquivos
Gerencia upload de arquivos para o agente
=====================================================
"""

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import List, Optional
import os
import uuid
import aiofiles

from config import get_settings, get_logger
from api.auth import get_current_user, UserInfo

# -------------------------------------------------
# Configuração
# -------------------------------------------------
router = APIRouter()
logger = get_logger(__name__)
settings = get_settings()

# Extensões permitidas
ALLOWED_EXTENSIONS = {
    # Documentos
    '.txt', '.md', '.json', '.csv', '.xml', '.yaml', '.yml',
    '.pdf', '.doc', '.docx', '.rtf',  # PDFs e Word
    # Código
    '.py', '.js', '.ts', '.html', '.css', '.sql', '.sh',
    '.java', '.c', '.cpp', '.h', '.cs', '.go', '.rs', '.rb',  # Linguagens compiladas
    '.php', '.swift', '.kt', '.scala', '.r', '.m', '.lua',     # Outras linguagens
    '.pl', '.ex', '.exs', '.vue', '.jsx', '.tsx',              # Web/Elixir
    '.bat', '.ps1', '.dockerfile', '.makefile',                # Scripts/Config
    # Áudio
    '.mp3', '.wav', '.m4a', '.ogg', '.flac', '.aac',
    # Vídeo
    '.mp4', '.webm', '.avi', '.mov',
    # Imagens
    '.jpg', '.jpeg', '.png', '.gif', '.webp',
}

# Tamanho máximo (50MB)
MAX_FILE_SIZE = 50 * 1024 * 1024


# -------------------------------------------------
# Modelos
# -------------------------------------------------
class UploadedFile(BaseModel):
    """Informações do arquivo enviado"""
    id: str
    filename: str
    original_name: str
    size: int
    extension: str
    path: str


class UploadResponse(BaseModel):
    """Resposta do upload"""
    success: bool
    files: List[UploadedFile]
    errors: List[str] = []


class FileListResponse(BaseModel):
    """Lista de arquivos"""
    files: List[UploadedFile]
    total: int


# -------------------------------------------------
# Endpoints
# -------------------------------------------------
@router.post("/", response_model=UploadResponse)
async def upload_files(
    files: List[UploadFile] = File(...),
    user: UserInfo = Depends(get_current_user)
):
    """
    Upload de um ou mais arquivos.
    
    Args:
        files: Lista de arquivos
        
    Returns:
        Informações dos arquivos enviados
    """
    logger.info("Upload iniciado", username=user.username, files_count=len(files))
    
    uploaded: List[UploadedFile] = []
    errors: List[str] = []
    
    for file in files:
        try:
            # Verificar extensão
            ext = os.path.splitext(file.filename)[1].lower()
            if ext not in ALLOWED_EXTENSIONS:
                errors.append(f"{file.filename}: Extensão '{ext}' não permitida")
                continue
            
            # Ler conteúdo para verificar tamanho
            content = await file.read()
            if len(content) > MAX_FILE_SIZE:
                errors.append(f"{file.filename}: Arquivo muito grande (máx: 50MB)")
                continue
            
            # Gerar nome (usar nome original)
            safe_name = file.filename
            file_path = os.path.join(settings.uploads_dir, safe_name)
            
            # Garantir diretório existe
            os.makedirs(settings.uploads_dir, exist_ok=True)
            
            # Salvar arquivo
            async with aiofiles.open(file_path, 'wb') as f:
                await f.write(content)
            
            uploaded.append(UploadedFile(
                id=safe_name,
                filename=safe_name,
                original_name=file.filename,
                size=len(content),
                extension=ext,
                path=file_path
            ))
            
            logger.info("Arquivo salvo", filename=safe_name, size=len(content))
            
        except Exception as e:
            errors.append(f"{file.filename}: Erro ao salvar - {str(e)}")
            logger.error("Erro no upload", filename=file.filename, error=str(e))
    
    return UploadResponse(
        success=len(errors) == 0,
        files=uploaded,
        errors=errors
    )


@router.get("/", response_model=FileListResponse)
async def list_files(
    user: UserInfo = Depends(get_current_user)
):
    """
    Lista arquivos do diretório de uploads.
    """
    files: List[UploadedFile] = []
    
    if not os.path.exists(settings.uploads_dir):
        return FileListResponse(files=[], total=0)
    
    for filename in os.listdir(settings.uploads_dir):
        filepath = os.path.join(settings.uploads_dir, filename)
        if os.path.isfile(filepath):
            ext = os.path.splitext(filename)[1].lower()
            size = os.path.getsize(filepath)
            
            # Agora o ID é o próprio nome do arquivo
            file_id = filename
            original_name = filename
            
            files.append(UploadedFile(
                id=file_id,
                filename=filename,
                original_name=original_name,
                size=size,
                extension=ext,
                path=filepath
            ))
    
    return FileListResponse(files=files, total=len(files))


@router.delete("/{file_id}")
async def delete_file(
    file_id: str,
    user: UserInfo = Depends(get_current_user)
):
    """
    Remove um arquivo.
    """
    if not os.path.exists(settings.uploads_dir):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    
    # O file_id agora é o nome exato do arquivo
    filepath = os.path.join(settings.uploads_dir, file_id)
    
    if os.path.exists(filepath) and os.path.isfile(filepath):
        try:
            os.remove(filepath)
            logger.info("Arquivo removido", filename=file_id)
            return {"message": "Arquivo removido com sucesso"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Erro ao remover: {str(e)}")
            
    # Fallback para compatibilidade com arquivos antigos (que tinham prefixo)
    # Se não achou pelo nome exato, tenta procurar por prefixo se o file_id parecer um hex de 8 chars
    if len(file_id) == 8: 
        for filename in os.listdir(settings.uploads_dir):
            if filename.startswith(file_id + "_"):
                filepath = os.path.join(settings.uploads_dir, filename)
                try:
                    os.remove(filepath)
                    logger.info("Arquivo antigo removido", filename=filename)
                    return {"message": "Arquivo removido com sucesso"}
                except Exception as e:
                    raise HTTPException(status_code=500, detail=f"Erro ao remover: {str(e)}")
    
    raise HTTPException(status_code=404, detail="Arquivo não encontrado")


# -------------------------------------------------
# Funções Helper para Carregar Arquivos
# -------------------------------------------------

def find_file_by_id(file_id: str) -> Optional[dict]:
    """
    Busca um arquivo pelo seu ID no diretório de uploads.
    
    Args:
        file_id: ID do arquivo (agora é o próprio nome do arquivo)
        
    Returns:
        Dicionário com info do arquivo ou None se não encontrado
    """
    if not os.path.exists(settings.uploads_dir):
        return None
        
    # Tentativa 1: Busca exata (novo padrão)
    filepath = os.path.join(settings.uploads_dir, file_id)
    if os.path.isfile(filepath):
         filename = file_id
         ext = os.path.splitext(filename)[1].lower()
         return {
            "id": file_id,
            "filename": filename,
            "original_name": filename,
            "extension": ext,
            "path": filepath,
            "size": os.path.getsize(filepath)
        }

    # Tentativa 2: Busca por prefixo (compatibilidade legada)
    # Se o ID tem 8 caracteres, pode ser um prefixo antigo
    if len(file_id) == 8:
        for filename in os.listdir(settings.uploads_dir):
            if filename.startswith(file_id + "_"):
                filepath = os.path.join(settings.uploads_dir, filename)
                if os.path.isfile(filepath):
                    ext = os.path.splitext(filename)[1].lower()
                    original_name = filename.split('_', 1)[1] if '_' in filename else filename
                    return {
                        "id": file_id,
                        "filename": filename,
                        "original_name": original_name,
                        "extension": ext,
                        "path": filepath,
                        "size": os.path.getsize(filepath)
                    }
    
    return None


async def load_file_content(file_id: str) -> Optional[dict]:
    """
    Carrega o conteúdo de um arquivo baseado no seu ID.
    
    Para arquivos de texto/código: retorna o texto completo.
    Para imagens: retorna base64 do conteúdo.
    Para PDFs: retorna indicação de que é PDF (precisa de biblioteca adicional).
    
    Args:
        file_id: ID do arquivo
        
    Returns:
        Dicionário com conteúdo ou None se não encontrado
        {
            "file_id": str,
            "name": str,
            "type": "text" | "image" | "binary",
            "content": str (texto ou base64)
        }
    """
    import base64
    
    file_info = find_file_by_id(file_id)
    if not file_info:
        logger.warning("Arquivo não encontrado", file_id=file_id)
        return None
    
    ext = file_info["extension"]
    filepath = file_info["path"]
    
    # Extensões de texto/código
    text_extensions = {
        '.txt', '.md', '.json', '.csv', '.xml', '.yaml', '.yml',
        '.py', '.js', '.ts', '.html', '.css', '.sql', '.sh',
        '.java', '.c', '.cpp', '.h', '.cs', '.go', '.rs', '.rb',
        '.php', '.swift', '.kt', '.scala', '.r', '.m', '.lua',
        '.pl', '.ex', '.exs', '.vue', '.jsx', '.tsx',
        '.bat', '.ps1', '.dockerfile', '.makefile', '.rtf'
    }
    
    # Extensões de imagem
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}
    
    try:
        if ext in text_extensions:
            # Arquivo de texto - ler como string
            async with aiofiles.open(filepath, 'r', encoding='utf-8', errors='replace') as f:
                content = await f.read()
            
            # Limitar tamanho para evitar contexto muito grande
            max_chars = 50000  # ~50KB de texto
            if len(content) > max_chars:
                content = content[:max_chars] + "\n\n[... conteúdo truncado, arquivo muito grande ...]"
            
            logger.info("Arquivo de texto carregado", file_id=file_id, chars=len(content))
            return {
                "file_id": file_id,
                "name": file_info["original_name"],
                "type": "text",
                "content": content
            }
            
        elif ext in image_extensions:
            # Imagem - ler como base64
            async with aiofiles.open(filepath, 'rb') as f:
                binary_content = await f.read()
            
            base64_content = base64.b64encode(binary_content).decode('utf-8')
            mime_type = {
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.png': 'image/png',
                '.gif': 'image/gif',
                '.webp': 'image/webp'
            }.get(ext, 'image/jpeg')
            
            logger.info("Imagem carregada como base64", file_id=file_id, size=len(binary_content))
            return {
                "file_id": file_id,
                "name": file_info["original_name"],
                "type": "image",
                "mime_type": mime_type,
                "content": f"data:{mime_type};base64,{base64_content}"
            }
            
        elif ext == '.pdf':
            # PDF - marcar como binário (necessita biblioteca específica para extração)
            logger.info("Arquivo PDF detectado", file_id=file_id)
            return {
                "file_id": file_id,
                "name": file_info["original_name"],
                "type": "pdf",
                "content": f"[Arquivo PDF: {file_info['original_name']}. O conteúdo do PDF foi anexado ao chat mas requer processamento adicional para extração de texto.]",
                "path": filepath
            }
            
        elif ext in {'.doc', '.docx'}:
            # Word - marcar como binário
            logger.info("Arquivo Word detectado", file_id=file_id)
            return {
                "file_id": file_id,
                "name": file_info["original_name"],
                "type": "word",
                "content": f"[Arquivo Word: {file_info['original_name']}. O arquivo foi anexado ao chat.]",
                "path": filepath
            }
            
        else:
            # Outros formatos binários
            logger.info("Arquivo binário detectado", file_id=file_id, ext=ext)
            return {
                "file_id": file_id,
                "name": file_info["original_name"],
                "type": "binary",
                "content": f"[Arquivo binário: {file_info['original_name']} ({ext})]",
                "path": filepath
            }
            
    except Exception as e:
        logger.error("Erro ao carregar arquivo", file_id=file_id, error=str(e))
        return {
            "file_id": file_id,
            "name": file_info["original_name"],
            "type": "error",
            "content": f"[Erro ao carregar arquivo: {str(e)}]"
        }


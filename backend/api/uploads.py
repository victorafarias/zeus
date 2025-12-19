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
    # Código
    '.py', '.js', '.ts', '.html', '.css', '.sql', '.sh',
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
            
            # Gerar nome único
            file_id = uuid.uuid4().hex[:8]
            safe_name = f"{file_id}_{file.filename}"
            file_path = os.path.join(settings.uploads_dir, safe_name)
            
            # Garantir diretório existe
            os.makedirs(settings.uploads_dir, exist_ok=True)
            
            # Salvar arquivo
            async with aiofiles.open(file_path, 'wb') as f:
                await f.write(content)
            
            uploaded.append(UploadedFile(
                id=file_id,
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
            file_id = filename.split('_')[0] if '_' in filename else filename[:8]
            
            files.append(UploadedFile(
                id=file_id,
                filename=filename,
                original_name=filename.split('_', 1)[1] if '_' in filename else filename,
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
    
    # Procurar arquivo pelo ID
    for filename in os.listdir(settings.uploads_dir):
        if filename.startswith(file_id + "_"):
            filepath = os.path.join(settings.uploads_dir, filename)
            try:
                os.remove(filepath)
                logger.info("Arquivo removido", filename=filename)
                return {"message": "Arquivo removido com sucesso"}
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"Erro ao remover: {str(e)}")
    
    raise HTTPException(status_code=404, detail="Arquivo não encontrado")

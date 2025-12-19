"""
=====================================================
ZEUS - Media Processor Tool
Transcrição de áudio e vídeo usando Whisper
=====================================================
"""

from typing import Dict, Any
import docker
import os
import uuid

from .base import BaseTool, ToolParameter
from .docker_helper import get_docker_client
from config import get_settings, get_logger

logger = get_logger(__name__)
settings = get_settings()


class TranscribeMediaTool(BaseTool):
    """Transcreve áudio ou vídeo para texto"""
    
    name = "transcribe_media"
    description = """Transcreve áudio ou vídeo para texto usando Whisper.
Formatos suportados: mp3, wav, m4a, mp4, webm, ogg, flac.
O arquivo deve estar na pasta de uploads."""
    
    parameters = [
        ToolParameter(
            name="file_path",
            type="string",
            description="Caminho do arquivo de áudio/vídeo"
        ),
        ToolParameter(
            name="language",
            type="string",
            description="Código do idioma (ex: 'pt', 'en'). Se omitido, detecta automaticamente.",
            required=False
        )
    ]
    
    @property
    def docker_client(self):
        """Obtém cliente Docker sob demanda"""
        return get_docker_client()
    
    async def execute(
        self,
        file_path: str,
        language: str = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Transcreve arquivo de mídia"""
        if not self.docker_client:
            return self._error("Docker não disponível")
        
        # Resolver caminho
        if not os.path.isabs(file_path):
            file_path = os.path.join(settings.uploads_dir, file_path)
        
        if not os.path.exists(file_path):
            return self._error(f"Arquivo não encontrado: {file_path}")
        
        # Verificar extensão
        ext = os.path.splitext(file_path)[1].lower()
        supported = ['.mp3', '.wav', '.m4a', '.mp4', '.webm', '.ogg', '.flac', '.aac']
        
        if ext not in supported:
            return self._error(
                f"Formato não suportado: {ext}. "
                f"Formatos aceitos: {', '.join(supported)}"
            )
        
        logger.info(
            "Transcrevendo mídia",
            file=file_path,
            language=language
        )
        
        try:
            # Diretório e nome do arquivo
            file_dir = os.path.dirname(file_path)
            file_name = os.path.basename(file_path)
            
            # Comando Whisper
            lang_arg = f"--language {language}" if language else ""
            cmd = f"whisper /media/{file_name} --model base {lang_arg} --output_format txt --output_dir /output"
            
            # Nome único para o container
            container_name = f"zeus-whisper-{uuid.uuid4().hex[:8]}"
            
            # Executar container com Whisper
            container = self.docker_client.containers.run(
                image="onerahmet/openai-whisper-asr-webservice:latest",
                command=f"bash -c 'pip install -q openai-whisper && {cmd}'",
                name=container_name,
                volumes={
                    file_dir: {'bind': '/media', 'mode': 'ro'},
                    settings.outputs_dir: {'bind': '/output', 'mode': 'rw'}
                },
                mem_limit=f"2g",  # Whisper precisa de mais memória
                remove=True,
                detach=False,
                stdout=True,
                stderr=True
            )
            
            # Ler resultado
            output_name = os.path.splitext(file_name)[0] + ".txt"
            output_path = os.path.join(settings.outputs_dir, output_name)
            
            if os.path.exists(output_path):
                with open(output_path, 'r', encoding='utf-8') as f:
                    transcription = f.read()
                
                logger.info(
                    "Transcrição concluída",
                    length=len(transcription)
                )
                
                return self._success(
                    f"**Transcrição de {file_name}:**\n\n{transcription}"
                )
            else:
                # Verificar output do container
                output = container.decode('utf-8') if isinstance(container, bytes) else str(container)
                logger.warning("Arquivo de transcrição não encontrado", output=output[:500])
                return self._error(f"Transcrição falhou. Output: {output[:500]}")
            
        except docker.errors.ImageNotFound:
            logger.info("Baixando imagem Whisper")
            return self._error(
                "Imagem do Whisper não encontrada. "
                "Execute: docker pull onerahmet/openai-whisper-asr-webservice"
            )
        except docker.errors.ContainerError as e:
            stderr = e.stderr.decode('utf-8') if e.stderr else str(e)
            logger.error("Erro no container Whisper", error=stderr)
            return self._error(f"Erro na transcrição: {stderr[:500]}")
        except Exception as e:
            logger.error("Erro ao transcrever", error=str(e))
            return self._error(f"Erro: {str(e)}")

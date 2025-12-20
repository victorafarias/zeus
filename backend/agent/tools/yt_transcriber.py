"""
=====================================================
ZEUS - YouTube Transcriber Tool
Baixa áudio temporário do YouTube e gera transcrição em Markdown
=====================================================
"""

from typing import Dict, Any
import os
import uuid
import asyncio
import re
import tempfile
import shutil
from datetime import datetime

from .base import BaseTool, ToolParameter
from config import get_settings, get_logger

logger = get_logger(__name__)
settings = get_settings()


class YouTubeTranscriberTool(BaseTool):
    """
    Baixa temporariamente o áudio de um vídeo do YouTube e gera
    uma transcrição completa em formato Markdown.
    
    Utiliza yt-dlp para download e faster_whisper para transcrição.
    O arquivo de áudio temporário é removido após a transcrição.
    """
    
    name = "yt_transcriber"
    description = """Transcreve vídeos do YouTube para texto em formato Markdown.
Baixa temporariamente o áudio do vídeo, transcreve usando Whisper e gera um arquivo .md formatado.
O arquivo de áudio temporário é removido automaticamente após a transcrição.
O resultado inclui: título do vídeo, link original, data da transcrição e conteúdo transcrito.
Ideal para criar notas de vídeos, resumos ou documentação a partir de conteúdo do YouTube."""
    
    parameters = [
        ToolParameter(
            name="url",
            type="string",
            description="URL do vídeo do YouTube (youtube.com ou youtu.be)"
        ),
        ToolParameter(
            name="language",
            type="string",
            description="Idioma esperado do vídeo (ex: 'pt', 'en'). Padrão: detecção automática.",
            required=False
        ),
        ToolParameter(
            name="model_size",
            type="string",
            description="Tamanho do modelo Whisper: 'tiny' (rápido), 'base' (padrão), 'small', 'medium'. Maior = mais preciso mas mais lento.",
            required=False
        )
    ]
    
    async def execute(
        self,
        url: str,
        language: str = None,
        model_size: str = "base",
        **kwargs
    ) -> Dict[str, Any]:
        """
        Executa o download do áudio e transcrição.
        
        Args:
            url: URL do vídeo do YouTube
            language: Idioma esperado (opcional)
            model_size: Tamanho do modelo Whisper
        """
        websocket = kwargs.get('websocket')
        loop = asyncio.get_running_loop()
        
        def report_progress(msg: str):
            """Envia progresso via WebSocket (thread-safe)"""
            if websocket:
                asyncio.run_coroutine_threadsafe(
                    websocket.send_json({
                        "type": "status",
                        "status": "processing",
                        "content": msg
                    }),
                    loop
                )
        
        # 1. Validar URL do YouTube
        if not url:
            return self._error("URL não fornecida.")
        
        if not self._is_youtube_url(url):
            return self._error(
                "URL inválida. Forneça um link do YouTube "
                "(youtube.com/watch?v=... ou youtu.be/...)"
            )
        
        # 2. Verificar dependências
        try:
            from yt_dlp import YoutubeDL
        except ImportError:
            return self._error(
                "yt-dlp não está instalado. Execute 'pip install yt-dlp'."
            )
        
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            return self._error(
                "faster-whisper não está instalado. Execute 'pip install faster-whisper'."
            )
        
        # 3. Validar modelo
        valid_models = ["tiny", "base", "small", "medium", "large-v2"]
        model_size = model_size.lower().strip() if model_size else "base"
        if model_size not in valid_models:
            return self._error(
                f"Modelo inválido: '{model_size}'. "
                f"Use: {', '.join(valid_models)}"
            )
        
        # 4. Garantir diretório de saída
        output_dir = settings.outputs_dir
        os.makedirs(output_dir, exist_ok=True)
        
        logger.info(
            "Iniciando transcrição YouTube",
            url=url,
            model=model_size,
            language=language
        )
        
        report_progress("Iniciando processo de transcrição do YouTube...")
        
        # 5. Executar em thread separada
        try:
            result = await asyncio.to_thread(
                self._transcribe_synchronously,
                url,
                language,
                model_size,
                output_dir,
                report_progress
            )
            return self._success(result)
            
        except Exception as e:
            error_str = str(e)
            logger.error("Erro na transcrição YouTube", error=error_str)
            return self._error(f"Falha na transcrição: {error_str}")
    
    
    def _is_youtube_url(self, url: str) -> bool:
        """Verifica se a URL é do YouTube."""
        youtube_patterns = [
            r'(https?://)?(www\.)?youtube\.com/watch\?v=',
            r'(https?://)?(www\.)?youtube\.com/shorts/',
            r'(https?://)?(www\.)?youtu\.be/',
            r'(https?://)?(www\.)?youtube\.com/embed/',
            r'(https?://)?m\.youtube\.com/watch\?v=',
        ]
        
        for pattern in youtube_patterns:
            if re.search(pattern, url, re.IGNORECASE):
                return True
        return False
    
    
    def _transcribe_synchronously(
        self,
        url: str,
        language: str,
        model_size: str,
        output_dir: str,
        progress_callback=None
    ) -> str:
        """
        Executa download e transcrição (bloqueante).
        
        Args:
            url: URL do vídeo
            language: Idioma esperado (opcional)
            model_size: Tamanho do modelo Whisper
            output_dir: Diretório de saída
            progress_callback: Função para reportar progresso
            
        Returns:
            Mensagem de sucesso com caminho do arquivo
        """
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError
        from faster_whisper import WhisperModel
        
        temp_dir = None
        
        try:
            # 1. Criar diretório temporário para o áudio
            temp_dir = tempfile.mkdtemp(prefix="yt_transcribe_")
            temp_audio_path = os.path.join(temp_dir, "audio")
            
            if progress_callback:
                progress_callback("Obtendo informações do vídeo...")
            
            # 2. Obter informações do vídeo primeiro
            ydl_info_opts = {
                'quiet': True,
                'no_warnings': True,
            }
            
            with YoutubeDL(ydl_info_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                video_title = info.get('title', 'Vídeo do YouTube')
                video_id = info.get('id', '')
                channel = info.get('channel', info.get('uploader', 'Canal desconhecido'))
                duration = info.get('duration', 0)
                
            logger.info(
                "Informações do vídeo obtidas",
                title=video_title,
                duration=duration
            )
            
            # 3. Baixar apenas o áudio
            if progress_callback:
                progress_callback(f"Baixando áudio de: {video_title}...")
            
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': temp_audio_path,
                'quiet': True,
                'noprogress': True,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '128',  # Qualidade menor = download mais rápido
                }],
            }
            
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            # Procurar o arquivo de áudio baixado
            audio_file = f"{temp_audio_path}.mp3"
            if not os.path.exists(audio_file):
                # Tentar encontrar com outra extensão
                for ext in ['.mp3', '.m4a', '.webm', '.opus', '.wav']:
                    test_path = f"{temp_audio_path}{ext}"
                    if os.path.exists(test_path):
                        audio_file = test_path
                        break
            
            if not os.path.exists(audio_file):
                raise Exception("Arquivo de áudio não encontrado após download.")
            
            logger.info("Áudio baixado", path=audio_file)
            
            # 4. Carregar modelo Whisper
            if progress_callback:
                progress_callback(f"Carregando modelo Whisper ({model_size})...")
            
            model = WhisperModel(
                model_size,
                device="cpu",
                compute_type="int8"  # Mais compatível com CPU
            )
            
            # 5. Transcrever
            if progress_callback:
                progress_callback("Transcrevendo áudio (pode demorar)...")
            
            logger.info("Iniciando transcrição Whisper...")
            
            segments, info = model.transcribe(
                audio_file,
                beam_size=5,
                language=language
            )
            
            # Coletar texto dos segmentos
            full_text = ""
            for segment in segments:
                full_text += segment.text + " "
            
            full_text = re.sub(r'\s+', ' ', full_text).strip()
            
            if not full_text:
                return "Nenhuma fala detectada no vídeo."
            
            # 6. Gerar arquivo Markdown
            if progress_callback:
                progress_callback("Gerando arquivo Markdown...")
            
            # Criar nome do arquivo baseado no título
            clean_title = self._sanitize_filename(video_title)
            output_filename = f"{clean_title}_transcricao.md"
            output_path = os.path.join(output_dir, output_filename)
            
            # Criar conteúdo Markdown formatado
            markdown_content = self._generate_markdown(
                title=video_title,
                url=url,
                channel=channel,
                duration=duration,
                transcription=full_text
            )
            
            # Salvar arquivo
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(markdown_content)
            
            logger.info("Transcrição salva", path=output_path)
            
            # 7. Estatísticas
            word_count = len(full_text.split())
            duration_min = duration // 60 if duration else 0
            duration_sec = duration % 60 if duration else 0
            
            return (
                f"✅ Transcrição concluída com sucesso!\n"
                f"📝 Arquivo: {output_path}\n"
                f"📊 Palavras: {word_count}\n"
                f"⏱️ Duração do vídeo: {duration_min}min {duration_sec}s"
            )
            
        except DownloadError as e:
            logger.error("Erro de download yt-dlp", error=str(e))
            raise Exception(f"Falha no download do áudio: {e}")
        except Exception as e:
            logger.error("Erro na transcrição", error=str(e))
            raise Exception(str(e))
        finally:
            # 8. Limpar arquivos temporários
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                    logger.debug("Arquivos temporários removidos", path=temp_dir)
                except Exception as e:
                    logger.warning("Falha ao limpar temp", error=str(e))
    
    
    def _sanitize_filename(self, filename: str) -> str:
        """Remove caracteres inválidos do nome do arquivo."""
        invalid_chars = r'[<>:"/\\|?*]'
        clean = re.sub(invalid_chars, '', filename)
        clean = re.sub(r'\s+', ' ', clean).strip()
        if len(clean) > 100:
            clean = clean[:100]
        return clean
    
    
    def _generate_markdown(
        self,
        title: str,
        url: str,
        channel: str,
        duration: int,
        transcription: str
    ) -> str:
        """
        Gera conteúdo formatado em Markdown.
        
        Args:
            title: Título do vídeo
            url: URL original
            channel: Nome do canal
            duration: Duração em segundos
            transcription: Texto transcrito
            
        Returns:
            Conteúdo Markdown formatado
        """
        # Formatar duração
        duration_min = duration // 60 if duration else 0
        duration_sec = duration % 60 if duration else 0
        duration_str = f"{duration_min}:{duration_sec:02d}"
        
        # Data atual
        date_str = datetime.now().strftime("%d/%m/%Y às %H:%M")
        
        # Quebrar transcrição em parágrafos para melhor leitura
        # Aproximadamente a cada 150 palavras
        words = transcription.split()
        paragraphs = []
        current_paragraph = []
        
        for word in words:
            current_paragraph.append(word)
            if len(current_paragraph) >= 150:
                paragraphs.append(" ".join(current_paragraph))
                current_paragraph = []
        
        if current_paragraph:
            paragraphs.append(" ".join(current_paragraph))
        
        formatted_transcription = "\n\n".join(paragraphs)
        
        # Montar Markdown
        markdown = f"""# {title}

## Informações do Vídeo

| Campo | Valor |
|-------|-------|
| **Canal** | {channel} |
| **Duração** | {duration_str} |
| **Link** | [{url}]({url}) |
| **Transcrito em** | {date_str} |

---

## Transcrição

{formatted_transcription}

---

*Transcrição gerada automaticamente pelo Zeus usando Whisper.*
"""
        
        return markdown

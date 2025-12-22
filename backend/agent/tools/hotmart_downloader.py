"""
=====================================================
ZEUS - Hotmart Downloader Tool
Baixa vídeos e áudios de links Hotmart usando yt-dlp
Suporte a cookies para downloads autenticados (arquivo ou texto)
=====================================================
"""

from typing import Dict, Any, Optional
import os
import shutil
import asyncio
import uuid
import sys

# Tentar importar yt_dlp, se não existir, o erro será tratado na execução se necessário,
# mas idealmente deve estar instalado.
try:
    from yt_dlp import YoutubeDL
    from yt_dlp.utils import DownloadError
except ImportError:
    YoutubeDL = None
    DownloadError = None

from .base import BaseTool, ToolParameter
from config import get_settings, get_logger

logger = get_logger(__name__)
settings = get_settings()


class HotmartDownloaderTool(BaseTool):
    """
    Baixa vídeos (MP4) ou extrai áudios (MP3) de links do Hotmart usando yt-dlp.
    Suporta autenticação via cookies (arquivo ou texto).
    """
    
    name = "hotmart_downloader"
    description = """Baixa vídeos ou áudios de links do Hotmart ('contentplayer.hotmart.com' ou 'vod-akm.play.hotmart.com').
Recebe a URL do vídeo (m3u8 ou link direto) e baixa como MP4 (vídeo) ou MP3 (áudio).
Use format='video' (padrão) para vídeo MP4 ou format='audio' para MP3.
Se o download falhar com erro 403 (Forbidden), você pode fornecer o conteúdo dos cookies (formato Netscape) ou o caminho de um arquivo cookies.txt.
"""
    
    parameters = [
        ToolParameter(
            name="url",
            type="string",
            description="URL do vídeo (m3u8) ou link da página do player Hotmart"
        ),
        ToolParameter(
            name="output_filename",
            type="string",
            description="Nome do arquivo de saída EXATO que será salvo. Ex: 'Aula 01 - Introdução'. A extensão correta será adicionada automaticamente (não precisa informar).",
            required=True
        ),
        ToolParameter(
            name="format",
            type="string",
            description="Formato de saída: 'video' para MP4 (padrão) ou 'audio' para MP3",
            required=False
        ),
        ToolParameter(
            name="cookies_file",
            type="string",
            description="Caminho para arquivo de cookies (formato Netscape). Ex: '/app/data/uploads/cookies.txt'",
            required=False
        ),
        ToolParameter(
            name="cookies_content",
            type="string",
            description="Conteúdo do arquivo de cookies em texto (formato Netscape). Se fornecido, será salvo como cookies.txt e usado.",
            required=False
        )
    ]
    
    async def execute(
        self,
        url: str,
        output_filename: str,
        format: str = "video",
        cookies_file: str = None,
        cookies_content: str = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Executa o download do conteúdo (vídeo ou áudio) usando yt-dlp.
        """
        
        # 0. Verificar dependência yt-dlp
        if YoutubeDL is None:
            return self._error("Biblioteca 'yt-dlp' não está instalada. Execute 'pip install yt-dlp' no sistema.")

        # 1. Validar e preparar parâmetros básicos
        if not url:
            return self._error("URL não fornecida.")
        
        if not output_filename:
            return self._error("Nome do arquivo de saída (output_filename) é obrigatório.")

        # Normalizar formato
        format = format.lower().strip() if format else "video"
        if format not in ["video", "audio"]:
            return self._error(f"Formato inválido: '{format}'. Use 'video' ou 'audio'.")
            
        # 2. Gerenciar Cookies
        # O script do usuário espera cookies em /app/data/uploads/cookies.txt como padrão ou passado explicitamente
        # Vamos definir um caminho padrão para cookies gerados via texto
        cookies_path = None
        
        uploads_dir = os.path.join(settings.data_dir, "uploads")
        if not os.path.exists(uploads_dir):
            os.makedirs(uploads_dir, exist_ok=True)
            
        default_cookies_path = os.path.join(uploads_dir, "cookies.txt")

        # Se conteúdo de cookies for passado, salvar arquivo
        if cookies_content:
            try:
                # Se não tem cabeçalho Netscape, adiciona (opcional, mas bom pra garantir validade se o user colar só os cookies)
                # Mas geralmente o user cola o arquivo todo. Vamos salvar direto.
                with open(default_cookies_path, "w", encoding="utf-8") as f:
                    f.write(cookies_content)
                cookies_path = default_cookies_path
                logger.info(f"Cookies salvos a partir do texto em: {cookies_path}")
            except Exception as e:
                return self._error(f"Erro ao salvar cookies a partir do texto: {e}")
        
        # Se path fornecido, usa ele. Se não, tenta usar o default se existir
        if cookies_file:
            if os.path.exists(cookies_file):
                cookies_path = cookies_file
            else:
                return self._error(f"Arquivo de cookies informado não existe: {cookies_file}")
        elif not cookies_path and os.path.exists(default_cookies_path):
            # Se não foi passado file nem content, mas existe o default, usa o default
            cookies_path = default_cookies_path
            logger.info(f"Usando cookies padrão encontrados em: {cookies_path}")

        # 3. Definir diretório de saída
        # O usuário usa /app/data/downloads no script, vamos usar o configurado no settings
        output_dir = settings.outputs_dir  # Geralmente /app/data/outputs ou downloads
        # Assegurar que existe
        settings.ensure_dirs() # Garante criação
        
        # O script original usa hardcoded /app/data/downloads, vamos honrar o settings.outputs_dir
        # mas se o usuário quiser explicitamente downloads, podemos ajustar. O padrão do Zeus é outputs_dir.
        
        # 4. Executar download
        try:
            full_path = ""
            if format == "audio":
                full_path = await asyncio.to_thread(
                    self._download_audio_with_ytdlp,
                    url=url,
                    output_dir=output_dir,
                    filename_base=output_filename, # Sem extensão (ou removida dentro da func)
                    cookies_path=cookies_path
                )
            else:
                full_path = await asyncio.to_thread(
                    self._download_video_with_ytdlp,
                    url=url,
                    output_dir=output_dir,
                    filename_base=output_filename,
                    cookies_path=cookies_path
                )
                
            return self._success(f"✅ Download concluído! Arquivo salvo em: {full_path}")
            
        except Exception as e:
            logger.error(f"Erro no download Hotmart ({format})", error=str(e))
            return self._error(f"Falha ao baixar {format}: {str(e)}")

    def _download_video_with_ytdlp(self, url: str, output_dir: str, filename_base: str, cookies_path: str = None) -> str:
        """
        Baixa vídeo usando yt-dlp (baseado no script do usuário).
        """
        # Garantir nome sem extensão para o outtmpl
        filename_base = filename_base.replace(".mp4", "").replace(".mp3", "")
        # Caminho completo esperado (para verificação "já existe")
        expected_filename = f"{filename_base}.mp4"
        caminho_completo_saida = os.path.join(output_dir, expected_filename)
        
        if os.path.exists(caminho_completo_saida):
            logger.info(f"Arquivo já existe, pulando download: {caminho_completo_saida}")
            return camino_completo_saida

        logger.info(f"Iniciando download VÍDEO yt-dlp: {filename_base}")

        ydl_opts = {
            'outtmpl': os.path.join(output_dir, filename_base) + '.%(ext)s',
            'recode-video': 'mp4', # Força container mp4
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Referer': 'https://cf-embed.play.hotmart.com/',
            },
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            # Opções extras pra robustez
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
        }
        
        if cookies_path:
            ydl_opts['cookiefile'] = cookies_path
            
        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
            
        # O yt-dlp pode ter gerado o arquivo, verificar
        if os.path.exists(caminho_completo_saida):
            return caminho_completo_saida
            
        # Se não achou com nome exato, tenta achar o que foi gerado (caso recode tenha falhado ou algo assim)
        # Mas com 'recode-video': 'mp4' deve estar em mp4.
        return caminho_completo_saida

    def _download_audio_with_ytdlp(self, url: str, output_dir: str, filename_base: str, cookies_path: str = None) -> str:
        """
        Baixa áudio MP3 usando yt-dlp (baseado no script do usuário).
        """
        # Nome base limpo
        filename_base = filename_base.replace(".mp3", "").replace(".mp4", "")
        nome_final_mp3 = f"{filename_base}.mp3"
        caminho_completo_saida = os.path.join(output_dir, nome_final_mp3)
        
        if os.path.exists(caminho_completo_saida):
            logger.info(f"Arquivo de áudio já existe: {caminho_completo_saida}")
            return caminho_completo_saida

        logger.info(f"Iniciando download ÁUDIO yt-dlp: {filename_base}")

        ydl_opts = {
            'outtmpl': os.path.join(output_dir, filename_base) + '.%(ext)s',
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Referer': 'https://cf-embed.play.hotmart.com/',
            },
            'format': 'bestaudio/best',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': True,
            'no_warnings': True,
            'nocheckcertificate': True,
        }

        if cookies_path:
            ydl_opts['cookiefile'] = cookies_path

        with YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if os.path.exists(caminho_completo_saida):
            return caminho_completo_saida
            
        return caminho_completo_saida



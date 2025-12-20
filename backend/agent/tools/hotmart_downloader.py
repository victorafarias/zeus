"""
=====================================================
ZEUS - Hotmart Downloader Tool
Baixa vídeos e áudios de links Hotmart usando FFmpeg e yt-dlp
Suporte a cookies para downloads autenticados
=====================================================
"""

from typing import Dict, Any, Optional
import os
import shutil
import subprocess
import asyncio
import uuid

from .base import BaseTool, ToolParameter
from config import get_settings, get_logger

logger = get_logger(__name__)
settings = get_settings()


class HotmartDownloaderTool(BaseTool):
    """
    Baixa vídeos (MP4) ou extrai áudios (MP3) de links do Hotmart.
    - Vídeo: Usa FFmpeg com headers específicos
    - Áudio: Usa yt-dlp com pós-processamento FFmpeg para extração MP3
    - Suporte a cookies para autenticação (erro 403)
    """
    
    name = "hotmart_downloader"
    description = """Baixa vídeos ou áudios de links do Hotmart ('contentplayer.hotmart.com' ou 'vod-akm.play.hotmart.com').
Recebe a URL do vídeo (m3u8 ou link direto) e baixa como MP4 (vídeo) ou MP3 (áudio).
Use format='video' (padrão) para vídeo MP4 ou format='audio' para MP3.
Se o download falhar com erro 403 (Forbidden), solicite ao usuário um arquivo de cookies e passe o caminho em cookies_file.
Requer FFmpeg instalado no sistema."""
    
    parameters = [
        ToolParameter(
            name="url",
            type="string",
            description="URL do vídeo (m3u8) ou link da página do player Hotmart"
        ),
        ToolParameter(
            name="output_filename",
            type="string",
            description="Nome do arquivo de saída (opcional). Se não fornecido, gera um nome aleatório. Não inclua a extensão, será adicionada automaticamente.",
            required=False
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
            description="Caminho para arquivo de cookies (formato Netscape). Use quando o download falhar com erro 403 Forbidden. O usuário pode fazer upload do arquivo cookies.txt exportado do navegador.",
            required=False
        )
    ]
    
    async def execute(
        self,
        url: str,
        output_filename: str = None,
        format: str = "video",
        cookies_file: str = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Executa o download do conteúdo (vídeo ou áudio).
        
        Args:
            url: URL do conteúdo Hotmart
            output_filename: Nome do arquivo de saída (sem extensão)
            format: 'video' para MP4 ou 'audio' para MP3
            cookies_file: Caminho para arquivo de cookies (opcional, para autenticação)
        """
        
        # 1. Validar parâmetros
        if not url:
            return self._error("URL não fornecida.")
        
        # Normalizar o formato para minúsculas
        format = format.lower().strip() if format else "video"
        if format not in ["video", "audio"]:
            return self._error(f"Formato inválido: '{format}'. Use 'video' ou 'audio'.")
        
        # 2. Validar arquivo de cookies se fornecido
        if cookies_file:
            if not os.path.exists(cookies_file):
                return self._error(
                    f"Arquivo de cookies não encontrado: {cookies_file}. "
                    "Faça upload do arquivo cookies.txt exportado do navegador."
                )
            logger.info("Usando arquivo de cookies para autenticação", cookies_file=cookies_file)
            
        # 3. Verificar FFmpeg (obrigatório para ambos os formatos)
        if not shutil.which("ffmpeg"):
            return self._error("FFmpeg não encontrado no sistema. Por favor, instale o FFmpeg.")
        
        # 4. Para áudio, verificar se yt-dlp está disponível
        if format == "audio":
            try:
                from yt_dlp import YoutubeDL
            except ImportError:
                return self._error(
                    "yt-dlp não está instalado. Execute 'pip install yt-dlp' para habilitar download de áudio."
                )
            
        # 5. Definir caminho de saída
        output_dir = settings.outputs_dir
        if not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir, exist_ok=True)
            except Exception as e:
                return self._error(f"Não foi possível criar diretório de saída: {str(e)}")
        
        # 6. Definir extensão e nome do arquivo
        extension = ".mp3" if format == "audio" else ".mp4"
        
        if not output_filename:
            prefix = "hotmart_audio" if format == "audio" else "hotmart_video"
            output_filename = f"{prefix}_{uuid.uuid4().hex[:8]}"
        else:
            # Limpar extensões existentes do nome do arquivo
            output_filename = output_filename.replace(".mp4", "").replace(".mp3", "").replace(".m4a", "")
        
        # Adicionar extensão correta
        if not output_filename.endswith(extension):
            output_filename += extension
            
        full_output_path = os.path.join(output_dir, output_filename)
        
        # Verificar se já existe e gerar novo nome se necessário
        if os.path.exists(full_output_path):
            base, ext = os.path.splitext(output_filename)
            output_filename = f"{base}_{uuid.uuid4().hex[:4]}{ext}"
            full_output_path = os.path.join(output_dir, output_filename)

        logger.info(
            "Iniciando download Hotmart",
            url=url,
            format=format,
            output=full_output_path,
            using_cookies=bool(cookies_file)
        )
        
        # 7. Executar download de acordo com o formato
        try:
            if format == "audio":
                result = await asyncio.to_thread(
                    self._download_audio_synchronously,
                    url,
                    full_output_path,
                    cookies_file
                )
            else:
                result = await asyncio.to_thread(
                    self._download_video_synchronously,
                    url,
                    full_output_path,
                    cookies_file
                )
            return self._success(result)
            
        except Exception as e:
            error_str = str(e)
            logger.error("Erro no download Hotmart", error=error_str, format=format)
            
            # Detectar erro 403 e sugerir uso de cookies
            if "403" in error_str or "Forbidden" in error_str:
                return self._error(
                    f"Falha ao baixar {format}: Erro 403 (Acesso Negado). "
                    "Este conteúdo requer autenticação. Solicite ao usuário o arquivo de cookies "
                    "(cookies.txt exportado do navegador) e passe o caminho no parâmetro 'cookies_file'."
                )
            
            return self._error(f"Falha ao baixar {format}: {error_str}")


    def _download_video_synchronously(
        self,
        url: str,
        output_path: str,
        cookies_file: str = None
    ) -> str:
        """
        Executa o download de VÍDEO usando FFmpeg (bloqueante).
        Suporte a cookies para autenticação.
        """
        
        # Headers necessários para Hotmart
        headers = (
            "Referer: https://cf-embed.play.hotmart.com/\r\n"
            "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36\r\n"
        )
        
        # Montar comando base
        command = [
            'ffmpeg',
            '-headers', headers,
        ]
        
        # Adicionar cookies se fornecido
        # FFmpeg não suporta cookies diretamente no formato Netscape,
        # então precisamos converter para header Cookie
        if cookies_file and os.path.exists(cookies_file):
            cookie_header = self._parse_cookies_for_ffmpeg(cookies_file, url)
            if cookie_header:
                # Adicionar cookie ao header
                headers_with_cookie = headers + f"Cookie: {cookie_header}\r\n"
                command[2] = headers_with_cookie
                logger.debug("Cookies adicionados ao request FFmpeg")
        
        # Continuar com resto do comando
        command.extend([
            '-i', url,
            '-c', 'copy',
            '-bsf:a', 'aac_adtstoasc',
            '-y',
            output_path
        ])
        
        logger.debug("Executando comando FFmpeg para vídeo")
        
        try:
            process = subprocess.run(
                command,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            logger.info("Download de vídeo concluído", output=output_path)
            return f"✅ Download concluído com sucesso! Vídeo salvo em: {output_path}"
            
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr if e.stderr else str(e)
            raise Exception(f"Erro do FFmpeg: {error_msg}")


    def _download_audio_synchronously(
        self,
        url: str,
        output_path: str,
        cookies_file: str = None
    ) -> str:
        """
        Executa o download de ÁUDIO usando yt-dlp + FFmpeg (bloqueante).
        Extrai apenas o áudio e converte para MP3.
        Suporte a cookies para autenticação.
        """
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError
        
        # Obter diretório e nome base do arquivo
        output_dir = os.path.dirname(output_path)
        nome_arquivo_limpo = os.path.basename(output_path).replace(".mp3", "")
        
        # Configurações do yt-dlp para extração de áudio
        ydl_opts = {
            # Buscar melhor áudio disponível
            'format': 'bestaudio/best',
            
            # Template de saída (sem extensão, yt-dlp adiciona após conversão)
            'outtmpl': os.path.join(output_dir, nome_arquivo_limpo),
            
            # Pós-processadores para converter para MP3
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            
            # Headers específicos do Hotmart
            'referer': 'https://cf-embed.play.hotmart.com/',
            'http_headers': {
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                ),
            },
            
            # Configurações de log
            'quiet': True,
            'noprogress': False,
            
            # Ignorar erros de certificado em alguns casos
            'nocheckcertificate': True,
        }
        
        # Adicionar arquivo de cookies se fornecido
        if cookies_file and os.path.exists(cookies_file):
            ydl_opts['cookiefile'] = cookies_file
            logger.info("Usando cookies para download de áudio", cookies_file=cookies_file)
        
        logger.debug(
            "Iniciando extração de áudio com yt-dlp",
            output_template=ydl_opts['outtmpl'],
            using_cookies=bool(cookies_file)
        )
        
        try:
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            # Verificar se o arquivo foi criado
            if os.path.exists(output_path):
                logger.info("Download de áudio concluído", output=output_path)
                return f"✅ Áudio extraído com sucesso! MP3 salvo em: {output_path}"
            else:
                # Às vezes o yt-dlp salva com extensão diferente
                alternative_path = output_path.replace(".mp3", ".opus")
                if os.path.exists(alternative_path):
                    return f"✅ Áudio extraído! Arquivo salvo em: {alternative_path}"
                    
                return f"✅ Áudio processado! Verifique a pasta: {output_dir}"
                
        except DownloadError as e:
            logger.error("Erro de download yt-dlp", error=str(e))
            raise Exception(f"Falha no download: {e}")
        except Exception as e:
            logger.error("Erro inesperado na extração de áudio", error=str(e))
            raise Exception(f"Erro inesperado: {e}")


    def _parse_cookies_for_ffmpeg(self, cookies_file: str, url: str) -> str:
        """
        Parseia arquivo de cookies no formato Netscape e retorna string de cookies
        para usar no header do FFmpeg.
        
        Args:
            cookies_file: Caminho para arquivo de cookies
            url: URL de destino (para filtrar cookies por domínio)
            
        Returns:
            String de cookies no formato "nome=valor; nome2=valor2"
        """
        try:
            cookies = []
            with open(cookies_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    # Ignorar comentários e linhas vazias
                    if not line or line.startswith('#'):
                        continue
                    
                    # Formato Netscape: domain, flag, path, secure, expiry, name, value
                    parts = line.split('\t')
                    if len(parts) >= 7:
                        domain = parts[0]
                        name = parts[5]
                        value = parts[6]
                        
                        # Filtrar cookies relevantes (domínio hotmart)
                        if 'hotmart' in domain.lower() or 'play.hotmart' in domain.lower():
                            cookies.append(f"{name}={value}")
            
            if cookies:
                cookie_string = "; ".join(cookies)
                logger.debug(f"Cookies parseados: {len(cookies)} cookies encontrados")
                return cookie_string
            
            return ""
            
        except Exception as e:
            logger.warning(f"Erro ao parsear cookies: {e}")
            return ""



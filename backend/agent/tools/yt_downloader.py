"""
=====================================================
ZEUS - YouTube Downloader Tool
Baixa vídeos e áudios do YouTube usando yt-dlp
=====================================================
"""

from typing import Dict, Any
import os
import uuid
import asyncio
import re
import tempfile

from .base import BaseTool, ToolParameter
from config import get_settings, get_logger

logger = get_logger(__name__)
settings = get_settings()


class YouTubeDownloaderTool(BaseTool):
    """
    Baixa vídeos (MP4) ou extrai áudios (MP3) de links do YouTube.
    Utiliza yt-dlp como primeira opção, pytubefix como fallback e pytube como última opção.
    """
    
    name = "yt_download"
    description = """Baixa vídeos ou áudios de links do YouTube.
Use format='video' (padrão) para baixar vídeo MP4 ou format='audio' para extrair apenas o áudio em MP3.
Parâmetro quality permite escolher qualidade do vídeo: 'best', '720p', '480p', '360p'.
O arquivo será salvo na pasta /outputs.
Tenta usar na ordem: yt-dlp -> pytubefix -> pytube.

Para vídeos com restrição de idade ou que exigem login, use o parâmetro cookies_text com o conteúdo do arquivo cookies.txt exportado do navegador (formato Netscape)."""
    
    parameters = [
        ToolParameter(
            name="url",
            type="string",
            description="URL do vídeo do YouTube (youtube.com ou youtu.be)"
        ),
        ToolParameter(
            name="format",
            type="string",
            description="Formato de saída: 'video' para MP4 (padrão) ou 'audio' para MP3",
            required=False
        ),
        ToolParameter(
            name="quality",
            type="string",
            description="Qualidade do vídeo: 'best' (padrão), '720p', '480p', '360p'. Ignorado para áudio.",
            required=False
        ),
        ToolParameter(
            name="output_filename",
            type="string",
            description="Nome do arquivo de saída (opcional, sem extensão). Se não fornecido, usa o título do vídeo.",
            required=False
        ),
        ToolParameter(
            name="cookies_text",
            type="string",
            description="Conteúdo do arquivo cookies.txt no formato Netscape. Necessário para vídeos com restrição de idade ou que exigem login. O usuário deve exportar os cookies do navegador usando extensão como 'Get cookies.txt LOCALLY'.",
            required=False
        ),
        ToolParameter(
            name="cookies_file",
            type="string",
            description="Caminho para arquivo cookies.txt existente (alternativa ao cookies_text). Útil quando o arquivo já foi enviado via upload.",
            required=False
        )
    ]
    
    async def execute(
        self,
        url: str,
        format: str = "video",
        quality: str = "best",
        output_filename: str = None,
        cookies_text: str = None,
        cookies_file: str = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Executa o download do conteúdo do YouTube.
        
        Args:
            url: URL do vídeo do YouTube
            format: 'video' para MP4 ou 'audio' para MP3
            quality: Qualidade do vídeo (best, 720p, 480p, 360p)
            output_filename: Nome do arquivo de saída (sem extensão)
            cookies_text: Conteúdo do arquivo cookies.txt (formato Netscape)
            cookies_file: Caminho para arquivo cookies.txt existente
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
        
        # 2. Normalizar e validar parâmetros
        format = format.lower().strip() if format else "video"
        if format not in ["video", "audio"]:
            return self._error(f"Formato inválido: '{format}'. Use 'video' ou 'audio'.")
        
        quality = quality.lower().strip() if quality else "best"
        valid_qualities = ["best", "720p", "480p", "360p"]
        if quality not in valid_qualities:
            return self._error(
                f"Qualidade inválida: '{quality}'. "
                f"Use: {', '.join(valid_qualities)}"
            )
        
        # 3. Verificar yt-dlp
        try:
            from yt_dlp import YoutubeDL
        except ImportError:
            return self._error(
                "yt-dlp não está instalado. Execute 'pip install yt-dlp'."
            )
            
        # Adicionar Deno ao PATH para resolver desafios do YouTube (necessário para yt-dlp recente)
        # O agente pode ter instalado o deno em /root/.deno/bin
        deno_paths = [
            os.path.expanduser("~/.deno/bin"),
            "/root/.deno/bin"
        ]
        
        for path in deno_paths:
            if os.path.exists(path):
                if path not in os.environ["PATH"]:
                    os.environ["PATH"] = f"{path}:{os.environ['PATH']}"
                    logger.info("Adicionado binário do Deno ao PATH", path=path)
                break
        
        # 4. Garantir diretório de saída
        output_dir = settings.outputs_dir
        os.makedirs(output_dir, exist_ok=True)
        
        # 5. Processar cookies (texto ou arquivo)
        temp_cookies_file = None
        effective_cookies_file = None
        
        if cookies_text:
            # Criar arquivo temporário com o conteúdo dos cookies
            temp_cookies_file = self._create_temp_cookies_file(cookies_text, output_dir)
            if temp_cookies_file:
                effective_cookies_file = temp_cookies_file
                logger.info("Arquivo de cookies temporário criado", path=temp_cookies_file)
        elif cookies_file:
            # Usar arquivo de cookies fornecido
            if os.path.exists(cookies_file):
                effective_cookies_file = cookies_file
                logger.info("Usando arquivo de cookies existente", path=cookies_file)
            else:
                logger.warning("Arquivo de cookies não encontrado", path=cookies_file)
        
        logger.info(
            "Iniciando download YouTube",
            url=url,
            format=format,
            quality=quality,
            using_cookies=bool(effective_cookies_file)
        )
        
        report_progress(f"Iniciando download do YouTube ({format})...")
        
        # 6. Executar download em thread separada
        try:
            # Tentar com yt-dlp primeiro
            result = await asyncio.to_thread(
                self._download_synchronously,
                url,
                format,
                quality,
                output_filename,
                output_dir,
                effective_cookies_file,
                report_progress
            )
            return self._success(result)
            
        except Exception as e:
            error_str = str(e)
            logger.warning(f"Falha com yt-dlp, tentando fallback com pytubefix: {error_str}")
            report_progress("⚠️ Falha com yt-dlp, tentando método alternativo (pytubefix)...")
            
            try:
                # Fallback par pytubefix
                result = await asyncio.to_thread(
                    self._download_with_pytubefix,
                    url,
                    format,
                    output_filename,
                    output_dir,
                    effective_cookies_file,
                    report_progress
                )
                return self._success(result)
            except Exception as e_fallback:
                fallback_error = str(e_fallback)
                logger.warning(f"Falha também no chatbot pytubefix: {fallback_error}")
                report_progress("⚠️ Falha com pytubefix, tentando último recurso (pytube)...")
                
                try:
                    # Último recurso: pytube
                    result = await asyncio.to_thread(
                        self._download_with_pytube,
                        url,
                        format,
                        output_filename,
                        output_dir,
                        progress_callback
                    )
                    return self._success(result)
                except Exception as e_last_resort:
                    last_resort_error = str(e_last_resort)
                    logger.error(f"Falha final com pytube: {last_resort_error}")
            
            # Se todos falharem, retornar erro detalhado do yt-dlp
            logger.error("Erro no download YouTube (todos métodos falharam)", error=error_str)
            
            # Detectar erro de restrição de idade e dar orientação
            age_restricted_keywords = [
                "age", "restricted", "Sign in", "confirm your age",
                "login", "verificar", "idade"
            ]
            is_age_restricted = any(kw.lower() in error_str.lower() for kw in age_restricted_keywords)
            
            if is_age_restricted and not effective_cookies_file:
                return self._error(
                    f"Falha no download (yt-dlp/pytubefix/pytube): {error_str}\n\n"
                    "🔒 **Este vídeo requer autenticação (restrição de idade/login).**\n\n"
                    "Para resolver, o usuário deve:\n"
                    "1. Instalar a extensão 'Get cookies.txt LOCALLY' no Chrome/Edge\n"
                    "2. Fazer login no YouTube\n"
                    "3. Acessar o vídeo desejado\n"
                    "4. Clicar na extensão e exportar os cookies\n"
                    "5. Colar o conteúdo do arquivo no parâmetro 'cookies_text'\n\n"
                    "Comando para extrair cookies via terminal (alternativo):\n"
                    "`yt-dlp --cookies-from-browser chrome --cookies cookies.txt 'URL'`"
                )
            
            return self._error(f"Falha no download:\nyt-dlp: {error_str}\npytubefix: {fallback_error}\npytube: {last_resort_error}")
        finally:
            # Limpar arquivo temporário de cookies após o download
            if temp_cookies_file and os.path.exists(temp_cookies_file):
                try:
                    os.remove(temp_cookies_file)
                    logger.debug("Arquivo de cookies temporário removido", path=temp_cookies_file)
                except Exception as e:
                    logger.warning("Erro ao remover cookies temporário", error=str(e))
    
    
    def _is_youtube_url(self, url: str) -> bool:
        """
        Verifica se a URL é do YouTube.
        
        Args:
            url: URL para verificar
            
        Returns:
            True se for URL válida do YouTube
        """
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
    
    
    def _create_temp_cookies_file(self, cookies_text: str, output_dir: str) -> str:
        """
        Cria um arquivo temporário com o conteúdo dos cookies.
        
        Args:
            cookies_text: Conteúdo do arquivo cookies.txt
            output_dir: Diretório onde criar o arquivo
            
        Returns:
            Caminho para o arquivo temporário criado, ou None se falhar
        """
        try:
            # Validar se o texto parece ser cookies no formato Netscape
            if not cookies_text or len(cookies_text.strip()) < 10:
                logger.warning("Texto de cookies muito curto ou vazio")
                return None
            
            # Verificar se tem o header Netscape (opcional, mas recomendado)
            lines = cookies_text.strip().split('\n')
            has_netscape_header = any('Netscape' in line for line in lines[:3])
            
            if not has_netscape_header:
                logger.info("Cookies sem header Netscape, adicionando...")
                cookies_text = "# Netscape HTTP Cookie File\n" + cookies_text
            
            # Criar arquivo temporário no diretório de saída
            temp_filename = f"yt_cookies_{uuid.uuid4().hex[:8]}.txt"
            temp_path = os.path.join(output_dir, temp_filename)
            
            with open(temp_path, 'w', encoding='utf-8') as f:
                f.write(cookies_text)
            
            logger.info("Arquivo de cookies temporário criado", path=temp_path, lines=len(lines))
            return temp_path
            
        except Exception as e:
            logger.error("Erro ao criar arquivo de cookies temporário", error=str(e))
            return None
    
    
    def _download_synchronously(
        self,
        url: str,
        format: str,
        quality: str,
        output_filename: str,
        output_dir: str,
        cookies_file: str = None,
        progress_callback=None
    ) -> str:
        """
        Executa o download usando yt-dlp (bloqueante).
        
        Args:
            url: URL do vídeo
            format: 'video' ou 'audio'
            quality: Qualidade desejada
            output_filename: Nome do arquivo (opcional)
            output_dir: Diretório de saída
            cookies_file: Caminho para arquivo de cookies (opcional)
            progress_callback: Função para reportar progresso
            
        Returns:
            Mensagem de sucesso com caminho do arquivo
        """
        from yt_dlp import YoutubeDL
        from yt_dlp.utils import DownloadError
        
        # Configurar template de saída
        if output_filename:
            # Limpar extensões existentes
            output_filename = re.sub(r'\.(mp4|mp3|webm|m4a)$', '', output_filename, flags=re.IGNORECASE)
            outtmpl = os.path.join(output_dir, f"{output_filename}.%(ext)s")
        else:
            # Usar título do vídeo
            outtmpl = os.path.join(output_dir, "%(title)s.%(ext)s")
        
        # Configurações base do yt-dlp
        ydl_opts = {
            'outtmpl': outtmpl,
            'quiet': True,
            'noprogress': False,
            'nocheckcertificate': True,
        }
        
        # Adicionar arquivo de cookies se fornecido (para vídeos restritos)
        if cookies_file and os.path.exists(cookies_file):
            ydl_opts['cookiefile'] = cookies_file
            logger.info("Usando cookies para bypass de restrições", cookies_file=cookies_file)
            if progress_callback:
                progress_callback("🍪 Usando cookies para autenticação...")
        
        # Configurar formato baseado no tipo de download
        if format == "audio":
            # Download apenas áudio e converter para MP3
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            })
            if progress_callback:
                progress_callback("Baixando áudio e convertendo para MP3...")
        else:
            # Download de vídeo com qualidade especificada
            format_string = self._get_video_format_string(quality)
            ydl_opts.update({
                'format': format_string,
                'merge_output_format': 'mp4',
            })
            if progress_callback:
                progress_callback(f"Baixando vídeo (qualidade: {quality})...")
        
        logger.debug("Configurações yt-dlp", opts=ydl_opts)
        
        try:
            with YoutubeDL(ydl_opts) as ydl:
                # Primeiro, obter informações do vídeo
                info = ydl.extract_info(url, download=False)
                video_title = info.get('title', 'video')
                
                if progress_callback:
                    progress_callback(f"Baixando: {video_title}...")
                
                # Fazer o download
                ydl.download([url])
                
                # Determinar extensão final
                ext = "mp3" if format == "audio" else "mp4"
                
                # Construir caminho do arquivo final
                if output_filename:
                    final_filename = f"{output_filename}.{ext}"
                else:
                    # Limpar título para nome de arquivo
                    clean_title = self._sanitize_filename(video_title)
                    final_filename = f"{clean_title}.{ext}"
                
                final_path = os.path.join(output_dir, final_filename)
                
                # Verificar se o arquivo existe
                if os.path.exists(final_path):
                    file_size = os.path.getsize(final_path)
                    size_mb = file_size / (1024 * 1024)
                    
                    logger.info(
                        "Download concluído",
                        file=final_path,
                        size_mb=round(size_mb, 2)
                    )
                    
                    return (
                        f"✅ Download concluído com sucesso!\n"
                        f"📁 Arquivo: {final_path}\n"
                        f"📊 Tamanho: {size_mb:.2f} MB"
                    )
                else:
                    # Procurar arquivo com padrão similar
                    return self._find_downloaded_file(output_dir, video_title, ext)
                    
        except DownloadError as e:
            logger.error("Erro de download yt-dlp", error=str(e))
            raise Exception(f"Falha no download: {e}")
        except Exception as e:
            logger.error("Erro inesperado no download", error=str(e))
            raise Exception(f"Erro inesperado: {e}")
    
    
    def _get_video_format_string(self, quality: str) -> str:
        """
        Retorna string de formato do yt-dlp para a qualidade especificada.
        
        Args:
            quality: Qualidade desejada
            
        Returns:
            String de formato para yt-dlp
        """
        quality_map = {
            'best': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            '720p': 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]',
            '480p': 'bestvideo[height<=480][ext=mp4]+bestaudio[ext=m4a]/best[height<=480]',
            '360p': 'bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/best[height<=360]',
        }
        return quality_map.get(quality, quality_map['best'])
    
    
    def _sanitize_filename(self, filename: str) -> str:
        """
        Remove caracteres inválidos do nome do arquivo.
        
        Args:
            filename: Nome original
            
        Returns:
            Nome limpo e seguro para sistema de arquivos
        """
        # Remover caracteres inválidos para sistemas de arquivos
        invalid_chars = r'[<>:"/\\|?*]'
        clean = re.sub(invalid_chars, '', filename)
        # Remover espaços extras
        clean = re.sub(r'\s+', ' ', clean).strip()
        # Limitar tamanho
        if len(clean) > 200:
            clean = clean[:200]
        return clean
    
    
    def _find_downloaded_file(self, output_dir: str, title: str, ext: str) -> str:
        """
        Procura pelo arquivo baixado no diretório de saída.
        
        Args:
            output_dir: Diretório onde o arquivo foi salvo
            title: Título do vídeo
            ext: Extensão esperada
            
        Returns:
            Mensagem com informação do arquivo encontrado
        """
        # Listar arquivos recentes no diretório
        try:
            files = os.listdir(output_dir)
            # Filtrar por extensão
            matching_files = [f for f in files if f.endswith(f'.{ext}')]
            
            if matching_files:
                # Ordenar por data de modificação (mais recente primeiro)
                matching_files.sort(
                    key=lambda f: os.path.getmtime(os.path.join(output_dir, f)),
                    reverse=True
                )
                latest_file = matching_files[0]
                return f"✅ Download concluído! Arquivo salvo: {os.path.join(output_dir, latest_file)}"
        except Exception as e:
            logger.warning("Erro ao procurar arquivo baixado", error=str(e))
        

    def _download_with_pytubefix(
        self,
        url: str,
        format: str,
        output_filename: str,
        output_dir: str,
        cookies_file: str = None,
        progress_callback=None
    ) -> str:
        """
        Executa o download usando pytubefix (fallback).
        
        Args:
            url: URL do vídeo
            format: 'video' ou 'audio'
            output_filename: Nome do arquivo (opcional)
            output_dir: Diretório de saída
            cookies_file: Caminho para arquivo de cookies (opcional)
            progress_callback: Função para reportar progresso
        """
        try:
            from pytubefix import YouTube
        except ImportError:
            raise Exception("pytubefix não instalado. Execute 'pip install pytubefix'.")
        
        logger.info("Iniciando fallback com pytubefix", url=url)
        
        def on_progress(stream, chunk, bytes_remaining):
            total_size = stream.filesize
            bytes_downloaded = total_size - bytes_remaining
            percentage = (bytes_downloaded / total_size) * 100
            if progress_callback and int(percentage) % 10 == 0:
                progress_callback(f"Baixando (pytubefix): {int(percentage)}%")

        try:
            # Configurar YouTube object
            # Nota: pytubefix suporta 'use_oauth' e 'allow_oauth_cache' para autenticação
            # Mas vamos tentar sem OAuth primeiro para não bloquear esperando input
            yt = YouTube(
                url, 
                on_progress_callback=on_progress,
                use_oauth=False,
                allow_oauth_cache=True
            )
            
            video_title = yt.title
            clean_title = self._sanitize_filename(video_title)
            final_filename = output_filename if output_filename else clean_title
            
            if format == "audio":
                if progress_callback:
                    progress_callback("Baixando áudio com pytubefix...")
                
                # Pegar apenas áudio
                stream = yt.streams.get_audio_only()
                if not stream:
                    raise Exception("Stream de áudio não encontrado")
                
                # Baixar
                download_path = stream.download(output_path=output_dir, filename=f"{final_filename}_temp.m4a")
                
                # Converter para MP3 usando ffmpeg manualmente se necessário
                # É mais garantido converter manualmente pois pytubefix baixa m4a/webm
                final_path = os.path.join(output_dir, f"{final_filename}.mp3")
                
                # Usar FFmpeg para converter
                self._convert_to_mp3(download_path, final_path)
                
                # Remover original
                if os.path.exists(download_path) and os.path.exists(final_path):
                    os.remove(download_path)
                    
            else:
                if progress_callback:
                    progress_callback("Baixando vídeo com pytubefix...")
                
                # Pegar melhor vídeo progressivo (video+audio) se disponível até 720p
                # Streams progressivos são mais seguros no pytube
                stream = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first()
                
                # Se não achar progressivo bom, pega o melhor adaptativo e teria que juntar áudio...
                # Para simplificar o fallback, vamos focar no progressivo que funciona direto
                if not stream:
                    stream = yt.streams.filter(file_extension='mp4').order_by('resolution').desc().first()
                
                if not stream:
                    raise Exception("Nenhum stream de vídeo compatível encontrado")
                    
                final_path = stream.download(output_path=output_dir, filename=f"{final_filename}.mp4")

            file_size = os.path.getsize(final_path)
            size_mb = file_size / (1024 * 1024)
            
            return (
                f"✅ Download concluído (via pytubefix)!\n"
                f"📁 Arquivo: {final_path}\n"
                f"📊 Tamanho: {size_mb:.2f} MB"
            )
            
        except Exception as e:
            logger.error("Erro no pytubefix", error=str(e))
            raise e


    def _download_with_pytube(
        self,
        url: str,
        format: str,
        output_filename: str,
        output_dir: str,
        progress_callback=None
    ) -> str:
        """
        Executa o download usando pytube (fallback secundário).
        
        Args:
            url: URL do vídeo
            format: 'video' ou 'audio'
            output_filename: Nome do arquivo (opcional)
            output_dir: Diretório de saída
            progress_callback: Função para reportar progresso
        """
        try:
            from pytube import YouTube
        except ImportError:
            raise Exception("pytube não instalado. Execute 'pip install pytube'.")
        
        logger.info("Iniciando fallback secundário com pytube", url=url)
        
        def on_progress(stream, chunk, bytes_remaining):
            total_size = stream.filesize
            bytes_downloaded = total_size - bytes_remaining
            percentage = (bytes_downloaded / total_size) * 100
            if progress_callback and int(percentage) % 10 == 0:
                progress_callback(f"Baixando (pytube): {int(percentage)}%")

        try:
            yt = YouTube(url, on_progress_callback=on_progress)
            
            video_title = yt.title
            clean_title = self._sanitize_filename(video_title)
            final_filename = output_filename if output_filename else clean_title
            
            if format == "audio":
                if progress_callback:
                    progress_callback("Baixando áudio com pytube...")
                
                stream = yt.streams.get_audio_only()
                if not stream:
                    raise Exception("Stream de áudio não encontrado")
                
                download_path = stream.download(output_path=output_dir, filename=f"{final_filename}_temp.m4a")
                final_path = os.path.join(output_dir, f"{final_filename}.mp3")
                
                self._convert_to_mp3(download_path, final_path)
                
                if os.path.exists(download_path) and os.path.exists(final_path):
                    os.remove(download_path)
                    
            else:
                if progress_callback:
                    progress_callback("Baixando vídeo com pytube...")
                
                stream = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first()
                
                if not stream:
                    stream = yt.streams.filter(file_extension='mp4').order_by('resolution').desc().first()
                
                if not stream:
                    raise Exception("Nenhum stream de vídeo compatível encontrado")
                    
                final_path = stream.download(output_path=output_dir, filename=f"{final_filename}.mp4")

            file_size = os.path.getsize(final_path)
            size_mb = file_size / (1024 * 1024)
            
            return (
                f"✅ Download concluído (via pytube)!\n"
                f"📁 Arquivo: {final_path}\n"
                f"📊 Tamanho: {size_mb:.2f} MB"
            )
            
        except Exception as e:
            logger.error("Erro no pytube", error=str(e))
            raise e


    def _convert_to_mp3(self, input_path: str, output_path: str):
        """Converte áudio para MP3 usando ffmpeg via subprocess"""
        import subprocess
        try:
            cmd = [
                'ffmpeg', '-y', # Overwrite
                '-i', input_path,
                '-vn', # No video
                '-acodec', 'libmp3lame',
                '-q:a', '2', # Boa qualidade (VBR ~190kbps)
                output_path
            ]
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            raise Exception(f"Erro na conversão FFmpeg: {e.stderr.decode('utf-8')}")
        except FileNotFoundError:
             raise Exception("FFmpeg não encontrado no sistema para conversão de áudio.")


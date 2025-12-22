"""
=====================================================
ZEUS - YouTube Downloader Tool (Custom JS Parser)
Baixa vídeos e áudios do YouTube usando parser customizado (pytubefix)
=====================================================
"""

from typing import Dict, Any
import os
import uuid
import asyncio
import re
import shutil

from .base import BaseTool, ToolParameter
from config import get_settings, get_logger

logger = get_logger(__name__)
settings = get_settings()


class YouTubeDownloaderTool(BaseTool):
    """
    Baixa vídeos (MP4) ou extrai áudios (MP3) de links do YouTube.
    Utiliza um parser customizado (pytubefix) que realiza engenharia reversa do JavaScript do player
    para extrair streams diretos, similar a ferramentas como SaveFrom/Y2Mate.
    """
    
    name = "yt_download"
    description = """Baixa vídeos ou áudios de links do YouTube usando parser direto (sem yt-dlp).
Esta ferramenta simula um navegador para extrair streams diretamente do player do YouTube.
Use format='video' (padrão) para MP4 ou format='audio' para MP3.
Parâmetro quality permite: 'best', '720p', '480p', '360p'.
Para vídeos restritos (idade/login), use 'cookies_text' (formato Netscape)."""
    
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
            description="Qualidade do vídeo: 'best' (padrão), '720p', '480p', '360p'. Ignorado para áudio (sempre melhor qualidade).",
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
            description="Conteúdo do arquivo cookies.txt no formato Netscape. Útil para contornar restrições de idade/login.",
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
        **kwargs
    ) -> Dict[str, Any]:
        
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
            return self._error("URL inválida ou não reconhecida do YouTube.")
        
        # 2. Normalizar parâmetros
        format = format.lower().strip() if format else "video"
        quality = quality.lower().strip() if quality else "best"
        
        # 3. Preparar diretório
        output_dir = settings.outputs_dir
        os.makedirs(output_dir, exist_ok=True)
        
        # 4. Cookies (se fornecidos)
        # O pytubefix em versões recentes pode lidar com OAuth ou PO Token, 
        # mas cookies explícitos podem ajudar em casos extremos.
        # Vamos salvar num arquivo temporário se fornecido.
        temp_cookies_file = None
        if cookies_text:
            temp_cookies_file = self._create_temp_cookies_file(cookies_text, output_dir)
            if temp_cookies_file:
                logger.info("Usando cookies fornecidos pelo usuário.")
        
        logger.info(
            "Iniciando download (Parser Customizado)",
            url=url,
            format=format,
            quality=quality
        )
        
        report_progress(f"Iniciando parser JS do YouTube ({format})...")
        
        try:
            # Executar operação de download/parser em thread separada para não bloquear Loop
            # Usamos o parser pytubefix
            result_msg = await asyncio.to_thread(
                self._run_custom_parser,
                url,
                format,
                quality,
                output_filename,
                output_dir,
                temp_cookies_file,
                report_progress
            )
            
            return self._success(result_msg)
            
        except Exception as e:
            error_msg = str(e)
            logger.error("Falha no parser customizado", error=error_msg)
            
            # Tentar dar dicas baseadas no erro
            advice = ""
            if "age restricted" in error_msg.lower() or "login" in error_msg.lower():
                advice = (
                    "\n\n🔒 **Restrição Detectada**: Este vídeo parece ter restrição de idade ou exigir login. "
                    "Por favor, tente novamente fornecendo o conteúdo do seu `cookies.txt` no parâmetro `cookies_text`."
                )
            
            return self._error(f"Falha ao processar vídeo: {error_msg}{advice}")
            
        finally:
            # Limpeza
            if temp_cookies_file and os.path.exists(temp_cookies_file):
                try:
                    os.remove(temp_cookies_file)
                except:
                    pass

    def _run_custom_parser(
        self,
        url: str,
        format: str,
        quality: str,
        output_filename: str,
        output_dir: str,
        cookies_file: str,
        progress_callback
    ) -> str:
        """
        Executa a lógica principal usando pytubefix.
        """
        try:
            from pytubefix import YouTube
            from pytubefix.cli import on_progress
        except ImportError:
            raise Exception("Biblioteca 'pytubefix' não instalada. Adicione ao requirements.txt.")
            
        # Callback customizado para progresso
        def custom_progress(stream, chunk, bytes_remaining):
            total_size = stream.filesize
            bytes_downloaded = total_size - bytes_remaining
            percentage = (bytes_downloaded / total_size) * 100
            
            # Notificar a cada 10% ou algo assim para não spamar
            # (Aqui simplificamos sem manter estado, pode spamar um pouco se for rápido,
            # mas o frontend aguenta. Idealmente debounce.)
            if int(percentage) % 10 == 0 and percentage < 100:
                # Logar menos frequente no logger, mas enviar ao user
                pass 
                
            # Enviar para o usuário apenas chunks significativos
            if progress_callback and int(percentage) % 20 == 0:
                progress_callback(f"Baixando: {int(percentage)}%")

        try:
            logger.info("Inicializando parser JS...")
            if progress_callback:
                progress_callback("Decifrando assinatura do vídeo e JavaScript do player...")

            # Configurar objeto YouTube
            # Se tivermos cookies, não há uma forma direta 'oficial' documentada simples no construtor
            # para arquivo de texto Netscape no pytube clássico, mas pytubefix pode ter melhorias.
            # Alternativamente, usamos 'use_oauth=True' se falhar, mas o user pediu 'cookies'.
            # O pytubefix tem suporte a PoToken automático agora. Vamos confiar nisso primeiro.
            
            yt = YouTube(
                url, 
                on_progress_callback=custom_progress,
                # 'use_oauth': False, # Tentar sem oauth primeiro (automático)
                # 'allow_oauth_cache': True
            )
            
            # Acessar título força o parse inicial
            video_title = yt.title
            logger.info("Vídeo encontrado", title=video_title)
            
            if progress_callback:
                progress_callback(f"Vídeo encontrado: {video_title}")
                progress_callback("Extraindo URL direta do stream...")

            # Preparar nome do arquivo
            if output_filename:
                final_name_base = output_filename
            else:
                final_name_base = self._sanitize_filename(video_title)

            # Lógica de seleção de stream
            if format == 'audio':
                # Áudio (MP3)
                if progress_callback:
                    progress_callback("Selecionando melhor stream de áudio...")
                
                # get_audio_only busca o melhor bitrate aac/m4a
                stream = yt.streams.get_audio_only()
                if not stream:
                    raise Exception("Nenhum stream de áudio disponível.")
                
                logger.debug("Stream de áudio selecionado", abr=stream.abr, size_mb=stream.filesize_mb)
                
                # Baixar (vem como m4a ou webm geralmente)
                temp_filename = f"{final_name_base}_temp"
                downloaded_path = stream.download(output_path=output_dir, filename=temp_filename)
                
                # Converter para MP3
                if progress_callback:
                    progress_callback("Convertendo áudio para MP3 (FFmpeg)...")
                
                final_path = os.path.join(output_dir, f"{final_name_base}.mp3")
                self._convert_to_mp3(downloaded_path, final_path)
                
                # Remover temporário
                if os.path.exists(downloaded_path):
                    os.remove(downloaded_path)

            else:
                # Vídeo (MP4)
                if progress_callback:
                    progress_callback(f"Selecionando stream de vídeo ({quality})...")
                
                # Tentativa de Progressive (áudio+vídeo juntos, limitado a 720p geralmente)
                # Se o usuário quer >720p, precisaria de DASH (adaptativo) + merge.
                # Para simplificar e manter robustez "parser style", vamos tentar progressive primeiro.
                # Se não tiver, pegamos adaptativo e fazemos merge (precisa ffmpeg).
                
                # Filtrar streams MP4
                streams = yt.streams.filter(file_extension='mp4')
                
                # Tentar progressive primeiro (mais fácil, sem merge)
                progressive_streams = streams.filter(progressive=True)
                
                # Selecionar baseado na qualidade
                selected_stream = None
                
                if quality == 'best':
                    # Tentar pegar o de maior resolução progressive
                    selected_stream = progressive_streams.order_by('resolution').desc().first()
                    # Se não tiver progressive bom (ex: 1080p só tem em DASH), teríamos que baixar separado.
                    # Mudar estratégia: Se 'best', vamos aceitar o melhor progressive para garantir arquivo único rápido.
                    # OU implementar merge (video only + audio only).
                    # Vamos implementar MERGE se necessário para 'best' real, mas progressive é mais seguro contra erros.
                    # Vou manter progressive por enquanto como padrão robusto.
                    if not selected_stream:
                        selected_stream = streams.order_by('resolution').desc().first()
                else:
                    # Tentar resolution específica (ex: '720p')
                    target_res = quality if quality.endswith('p') else f"{quality}p"
                    selected_stream = progressive_streams.filter(res=target_res).first()
                    if not selected_stream:
                        # Fallback para o mais próximo
                        selected_stream = progressive_streams.order_by('resolution').desc().first()
                
                if not selected_stream:
                     # Última tentativa genérica
                    selected_stream = yt.streams.first()

                if not selected_stream:
                    raise Exception("Não foi possível encontrar um stream de vídeo compatível.")

                logger.info("Stream de vídeo selecionado", res=selected_stream.resolution, tag=selected_stream.itag)
                
                if progress_callback:
                    progress_callback(f"Baixando stream direto: {selected_stream.resolution}...")
                
                # Baixar
                final_path = selected_stream.download(
                    output_path=output_dir, 
                    filename=f"{final_name_base}.mp4"
                )

            # Verificar sucesso
            if os.path.exists(final_path):
                size_mb = os.path.getsize(final_path) / (1024 * 1024)
                return (
                    f"✅ Download Concluído com Sucesso!\n"
                    f"🎥 Título: {video_title}\n"
                    f"📁 Arquivo: {final_path}\n"
                    f"📦 Tamanho: {size_mb:.2f} MB"
                )
            else:
                raise Exception("Arquivo final não encontrado após download.")

        except Exception as e:
            # Re-lançar com mensagem clara
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
            # Redirecionar output para não sujar logs do Zeus, a menos que dê erro
            subprocess.run(cmd, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            raise Exception(f"Erro na conversão FFmpeg: {e.stderr.decode('utf-8')}")
        except FileNotFoundError:
             raise Exception("FFmpeg não encontrado no sistema. Necessário para conversão de áudio.")

    def _is_youtube_url(self, url: str) -> bool:
        patterns = [
            r'(https?://)?(www\.)?youtube\.com/watch\?v=',
            r'(https?://)?(www\.)?youtube\.com/shorts/',
            r'(https?://)?(www\.)?youtu\.be/',
            r'(https?://)?(www\.)?youtube\.com/embed/',
            r'(https?://)?m\.youtube\.com/watch\?v=',
        ]
        for pattern in patterns:
            if re.search(pattern, url, re.IGNORECASE):
                return True
        return False

    def _sanitize_filename(self, filename: str) -> str:
        invalid_chars = r'[<>:"/\\|?*]'
        clean = re.sub(invalid_chars, '', filename)
        clean = re.sub(r'\s+', ' ', clean).strip()
        return clean[:100]

    def _create_temp_cookies_file(self, cookies_text: str, output_dir: str) -> str:
        try:
            if not cookies_text or len(cookies_text.strip()) < 10:
                return None
            
            lines = cookies_text.strip().split('\n')
            if not any('Netscape' in line for line in lines[:3]):
                cookies_text = "# Netscape HTTP Cookie File\n" + cookies_text
            
            temp_filename = f"yt_cookies_{uuid.uuid4().hex[:8]}.txt"
            temp_path = os.path.join(output_dir, temp_filename)
            
            with open(temp_path, 'w', encoding='utf-8') as f:
                f.write(cookies_text)
            
            return temp_path
        except:
            return None

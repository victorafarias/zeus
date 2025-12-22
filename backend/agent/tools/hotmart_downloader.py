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

# Tentar importar yt_dlp apenas para verificação de tipos se necessário, mas não para execução
# A execução real acontecerá dentro do container

from .base import BaseTool, ToolParameter
from config import get_settings, get_logger
from agent.container_session_manager import ContainerSessionManager

logger = get_logger(__name__)
settings = get_settings()


class HotmartDownloaderTool(BaseTool):
    """
    Baixa vídeos (MP4) ou extrai áudios (MP3) de links do Hotmart usando yt-dlp.
    Executa dentro de um container isolado para garantir dependências.
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
        ),
        ToolParameter(
            name="session_id",
            type="string",
            description="ID da sessão atual (injetado automaticamente)",
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
        session_id: str = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Executa o download do conteúdo (vídeo ou áudio) usando yt-dlp dentro do container.
        """
        if not session_id:
            # Tentar fallback para obter session_id do kwargs se não vier direto
            session_id = kwargs.get('session_id')
            
        if not session_id:
             # Se ainda não tiver session_id (ex: execução direta sem contexto de sessão), 
             # criar uma sessão temporária ou falhar.
             # Para simplificar, vamos falhar solicitando o ID.
             # Mas o orchestrator deve injetar "session_id" se configurado.
             # Verificando se orchestrator injeta:
             # orchestrator.py: tool_args["session_id"] = conversation.id
             # Então sempre deve vir.
             return self._error("ID de sessão não fornecido (erro interno).")

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
                # Salvar arquivo no HOST (que é montado no container)
                with open(default_cookies_path, "w", encoding="utf-8") as f:
                    f.write(cookies_content)
                cookies_path = default_cookies_path
                logger.info(f"Cookies salvos a partir do texto em: {cookies_path}")
            except Exception as e:
                return self._error(f"Erro ao salvar cookies a partir do texto: {e}")
        
        # Se path fornecido, usa ele. Se não, tenta usar o default se existir
        if cookies_file:
            cookies_path = cookies_file # Assume path válido dentro do container (/app/data/...)
        elif not cookies_path and os.path.exists(default_cookies_path):
            cookies_path = default_cookies_path
            
        # Garantir paths relativos ao container se necessário
        # Assumindo que settings.data_dir é /app/data e mapeia corretamente
        
        # 3. Gerar Script Python para execução no Container
        script_code = self._generate_download_script(
            url=url,
            output_filename=output_filename,
            format=format,
            cookies_path=cookies_path,
            output_dir="/app/data/outputs" # Caminho interno fixo ou settings.outputs_dir
        )
        
        # 4. Executar no Container
        logger.info(f"Executando download ({format}) no container via hotmart_downloader...")
        
        success, output = await ContainerSessionManager.execute_python_in_container(
            session_id=session_id,
            code=script_code,
            timeout=600 # 10 min timeout para download
        )
        
        if success:
            return self._success(output)
        else:
            return self._error(f"Erro no download: {output}")

    def _generate_download_script(self, url: str, output_filename: str, format: str, cookies_path: str, output_dir: str) -> str:
        """Gera o código Python para rodar dentro do container"""
        
        # Escapar strings para python
        safe_url = url.replace('"', '\\"')
        safe_filename = output_filename.replace('"', '\\"')
        safe_cookies = f'"{cookies_path}"' if cookies_path else "None"
        
        return f"""
import os
import sys

# Garantir output dir
output_dir = "{output_dir}"
os.makedirs(output_dir, exist_ok=True)

try:
    from yt_dlp import YoutubeDL
except ImportError:
    print("Erro Crítico: yt-dlp não instalado no container.")
    sys.exit(1)

url = "{safe_url}"
filename_base = "{safe_filename}"
format_type = "{format}"
cookies_path = {safe_cookies}

# Limpar extensão do base name
filename_base = filename_base.replace(".mp4", "").replace(".mp3", "")

print(f"Iniciando download '{{format_type}}' para: {{filename_base}}")

ydl_opts = {{
    'outtmpl': os.path.join(output_dir, filename_base) + '.%(ext)s',
    'http_headers': {{
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://cf-embed.play.hotmart.com/',
    }},
    'quiet': True,
    'no_warnings': True,
    'nocheckcertificate': True,
}}

if cookies_path and os.path.exists(cookies_path):
    ydl_opts['cookiefile'] = cookies_path
elif cookies_path:
    print(f"Aviso: Arquivo de cookies não encontrado: {{cookies_path}}")

if format_type == 'audio':
    ydl_opts.update({{
        'format': 'bestaudio/best',
        'postprocessors': [{{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }}],
    }})
else:
    ydl_opts.update({{
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'recode-video': 'mp4',
    }})

try:
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    
    # Verificar resultado
    expected_ext = 'mp3' if format_type == 'audio' else 'mp4'
    expected_file = os.path.join(output_dir, f"{{filename_base}}.{{expected_ext}}")
    
    if os.path.exists(expected_file):
        print(f"✅ Download concluído com sucesso: {{expected_file}}")
    else:
        # Tentar encontrar qualquer arquivo que comece com o base
        files = [f for f in os.listdir(output_dir) if f.startswith(filename_base)]
        if files:
            print(f"✅ Download concluído (arquivo salvo): {{files[0]}}")
        else:
            print("❌ Erro: Arquivo final não encontrado após execução.")
            sys.exit(1)

except Exception as e:
    print(f"❌ Erro yt-dlp: {{str(e)}}")
    sys.exit(1)
"""

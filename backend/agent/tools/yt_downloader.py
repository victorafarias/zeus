"""
=====================================================
ZEUS - YouTube Downloader Tool (Custom JS Parser)
Baixa vídeos e áudios do YouTube usando parser customizado (pytubefix)
Execução isolada em container Docker
COM VERIFICAÇÃO AUTOMÁTICA DE ATUALIZAÇÕES
=====================================================
"""

from typing import Dict, Any
import os
import uuid
import asyncio
import re

from .base import BaseTool, ToolParameter
from config import get_settings, get_logger
from agent.container_session_manager import ContainerSessionManager

logger = get_logger(__name__)
settings = get_settings()


class YouTubeDownloaderTool(BaseTool):
    """
    Baixa vídeos (MP4) ou extrai áudios (MP3) de links do YouTube.
    Executa dentro de um container isolado usando pytubefix.
    Verifica e atualiza automaticamente as bibliotecas antes do download.
    """
    
    name = "yt_download"
    description = """Baixa vídeos ou áudios de links do YouTube usando parser direto.
Esta ferramenta simula um navegador para extrair streams diretamente do player do YouTube.
IMPORTANTE: Verifica automaticamente se há atualizações de yt-dlp/pytubefix antes de baixar.
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
        format: str = "video",
        quality: str = "best",
        output_filename: str = None,
        cookies_text: str = None,
        session_id: str = None,
        **kwargs
    ) -> Dict[str, Any]:
        
        # Obter session_id
        if not session_id:
            session_id = kwargs.get('session_id')
        if not session_id:
            return self._error("ID de sessão não fornecido (erro interno).")

        # 1. Validar URL do YouTube
        if not url:
            return self._error("URL não fornecida.")
        
        # 2. Normalizar parâmetros
        format = format.lower().strip() if format else "video"
        quality = quality.lower().strip() if quality else "best"
        
        # 3. Preparar Cookies Host -> Container
        # Se fornecidos, salvar no host.
        cookies_path = None
        if cookies_text:
             uploads_dir = os.path.join(settings.data_dir, "uploads")
             os.makedirs(uploads_dir, exist_ok=True)
             cookies_path = os.path.join(uploads_dir, f"yt_cookies_{uuid.uuid4().hex[:8]}.txt")
             try:
                 with open(cookies_path, "w", encoding="utf-8") as f:
                     f.write(cookies_text)
             except Exception as e:
                 logger.error(f"Erro ao salvar cookies: {e}")
                 # Continua sem cookies

        # 4. Gerar Script Python (COM verificação de atualizações integrada)
        script_code = self._generate_script(
            url=url,
            format=format,
            quality=quality,
            output_filename=output_filename,
            cookies_path=cookies_path,
            output_dir="/app/data/outputs"
        )
        
        # 5. Executar no Container
        logger.info(f"Executando pytubefix (com auto-update) via container para {url}")
        
        success, output = await ContainerSessionManager.execute_python_in_container(
            session_id=session_id,
            code=script_code,
            timeout=900  # 15 min (considerando tempo para update + download)
        )
        
        # Limpeza cookies
        if cookies_path and os.path.exists(cookies_path):
            try:
                os.remove(cookies_path)
            except:
                pass

        if success:
            return self._success(output)
        else:
            return self._error(f"Erro no download YouTube: {output}")

    def _generate_script(self, url, format, quality, output_filename, cookies_path, output_dir) -> str:
        """
        Gera o script Python que será executado dentro do container.
        Inclui lógica de verificação e atualização automática de bibliotecas.
        """
        safe_url = url.replace('"', '\\"')
        # CORREÇÃO: Quando output_filename tem valor, precisa de aspas ao redor
        # para ser tratado como string literal no script Python gerado
        safe_filename = f'"{output_filename.replace(chr(34), chr(92)+chr(34))}"' if output_filename else "None"
        safe_cookies = f'"{cookies_path}"' if cookies_path else "None"
        
        return f'''
import os
import sys
import json
import subprocess
from datetime import datetime, timedelta

# =====================================================
# FASE 1: VERIFICAÇÃO E ATUALIZAÇÃO DE BIBLIOTECAS
# =====================================================

CACHE_FILE = "/app/data/.yt_lib_cache.json"
CACHE_DURATION_HOURS = 1  # Verificar no máximo 1x por hora
PACKAGES_TO_CHECK = ["pytubefix", "yt-dlp"]

def get_installed_version(package_name):
    """Obtém a versão instalada de um pacote."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "show", package_name],
            capture_output=True,
            text=True,
            timeout=10
        )
        for line in result.stdout.split("\\n"):
            if line.startswith("Version:"):
                return line.split(":")[1].strip()
    except Exception:
        pass
    return None

def get_pypi_version(package_name):
    """Consulta PyPI para obter a versão mais recente."""
    try:
        import urllib.request
        url = f"https://pypi.org/pypi/{{package_name}}/json"
        req = urllib.request.Request(url, headers={{"User-Agent": "Zeus/1.0"}})
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            return data["info"]["version"]
    except Exception as e:
        print(f"⚠️ Aviso: Não foi possível consultar PyPI para {{package_name}}: {{e}}")
        return None

def load_cache():
    """Carrega cache de verificação anterior."""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return None

def save_cache(versions):
    """Salva cache com versões atuais."""
    try:
        cache_data = {{
            "last_check": datetime.now().isoformat(),
            "versions": versions
        }}
        with open(CACHE_FILE, "w") as f:
            json.dump(cache_data, f)
    except Exception as e:
        print(f"⚠️ Aviso: Não foi possível salvar cache: {{e}}")

def should_check_updates():
    """Verifica se devemos checar atualizações (cache expirado?)."""
    cache = load_cache()
    if not cache:
        return True
    
    try:
        last_check = datetime.fromisoformat(cache["last_check"])
        if datetime.now() - last_check > timedelta(hours=CACHE_DURATION_HOURS):
            return True
    except Exception:
        return True
    
    return False

def check_and_update_packages():
    """Verifica e atualiza pacotes se necessário."""
    print("🔍 Verificando atualizações de bibliotecas...")
    
    if not should_check_updates():
        cache = load_cache()
        print(f"✅ Cache válido (última verificação: {{cache.get('last_check', 'desconhecido')[:16]}})")
        return
    
    print("📡 Consultando PyPI para versões mais recentes...")
    
    current_versions = {{}}
    updates_needed = []
    
    for package in PACKAGES_TO_CHECK:
        installed = get_installed_version(package)
        latest = get_pypi_version(package)
        
        current_versions[package] = installed or "não instalado"
        
        if latest:
            if installed != latest:
                print(f"  📦 {{package}}: {{installed or 'não instalado'}} → {{latest}} (ATUALIZANDO)")
                updates_needed.append(package)
            else:
                print(f"  ✅ {{package}}: {{installed}} (atualizado)")
        else:
            print(f"  ⚠️ {{package}}: {{installed or 'não instalado'}} (PyPI indisponível)")
    
    # Executar atualizações se necessário
    if updates_needed:
        print(f"\\n🔄 Atualizando {{len(updates_needed)}} pacote(s)...")
        for package in updates_needed:
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "--upgrade", package, "-q"],
                    capture_output=True,
                    text=True,
                    timeout=120
                )
                if result.returncode == 0:
                    new_version = get_installed_version(package)
                    current_versions[package] = new_version
                    print(f"  ✅ {{package}} atualizado para {{new_version}}")
                else:
                    print(f"  ❌ Erro ao atualizar {{package}}: {{result.stderr}}")
            except Exception as e:
                print(f"  ❌ Erro ao atualizar {{package}}: {{e}}")
    
    # Salvar cache
    save_cache(current_versions)
    print("")

# Executar verificação de atualizações
check_and_update_packages()

# =====================================================
# FASE 2: DOWNLOAD DO VÍDEO/ÁUDIO
# =====================================================

output_dir = "{output_dir}"
os.makedirs(output_dir, exist_ok=True)

try:
    from pytubefix import YouTube
    from pytubefix.cli import on_progress
except ImportError:
    print("❌ Erro Crítico: pytubefix não instalado no container.")
    sys.exit(1)

url = "{safe_url}"
fmt = "{format}"
qual = "{quality}"
filename_arg = {safe_filename}
cookies_path = {safe_cookies}

def clean_filename(name):
    """Sanitiza nome de arquivo removendo caracteres inválidos."""
    import re
    return re.sub(r'[<>:"/\\\\|?*]', '', name).strip()

try:
    print(f"🎬 Iniciando pytubefix para {{url}}")
    
    # Configurar YouTube object
    yt = YouTube(url)
    
    # Título (força fetch)
    title = yt.title
    print(f"📺 Vídeo encontrado: {{title}}")
    
    safe_title = filename_arg if filename_arg else clean_filename(title)
    
    if fmt == 'audio':
        print("🎵 Selecionando stream de áudio...")
        stream = yt.streams.get_audio_only()
        if not stream:
            print("❌ Erro: Nenhum stream de áudio encontrado.")
            sys.exit(1)
            
        temp_name = f"{{safe_title}}_temp"
        print(f"⬇️ Baixando áudio: {{stream.abr}} ({{stream.filesize_mb:.1f}} MB)")
        
        out_path = stream.download(output_path=output_dir, filename=temp_name)
        
        # Converter para mp3 com ffmpeg
        final_path = os.path.join(output_dir, f"{{safe_title}}.mp3")
        print(f"🔄 Convertendo para MP3: {{final_path}}")
        
        cmd = f'ffmpeg -y -i "{{out_path}}" -vn -acodec libmp3lame -q:a 2 "{{final_path}}"'
        ret = os.system(cmd)
        
        if ret != 0:
            print("⚠️ Aviso: Erro na conversão FFmpeg.")
        
        if os.path.exists(out_path):
            os.remove(out_path)
            
        if os.path.exists(final_path):
             print(f"✅ Download concluído: {{final_path}}")
        else:
             print("❌ Erro: Arquivo final não criado.")
             sys.exit(1)

    else:
        # Vídeo MP4
        print(f"🎥 Selecionando stream de vídeo ({{qual}})...")
        streams = yt.streams.filter(file_extension='mp4')
        
        # Tentar progressive
        prog_streams = streams.filter(progressive=True)
        selected = None
        
        if qual == 'best':
            selected = prog_streams.order_by('resolution').desc().first()
            if not selected:
                selected = streams.order_by('resolution').desc().first()
        else:
            target = qual if qual.endswith('p') else f"{{qual}}p"
            selected = prog_streams.filter(res=target).first()
            if not selected:
                selected = prog_streams.order_by('resolution').desc().first()
                
        if not selected:
            # Fallback
            selected = yt.streams.first()
            
        if not selected:
            print("❌ Erro: Nenhum stream de vídeo encontrado.")
            sys.exit(1)
            
        print(f"📊 Stream selecionado: {{selected.resolution}}")
        final_path = os.path.join(output_dir, f"{{safe_title}}.mp4")
        
        selected.download(output_path=output_dir, filename=f"{{safe_title}}.mp4")
        
        if os.path.exists(final_path):
            print(f"✅ Download concluído: {{final_path}}")
        else:
            print("❌ Erro: Arquivo não encontrado após download.")
            sys.exit(1)

except Exception as e:
    print(f"❌ Erro pytubefix: {{str(e)}}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
'''

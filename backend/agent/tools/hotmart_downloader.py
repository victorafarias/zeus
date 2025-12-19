"""
=====================================================
ZEUS - Hotmart Downloader Tool
Baixa vídeos de links Hotmart usando FFmpeg
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
    """Baixa vídeos de links do Hotmart usando FFmpeg headers específicos"""
    
    name = "hotmart_downloader"
    description = """Baixa vídeos de links do Hotmart ('contentplayer.hotmart.com' ou 'vod-akm.play.hotmart.com').
Recebe a URL do vídeo (m3u8 ou link direto) e baixa o arquivo mp4 processado.
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
            description="Nome do arquivo de saída (opcional). Se não fornecido, gera um nome aleatório.",
            required=False
        )
    ]
    
    async def execute(
        self,
        url: str,
        output_filename: str = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Executa o download do vídeo"""
        
        # 1. Validar URL (básico)
        if not url:
            return self._error("URL não fornecida.")
            
        # 2. Verificar FFmpeg
        if not shutil.which("ffmpeg"):
            return self._error("FFmpeg não encontrado no sistema. Por favor, instale o FFmpeg.")
            
        # 3. Definir caminho de saída
        # Salvar em /outputs por padrão
        output_dir = settings.outputs_dir
        if not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir, exist_ok=True)
            except Exception as e:
                return self._error(f"Não foi possível criar diretório de saída: {str(e)}")
                
        if not output_filename:
            # Gerar nome único
            output_filename = f"hotmart_video_{uuid.uuid4().hex[:8]}.mp4"
            
        if not output_filename.endswith(".mp4"):
            output_filename += ".mp4"
            
        full_output_path = os.path.join(output_dir, output_filename)
        
        if os.path.exists(full_output_path):
             # Se já existe, tenta gerar outro nome para não sobrescrever acidentalmente
             base, ext = os.path.splitext(output_filename)
             output_filename = f"{base}_{uuid.uuid4().hex[:4]}{ext}"
             full_output_path = os.path.join(output_dir, output_filename)

        logger.info("Iniciando download Hotmart", url=url, output=full_output_path)
        
        # 4. Executar download em thread separada
        try:
            result = await asyncio.to_thread(
                self._download_synchronously,
                url,
                full_output_path
            )
            return self._success(result)
            
        except Exception as e:
            logger.error("Erro no download Hotmart", error=str(e))
            return self._error(f"Falha ao baixar vídeo: {str(e)}")


    def _download_synchronously(self, url: str, output_path: str) -> str:
        """Executa o comando FFmpeg (bloqueante)"""
        
        # Headers necessários para Hotmart
        headers = "Referer: https://cf-embed.play.hotmart.com/\r\nUser-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36\r\n"
        
        command = [
            'ffmpeg',
            '-headers', headers,
            '-i', url,
            '-c', 'copy',
            '-bsf:a', 'aac_adtstoasc',
            '-y', # Sobrescrever se existir (já tratamos nome antes, mas por segurança do ffmpeg)
            output_path
        ]
        
        # Executar
        # Capture_output=True para não sujar o log principal, mas se falhar pegamos o stderr
        try:
            process = subprocess.run(
                command,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            return f"Download concluído com sucesso! Vídeo salvo em: {output_path}"
            
        except subprocess.CalledProcessError as e:
            error_msg = e.stderr if e.stderr else str(e)
            raise Exception(f"Erro do FFmpeg: {error_msg}")


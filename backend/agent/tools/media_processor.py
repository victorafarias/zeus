"""
=====================================================
ZEUS - Media Processor Tool
Transcrição de áudio e vídeo usando Faster Whisper
=====================================================
"""

from typing import Dict, Any, List
import os
import uuid
import re
import asyncio
import pathlib
from faster_whisper import WhisperModel

from .base import BaseTool, ToolParameter
from config import get_settings, get_logger

logger = get_logger(__name__)
settings = get_settings()


class TranscribeMediaTool(BaseTool):
    """Transcreve áudio ou vídeo para texto usando Faster Whisper"""
    
    name = "transcribe_media"
    description = """Transcreve áudio ou vídeo para texto usando Whisper (modelo local).
Suporta arquivos grandes e divide o resultado em partes.
Formatos: mp3, wav, m4a, mp4, webm, ogg, flac, aac, avi, mkv, mov.
O arquivo deve estar na pasta /uploads ou /outputs."""
    
    parameters = [
        ToolParameter(
            name="file_path",
            type="string",
            description="Caminho do arquivo (ex: 'video.mp4' ou '/app/data/uploads/video.mp4')"
        ),
        ToolParameter(
            name="language",
            type="string",
            description="Idioma (ex: 'pt', 'en'). Padrão: detecção automática.",
            required=False
        ),
        ToolParameter(
            name="model_size",
            type="string",
            description="Tamanho do modelo: 'tiny', 'base', 'small', 'medium', 'large-v2'. Padrão: 'base' (rápido).",
            required=False
        )
    ]
    
    async def execute(
        self,
        file_path: str,
        language: str = None,
        model_size: str = "base",
        **kwargs
    ) -> Dict[str, Any]:
        """Transcreve arquivo de mídia"""
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
        
        # 1. Resolver caminho do arquivo
        target_path = file_path
        if not os.path.isabs(file_path):
            # Tenta em uploads primeiro
            uploads_path = os.path.join(settings.uploads_dir, file_path)
            if os.path.exists(uploads_path):
                target_path = uploads_path
            else:
                # Tenta em outputs
                outputs_path = os.path.join(settings.outputs_dir, file_path)
                if os.path.exists(outputs_path):
                    target_path = outputs_path
                else:
                    # Tenta no diretório base de dados
                    data_path = os.path.join(settings.data_dir, file_path)
                    if os.path.exists(data_path):
                        target_path = data_path

        if not os.path.exists(target_path):
            return self._error(f"Arquivo não encontrado: {file_path}")
        
        # 2. Verificar extensão
        ext = os.path.splitext(target_path)[1].lower()
        supported = [
            '.mp3', '.wav', '.flac', '.aac', '.m4a', '.ogg', '.wma',
            '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm'
        ]
        
        if ext not in supported:
            return self._error(
                f"Formato não suportado: {ext}. "
                f"Aceitos: {', '.join(supported)}"
            )

        # 3. Executar em thread separada para não bloquear
        report_progress(f"Iniciando transcrição de {os.path.basename(target_path)}...")
        logger.info("Iniciando transcrição", file=target_path, model=model_size)
        
        try:
            result = await asyncio.to_thread(
                self._transcribe_synchronously,
                target_path,
                language,
                model_size,
                report_progress
            )
            return self._success(result)
            
        except Exception as e:
            logger.error("Erro na transcrição", error=str(e))
            return self._error(f"Erro ao transcrever: {str(e)}")


    def _transcribe_synchronously(self, file_path: str, language: str, model_size: str, progress_callback=None) -> str:
        """Executa a lógica pesada de transcrição (bloqueante)"""
        try:
            # Configurações
            device = "cpu" # Default para servidor sem GPU garantida
            compute_type = "int8" # Mais compatível com CPU
            
            # Carregar modelo
            if progress_callback: progress_callback(f"Carregando modelo Whisper ({model_size})...")
            logger.info("Carregando modelo Whisper...", size=model_size)
            model = WhisperModel(model_size, device=device, compute_type=compute_type)
            
            # Transcrever
            if progress_callback: progress_callback("Processando áudio (pode demorar)...")
            logger.info("Processando áudio...")
            segments, info = model.transcribe(
                file_path, 
                beam_size=5, 
                language=language
            )
            
            # Coletar texto
            full_text = ""
            for segment in segments:
                full_text += segment.text + " "
                # Opcional: reportar progresso parcial se possível, mas segments é generator
                # Iterar consome tempo
            
            full_text = re.sub(r'\s+', ' ', full_text).strip()
            
            if not full_text:
                return "Nenhuma fala detectada no arquivo."

            # Salvar resultado em arquivo txt
            base_name = os.path.splitext(os.path.basename(file_path))[0]
            output_filename = f"{base_name}_transcricao.txt"
            output_path = os.path.join(settings.outputs_dir, output_filename)
            
            # Garantir diretório output
            os.makedirs(settings.outputs_dir, exist_ok=True)
            
            if progress_callback: progress_callback("Salvando arquivo...")
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(full_text)
                
            # Se for muito longo, salvar em partes (lógica do usuário)
            MAX_WORDS = 7500
            words = full_text.split()
            if len(words) > MAX_WORDS:
                self._split_transcription(words, base_name, settings.outputs_dir, MAX_WORDS)
                return f"Transcrição longa concluída. Arquivo salvo em: /outputs/{output_filename} (e partes divididas)"

            return f"Transcrição concluída. Arquivo salvo em: /outputs/{output_filename}\n\n**Trecho inicial:**\n{full_text[:500]}..."

        except Exception as e:
            raise e

    def _split_transcription(self, words: List[str], base_name: str, output_dir: str, max_words: int):
        """Divide transcrição em partes"""
        part_num = 1
        current_words = []
        
        for word in words:
            current_words.append(word)
            if len(current_words) >= max_words:
                out_name = f"{base_name}-parte-{part_num}.txt"
                with open(os.path.join(output_dir, out_name), 'w', encoding='utf-8') as f:
                    f.write(" ".join(current_words))
                current_words = []
                part_num += 1
                
        if current_words:
            out_name = f"{base_name}-parte-{part_num}.txt"
            with open(os.path.join(output_dir, out_name), 'w', encoding='utf-8') as f:
                f.write(" ".join(current_words))

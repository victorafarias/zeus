"""
=====================================================
ZEUS - Media Processor Tool
Transcrição de áudio e vídeo usando Faster Whisper
=====================================================
"""

from typing import Dict, Any, List, Optional
import os
import pathlib
from faster_whisper import WhisperModel
try:
    import torch
except ImportError:
    torch = None

from .base import BaseTool, ToolParameter
from config import get_settings, get_logger

logger = get_logger(__name__)
settings = get_settings()


class TranscribeMediaTool(BaseTool):
    """Transcreve áudio ou vídeo para texto usando Faster Whisper"""
    
    name = "transcribe_media"
    description = """Transcreve áudio ou vídeo para texto usando Whisper (modelo local).
Suporta arquivos individuais ou processamento em lote (pasta inteira).
Formatos suportados: mp3, wav, flac, aac, m4a, ogg, wma, mp4, avi, mkv, mov, wmv, flv, webm.
O sistema detecta automaticamente se há GPU disponível para aceleração."""
    
    parameters = [
        ToolParameter(
            name="file_path",
            type="string",
            description="Caminho do arquivo ou pasta (ex: 'video.mp4', '/uploads', '/uploads/pasta_audios')"
        ),
        ToolParameter(
            name="language",
            type="string",
            description="Idioma (ex: 'pt', 'en'). Padrão: 'pt' (Português do Brasil).",
            required=False
        ),
        ToolParameter(
            name="model_size",
            type="string",
            description="Tamanho do modelo: 'base', 'small', 'medium', 'large-v2'. Padrão: 'medium'.",
            required=False
        )
    ]
    
    async def execute(
        self,
        file_path: str,
        language: str = "pt",
        model_size: str = "medium",
        **kwargs
    ) -> Dict[str, Any]:
        """Transcreve arquivo de mídia ou pasta de arquivos"""
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
        
        # 1. Resolver caminho
        target_path = pathlib.Path(file_path)
        if not target_path.is_absolute():
            # Tenta encontrar em diretórios padrão se for relativo
            possible_roots = [settings.uploads_dir, settings.outputs_dir, settings.data_dir]
            found = False
            for root in possible_roots:
                candidate = pathlib.Path(root) / file_path
                if candidate.exists():
                    target_path = candidate
                    found = True
                    break
            
            if not found:
                 return self._error(f"Arquivo ou diretório não encontrado: {file_path}")
        else:
             if not target_path.exists():
                return self._error(f"Arquivo ou diretório não encontrado: {file_path}")

        # 2. Identificar arquivos para processar
        files_to_process = []
        supported_extensions = {
            '.mp3', '.wav', '.flac', '.aac', '.m4a', '.ogg', '.wma', # Áudio
            '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm'  # Vídeo
        }

        if target_path.is_file():
            if target_path.suffix.lower() in supported_extensions:
                files_to_process.append(target_path)
            else:
                return self._error(f"Formato não suportado: {target_path.suffix}. Suportados: {', '.join(supported_extensions)}")
        elif target_path.is_dir():
            report_progress(f"Buscando arquivos de mídia em: {target_path.name}...")
            for item in target_path.iterdir():
                if item.is_file() and item.suffix.lower() in supported_extensions:
                    files_to_process.append(item)
            
            if not files_to_process:
                return self._error(f"Nenhum arquivo de mídia encontrado em: {target_path}")
        
        # 3. Detectar GPU (Lógica solicitada pelo usuário)
        try:
            has_gpu = False
            if torch and torch.cuda.is_available():
                has_gpu = True
                device_info = f"CUDA (GPU: {torch.cuda.get_device_name(0)})"
            else:
                device_info = "CPU"
        except Exception:
            has_gpu = False
            device_info = "CPU (erro detecção)"

        device = "cuda" if has_gpu else "cpu"
        compute_type = "float16" if has_gpu else "int8" # int8 é mais rápido/compatível pra CPU

        logger.info(f"Ambiente de execução: {device_info} | Device: {device} | Compute: {compute_type}")
        report_progress(f"Iniciando processamento de {len(files_to_process)} arquivo(s) usando {device_info}...")

        # 4. Executar processamento em batch na thread
        try:
            result_summary = await asyncio.to_thread(
                self._process_batch,
                files_to_process,
                language,
                model_size,
                device,
                compute_type,
                report_progress
            )
            return self._success(result_summary)
            
        except Exception as e:
            logger.error("Erro na transcrição", error=str(e))
            return self._error(f"Erro fatal no processo de transcrição: {str(e)}")

    def _process_batch(
        self, 
        files: List[pathlib.Path], 
        language: str, 
        model_size: str,
        device: str, 
        compute_type: str,
        progress_callback
    ) -> str:
        """Carrega o modelo UMA VEZ e processa todos os arquivos"""
        
        # Carregar Modelo
        try:
            if progress_callback: progress_callback(f"Carregando modelo Whisper '{model_size}' em {device}...")
            model = WhisperModel(model_size, device=device, compute_type=compute_type)
            if progress_callback: progress_callback("Modelo carregado com sucesso.")
        except Exception as e:
            # Fallback para CPU se falhar no CUDA (ex: driver incompatível mesmo com GPU presente)
            if device == "cuda":
                if progress_callback: progress_callback(f"Erro ao carregar em CUDA ({str(e)}). Tentando CPU...")
                logger.warning(f"Fallback para CPU devido a erro: {e}")
                model = WhisperModel(model_size, device="cpu", compute_type="int8")
            else:
                raise e

        # Diretório de saída padrão (mesmo do arquivo ou /outputs se read-only?)
        # O script original salva no mesmo diretório da entrada. Vamos tentar manter isso,
        # mas se falhar (permissão), fallback para settings.outputs_dir.
        
        results = []
        
        for i, file_path in enumerate(files):
            current_progress = f"[{i+1}/{len(files)}] {file_path.name}"
            if progress_callback: progress_callback(f"Transcrevendo: {current_progress}")
            logger.info(f"Transcrevendo arquivo: {file_path}")

            try:
                # Tenta salvar no mesmo diretório
                output_dir = file_path.parent
                if not os.access(output_dir, os.W_OK):
                    output_dir = pathlib.Path(settings.outputs_dir)
                
                self._transcribe_single_file(model, file_path, output_dir, language)
                results.append(f"✅ {file_path.name}")
                
            except Exception as e:
                logger.error(f"Erro ao transcrever {file_path.name}: {e}")
                results.append(f"❌ {file_path.name} (Erro: {str(e)})")

        return f"Processamento concluído.\n\nResultado:\n" + "\n".join(results)

    def _transcribe_single_file(self, model: WhisperModel, file_path: pathlib.Path, output_dir: pathlib.Path, language: str):
        """Lógica de transcrição e divisão idêntica ao script do usuário"""
        
        # Transcrever
        segments, info = model.transcribe(str(file_path), beam_size=5, language=language)
        
        full_transcription_text = ""
        for segment in segments:
            full_transcription_text += segment.text + " "

        # Limpeza
        full_transcription_text = re.sub(r'\s+', ' ', full_transcription_text).strip()
        
        words = full_transcription_text.split()
        num_words = len(words)
        
        if num_words == 0:
            logger.warning(f"Arquivo vazio: {file_path.name}")
            return

        # Divisão em partes
        MAX_WORDS_PER_PART = 7500
        current_part_words = []
        part_number = 1
        
        base_name = file_path.stem
        
        for word in words:
            current_part_words.append(word)
            
            if len(current_part_words) >= MAX_WORDS_PER_PART:
                output_filename = f"{base_name}-parte-{part_number}.txt"
                output_filepath = output_dir / output_filename
                
                with open(output_filepath, 'w', encoding='utf-8') as f:
                    f.write(" ".join(current_part_words))
                
                logger.info(f"Salvo: {output_filename}")
                current_part_words = []
                part_number += 1
        
        if current_part_words:
            output_filename = f"{base_name}-parte-{part_number}.txt"
            output_filepath = output_dir / output_filename
            
            with open(output_filepath, 'w', encoding='utf-8') as f:
                f.write(" ".join(current_part_words))
            logger.info(f"Salvo: {output_filename}")

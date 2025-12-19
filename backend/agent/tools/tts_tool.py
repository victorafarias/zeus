"""
=====================================================
ZEUS - Text To Speech Tool
Geração de áudio a partir de texto usando Coqui TTS
=====================================================
"""

import os
import asyncio
import uuid
import torch
from typing import Dict, Any, Optional
from TTS.api import TTS

from .base import BaseTool, ToolParameter
from config import get_settings, get_logger

logger = get_logger(__name__)
settings = get_settings()

class TextToSpeechTool(BaseTool):
    """Gera áudio a partir de texto usando Coqui TTS"""
    
    name = "text_to_speech"
    description = """Gera um arquivo de áudio (wav) a partir de um texto fornecido.
    Use esta ferramenta quando o usuário pedir para 'falar', 'narrar' ou 'gerar áudio'.
    Suporta múltiplos idiomas (padrão: pt)."""
    
    parameters = [
        ToolParameter(
            name="text",
            type="string",
            description="O texto a ser convertido em fala."
        ),
        ToolParameter(
            name="language",
            type="string",
            description="Código do idioma (ex: 'pt', 'en'). Padrão: 'pt'.",
            required=False
        ),
        ToolParameter(
            name="speaker",
            type="string",
            description="Nome do speaker (se o modelo suportar multi-speaker).",
            required=False
        )
    ]
    
    def __init__(self):
        super().__init__()
        # Cache do modelo para evitar recarregar a cada chamada
        self._tts_model = None
        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        
    def _get_model(self):
        """Carrega o modelo TTS sob demanda"""
        if self._tts_model is None:
            logger.info("Carregando modelo TTS...", device=self._device)
            # Usando um modelo multilingue decente por padrão
            # 'tts_models/multilingual/multi-dataset/xtts_v2' é ótimo mas pesado
            # Vamos começar com algo mais leve ou o padrão do usuário se ele não especificou
            # Para simplicidade e qualidade, vamos tentar o xtts_v2 se tiver recurso, ou um mais simples.
            # Vou usar um modelo genérico bom para PT.
            
            try:
                # Inicializa com o modelo padrão. O Coqui TTS gerencia o download.
                # xtts_v2 é o estado da arte atual do Coqui para multilingue.
                self._tts_model = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(self._device)
            except Exception as e:
                logger.error("Erro ao carregar modelo TTS default, tentando fallback", error=str(e))
                # Fallback para um modelo mais simples se o xtts falhar
                self._tts_model = TTS(model_name="tts_models/en/ljspeech/glow-tts").to(self._device) # Exemplo
                
        return self._tts_model

    async def execute(
        self,
        text: str,
        language: str = "pt",
        speaker: str = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Executa a geração de áudio"""
        
        websocket = kwargs.get('websocket')
        loop = asyncio.get_running_loop()

        def report_progress(msg: str):
            if websocket:
                asyncio.run_coroutine_threadsafe(
                    websocket.send_json({
                        "type": "status",
                        "status": "processing",
                        "content": msg
                    }),
                    loop
                )

        try:
            report_progress("Iniciando geração de áudio...")
            
            # Definir caminho de saída
            filename = f"tts_{uuid.uuid4().hex[:8]}.wav"
            # Caminho corrigido para data/outputs conforme solicitado
            output_dir = os.path.join(settings.data_dir, "outputs")
            os.makedirs(output_dir, exist_ok=True)
            output_path = os.path.join(output_dir, filename)
            
            logger.info("Gerando áudio", text_len=len(text), lang=language, out=output_path)
            
            # Executar em thread separada (CPU bound)
            await asyncio.to_thread(
                self._generate_audio_sync,
                text,
                language,
                output_path,
                speaker,
                report_progress
            )
            
            return self._success(
                f"Áudio gerado com sucesso!\nArquivo salvo em: {output_path}\n"
                f"(Você pode reproduzir este arquivo se tiver acesso ao sistema de arquivos)"
            )
            
        except Exception as e:
            logger.error("Erro na geração de TTS", error=str(e))
            return self._error(f"Erro ao gerar áudio: {str(e)}")

    def _generate_audio_sync(self, text: str, language: str, output_path: str, speaker: str, progress_callback):
        """Geração síncrona de áudio"""
        tts = self._get_model()
        
        # Parâmetros para XTTS v2 (precisa de speaker wav para clonar ou nome de speaker pré-definido)
        # Se não tiver speaker, vamos pegar o primeiro disponível ou um padrão
        
        # Verifica se o modelo suporta speaker
        if tts.is_multi_speaker:
            if not speaker:
                # Pega um speaker aleatório ou o primeiro se nenhum for fornecido
                # Para XTTS, geralmente precisa de um arquivo de som de referência ou nome.
                # Vamos tentar usar um speaker padrão se disponível na lista
                if tts.speakers:
                    speaker = tts.speakers[0]
                    if progress_callback: progress_callback(f"Usando voz: {speaker}")
            
            if speaker:
                tts.tts_to_file(
                    text=text,
                    file_path=output_path,
                    speaker=speaker,
                    language=language
                )
            else:
                 # Fallback para modelos que não precisam de speaker explícito ou tem default
                tts.tts_to_file(text=text, file_path=output_path, language=language)
        else:
            # Modelo single speaker
            tts.tts_to_file(text=text, file_path=output_path)
            

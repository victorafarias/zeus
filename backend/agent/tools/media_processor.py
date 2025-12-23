"""
=====================================================
ZEUS - Media Processor Tool
Transcrição de áudio e vídeo usando Faster Whisper
Execução isolada em container Docker
=====================================================
"""

from typing import Dict, Any, List, Optional
import os
import pathlib
import asyncio
import uuid
import re

from .base import BaseTool, ToolParameter
from config import get_settings, get_logger
from agent.container_session_manager import ContainerSessionManager

logger = get_logger(__name__)
settings = get_settings()


class TranscribeMediaTool(BaseTool):
    """Transcreve áudio ou vídeo para texto usando Faster Whisper no container isolado"""
    
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
        file_path: str,
        language: str = "pt",
        model_size: str = "medium",
        session_id: str = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Transcreve arquivo de mídia ou pasta de arquivos no container"""
        websocket = kwargs.get('websocket')
        loop = asyncio.get_running_loop()

        if not session_id:
             session_id = kwargs.get('session_id')
        if not session_id:
             return self._error("ID de sessão não fornecido.")

        # 1. Resolver caminho (Assume paths mapeados /app/data)
        # Se o comando vem do usuário como "uploads/file.mp3", precisamos garantir path absoluto ou relativo correto
        # Para container, preferimos absoluto "/app/data/..."
        
        target_path_str = file_path
        if not file_path.startswith("/"):
            # Assume relativo a /app/data se não começar com /
            # Mas uploads geralmente é /app/data/uploads
            # Se user digitar "uploads/X", vira /app/data/uploads/X
             target_path_str = f"/app/data/{file_path}" if not file_path.startswith("app/data") else f"/{file_path}"
        
        # 2. Gerar Script Python
        script_code = self._generate_script(
            target_path=target_path_str,
            language=language or "pt",
            model_size=model_size or "medium"
        )
        
        # 3. Executar no Container com Streaming
        logger.info(f"Iniciando transcrição ({model_size}) no container...")
        
        container = ContainerSessionManager.get_or_create_container(session_id)
        if not container:
            return self._error("Falha ao obter container de sessão.")
            
        return await self._run_script_in_container(container, script_code, websocket, loop)

    async def _run_script_in_container(self, container, script_code, websocket, loop):
        """Executa script e faz streaming do output"""
        import threading
        
        # Preparar script
        encoded_code = script_code.encode('utf-8').hex()
        script_name = f"transcribe_{uuid.uuid4().hex[:8]}.py"
        setup_cmd = f"/bin/bash -c 'if ! command -v xxd &> /dev/null; then apt-get update && apt-get install -y xxd; fi; echo {encoded_code} | xxd -r -p > /app/data/{script_name}'"
        
        exit_code, out = container.exec_run(setup_cmd)
        if exit_code != 0:
            return self._error(f"Erro ao preparar script: {out.decode('utf-8')}")

        output_buffer = []
        
        def stream_generator():
            return container.exec_run(f"python3 /app/data/{script_name}", stream=True, demux=True)

        q = asyncio.Queue()
        
        def producer():
            try:
                gen = stream_generator()
                for stdout, stderr in gen:
                    chunk = ""
                    if stdout: chunk = stdout.decode('utf-8', errors='replace')
                    if stderr: chunk += stderr.decode('utf-8', errors='replace') # Merge stderr to log
                    if chunk:
                        asyncio.run_coroutine_threadsafe(q.put(chunk), loop)
            except Exception:
                pass
            finally:
                asyncio.run_coroutine_threadsafe(q.put(None), loop)

        t = threading.Thread(target=producer, daemon=True)
        t.start()
        
        # Consumir
        while True:
            item = await q.get()
            if item is None:
                break
            
            # Enviar para websocket se parecer progresso
            output_buffer.append(item)
            
            if websocket:
                # Filtrar mensagens de progresso para UX
                # [PROGRESS] txt
                if "[INFO]" in item or "Transcrevendo" in item or "%" in item:
                     try:
                        await websocket.send_json({
                            "type": "status",
                            "status": "processing",
                            "content": item.strip()
                        })
                     except: pass
        
        # Limpar
        container.exec_run(f"rm /app/data/{script_name}")
        
        full_output = "".join(output_buffer)
        if "Processamento concluído" in full_output:
            # Extrair resumo se possível
            return self._success(full_output)
        else:
             return self._error(f"Erro ou execução incompleta:\n{full_output}")

    def _generate_script(self, target_path: str, language: str, model_size: str) -> str:
        safe_path = target_path.replace('"', '\\"')
        
        return f"""
import os
import sys
import re
import pathlib
try:
    from faster_whisper import WhisperModel
    import torch
except ImportError as e:
    print(f"Erro ao importar dependências: {{e}}")
    print("Verifique se faster-whisper e torch estão instalados no container.")
    sys.exit(1)

target_path = pathlib.Path("{safe_path}")
language = "{language}"
model_size = "{model_size}"

def log(msg):
    print(f"[INFO] {{msg}}", flush=True)

if not target_path.exists():
    print(f"Erro: Arquivo não encontrado: {{target_path}}")
    sys.exit(1)

# Identificar arquivos
files = []
exts = {{'.mp3', '.wav', '.flac', '.aac', '.m4a', '.ogg', '.wma', '.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm'}}

if target_path.is_file():
    if target_path.suffix.lower() in exts:
        files.append(target_path)
elif target_path.is_dir():
    for item in target_path.iterdir():
        if item.is_file() and item.suffix.lower() in exts:
            files.append(item)

if not files:
    print("Nenhum arquivo encontrado.")
    sys.exit(1)

# Configurar Device
device = "cpu"
compute_type = "int8"
if torch.cuda.is_available():
    device = "cuda"
    compute_type = "float16"
    log(f"Usando GPU: {{torch.cuda.get_device_name(0)}}")
else:
    log("Usando CPU")

# Carregar Modelo
log(f"Carregando modelo {{model_size}}...")
try:
    model = WhisperModel(model_size, device=device, compute_type=compute_type)
except Exception as e:
    log(f"Erro com GPU/float16, tentando fallback CPU/int8... ({{e}})")
    model = WhisperModel(model_size, device="cpu", compute_type="int8")

log("Modelo carregado.")

results = []

for i, file_path in enumerate(files):
    log(f"Transcrevendo [{{i+1}}/{{len(files)}}]: {{file_path.name}}")
    
    try:
        segments, info = model.transcribe(str(file_path), beam_size=5, language=language)
        
        full_text = ""
        for segment in segments:
            full_text += segment.text + " "
            # Opcional: print progress
        
        full_text = re.sub(r'\s+', ' ', full_text).strip()
        
        # Salvar
        output_dir = file_path.parent
        base_name = file_path.stem
        
        # Dividir se grande
        words = full_text.split()
        MAX = 7500
        part = 1
        current = []
        
        saved_files = []
        
        if not words:
            log(f"Audio vazio: {{file_path.name}}")
            continue
            
        for w in words:
            current.append(w)
            if len(current) >= MAX:
                fname = f"{{base_name}}-parte-{{part}}.txt"
                with open(output_dir / fname, 'w', encoding='utf-8') as f:
                    f.write(" ".join(current))
                saved_files.append(fname)
                current = []
                part += 1
        
        if current:
            fname = f"{{base_name}}-parte-{{part}}.txt" if part > 1 else f"{{base_name}}.txt"
            with open(output_dir / fname, 'w', encoding='utf-8') as f:
                f.write(" ".join(current))
            saved_files.append(fname)
            
        log(f"Concluído: {{file_path.name}} -> {{', '.join(saved_files)}}")
        results.append(f"✅ {{file_path.name}}")
        
    except Exception as e:
        log(f"Erro em {{file_path.name}}: {{e}}")
        results.append(f"❌ {{file_path.name}}")

print("Processamento concluído.")
print("Resumo:")
print("\\n".join(results))
"""

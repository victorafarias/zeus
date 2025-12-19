# =====================================================
# ZEUS - Dockerfile Processador de Mídia
# Container com FFmpeg e Whisper para transcrições
# =====================================================

FROM python:3.11-slim

# Metadados
LABEL maintainer="Zeus AI Agent"
LABEL description="Container sandbox para processamento de mídia"

# Evitar prompts interativos
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Instalar FFmpeg e dependências de áudio
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

# Instalar Whisper e dependências
RUN pip install --no-cache-dir \
    openai-whisper \
    torch --index-url https://download.pytorch.org/whl/cpu \
    torchaudio --index-url https://download.pytorch.org/whl/cpu \
    && pip cache purge

# Criar usuário não-root
RUN groupadd -r media && useradd -r -g media media

# Diretórios de trabalho
WORKDIR /app
RUN mkdir -p /media /output && chown -R media:media /media /output

# Mudar para usuário não-root
USER media

# Comando padrão
CMD ["python", "-c", "import whisper; print('Whisper disponível')"]

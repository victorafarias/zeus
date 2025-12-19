# =====================================================
# ZEUS BACKEND - Dockerfile
# Imagem Python 3.11 com dependências para o agente
# =====================================================

FROM python:3.11-slim

# Definir diretório de trabalho
WORKDIR /app

# Instalar dependências do sistema
# - docker.io: Para comunicação com Docker socket
# - ffmpeg: Para processamento de mídia
# - git: Para alguns pacotes Python
RUN apt-get update && apt-get install -y \
    docker.io \
    ffmpeg \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copiar arquivo de dependências primeiro (para cache de camadas)
COPY requirements.txt .

# Instalar dependências Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código fonte
COPY . .

# Criar diretórios necessários
RUN mkdir -p /app/data/uploads \
    /app/data/outputs \
    /app/data/conversations \
    /app/data/chromadb

# Expor porta da API
EXPOSE 8000

# Comando de inicialização
# Em produção, sem --reload para melhor performance
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

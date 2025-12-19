# =====================================================
# ZEUS BACKEND - Dockerfile
# Imagem Python 3.11 com dependências para o agente
# =====================================================

FROM python:3.11-slim

# Definir diretório de trabalho
WORKDIR /app

# Instalar dependências do sistema
RUN apt-get update && apt-get install -y \
    docker.io \
    ffmpeg \
    git \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Copiar arquivo de dependências primeiro (para cache de camadas)
COPY requirements.txt .

# Instalar dependências Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código fonte do backend
COPY . .

# Copiar frontend (será montado ou copiado pelo docker-compose)
# O frontend fica em /app/frontend

# Criar diretórios necessários
RUN mkdir -p /app/data/uploads \
    /app/data/outputs \
    /app/data/conversations \
    /app/data/chromadb \
    /app/frontend

# Expor porta da API
EXPOSE 8000

# Comando de inicialização
# Em produção, sem --reload para melhor performance
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "3600"]

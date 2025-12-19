# =====================================================
# ZEUS - Dockerfile Executor Python
# Container otimizado para execução segura de código
# =====================================================

FROM python:3.11-slim

# Metadados
LABEL maintainer="Zeus AI Agent"
LABEL description="Container sandbox para execução de código Python"

# Evitar prompts interativos
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Criar usuário não-root para segurança
RUN groupadd -r sandbox && useradd -r -g sandbox sandbox

# Instalar bibliotecas científicas e utilitárias comuns
RUN pip install --no-cache-dir \
    numpy \
    pandas \
    scipy \
    matplotlib \
    pillow \
    requests \
    beautifulsoup4 \
    lxml \
    openpyxl \
    python-dateutil \
    pytz \
    pyyaml \
    && pip cache purge

# Diretório de trabalho
WORKDIR /code

# Mudar para usuário não-root
USER sandbox

# Comando padrão
CMD ["python", "-c", "print('Sandbox Python pronto')"]

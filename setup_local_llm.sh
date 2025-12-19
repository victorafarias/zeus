#!/bin/bash
# =====================================================
# ZEUS - Script de Instalação do LLM Local (Ollama)
# Execute na VPS: bash setup_local_llm.sh
# =====================================================

set -e

echo "========================================"
echo "ZEUS - Instalação do Ollama + Llama 3.1"
echo "========================================"

# Verificar se está rodando como root
if [ "$EUID" -ne 0 ]; then
    echo "⚠️  Por favor, execute como root: sudo bash setup_local_llm.sh"
    exit 1
fi

# 1. Instalar Ollama
echo ""
echo "📦 Instalando Ollama..."
if command -v ollama &> /dev/null; then
    echo "✅ Ollama já está instalado"
else
    curl -fsSL https://ollama.com/install.sh | sh
    echo "✅ Ollama instalado com sucesso"
fi

# 2. Iniciar serviço Ollama
echo ""
echo "🚀 Iniciando serviço Ollama..."
systemctl enable ollama 2>/dev/null || true
systemctl start ollama 2>/dev/null || ollama serve &

# Aguardar inicialização
sleep 5

# 3. Baixar modelo Llama 3.1 8B
echo ""
echo "📥 Baixando modelo Llama 3.1 8B (pode demorar alguns minutos)..."
ollama pull llama3.1:8b

# 4. Verificar instalação
echo ""
echo "🔍 Verificando instalação..."
if ollama list | grep -q "llama3.1:8b"; then
    echo "✅ Modelo llama3.1:8b instalado com sucesso!"
else
    echo "❌ Erro: modelo não encontrado"
    exit 1
fi

# 5. Testar modelo
echo ""
echo "🧪 Testando modelo..."
RESPONSE=$(curl -s http://localhost:11434/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{
        "model": "llama3.1:8b",
        "messages": [{"role": "user", "content": "Responda apenas: OK"}],
        "max_tokens": 10
    }')

if echo "$RESPONSE" | grep -q "OK"; then
    echo "✅ Modelo respondendo corretamente!"
else
    echo "⚠️  Modelo instalado, mas teste pode ter falhado. Verifique manualmente."
fi

echo ""
echo "========================================"
echo "✅ INSTALAÇÃO CONCLUÍDA!"
echo "========================================"
echo ""
echo "O Ollama está rodando em: http://localhost:11434"
echo "API compatível com OpenAI: http://localhost:11434/v1"
echo ""
echo "Para testar manualmente:"
echo "  ollama run llama3.1:8b"
echo ""

#!/bin/bash
# =====================================================
# ZEUS - Build das imagens sandbox
# Execute este script para buildar as imagens localmente
# =====================================================

set -e

echo "=== Buildando imagens sandbox do Zeus ==="

# Diretório do script
SCRIPT_DIR=$(dirname "$0")

echo ""
echo ">>> Buildando zeus-sandbox-python..."
docker build -t zeus-sandbox-python:latest "$SCRIPT_DIR/python"

echo ""
echo ">>> Buildando zeus-sandbox-media..."
docker build -t zeus-sandbox-media:latest "$SCRIPT_DIR/media"

echo ""
echo "=== Build concluído! ==="
echo ""
echo "Imagens criadas:"
docker images | grep zeus-sandbox

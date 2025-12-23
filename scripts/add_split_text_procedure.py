"""
Script para adicionar procedimento RAG da tool split_text_files.

Execute após o deploy do Zeus para registrar o procedimento na base de conhecimento.

Como usar:
1. Acesse o Zeus via chat
2. Envie o seguinte comando:

---
Adicione o seguinte procedimento ao RAG usando a tool manage_rag:

Descrição: Dividir arquivos TXT grandes em partes menores, preservando a integridade das frases. Útil para transcrições longas, documentos extensos, ou qualquer texto que precise ser dividido em arquivos menores.

Solução: Use a tool split_text_files com os parâmetros:
- input_path: caminho do arquivo TXT ou diretório (ex: "outputs" ou "outputs/arquivo.txt")
- max_chars: limite de caracteres por parte (padrão: 7500)
- output_dir: diretório de saída (opcional, padrão é o mesmo do original)

Exemplo: Para dividir todos os arquivos TXT na pasta outputs em partes de 7500 caracteres:
split_text_files(input_path="outputs", max_chars=7500)

Os arquivos serão nomeados como: nome_original-1.txt, nome_original-2.txt, etc.
Arquivos já divididos (com sufixo -N.txt) são ignorados automaticamente.

Ferramenta: split_text_files
Tags: arquivo, texto, divisão, split, txt, transcrição
---
"""

# Procedimento em formato estruturado para referência:
PROCEDURE = {
    "description": "Dividir arquivos TXT grandes em partes menores, preservando a integridade das frases. Útil para transcrições longas, documentos extensos, ou qualquer texto que precise ser dividido em arquivos menores.",
    "solution": """Use a tool split_text_files com os parâmetros:
- input_path: caminho do arquivo TXT ou diretório (ex: "outputs" ou "outputs/arquivo.txt")
- max_chars: limite de caracteres por parte (padrão: 7500)
- output_dir: diretório de saída (opcional, padrão é o mesmo do original)

Exemplo: Para dividir todos os arquivos TXT na pasta outputs em partes de 7500 caracteres:
split_text_files(input_path="outputs", max_chars=7500)

Os arquivos serão nomeados como: nome_original-1.txt, nome_original-2.txt, etc.
Arquivos já divididos (com sufixo -N.txt) são ignorados automaticamente.""",
    "tool_used": "split_text_files",
    "tags": ["arquivo", "texto", "divisão", "split", "txt", "transcrição"]
}

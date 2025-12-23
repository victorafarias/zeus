"""
=====================================================
ZEUS - Split Text Files Tool
Divide arquivos TXT em partes menores preservando
integridade de frases
=====================================================
"""

import os
import re
from typing import Dict, Any, List

from .base import BaseTool, ToolParameter
from config import get_settings, get_logger

logger = get_logger(__name__)
settings = get_settings()


class SplitTextFilesTool(BaseTool):
    """
    Divide arquivos TXT grandes em partes menores.
    
    Preserva a integridade das frases, garantindo que nenhum
    corte ocorra no meio de uma sentença.
    """
    
    name = "split_text_files"
    description = """Divide arquivos TXT em partes menores preservando integridade de frases.
Use para: dividir transcrições longas, textos grandes, documentos extensos.
Cada parte terá no máximo o limite de caracteres especificado.
Os arquivos divididos são nomeados como: {nome_original}-1.txt, {nome_original}-2.txt, etc."""
    
    parameters = [
        ToolParameter(
            name="input_path",
            type="string",
            description="Caminho do arquivo TXT ou diretório contendo arquivos TXT a processar"
        ),
        ToolParameter(
            name="max_chars",
            type="integer",
            description="Limite máximo de caracteres por arquivo dividido (padrão: 7500)",
            required=False
        ),
        ToolParameter(
            name="output_dir",
            type="string",
            description="Diretório de saída para os arquivos divididos (padrão: mesmo diretório do original)",
            required=False
        )
    ]
    
    # Padrão para detectar arquivos já divididos (nome-N.txt onde N é número)
    SPLIT_FILE_PATTERN = re.compile(r'^.+-\d+\.txt$', re.IGNORECASE)
    
    async def execute(
        self,
        input_path: str,
        max_chars: int = 7500,
        output_dir: str = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Executa a divisão de arquivos TXT.
        
        Args:
            input_path: Caminho do arquivo ou diretório
            max_chars: Máximo de caracteres por parte
            output_dir: Diretório de saída (opcional)
            
        Returns:
            Resultado da operação com lista de arquivos criados
        """
        # Resolver caminho absoluto
        if not os.path.isabs(input_path):
            input_path = os.path.join(settings.data_dir, input_path)
        
        # Verificar se está em diretório permitido
        allowed_dirs = ["/app/data", settings.uploads_dir, settings.outputs_dir]
        is_allowed = any(input_path.startswith(d) for d in allowed_dirs)
        
        if not is_allowed:
            logger.warning("Acesso negado", path=input_path)
            return self._error(
                f"Acesso negado. Apenas arquivos em {settings.data_dir} são permitidos."
            )
        
        # Verificar se existe
        if not os.path.exists(input_path):
            return self._error(f"Caminho não encontrado: {input_path}")
        
        # Validar max_chars
        if max_chars < 500:
            return self._error("O limite mínimo de caracteres é 500")
        if max_chars > 50000:
            return self._error("O limite máximo de caracteres é 50000")
        
        logger.info(
            "Iniciando divisão de arquivos",
            input_path=input_path,
            max_chars=max_chars,
            output_dir=output_dir
        )
        
        try:
            # Coletar arquivos a processar
            files_to_process: List[str] = []
            
            if os.path.isfile(input_path):
                # Arquivo único
                if not input_path.lower().endswith('.txt'):
                    return self._error("Apenas arquivos .txt são suportados")
                files_to_process.append(input_path)
            else:
                # Diretório - listar todos os .txt que NÃO são arquivos já divididos
                for filename in os.listdir(input_path):
                    if filename.lower().endswith('.txt'):
                        # Ignorar arquivos já divididos (ex: arquivo-1.txt, arquivo-2.txt)
                        if not self.SPLIT_FILE_PATTERN.match(filename):
                            files_to_process.append(os.path.join(input_path, filename))
            
            if not files_to_process:
                return self._error("Nenhum arquivo TXT encontrado para processar")
            
            # Processar cada arquivo
            all_created_files: List[str] = []
            processed_count = 0
            
            for filepath in files_to_process:
                created_files = await self._split_file(filepath, max_chars, output_dir)
                all_created_files.extend(created_files)
                processed_count += 1
                
                logger.info(
                    "Arquivo processado",
                    file=os.path.basename(filepath),
                    parts=len(created_files)
                )
            
            # Montar resultado
            result_lines = [
                f"✅ **Divisão concluída com sucesso!**\n",
                f"**Arquivos processados:** {processed_count}",
                f"**Arquivos criados:** {len(all_created_files)}",
                f"**Limite de caracteres:** {max_chars}\n",
                "**Arquivos gerados:**"
            ]
            
            for f in all_created_files:
                result_lines.append(f"- `{os.path.basename(f)}`")
            
            logger.info(
                "Divisão concluída",
                processed=processed_count,
                created=len(all_created_files)
            )
            
            return self._success("\n".join(result_lines))
            
        except Exception as e:
            logger.error("Erro ao dividir arquivos", error=str(e))
            return self._error(f"Erro durante processamento: {str(e)}")
    
    async def _split_file(
        self,
        filepath: str,
        max_chars: int,
        output_dir: str = None
    ) -> List[str]:
        """
        Divide um único arquivo TXT em partes.
        
        Args:
            filepath: Caminho do arquivo
            max_chars: Limite de caracteres
            output_dir: Diretório de saída
            
        Returns:
            Lista de caminhos dos arquivos criados
        """
        # Ler conteúdo
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Se o conteúdo for menor que o limite, não precisa dividir
        if len(content) <= max_chars:
            logger.debug("Arquivo pequeno, não precisa dividir", file=filepath)
            return []
        
        # Preparar caminhos
        base_name = os.path.splitext(os.path.basename(filepath))[0]
        directory = output_dir if output_dir else os.path.dirname(filepath)
        
        # Garantir que o diretório de saída existe
        os.makedirs(directory, exist_ok=True)
        
        # Dividir conteúdo
        parts = self._split_content(content, max_chars)
        
        # Salvar partes
        created_files = []
        for i, part in enumerate(parts, 1):
            output_filename = f"{base_name}-{i}.txt"
            output_path = os.path.join(directory, output_filename)
            
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(part.strip())
            
            created_files.append(output_path)
        
        return created_files
    
    def _split_content(self, content: str, max_chars: int) -> List[str]:
        """
        Divide o conteúdo em partes respeitando integridade de frases.
        
        Lógica:
        1. Tenta cortar em max_chars
        2. Se não for fim de frase, retrocede até encontrar um
        3. Se não houver fim de frase antes, avança até o próximo
        
        Args:
            content: Texto a dividir
            max_chars: Limite de caracteres
            
        Returns:
            Lista de partes do texto
        """
        parts = []
        start = 0
        
        # Caracteres que indicam fim de frase
        sentence_endings = {'.', '!', '?'}
        
        while start < len(content):
            # Posição de corte inicial
            end = min(start + max_chars, len(content))
            
            # Se chegamos ao final, pegar o resto
            if end >= len(content):
                parts.append(content[start:])
                break
            
            # Verificar se o caractere no ponto de corte é fim de frase
            if content[end - 1] in sentence_endings:
                # Perfeito, cortar aqui
                parts.append(content[start:end])
                start = end
                continue
            
            # Procurar último fim de frase antes do limite
            last_sentence_end = -1
            for i in range(end - 1, start, -1):
                if content[i] in sentence_endings:
                    # Verificar se não é parte de abreviação ou número decimal
                    # (verificação simples: se o próximo char não é espaço ou quebra, pode ser abreviação)
                    if i + 1 < len(content) and content[i + 1] in [' ', '\n', '\r', '\t']:
                        last_sentence_end = i + 1  # Incluir o ponto
                        break
            
            if last_sentence_end > start:
                # Encontrou fim de frase, usar esse ponto
                parts.append(content[start:last_sentence_end])
                start = last_sentence_end
            else:
                # Não encontrou fim de frase antes do limite
                # Avançar até o próximo fim de frase (para não cortar no meio)
                next_sentence_end = -1
                for i in range(end, min(end + max_chars, len(content))):
                    if content[i] in sentence_endings:
                        if i + 1 >= len(content) or content[i + 1] in [' ', '\n', '\r', '\t']:
                            next_sentence_end = i + 1
                            break
                
                if next_sentence_end > 0:
                    parts.append(content[start:next_sentence_end])
                    start = next_sentence_end
                else:
                    # Último recurso: cortar em quebra de linha ou no limite
                    newline_pos = content.find('\n', end)
                    if newline_pos > 0 and newline_pos - start <= max_chars * 1.5:
                        parts.append(content[start:newline_pos + 1])
                        start = newline_pos + 1
                    else:
                        # Forçar corte no limite (caso extremo)
                        parts.append(content[start:end])
                        start = end
        
        return parts

"""
=====================================================
ZEUS - Shell Executor Tool
Executa comandos shell de forma segura
=====================================================
"""

from typing import Dict, Any, List
import asyncio
import shlex

from .base import BaseTool, ToolParameter
from config import get_settings, get_logger

logger = get_logger(__name__)
settings = get_settings()

# Lista de comandos perigosos que não devem ser executados
BLOCKED_COMMANDS = [
    "rm -rf /",
    "rm -rf /*",
    "mkfs",
    "dd if=/dev/zero",
    ":(){:|:&};:",  # Fork bomb
    "chmod -R 777 /",
    "chown -R",
]

# Comandos que requerem confirmação (não bloqueados, mas alertados)
DANGEROUS_PATTERNS = [
    "rm -rf",
    "rm -r",
    "shutdown",
    "reboot",
    "halt",
    "init 0",
    "init 6",
]


class ShellExecutorTool(BaseTool):
    """
    Executa comandos shell no servidor.
    
    Implementa algumas proteções básicas contra comandos destrutivos.
    """
    
    name = "execute_shell"
    description = """Executa comandos shell/bash no servidor Linux.
Use para: listar arquivos, verificar status do sistema, manipular arquivos,
executar programas, verificar logs, etc.
ATENÇÃO: Comandos destrutivos podem afetar o sistema.
Para tarefas longas (downloads, instalações), aumente o timeout."""
    
    parameters = [
        ToolParameter(
            name="command",
            type="string",
            description="Comando shell a ser executado"
        ),
        ToolParameter(
            name="working_dir",
            type="string",
            description="Diretório de trabalho (padrão: /app/data)",
            required=False
        ),
        ToolParameter(
            name="timeout",
            type="integer",
            description="Tempo máximo em segundos (padrão: 30, máx: 3600). Defina um valor alto para tarefas demoradas.",
            required=False
        )
    ]
    
    async def execute(
        self,
        command: str,
        working_dir: str = "/app/data",
        timeout: int = 30,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Executa comando shell.
        
        Args:
            command: Comando a executar
            working_dir: Diretório de trabalho
            timeout: Timeout em segundos
            
        Returns:
            Resultado da execução
        """
        websocket = kwargs.get('websocket')

        # Verificar comandos bloqueados
        command_lower = command.lower().strip()
        
        for blocked in BLOCKED_COMMANDS:
            if blocked in command_lower:
                logger.warning(
                    "Comando bloqueado",
                    command=command[:100]
                )
                return self._error(f"Comando bloqueado por segurança: {blocked}")
        
        # Alertar sobre comandos perigosos
        is_dangerous = any(
            pattern in command_lower 
            for pattern in DANGEROUS_PATTERNS
        )
        
        if is_dangerous:
            logger.warning("Executando comando potencialmente perigoso", command=command[:100])
        
        # Limitar timeout
        timeout = min(timeout, settings.max_execution_time)
        
        logger.info(
            "Executando shell",
            command=command[:100],
            working_dir=working_dir
        )
        
        try:
            # Detectar se é um comando em background
            is_background = (
                command.strip().endswith('&') or
                'nohup' in command.lower() or
                command.strip().endswith('&>')
            )
            
            if is_background:
                # Para comandos em background, garantir que tenha & no final
                cmd_to_run = command.strip()
                if not cmd_to_run.endswith('&'):
                    cmd_to_run = cmd_to_run + ' &'
                
                # Executar e não esperar
                process = await asyncio.create_subprocess_shell(
                    cmd_to_run,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=working_dir
                )
                
                # Esperar um pouco para ver se há erro imediato
                await asyncio.sleep(0.5)
                
                # Verificar se o processo ainda está rodando (bom sinal)
                if process.returncode is None:
                    logger.info("Processo em background iniciado", pid=process.pid)
                    return self._success(f"Processo iniciado em background (PID: {process.pid})")
                else:
                    # Processo terminou rapidamente - pode ser erro
                    try:
                        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=2.0)
                        stdout_str = stdout.decode('utf-8', errors='replace')
                        stderr_str = stderr.decode('utf-8', errors='replace')
                        if process.returncode != 0:
                            return self._error(f"Erro ao iniciar processo: {stderr_str or stdout_str}")
                        return self._success(stdout_str or "(processo iniciado)")
                    except asyncio.TimeoutError:
                        # Se der timeout, assumimos que o processo está rodando e segurando as pipes
                        # Isso é comum com nohup/background
                        logger.info("Timeout ao ler saída inicial de processo background (provavelmente OK)")
                        return self._success(f"Processo iniciado em background (PID: {process.pid}) - Saída não capturada imediatamente")
            
            # Para comandos normais, comportamento padrão
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir
            )
            
            stdout_buffer = []
            stderr_buffer = []

            async def read_stream(stream, buffer, is_stderr=False):
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    decoded = line.decode('utf-8', errors='replace')
                    buffer.append(decoded)
                    
                    if websocket:
                        try:
                            await websocket.send_json({
                                "type": "tool_log",
                                "tool": "execute_shell",
                                "output": decoded,
                                "is_error": is_stderr
                            })
                        except Exception:
                            pass # Ignorar erros de envio

            # Tarefas de leitura
            tasks = [
                asyncio.create_task(read_stream(process.stdout, stdout_buffer)),
                asyncio.create_task(read_stream(process.stderr, stderr_buffer, True))
            ]
            
            # Aguardar processo com timeout
            try:
                await asyncio.wait_for(process.wait(), timeout=timeout)
                # Garantir leitura completa dos buffers
                await asyncio.gather(*tasks)
            except asyncio.TimeoutError:
                process.kill()
                # Cancelar tasks pendentes
                for t in tasks: t.cancel()
                return self._error(f"Comando excedeu timeout de {timeout}s")
            
            # Reconstruir output completo
            stdout_str = "".join(stdout_buffer)
            stderr_str = "".join(stderr_buffer)
            
            # Verificar código de retorno
            if process.returncode != 0:
                logger.warning(
                    "Comando retornou erro",
                    returncode=process.returncode,
                    stderr=stderr_str[:200]
                )
                output = f"Código de saída: {process.returncode}\n"
                if stdout_str:
                    output += f"Saída:\n{stdout_str}\n"
                if stderr_str:
                    output += f"Erro:\n{stderr_str}"
                return self._error(output)
            
            # Sucesso
            output = stdout_str
            if stderr_str:
                output += f"\nAvisos:\n{stderr_str}"
            
            logger.info(
                "Shell executado com sucesso",
                output_length=len(output)
            )
            
            return self._success(output or "(sem saída)")
            
        except Exception as e:
            logger.error("Erro ao executar shell", error=str(e))
            return self._error(f"Erro: {str(e)}")

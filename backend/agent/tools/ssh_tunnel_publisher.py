"""
=====================================================
ZEUS - SSH Tunnel Publisher Tool
Publica links HTTP públicos via túnel SSH reverso
=====================================================

Este módulo permite publicar arquivos de /app/data 
externamente através de túnel SSH reverso para um 
servidor público (VPS).

Requisitos no servidor remoto:
- GatewayPorts yes em /etc/ssh/sshd_config
- Usuário dedicado para túnel (ex: tunneluser)
- Chave SSH pública autorizada

=====================================================
"""

from typing import Dict, Any, List, Optional
import asyncio
import os

from .base import BaseTool, ToolParameter
from config import get_settings, get_logger

logger = get_logger(__name__)
settings = get_settings()

# Dicionário para rastrear túneis ativos
# Formato: {port: {"process": asyncio.Process, "file": str, "remote_host": str}}
_active_tunnels: Dict[int, Dict[str, Any]] = {}

# Servidor HTTP simples em execução
_http_server_process: Optional[asyncio.subprocess.Process] = None
_http_server_port: int = 0


class SSHTunnelPublisherTool(BaseTool):
    """
    Publica arquivos via túnel SSH reverso para acesso HTTP externo.
    
    Permite criar links públicos para arquivos em /app/data sem
    necessitar de configurações de firewall na VM local.
    """
    
    name = "publish_http_link"
    description = """Publica links HTTP públicos para arquivos em /app/data via túnel SSH reverso.
Use para:
- Criar links de download públicos para arquivos
- Listar túneis ativos
- Parar túneis
- Verificar se um link está acessível

REQUISITOS: O servidor remoto deve ter:
- SSH acessível
- GatewayPorts yes configurado
- Chave SSH autorizada"""
    
    parameters = [
        ToolParameter(
            name="action",
            type="string",
            description="Ação: 'publish' (criar link), 'list' (listar túneis), 'stop' (parar túnel), 'verify' (testar link)",
            enum=["publish", "list", "stop", "verify"]
        ),
        ToolParameter(
            name="file_path",
            type="string",
            description="Caminho do arquivo relativo a /app/data (ex: 'outputs/video.mp4'). Obrigatório para 'publish'.",
            required=False
        ),
        ToolParameter(
            name="remote_host",
            type="string",
            description="IP ou hostname do servidor público (padrão: 31.97.163.164)",
            required=False
        ),
        ToolParameter(
            name="remote_port",
            type="integer",
            description="Porta no servidor remoto (padrão: 9090)",
            required=False
        ),
        ToolParameter(
            name="local_port",
            type="integer",
            description="Porta local para servir arquivos (padrão: 9090)",
            required=False
        ),
        ToolParameter(
            name="tunnel_user",
            type="string",
            description="Usuário SSH no servidor remoto (padrão: 'root')",
            required=False
        ),
        ToolParameter(
            name="url",
            type="string",
            description="URL para verificar (apenas para action='verify')",
            required=False
        )
    ]
    
    async def execute(
        self,
        action: str,
        file_path: str = None,
        remote_host: str = "31.97.163.164",
        remote_port: int = 9090,
        local_port: int = 9090,
        tunnel_user: str = "root",
        url: str = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Executa ação de publicação de link HTTP.
        
        Args:
            action: Ação a executar
            file_path: Caminho do arquivo relativo a /app/data
            remote_host: IP do servidor público
            remote_port: Porta no servidor remoto
            local_port: Porta local para HTTP
            tunnel_user: Usuário SSH
            url: URL para verificar
            
        Returns:
            Resultado da operação
        """
        global _active_tunnels, _http_server_process, _http_server_port
        
        try:
            # -------------------------------------------------
            # Action: PUBLISH (criar túnel e link)
            # -------------------------------------------------
            if action == "publish":
                if not file_path:
                    return self._error("Parâmetro 'file_path' é obrigatório para publicar")
                
                # Verificar se arquivo existe
                full_path = os.path.join(settings.data_dir, file_path)
                if not os.path.exists(full_path):
                    return self._error(f"Arquivo não encontrado: {full_path}")
                
                # Determinar o diretório base para servir
                file_dir = os.path.dirname(full_path)
                file_name = os.path.basename(full_path)
                
                # Verificar se já existe túnel nessa porta
                if remote_port in _active_tunnels:
                    existing = _active_tunnels[remote_port]
                    return self._success(
                        f"⚠️ Túnel já existe na porta {remote_port}!\n\n"
                        f"**Arquivo atual:** {existing['file']}\n"
                        f"**URL:** http://{existing['remote_host']}:{remote_port}/{os.path.basename(existing['file'])}\n\n"
                        f"Use action='stop' para parar o túnel existente antes de criar um novo."
                    )
                
                # 1. Iniciar servidor HTTP simples (Python)
                http_cmd = (
                    f"python3 -m http.server {local_port} "
                    f"--directory {settings.data_dir}"
                )
                
                logger.info(
                    "Iniciando servidor HTTP",
                    port=local_port,
                    directory=settings.data_dir
                )
                
                # Verificar se servidor HTTP já está rodando nessa porta
                if _http_server_process is None or _http_server_port != local_port:
                    # Parar servidor anterior se existir
                    if _http_server_process is not None:
                        try:
                            _http_server_process.terminate()
                            await _http_server_process.wait()
                        except Exception:
                            pass
                    
                    # Iniciar novo servidor
                    _http_server_process = await asyncio.create_subprocess_shell(
                        http_cmd,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                        cwd=settings.data_dir
                    )
                    _http_server_port = local_port
                    
                    # Aguardar servidor iniciar
                    await asyncio.sleep(1)
                    
                    if _http_server_process.returncode is not None:
                        return self._error(
                            f"Falha ao iniciar servidor HTTP na porta {local_port}. "
                            f"Verifique se a porta está disponível."
                        )
                
                # 2. Criar túnel SSH reverso
                ssh_cmd = (
                    f"ssh -o StrictHostKeyChecking=no -o BatchMode=yes "
                    f"-N -R 0.0.0.0:{remote_port}:localhost:{local_port} "
                    f"{tunnel_user}@{remote_host}"
                )
                
                logger.info(
                    "Criando túnel SSH reverso",
                    remote=f"{tunnel_user}@{remote_host}:{remote_port}",
                    local_port=local_port
                )
                
                tunnel_process = await asyncio.create_subprocess_shell(
                    ssh_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                # Aguardar conexão estabelecer
                await asyncio.sleep(2)
                
                # Verificar se túnel está ativo
                if tunnel_process.returncode is not None:
                    # Ler erro
                    _, stderr = await tunnel_process.communicate()
                    error_msg = stderr.decode('utf-8', errors='replace')
                    return self._error(
                        f"Falha ao estabelecer túnel SSH:\n{error_msg}\n\n"
                        f"Verifique:\n"
                        f"- Chave SSH configurada\n"
                        f"- GatewayPorts yes no servidor remoto\n"
                        f"- Porta {remote_port} disponível no servidor"
                    )
                
                # Registrar túnel ativo
                _active_tunnels[remote_port] = {
                    "process": tunnel_process,
                    "file": full_path,
                    "remote_host": remote_host,
                    "tunnel_user": tunnel_user,
                    "local_port": local_port
                }
                
                # Construir URL pública
                public_url = f"http://{remote_host}:{remote_port}/{file_path}"
                
                logger.info(
                    "Túnel SSH estabelecido",
                    url=public_url,
                    tunnel_pid=tunnel_process.pid
                )
                
                return self._success(
                    f"✅ **Link publicado com sucesso!**\n\n"
                    f"🔗 **URL Pública:** {public_url}\n\n"
                    f"📁 **Arquivo:** {full_path}\n"
                    f"🌐 **Servidor:** {remote_host}:{remote_port}\n"
                    f"🔌 **Porta Local:** {local_port}\n\n"
                    f"⚠️ O link permanecerá ativo enquanto o processo estiver rodando.\n"
                    f"Use `action='stop'` para encerrar o túnel."
                )
            
            # -------------------------------------------------
            # Action: LIST (listar túneis ativos)
            # -------------------------------------------------
            elif action == "list":
                if not _active_tunnels:
                    return self._success("Nenhum túnel ativo no momento.")
                
                lines = [f"📡 **{len(_active_tunnels)} túnel(is) ativo(s):**\n"]
                
                for port, info in _active_tunnels.items():
                    file_name = os.path.basename(info['file'])
                    url = f"http://{info['remote_host']}:{port}/{file_name}"
                    
                    lines.append(f"### Porta {port}")
                    lines.append(f"**Arquivo:** {info['file']}")
                    lines.append(f"**URL:** {url}")
                    lines.append(f"**Servidor:** {info['tunnel_user']}@{info['remote_host']}")
                    lines.append(f"**PID:** {info['process'].pid}")
                    lines.append("---")
                
                return self._success("\n".join(lines))
            
            # -------------------------------------------------
            # Action: STOP (parar túnel)
            # -------------------------------------------------
            elif action == "stop":
                if not remote_port:
                    # Parar todos os túneis
                    if not _active_tunnels:
                        return self._success("Nenhum túnel ativo para parar.")
                    
                    count = 0
                    for port, info in list(_active_tunnels.items()):
                        try:
                            info['process'].terminate()
                            await info['process'].wait()
                            del _active_tunnels[port]
                            count += 1
                        except Exception as e:
                            logger.warning(f"Erro ao parar túnel {port}", error=str(e))
                    
                    # Parar servidor HTTP também
                    if _http_server_process is not None:
                        try:
                            _http_server_process.terminate()
                            await _http_server_process.wait()
                        except Exception:
                            pass
                        _http_server_process = None
                    
                    return self._success(f"✅ {count} túnel(is) encerrado(s).")
                
                # Parar túnel específico
                if remote_port not in _active_tunnels:
                    return self._error(f"Nenhum túnel ativo na porta {remote_port}")
                
                info = _active_tunnels[remote_port]
                try:
                    info['process'].terminate()
                    await info['process'].wait()
                    del _active_tunnels[remote_port]
                    
                    logger.info("Túnel encerrado", port=remote_port)
                    return self._success(f"✅ Túnel da porta {remote_port} encerrado com sucesso.")
                except Exception as e:
                    return self._error(f"Erro ao encerrar túnel: {str(e)}")
            
            # -------------------------------------------------
            # Action: VERIFY (verificar link)
            # -------------------------------------------------
            elif action == "verify":
                if not url:
                    # Tentar construir URL a partir dos parâmetros
                    if file_path:
                        url = f"http://{remote_host}:{remote_port}/{file_path}"
                    else:
                        return self._error("Parâmetro 'url' ou 'file_path' é obrigatório para verificar")
                
                # Usar curl para verificar
                verify_cmd = f"curl -I -s -o /dev/null -w '%{{http_code}}' --connect-timeout 5 '{url}'"
                
                logger.info("Verificando URL", url=url)
                
                process = await asyncio.create_subprocess_shell(
                    verify_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=10
                )
                
                status_code = stdout.decode('utf-8', errors='replace').strip()
                
                if status_code == "200":
                    return self._success(
                        f"✅ **Link acessível!**\n\n"
                        f"**URL:** {url}\n"
                        f"**Status:** {status_code} OK"
                    )
                elif status_code == "000":
                    return self._error(
                        f"❌ **Não foi possível conectar ao servidor**\n\n"
                        f"**URL:** {url}\n\n"
                        f"Verifique:\n"
                        f"- O túnel está ativo?\n"
                        f"- O servidor remoto está acessível?\n"
                        f"- A porta está correta?"
                    )
                else:
                    return self._error(
                        f"⚠️ **Link retornou erro**\n\n"
                        f"**URL:** {url}\n"
                        f"**Status:** {status_code}"
                    )
            
            else:
                return self._error(f"Ação desconhecida: {action}")
        
        except asyncio.TimeoutError:
            return self._error("Timeout ao verificar link (servidor demorou demais)")
        except Exception as e:
            logger.error("Erro na publicação SSH", action=action, error=str(e))
            return self._error(f"Erro ao executar '{action}': {str(e)}")

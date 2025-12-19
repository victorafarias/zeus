"""
=====================================================
ZEUS - Docker Manager Tools
Ferramentas para gerenciar containers Docker
=====================================================
"""

from typing import Dict, Any, List, Optional
import docker

from .base import BaseTool, ToolParameter
from .docker_helper import get_docker_client
from config import get_logger

logger = get_logger(__name__)


class DockerListTool(BaseTool):
    """Lista containers Docker em execução"""
    
    name = "docker_list"
    description = """Lista todos os containers Docker em execução no servidor.
Mostra: nome, status, imagem, portas mapeadas."""
    
    parameters = [
        ToolParameter(
            name="all",
            type="boolean",
            description="Se True, lista também containers parados (padrão: False)",
            required=False
        )
    ]
    
    @property
    def docker_client(self):
        """Obtém cliente Docker sob demanda"""
        return get_docker_client()
    
    async def execute(self, all: bool = False, **kwargs) -> Dict[str, Any]:
        """Lista containers Docker"""
        if not self.docker_client:
            return self._error("Docker não disponível")
        
        try:
            containers = self.docker_client.containers.list(all=all)
            
            if not containers:
                return self._success("Nenhum container encontrado.")
            
            lines = ["Containers:\n"]
            
            for c in containers:
                # Extrair portas
                ports = []
                for p, bindings in (c.ports or {}).items():
                    if bindings:
                        for b in bindings:
                            ports.append(f"{b.get('HostPort', '?')}->{p}")
                    else:
                        ports.append(p)
                
                ports_str = ", ".join(ports) if ports else "nenhuma"
                
                lines.append(
                    f"- **{c.name}**\n"
                    f"  - Status: {c.status}\n"
                    f"  - Imagem: {c.image.tags[0] if c.image.tags else c.image.short_id}\n"
                    f"  - Portas: {ports_str}\n"
                )
            
            logger.info("Containers listados", count=len(containers))
            return self._success("\n".join(lines))
            
        except Exception as e:
            logger.error("Erro ao listar containers", error=str(e))
            return self._error(f"Erro: {str(e)}")


class DockerCreateTool(BaseTool):
    """Cria um novo container Docker"""
    
    name = "docker_create"
    description = """Cria e inicia um novo container Docker.
Use para: criar serviços, bancos de dados, aplicações, etc."""
    
    parameters = [
        ToolParameter(
            name="image",
            type="string",
            description="Nome da imagem Docker (ex: nginx, redis, postgres)"
        ),
        ToolParameter(
            name="name",
            type="string",
            description="Nome do container"
        ),
        ToolParameter(
            name="ports",
            type="object",
            description="Mapeamento de portas (ex: {'80/tcp': 8080})",
            required=False
        ),
        ToolParameter(
            name="environment",
            type="object",
            description="Variáveis de ambiente (ex: {'POSTGRES_PASSWORD': 'senha'})",
            required=False
        ),
        ToolParameter(
            name="detach",
            type="boolean",
            description="Executar em background (padrão: True)",
            required=False
        )
    ]
    
    @property
    def docker_client(self):
        """Obtém cliente Docker sob demanda"""
        return get_docker_client()
    
    async def execute(
        self,
        image: str,
        name: str,
        ports: Optional[Dict[str, Any]] = None,
        environment: Optional[Dict[str, str]] = None,
        detach: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """Cria container Docker"""
        if not self.docker_client:
            return self._error("Docker não disponível")
        
        logger.info(
            "Criando container",
            image=image,
            name=name
        )
        
        try:
            # Verificar se já existe
            try:
                existing = self.docker_client.containers.get(name)
                return self._error(
                    f"Container '{name}' já existe (status: {existing.status})"
                )
            except docker.errors.NotFound:
                pass
            
            # Baixar imagem se necessário
            try:
                self.docker_client.images.get(image)
            except docker.errors.ImageNotFound:
                logger.info("Baixando imagem", image=image)
                self.docker_client.images.pull(image)
            
            # Criar container
            container = self.docker_client.containers.run(
                image=image,
                name=name,
                ports=ports,
                environment=environment or {},
                detach=detach,
                restart_policy={"Name": "unless-stopped"}
            )
            
            logger.info("Container criado", name=name, id=container.short_id)
            
            return self._success(
                f"Container '{name}' criado com sucesso!\n"
                f"- ID: {container.short_id}\n"
                f"- Status: {container.status}\n"
                f"- Imagem: {image}"
            )
            
        except docker.errors.APIError as e:
            logger.error("Erro da API Docker", error=str(e))
            return self._error(f"Erro Docker: {str(e)}")
        except Exception as e:
            logger.error("Erro ao criar container", error=str(e))
            return self._error(f"Erro: {str(e)}")


class DockerRemoveTool(BaseTool):
    """Remove um container Docker"""
    
    name = "docker_remove"
    description = """Remove um container Docker pelo nome ou ID.
ATENÇÃO: Esta ação é irreversível. Dados não persistidos serão perdidos."""
    
    parameters = [
        ToolParameter(
            name="name",
            type="string",
            description="Nome ou ID do container a remover"
        ),
        ToolParameter(
            name="force",
            type="boolean",
            description="Forçar remoção mesmo se estiver rodando (padrão: False)",
            required=False
        )
    ]
    
    @property
    def docker_client(self):
        """Obtém cliente Docker sob demanda"""
        return get_docker_client()
    
    async def execute(
        self,
        name: str,
        force: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """Remove container Docker"""
        if not self.docker_client:
            return self._error("Docker não disponível")
        
        # Proteção: não permitir remover containers do Zeus
        protected = ["zeus-backend", "zeus-backend-local", "traefik"]
        if name in protected:
            return self._error(f"Container '{name}' é protegido e não pode ser removido")
        
        logger.info("Removendo container", name=name, force=force)
        
        try:
            container = self.docker_client.containers.get(name)
            container.remove(force=force)
            
            logger.info("Container removido", name=name)
            return self._success(f"Container '{name}' removido com sucesso!")
            
        except docker.errors.NotFound:
            return self._error(f"Container '{name}' não encontrado")
        except docker.errors.APIError as e:
            if "is running" in str(e):
                return self._error(
                    f"Container '{name}' está em execução. "
                    "Use force=True para forçar remoção."
                )
            return self._error(f"Erro Docker: {str(e)}")
        except Exception as e:
            logger.error("Erro ao remover container", error=str(e))
            return self._error(f"Erro: {str(e)}")

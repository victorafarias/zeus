"""
=====================================================
ZEUS - Servidor Principal FastAPI
Ponto de entrada da aplicação
=====================================================
"""

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import os

from config import get_settings, get_logger

# Importar routers
from api.auth import router as auth_router
from api.models import router as models_router
from api.conversations import router as conversations_router
from api.websocket import router as websocket_router
from api.uploads import router as uploads_router
from api.tasks import router as tasks_router

# Importar background worker
from services.background_worker import start_background_worker, stop_background_worker

# -------------------------------------------------
# Inicialização
# -------------------------------------------------
logger = get_logger(__name__)
settings = get_settings()

# Criar aplicação FastAPI
app = FastAPI(
    title="Zeus - Agente de IA",
    description="Sistema de chat com agente de IA capaz de executar tarefas na VPS",
    version="1.0.0"
)

# -------------------------------------------------
# Middleware CORS
# Permite requisições do frontend
# -------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Em produção, especificar domínios
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------------------------------------
# Eventos de Startup/Shutdown
# -------------------------------------------------
@app.on_event("startup")
async def startup_event():
    """
    Executado quando a aplicação inicia.
    Inicializa serviços e verifica configurações.
    """
    logger.info(
        "Zeus iniciando",
        environment=settings.environment,
        openrouter_configured=bool(settings.openrouter_api_key)
    )
    
    # Criar diretórios se não existirem
    for dir_path in [
        settings.uploads_dir,
        settings.outputs_dir,
        settings.conversations_dir,
        settings.chromadb_dir
    ]:
        os.makedirs(dir_path, exist_ok=True)
    
    logger.info("Diretórios de dados verificados")
    
    # Iniciar background worker para processamento de tarefas
    await start_background_worker()
    logger.info("Background worker iniciado")


@app.on_event("shutdown")
async def shutdown_event():
    """
    Executado quando a aplicação encerra.
    Limpa recursos e conexões.
    """
    # Parar background worker
    await stop_background_worker()
    logger.info("Background worker parado")
    
    logger.info("Zeus encerrando")


# -------------------------------------------------
# Registrar Routers
# -------------------------------------------------
app.include_router(auth_router, prefix="/api/auth", tags=["Autenticação"])
app.include_router(models_router, prefix="/api/models", tags=["Modelos"])
app.include_router(conversations_router, prefix="/api/conversations", tags=["Conversas"])
app.include_router(uploads_router, prefix="/api/uploads", tags=["Uploads"])
app.include_router(tasks_router, prefix="/api/tasks", tags=["Tarefas"])
app.include_router(websocket_router, tags=["WebSocket"])


# -------------------------------------------------
# Rotas de Arquivos Estáticos e Frontend
# -------------------------------------------------

# Montar diretório de arquivos estáticos (CSS, JS)
# O caminho depende do ambiente (local vs container)
frontend_path = os.path.join(os.path.dirname(__file__), "..", "frontend")
if not os.path.exists(frontend_path):
    frontend_path = "/app/frontend"

if os.path.exists(frontend_path):
    app.mount("/css", StaticFiles(directory=os.path.join(frontend_path, "css")), name="css")
    app.mount("/js", StaticFiles(directory=os.path.join(frontend_path, "js")), name="js")

# Montar diretórios de dados para download público
# CUIDADO: Isso expõe os arquivos gerados publicamente se não houver autenticação extra
if os.path.exists(settings.outputs_dir):
    app.mount("/outputs", StaticFiles(directory=settings.outputs_dir), name="outputs")

if os.path.exists(settings.uploads_dir):
    app.mount("/uploads", StaticFiles(directory=settings.uploads_dir), name="uploads")


@app.get("/", response_class=HTMLResponse)
async def root():
    """
    Página inicial - Tela de login.
    """
    index_path = os.path.join(frontend_path, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h1>Zeus - Frontend não encontrado</h1>")


@app.get("/chat", response_class=HTMLResponse)
async def chat_page():
    """
    Página de chat - Requer autenticação.
    """
    chat_path = os.path.join(frontend_path, "chat.html")
    if os.path.exists(chat_path):
        return FileResponse(chat_path)
    return HTMLResponse("<h1>Zeus - Chat não encontrado</h1>")


# -------------------------------------------------
# Health Check
# -------------------------------------------------
@app.get("/health")
async def health_check():
    """
    Endpoint de health check para monitoramento.
    """
    return {
        "status": "healthy",
        "environment": settings.environment,
        "version": "1.0.0"
    }


# -------------------------------------------------
# Log de requisições (middleware simples)
# -------------------------------------------------
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """
    Middleware que loga todas as requisições HTTP.
    Útil para debugging.
    """
    logger.debug(
        "Requisição recebida",
        method=request.method,
        path=request.url.path
    )
    
    response = await call_next(request)
    
    logger.debug(
        "Resposta enviada",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code
    )
    
    return response

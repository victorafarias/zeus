"""
=====================================================
ZEUS - API de Autenticação
Endpoints para login, logout e verificação de token
=====================================================
"""

from fastapi import APIRouter, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from datetime import datetime, timedelta
from jose import JWTError, jwt
from passlib.context import CryptContext
from typing import Optional

from config import get_settings, get_logger

# -------------------------------------------------
# Configuração
# -------------------------------------------------
router = APIRouter()
logger = get_logger(__name__)
settings = get_settings()

# Contexto para hash de senha (não usado aqui, mas disponível)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Esquema de segurança Bearer
security = HTTPBearer()


# -------------------------------------------------
# Modelos Pydantic
# -------------------------------------------------
class LoginRequest(BaseModel):
    """Dados de entrada para login"""
    username: str
    password: str


class LoginResponse(BaseModel):
    """Resposta de login bem-sucedido"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # segundos


class TokenData(BaseModel):
    """Dados decodificados do token"""
    username: Optional[str] = None
    exp: Optional[datetime] = None


class UserInfo(BaseModel):
    """Informações do usuário autenticado"""
    username: str
    authenticated: bool = True


# -------------------------------------------------
# Funções de Token JWT
# -------------------------------------------------
def create_access_token(username: str) -> tuple[str, int]:
    """
    Cria um token JWT para o usuário.
    
    Args:
        username: Nome do usuário
        
    Returns:
        Tupla com (token, segundos_para_expirar)
    """
    expire = datetime.utcnow() + timedelta(hours=settings.jwt_expire_hours)
    
    payload = {
        "sub": username,
        "exp": expire,
        "iat": datetime.utcnow()
    }
    
    token = jwt.encode(
        payload,
        settings.secret_key,
        algorithm=settings.jwt_algorithm
    )
    
    expires_in = int((expire - datetime.utcnow()).total_seconds())
    
    logger.info("Token JWT criado", username=username, expires_in=expires_in)
    
    return token, expires_in


def verify_token(token: str) -> TokenData:
    """
    Verifica e decodifica um token JWT.
    
    Args:
        token: Token JWT a verificar
        
    Returns:
        Dados do token decodificado
        
    Raises:
        HTTPException: Se token inválido ou expirado
    """
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm]
        )
        
        username: str = payload.get("sub")
        exp = payload.get("exp")
        
        if username is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token inválido: usuário não encontrado"
            )
        
        return TokenData(username=username, exp=datetime.fromtimestamp(exp))
        
    except JWTError as e:
        logger.warning("Falha na verificação do token", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido ou expirado"
        )


# -------------------------------------------------
# Dependência de Autenticação
# -------------------------------------------------
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> UserInfo:
    """
    Dependência que verifica se o usuário está autenticado.
    Usar em rotas que requerem autenticação.
    
    Uso:
        @router.get("/rota-protegida")
        async def rota(user: UserInfo = Depends(get_current_user)):
            return {"usuario": user.username}
    """
    token_data = verify_token(credentials.credentials)
    return UserInfo(username=token_data.username)


# -------------------------------------------------
# Endpoints
# -------------------------------------------------
@router.post("/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """
    Realiza login do usuário.
    
    Valida usuário/senha contra valores do `.env`.
    Retorna token JWT se credenciais válidas.
    """
    logger.info("Tentativa de login", username=request.username)
    
    # Validar credenciais contra .env
    if (
        request.username != settings.auth_username or
        request.password != settings.auth_password
    ):
        logger.warning(
            "Login falhou: credenciais inválidas",
            username=request.username
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Usuário ou senha incorretos"
        )
    
    # Criar token JWT
    token, expires_in = create_access_token(request.username)
    
    logger.info("Login bem-sucedido", username=request.username)
    
    return LoginResponse(
        access_token=token,
        expires_in=expires_in
    )


@router.get("/verify", response_model=UserInfo)
async def verify(user: UserInfo = Depends(get_current_user)):
    """
    Verifica se o token é válido.
    
    Retorna informações do usuário se token válido.
    Usado pelo frontend para verificar sessão.
    """
    logger.debug("Token verificado", username=user.username)
    return user


@router.post("/logout")
async def logout(user: UserInfo = Depends(get_current_user)):
    """
    Realiza logout do usuário.
    
    Nota: Como usamos JWT, o logout é feito no frontend
    removendo o token do localStorage. Este endpoint
    existe apenas para logging e conformidade da API.
    """
    logger.info("Logout realizado", username=user.username)
    return {"message": "Logout realizado com sucesso"}

/**
 * =====================================================
 * ZEUS - Autenticação JavaScript
 * Gerencia login, logout e verificação de token
 * =====================================================
 */

// Configuração da API
const API_BASE = '';  // Mesmo servidor

// Chave do localStorage para o token
const TOKEN_KEY = 'zeus_token';
const USER_KEY = 'zeus_user';


/**
 * Obtém o token salvo no localStorage
 * @returns {string|null} Token ou null
 */
function getToken() {
    return localStorage.getItem(TOKEN_KEY);
}


/**
 * Salva o token no localStorage
 * @param {string} token - Token JWT
 */
function saveToken(token) {
    localStorage.setItem(TOKEN_KEY, token);
}


/**
 * Remove o token do localStorage
 */
function clearToken() {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
}


/**
 * Obtém dados do usuário
 * @returns {object|null} Dados do usuário ou null
 */
function getUser() {
    const user = localStorage.getItem(USER_KEY);
    return user ? JSON.parse(user) : null;
}


/**
 * Salva dados do usuário
 * @param {object} user - Dados do usuário
 */
function saveUser(user) {
    localStorage.setItem(USER_KEY, JSON.stringify(user));
}


/**
 * Verifica se é a página de login
 * @returns {boolean}
 */
function isLoginPage() {
    return window.location.pathname === '/' ||
        window.location.pathname === '/index.html';
}


/**
 * Verifica se o token é válido fazendo requisição ao servidor
 * @returns {Promise<boolean>}
 */
async function verifyToken() {
    const token = getToken();

    if (!token) {
        console.log('[Auth] Nenhum token encontrado');
        return false;
    }

    try {
        const response = await fetch(`${API_BASE}/api/auth/verify`, {
            method: 'GET',
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });

        if (response.ok) {
            const user = await response.json();
            saveUser(user);
            console.log('[Auth] Token válido', user);
            return true;
        } else {
            console.log('[Auth] Token inválido');
            clearToken();
            return false;
        }
    } catch (error) {
        console.error('[Auth] Erro ao verificar token:', error);
        return false;
    }
}


/**
 * Realiza login
 * @param {string} username - Nome de usuário
 * @param {string} password - Senha
 * @returns {Promise<{success: boolean, error?: string}>}
 */
async function login(username, password) {
    console.log('[Auth] Tentando login...', username);

    try {
        const response = await fetch(`${API_BASE}/api/auth/login`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ username, password })
        });

        if (response.ok) {
            const data = await response.json();
            saveToken(data.access_token);
            saveUser({ username, authenticated: true });
            console.log('[Auth] Login bem-sucedido');
            return { success: true };
        } else {
            const error = await response.json();
            console.log('[Auth] Login falhou:', error);
            return {
                success: false,
                error: error.detail || 'Credenciais inválidas'
            };
        }
    } catch (error) {
        console.error('[Auth] Erro no login:', error);
        return {
            success: false,
            error: 'Erro de conexão. Tente novamente.'
        };
    }
}


/**
 * Realiza logout
 */
async function logout() {
    const token = getToken();

    if (token) {
        try {
            // Notificar servidor (opcional, já que usamos JWT)
            await fetch(`${API_BASE}/api/auth/logout`, {
                method: 'POST',
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });
        } catch (e) {
            // Ignorar erros de logout
        }
    }

    clearToken();
    console.log('[Auth] Logout realizado');
    window.location.href = '/';
}


/**
 * Redireciona para login se não autenticado
 * Redireciona para chat se autenticado na página de login
 */
async function checkAuth() {
    const isAuthenticated = await verifyToken();

    if (isLoginPage()) {
        if (isAuthenticated) {
            console.log('[Auth] Já autenticado, redirecionando para chat');
            window.location.href = '/chat';
        }
    } else {
        if (!isAuthenticated) {
            console.log('[Auth] Não autenticado, redirecionando para login');
            window.location.href = '/';
        }
    }
}


// =====================================================
// Event Listeners para página de login
// =====================================================

document.addEventListener('DOMContentLoaded', function () {
    console.log('[Auth] Inicializando...');

    // Verificar autenticação
    checkAuth();

    // Formulário de login
    const loginForm = document.getElementById('login-form');
    if (loginForm) {
        loginForm.addEventListener('submit', handleLoginSubmit);
    }

    // Toggle de senha
    const togglePassword = document.querySelector('.toggle-password');
    if (togglePassword) {
        togglePassword.addEventListener('click', function () {
            const input = document.getElementById('password');
            const type = input.type === 'password' ? 'text' : 'password';
            input.type = type;
        });
    }

    // Botão de logout
    const btnLogout = document.getElementById('btn-logout');
    if (btnLogout) {
        btnLogout.addEventListener('click', logout);
    }
});


/**
 * Handler do submit do formulário de login
 * @param {Event} e - Evento de submit
 */
async function handleLoginSubmit(e) {
    e.preventDefault();

    const form = e.target;
    const username = form.username.value.trim();
    const password = form.password.value;
    const btnLogin = document.getElementById('btn-login');
    const errorMessage = document.getElementById('error-message');

    // Validação básica
    if (!username || !password) {
        showError('Preencha todos os campos');
        return;
    }

    // Desabilitar botão e mostrar loader
    btnLogin.disabled = true;
    btnLogin.querySelector('.btn-text').hidden = true;
    btnLogin.querySelector('.btn-loader').hidden = false;
    btnLogin.querySelector('.btn-loader').style.display = 'block'; // Forçar display
    errorMessage.hidden = true;

    try {
        const result = await login(username, password);

        if (result.success) {
            // Redirecionar para chat
            window.location.href = '/chat';
        } else {
            showError(result.error);
            // Reabilitar botão
            btnLogin.disabled = false;
            btnLogin.querySelector('.btn-text').hidden = false;
            btnLogin.querySelector('.btn-loader').hidden = true;
            btnLogin.querySelector('.btn-loader').style.display = 'none'; // Forçar esconder
        }
    } catch (error) {
        showError('Erro inesperado. Tente novamente.');
        btnLogin.disabled = false;
        btnLogin.querySelector('.btn-text').hidden = false;
        btnLogin.querySelector('.btn-loader').hidden = true;
        btnLogin.querySelector('.btn-loader').style.display = 'none'; // Forçar esconder
    }
}


/**
 * Exibe mensagem de erro
 * @param {string} message - Mensagem de erro
 */
function showError(message) {
    const errorMessage = document.getElementById('error-message');
    if (errorMessage) {
        errorMessage.querySelector('span').textContent = message;
        errorMessage.hidden = false;
    }
}


/**
 * Adiciona header de autenticação a uma requisição
 * @param {object} headers - Headers existentes
 * @returns {object} Headers com Authorization
 */
function withAuth(headers = {}) {
    const token = getToken();
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }
    return headers;
}


// Exportar funções para uso em outros módulos
window.Auth = {
    getToken,
    getUser,
    logout,
    withAuth,
    verifyToken
};

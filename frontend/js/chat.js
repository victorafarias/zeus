/**
 * =====================================================
 * ZEUS - Chat JavaScript
 * Gerencia WebSocket, mensagens e interface de chat
 * =====================================================
 */

// Estado do chat
let websocket = null;
let isConnected = false;
let isProcessing = false;
let pendingFiles = [];
let toolModalTimeout = null;

// Elementos DOM
let messagesContainer = null;
let messagesDiv = null;
let welcomeScreen = null;
let messageInput = null;
let btnSend = null;
let typingIndicator = null;
let connectionStatus = null;


/**
 * Conecta ao WebSocket do servidor
 * @param {string} conversationId - ID da conversa (opcional)
 */
function connectWebSocket(conversationId = null) {
    const token = Auth.getToken();
    if (!token) {
        console.error('[Chat] Sem token para conectar WebSocket');
        return;
    }

    // Se já está conectado com a mesma conversa, não reconectar
    if (websocket && websocket.readyState === WebSocket.OPEN) {
        // Obter parameters da URL atual do socket para comparar
        const url = new URL(websocket.url);
        const currentConvId = url.searchParams.get('conversation_id');

        // Se conversationId for null (nova conversa) e socket não tiver conversation_id, ok
        // Se conversationId for igual ao do socket, ok
        if (currentConvId === conversationId || (!currentConvId && !conversationId)) {
            console.log('[Chat] WebSocket já conectado nesta conversa');
            return;
        }
    }

    // Fechar conexão existente
    if (websocket) {
        websocket.close();
    }

    // Construir URL do WebSocket
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    let wsUrl = `${protocol}//${window.location.host}/ws/chat?token=${token}`;

    if (conversationId) {
        wsUrl += `&conversation_id=${conversationId}`;
    }

    console.log('[Chat] Conectando WebSocket...', conversationId || 'nova conversa');
    updateConnectionStatus('connecting');

    websocket = new WebSocket(wsUrl);

    websocket.onopen = () => {
        console.log('[Chat] WebSocket conectado');
        isConnected = true;
        updateConnectionStatus('connected');
    };

    websocket.onclose = (event) => {
        console.log('[Chat] WebSocket desconectado', event.code);
        isConnected = false;
        updateConnectionStatus('disconnected');
        // Não reconectar automaticamente - será reconectado quando necessário
    };

    websocket.onerror = (error) => {
        console.error('[Chat] Erro no WebSocket', error);
        updateConnectionStatus('disconnected');
    };

    websocket.onmessage = handleWebSocketMessage;
}


/**
 * Atualiza logs da tool em execução
 * @param {string} output - Texto do log
 */
function updateToolLog(output) {
    const logsContainer = document.querySelector('.tool-logs-container');
    const logsPre = document.getElementById('tool-logs');

    if (logsContainer && logsPre) {
        logsContainer.style.display = 'block';
        logsPre.textContent += output;
        // Auto scroll
        logsContainer.scrollTop = logsContainer.scrollHeight;
    }

    // Mostrar última linha no indicador de digitação para feedback imediato
    const lines = output.split('\n').filter(line => line.trim());
    if (lines.length > 0) {
        const lastLine = lines[lines.length - 1];
        // Limitar tamanho
        const truncated = lastLine.length > 50 ? lastLine.substring(0, 47) + '...' : lastLine;
        showTypingIndicator(truncated);
    }
}


/**
 * Processa mensagem recebida do WebSocket
 * @param {MessageEvent} event - Evento de mensagem
 */
function handleWebSocketMessage(event) {
    try {
        const data = JSON.parse(event.data);
        console.log('[Chat] Mensagem recebida:', data.type);

        switch (data.type) {
            case 'conversation_created':
                // Nova conversa criada pelo servidor
                Conversations.loadConversations();
                break;

            case 'message':
                // Mensagem completa do assistente
                hideTypingIndicator();
                hideToolModal(); // Garantir que modal está fechado
                addMessage('assistant', data.content, data.tool_calls);
                isProcessing = false;
                enableInput();
                break;

            case 'chunk':
                // Chunk de streaming (não implementado nesta versão)
                break;

            case 'status':
                if (data.status === 'processing') {
                    showTypingIndicator(data.content);
                } else if (data.status === 'idle') {
                    hideTypingIndicator();
                }
                break;

            case 'tool_start':
                showToolModal(data.tool);
                break;

            case 'tool_log':
                updateToolLog(data.output);
                break;

            case 'tool_result':
                hideToolModal();
                break;

            case 'backend_log':
                // Exibe descrição do log do backend no indicador de digitação
                console.log('[Chat] Backend log:', data.message);
                showTypingIndicator(data.message);
                break;

            case 'error':
                hideTypingIndicator();
                hideToolModal();
                addMessage('system', `❌ ${data.content}`);
                isProcessing = false;
                enableInput();
                break;

            case 'pong':
                // Keep-alive response
                break;
        }

    } catch (error) {
        console.error('[Chat] Erro ao processar mensagem:', error);
    }
}


/**
 * Envia mensagem para o servidor
 * @param {string} content - Conteúdo da mensagem
 */
function sendMessage(content) {
    if (!content.trim()) {
        return;
    }

    // Verificar/criar conversa
    let conversation = Conversations.getCurrentConversation();

    if (!conversation) {
        // Criar nova conversa se não existir
        console.log('[Chat] Criando nova conversa...');
        Conversations.createConversation('Nova Conversa', Models.getSelectedModel())
            .then(conv => {
                if (conv) {
                    Conversations.setCurrentConversation(conv);
                    // Reconectar WebSocket com ID da conversa
                    connectWebSocket(conv.id);

                    // Aguardar conexão abrir e enviar
                    const waitAndSend = () => {
                        if (isConnected && websocket && websocket.readyState === WebSocket.OPEN) {
                            sendMessage(content);
                        } else {
                            setTimeout(waitAndSend, 100);
                        }
                    };
                    setTimeout(waitAndSend, 200);
                }
            });
        return;
    }

    // Verificar conexão WebSocket
    if (!websocket || websocket.readyState !== WebSocket.OPEN) {
        console.log('[Chat] WebSocket não pronto, reconectando...');
        connectWebSocket(conversation.id);
        setTimeout(() => sendMessage(content), 500);
        return;
    }

    // Adicionar mensagem do usuário à interface
    addMessage('user', content);

    // Esconder tela de boas-vindas
    hideWelcomeScreen();

    // Desabilitar input
    disableInput();
    isProcessing = true;

    // Mostrar indicador de digitação
    showTypingIndicator();

    // Enviar via WebSocket
    const message = {
        type: 'message',
        content: content,
        model_id: Models.getSelectedModel()
    };

    console.log('[Chat] Enviando mensagem...');
    websocket.send(JSON.stringify(message));
    console.log('[Chat] Mensagem enviada');
}


/**
 * Adiciona mensagem à interface
 * @param {string} role - 'user', 'assistant', ou 'system'
 * @param {string} content - Conteúdo da mensagem
 * @param {Array} toolCalls - Tool calls (opcional)
 */
function addMessage(role, content, toolCalls = null) {
    if (!messagesDiv) return;

    const message = document.createElement('div');
    message.className = `message ${role}`;

    const time = new Date().toLocaleTimeString('pt-BR', {
        hour: '2-digit',
        minute: '2-digit'
    });

    // Avatar
    let avatarSvg = '';
    let authorName = '';

    if (role === 'user') {
        avatarSvg = '<path d="M12 12c2.21 0 4-1.79 4-4s-1.79-4-4-4-4 1.79-4 4 1.79 4 4 4zm0 2c-2.67 0-8 1.34-8 4v2h16v-2c0-2.66-5.33-4-8-4z"/>';
        authorName = 'Você';
    } else if (role === 'assistant') {
        avatarSvg = '<path d="M12 2L1 21h22L12 2zm0 4l7.53 13H4.47L12 6z"/>';
        authorName = 'Zeus';
    } else {
        avatarSvg = '<path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm1 15h-2v-2h2v2zm0-4h-2V7h2v6z"/>';
        authorName = 'Sistema';
    }

    // Renderizar conteúdo com Markdown
    let renderedContent = content;
    if (typeof marked !== 'undefined') {
        renderedContent = marked.parse(content);
    }

    message.innerHTML = `
        <div class="message-avatar">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor">
                ${avatarSvg}
            </svg>
        </div>
        <div class="message-content">
            <div class="message-header">
                <span class="message-author">${authorName}</span>
                <span class="message-time">${time}</span>
            </div>
            <div class="message-body">${renderedContent}</div>
        </div>
    `;

    messagesDiv.appendChild(message);

    // Syntax highlighting
    if (typeof hljs !== 'undefined') {
        message.querySelectorAll('pre code').forEach(block => {
            hljs.highlightElement(block);
        });
    }

    // Scroll para o final
    scrollToBottom();
}


/**
 * Carrega conversa e exibe mensagens
 * @param {object} conversation - Objeto da conversa
 */
function loadConversation(conversation) {
    console.log('[Chat] Carregando conversa:', conversation.id);

    // Limpar mensagens
    clearMessages();

    // Conectar WebSocket com ID da conversa
    connectWebSocket(conversation.id);

    // Esconder tela de boas-vindas se houver mensagens
    if (conversation.messages && conversation.messages.length > 0) {
        hideWelcomeScreen();

        // Renderizar mensagens
        conversation.messages.forEach(msg => {
            addMessage(msg.role, msg.content, msg.tool_calls);
        });
    } else {
        showWelcomeScreen();
    }
}


/**
 * Limpa todas as mensagens
 */
function clearMessages() {
    if (messagesDiv) {
        messagesDiv.innerHTML = '';
    }
    showWelcomeScreen();
}


/**
 * Scroll para o final das mensagens
 */
function scrollToBottom() {
    if (messagesContainer) {
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }
}


/**
 * Atualiza status de conexão
 * @param {string} status - 'connecting', 'connected', 'disconnected'
 */
function updateConnectionStatus(status) {
    if (!connectionStatus) return;

    connectionStatus.className = 'connection-status ' + status;

    const textEl = connectionStatus.querySelector('.status-text');
    if (textEl) {
        const texts = {
            connecting: 'Conectando...',
            connected: 'Conectado',
            disconnected: 'Desconectado'
        };
        textEl.textContent = texts[status] || status;
    }
}


/**
 * Mostra indicador de digitação
 */
/**
 * Mostra indicador de digitação
 */
function showTypingIndicator(text = null) {
    if (typingIndicator) {
        typingIndicator.hidden = false;
        typingIndicator.style.display = 'flex';

        // Atualizar texto se fornecido
        if (text) {
            const textEl = typingIndicator.querySelector('.typing-text') || typingIndicator.querySelector('span');
            if (textEl) {
                textEl.textContent = text;
            } else {
                // Se não tiver elemento de texto, criar
                const span = document.createElement('span');
                span.className = 'typing-text';
                span.style.marginLeft = '10px';
                span.style.fontSize = '0.9em';
                span.style.color = '#888';
                span.textContent = text;
                typingIndicator.appendChild(span);
            }
        }

        scrollToBottom();
    }
}


/**
 * Esconde indicador de digitação
 */
function hideTypingIndicator() {
    if (typingIndicator) {
        typingIndicator.hidden = true;
        typingIndicator.style.display = 'none';
        isProcessing = false; // Resetar estado caso esteja preso
    }
}


/**
 * Mostra modal de execução de tool
 * @param {string} toolName - Nome da tool
 */
function showToolModal(toolName) {
    const modal = document.getElementById('tool-modal');
    const toolNameEl = document.getElementById('tool-name');
    const logsContainer = document.querySelector('.tool-logs-container');
    const logsPre = document.getElementById('tool-logs');

    if (modal && toolNameEl) {
        toolNameEl.textContent = toolName;
        modal.hidden = false;

        // Limpar logs anteriores
        if (logsContainer) logsContainer.style.display = 'none';
        if (logsPre) logsPre.textContent = '';

        // Timeout de segurança: fechar após 60 segundos
        if (toolModalTimeout) {
            clearTimeout(toolModalTimeout);
        }
        toolModalTimeout = setTimeout(() => {
            hideToolModal();
        }, 60000);
    }
}


/**
 * Esconde modal de tool
 */
function hideToolModal() {
    const modal = document.getElementById('tool-modal');
    if (modal) {
        modal.hidden = true;
    }
    // Limpar timeout
    if (toolModalTimeout) {
        clearTimeout(toolModalTimeout);
        toolModalTimeout = null;
    }
}


/**
 * Mostra tela de boas-vindas
 */
function showWelcomeScreen() {
    if (welcomeScreen) {
        welcomeScreen.style.display = 'flex';
    }
    if (messagesDiv) {
        messagesDiv.style.display = 'none';
    }
}


/**
 * Esconde tela de boas-vindas
 */
function hideWelcomeScreen() {
    if (welcomeScreen) {
        welcomeScreen.style.display = 'none';
    }
    if (messagesDiv) {
        messagesDiv.style.display = 'flex';
    }
}


/**
 * Desabilita input durante processamento
 */
function disableInput() {
    if (messageInput) messageInput.disabled = true;
    if (btnSend) btnSend.disabled = true;
}


/**
 * Habilita input após processamento
 */
function enableInput() {
    if (messageInput) {
        messageInput.disabled = false;
        messageInput.focus();
    }
    if (btnSend) btnSend.disabled = false;
}


/**
 * Auto-resize do textarea
 * @param {HTMLTextAreaElement} textarea
 */
function autoResize(textarea) {
    textarea.style.height = 'auto';
    textarea.style.height = Math.min(textarea.scrollHeight, 150) + 'px';
}


/**
 * Inicializa o chat
 */
function initChat() {
    console.log('[Chat] Inicializando...');

    // Capturar elementos
    messagesContainer = document.getElementById('messages-container');
    messagesDiv = document.getElementById('messages');
    welcomeScreen = document.getElementById('welcome-screen');
    messageInput = document.getElementById('message-input');
    btnSend = document.getElementById('btn-send');
    typingIndicator = document.getElementById('typing-indicator');
    connectionStatus = document.getElementById('connection-status');

    // Garantir que modais estejam escondidos ao iniciar
    hideToolModal();
    hideTypingIndicator();

    // Formulário de mensagem
    const messageForm = document.getElementById('message-form');
    if (messageForm) {
        messageForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const content = messageInput.value.trim();
            if (content && !isProcessing) {
                sendMessage(content);
                messageInput.value = '';
                autoResize(messageInput);
                btnSend.disabled = true;
            }
        });
    }

    // Auto-resize e habilitar/desabilitar botão
    if (messageInput) {
        messageInput.addEventListener('input', () => {
            autoResize(messageInput);
            btnSend.disabled = !messageInput.value.trim();
        });

        // Enter para enviar (Shift+Enter para nova linha)
        messageInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                messageForm.dispatchEvent(new Event('submit'));
            }
        });
    }

    // Upload de arquivos
    const btnUpload = document.getElementById('btn-upload');
    const fileInput = document.getElementById('file-input');

    if (btnUpload && fileInput) {
        btnUpload.addEventListener('click', () => {
            fileInput.click();
        });

        fileInput.addEventListener('change', handleFileSelect);
    }

    // Toggle sidebar (mobile)
    const btnToggle = document.getElementById('btn-toggle-sidebar');
    const sidebar = document.getElementById('sidebar');

    if (btnToggle && sidebar) {
        btnToggle.addEventListener('click', () => {
            sidebar.classList.toggle('open');
        });
    }

    // Conectar WebSocket inicial
    connectWebSocket();

    // Keep-alive
    setInterval(() => {
        if (isConnected && websocket) {
            websocket.send(JSON.stringify({ type: 'ping' }));
        }
    }, 30000);
}


/**
 * Handler para seleção de arquivos
 * @param {Event} e - Evento de change
 */
function handleFileSelect(e) {
    const files = e.target.files;
    if (!files.length) return;

    // TODO: Implementar upload de arquivos
    console.log('[Chat] Arquivos selecionados:', files.length);

    // Por enquanto, apenas notificar que ainda não está implementado
    alert('Upload de arquivos será implementado em uma próxima versão.');

    e.target.value = '';
}


// Inicializar quando DOM estiver pronto
document.addEventListener('DOMContentLoaded', function () {
    if (document.getElementById('message-form')) {
        // Marcar marked para usar GitHub Flavored Markdown
        if (typeof marked !== 'undefined') {
            marked.setOptions({
                gfm: true,
                breaks: true
            });
        }

        initChat();
    }
});


// Exportar funções
window.Chat = {
    sendMessage,
    addMessage,
    loadConversation,
    clearMessages,
    connectWebSocket
};

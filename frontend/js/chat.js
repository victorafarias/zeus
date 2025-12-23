/**
 * =====================================================
 * ZEUS - Chat JavaScript
 * Gerencia WebSocket, mensagens e interface de chat
 * =====================================================
 */

// Estado do chat
let websocket = null;
let isConnected = false;
// Estado de processamento por conversa (permite múltiplas conversas processando em paralelo)
const processingByConversation = new Map(); // conversation_id -> boolean
let pendingFiles = [];
let toolModalTimeout = null;

// Elementos DOM
let messagesContainer = null;
let messagesDiv = null;
let welcomeScreen = null;
let messageInput = null;
let btnSend = null;
let btnCancel = null;
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
 * Retorna o ID da conversa atual
 * @returns {string|null} ID da conversa ou null
 */
function getCurrentConversationId() {
    const conversation = Conversations.getCurrentConversation();
    return conversation ? conversation.id : null;
}


/**
 * Define o estado de processamento de uma conversa
 * @param {string} conversationId - ID da conversa
 * @param {boolean} processing - Se está processando
 */
function setConversationProcessing(conversationId, processing) {
    if (!conversationId) return;

    processingByConversation.set(conversationId, processing);
    console.log(`[Chat] Conversa ${conversationId.substring(0, 8)}... processando: ${processing}`);

    // Atualizar loader na sidebar
    updateSidebarLoader(conversationId, processing);
}


/**
 * Verifica se uma conversa está processando
 * @param {string} conversationId - ID da conversa
 * @returns {boolean} Se está processando
 */
function isConversationProcessing(conversationId) {
    return processingByConversation.get(conversationId) || false;
}


/**
 * Verifica se a conversa ATUAL está processando
 * @returns {boolean} Se a conversa atual está processando
 */
function isCurrentConversationProcessing() {
    const convId = getCurrentConversationId();
    return convId ? isConversationProcessing(convId) : false;
}


/**
 * Atualiza o loader visual na sidebar para indicar processamento
 * @param {string} conversationId - ID da conversa
 * @param {boolean} processing - Se está processando
 */
function updateSidebarLoader(conversationId, processing) {
    const conversationItem = document.querySelector(`.conversation-item[data-id="${conversationId}"]`);

    if (!conversationItem) return;

    // Remover loader existente se houver
    const existingLoader = conversationItem.querySelector('.processing-loader');
    if (existingLoader) {
        existingLoader.remove();
    }

    // Adicionar loader se estiver processando
    if (processing) {
        const loader = document.createElement('div');
        loader.className = 'processing-loader';
        loader.title = 'Processando...';
        loader.innerHTML = `
            <svg class="spinner" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
                <circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-dasharray="31.415 31.415" />
            </svg>
        `;

        // Inserir antes das actions (botão de deletar)
        const actions = conversationItem.querySelector('.conversation-actions');
        if (actions) {
            conversationItem.insertBefore(loader, actions);
        } else {
            conversationItem.appendChild(loader);
        }
    }
}


/**
 * Restaura loaders de todas as conversas que estão processando.
 * Chamado após re-renderização da lista de conversas.
 */
function restoreAllProcessingLoaders() {
    processingByConversation.forEach((isProcessing, conversationId) => {
        if (isProcessing) {
            updateSidebarLoader(conversationId, true);
        }
    });
    console.log('[Chat] Loaders restaurados para conversas em processamento');
}

// Exportar função globalmente para uso em conversations.js
window.restoreAllProcessingLoaders = restoreAllProcessingLoaders;


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
                hideCancelButton(); // Esconder botão de cancelar
                addMessage('assistant', data.content, data.tool_calls);
                setConversationProcessing(getCurrentConversationId(), false);
                enableInput();
                break;

            case 'cancelled':
                // Processamento foi cancelado pelo usuário
                hideTypingIndicator();
                hideToolModal();
                hideCancelButton();
                addMessage('system', `⛔ ${data.content || 'Processamento cancelado pelo usuário.'}`);
                setConversationProcessing(getCurrentConversationId(), false);
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
                hideCancelButton();
                addMessage('system', `❌ ${data.content}`);
                setConversationProcessing(getCurrentConversationId(), false);
                enableInput();
                break;

            case 'task_created':
                // Tarefa foi criada para processamento em background
                console.log('[Chat] Tarefa criada:', data.task_id);
                showTypingIndicator('Processamento em background iniciado...');
                addMessage('system', `📋 ${data.message || 'Sua mensagem foi enfileirada para processamento em background.'}`);
                // Não esconder botão de cancelar - tarefa ainda está processando
                break;

            case 'task_status':
                // Atualização de status de tarefa
                console.log('[Chat] Status da tarefa:', data.task_id, data.status, data.conversation_id);

                // Sempre atualizar estado de processamento desta conversa específica
                // Se completou ou falhou, não está mais processando
                if (data.status === 'completed' || data.status === 'failed') {
                    if (data.conversation_id) {
                        setConversationProcessing(data.conversation_id, false);
                    }
                }

                // Só atualizar UI se for a conversa atual
                const isCurrentConv = !data.conversation_id || data.conversation_id === getCurrentConversationId();

                if (isCurrentConv) {
                    if (data.status === 'completed') {
                        hideTypingIndicator();
                        hideCancelButton();
                        if (data.result) {
                            addMessage('assistant', data.result, data.tool_calls);
                        }
                        enableInput();
                        // Recarregar conversa para pegar mensagens salvas
                        Conversations.loadConversations();
                    } else if (data.status === 'failed') {
                        hideTypingIndicator();
                        hideCancelButton();
                        addMessage('system', `❌ Erro no processamento: ${data.error || 'Erro desconhecido'}`);
                        enableInput();
                    } else if (data.status === 'processing') {
                        showTypingIndicator(`Processando tarefa...`);
                    } else if (data.status === 'pending') {
                        showTypingIndicator(`Tarefa na fila de processamento...`);
                    }
                }
                break;

            case 'task_progress':
                // Progresso de uma tarefa em execução
                console.log('[Chat] Progresso da tarefa:', data.message, data.conversation_id);

                // Sempre marcar como processando se receber progresso
                if (data.conversation_id) {
                    setConversationProcessing(data.conversation_id, true);
                }

                // Só atualizar UI se for a conversa atual
                if (!data.conversation_id || data.conversation_id === getCurrentConversationId()) {
                    showTypingIndicator(data.message);
                }
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
    // Se houver arquivos anexados, mostrar indicação
    let displayContent = content;
    if (pendingFiles.length > 0) {
        const fileNames = pendingFiles.map(f => f.original_name).join(', ');
        displayContent = content + `\n\n📎 Arquivos anexados: ${fileNames}`;
    }
    addMessage('user', displayContent);

    // Esconder tela de boas-vindas
    hideWelcomeScreen();

    // Desabilitar input e marcar conversa como processando
    disableInput();
    setConversationProcessing(conversation.id, true);

    // Mostrar indicador de digitação e botão de cancelar
    showTypingIndicator();
    showCancelButton();

    // Preparar lista de IDs dos arquivos anexados
    const attachedFileIds = pendingFiles.map(f => f.id);

    // Enviar via WebSocket
    // Incluir os três modelos selecionados para o sistema de fallback
    // Usar modo BACKGROUND para permitir processamento paralelo e independente
    const selectedModels = Models.getSelectedModels();
    const message = {
        type: 'message',
        content: content,
        background: true,  // SEMPRE usar background para permitir processamento paralelo
        models: {
            primary: selectedModels.primary,
            secondary: selectedModels.secondary,
            tertiary: selectedModels.tertiary
        },
        attached_files: attachedFileIds  // IDs dos arquivos anexados
    };

    console.log('[Chat] Enviando mensagem com modelos:', selectedModels);
    console.log('[Chat] Arquivos anexados:', attachedFileIds);
    websocket.send(JSON.stringify(message));
    console.log('[Chat] Mensagem enviada (modo background)');

    // Limpar arquivos pendentes e esconder preview
    pendingFiles = [];
    renderFilePreview();
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

    // Ícone de copiar (clipboard)
    const copyIcon = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor">
        <path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z"/>
    </svg>`;

    // Ícone de check (copiado)
    const checkIcon = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor">
        <path d="M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z"/>
    </svg>`;

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
        <button class="btn-copy-message" title="Copiar texto">
            ${copyIcon}
        </button>
    `;

    // Armazenar o texto original para copiar (sem formatação HTML)
    message.dataset.originalText = content;

    // Event listener para o botão de copiar
    const btnCopy = message.querySelector('.btn-copy-message');
    if (btnCopy) {
        btnCopy.addEventListener('click', () => {
            copyMessageText(content, btnCopy, copyIcon, checkIcon);
        });
    }

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
 * Copia o texto de uma mensagem para a área de transferência
 * @param {string} text - Texto a copiar
 * @param {HTMLElement} button - Botão que foi clicado
 * @param {string} copyIcon - HTML do ícone de copiar
 * @param {string} checkIcon - HTML do ícone de check
 */
async function copyMessageText(text, button, copyIcon, checkIcon) {
    try {
        await navigator.clipboard.writeText(text);
        console.log('[Chat] Texto copiado para área de transferência');

        // Feedback visual: mudar ícone para check
        button.innerHTML = checkIcon;
        button.classList.add('copied');
        button.title = 'Copiado!';

        // Restaurar ícone original após 2 segundos
        setTimeout(() => {
            button.innerHTML = copyIcon;
            button.classList.remove('copied');
            button.title = 'Copiar texto';
        }, 2000);

    } catch (error) {
        console.error('[Chat] Erro ao copiar texto:', error);
        // Fallback para navegadores antigos
        try {
            const textArea = document.createElement('textarea');
            textArea.value = text;
            textArea.style.position = 'fixed';
            textArea.style.left = '-9999px';
            document.body.appendChild(textArea);
            textArea.select();
            document.execCommand('copy');
            document.body.removeChild(textArea);

            // Feedback visual
            button.innerHTML = checkIcon;
            button.classList.add('copied');
            button.title = 'Copiado!';

            setTimeout(() => {
                button.innerHTML = copyIcon;
                button.classList.remove('copied');
                button.title = 'Copiar texto';
            }, 2000);
        } catch (fallbackError) {
            console.error('[Chat] Fallback de cópia também falhou:', fallbackError);
            alert('Não foi possível copiar o texto. Por favor, selecione e copie manualmente.');
        }
    }
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

    // Restaurar estado de interface baseado no processamento DESTA conversa específica
    if (isConversationProcessing(conversation.id)) {
        // Esta conversa está processando - mostrar indicadores
        showTypingIndicator('Processando...');
        showCancelButton();
        disableInput();
        console.log('[Chat] Conversa em processamento - indicadores restaurados');
    } else {
        // Esta conversa NÃO está processando - esconder indicadores e habilitar input
        hideTypingIndicator();
        hideCancelButton();
        enableInput();
        console.log('[Chat] Conversa não está processando - input habilitado');
    }

    // Fechar sidebar no mobile após selecionar conversa
    closeSidebarMobile();
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
        // Não resetar estado aqui - o estado é controlado por conversa
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
        // Usar preventScroll para evitar que o navegador role a página no mobile
        messageInput.focus({ preventScroll: true });
    }
    if (btnSend) btnSend.disabled = false;
}


/**
 * Mostra botão de cancelar
 */
function showCancelButton() {
    if (btnCancel) {
        btnCancel.hidden = false;
        btnCancel.style.display = 'flex';
        console.log('[Chat] Botão de cancelar exibido');
    }
}


/**
 * Esconde botão de cancelar
 */
function hideCancelButton() {
    if (btnCancel) {
        btnCancel.hidden = true;
        btnCancel.style.display = 'none';
        console.log('[Chat] Botão de cancelar escondido');
    }
}


/**
 * Cancela o processamento atual
 */
function cancelProcessing() {
    if (!isCurrentConversationProcessing()) {
        console.log('[Chat] Nenhum processamento em andamento para cancelar');
        return;
    }

    if (!websocket || websocket.readyState !== WebSocket.OPEN) {
        console.error('[Chat] WebSocket não está conectado');
        return;
    }

    console.log('[Chat] Enviando solicitação de cancelamento...');

    // Enviar mensagem de cancelamento
    websocket.send(JSON.stringify({
        type: 'cancel'
    }));

    // Feedback visual imediato
    showTypingIndicator('Cancelando processamento...');
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
    btnCancel = document.getElementById('btn-cancel');
    typingIndicator = document.getElementById('typing-indicator');
    connectionStatus = document.getElementById('connection-status');

    // Garantir que modais e botão de cancelar estejam escondidos ao iniciar
    hideToolModal();
    hideTypingIndicator();
    hideCancelButton();

    // Event listener para botão de cancelar
    if (btnCancel) {
        btnCancel.addEventListener('click', cancelProcessing);
    }

    // Formulário de mensagem
    const messageForm = document.getElementById('message-form');
    if (messageForm) {
        messageForm.addEventListener('submit', (e) => {
            e.preventDefault();
            const content = messageInput.value.trim();
            // Permitir envio mesmo se outra conversa estiver processando (paralelo)
            if (content) {
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

    // -------------------------------------------------
    // Drag and Drop de arquivos na área de input
    // -------------------------------------------------
    const inputArea = document.querySelector('.input-area');

    if (inputArea) {
        // Prevenir comportamento padrão do navegador
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            inputArea.addEventListener(eventName, preventDefaults, false);
        });

        function preventDefaults(e) {
            e.preventDefault();
            e.stopPropagation();
        }

        // Highlight visual ao arrastar sobre a área
        ['dragenter', 'dragover'].forEach(eventName => {
            inputArea.addEventListener(eventName, () => {
                inputArea.classList.add('drag-over');
            }, false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            inputArea.addEventListener(eventName, () => {
                inputArea.classList.remove('drag-over');
            }, false);
        });

        // Handler do drop
        inputArea.addEventListener('drop', handleDrop, false);
    }

    // Toggle sidebar (mobile) com overlay
    const btnToggle = document.getElementById('btn-toggle-sidebar');
    const sidebar = document.getElementById('sidebar');
    const sidebarOverlay = document.getElementById('sidebar-overlay');

    if (btnToggle && sidebar) {
        btnToggle.addEventListener('click', () => {
            toggleSidebar();
        });
    }

    // Fechar sidebar ao clicar no overlay
    if (sidebarOverlay) {
        sidebarOverlay.addEventListener('click', () => {
            closeSidebarMobile();
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
 * Abre/fecha a sidebar no mobile
 */
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebar-overlay');

    if (sidebar && overlay) {
        const isOpen = sidebar.classList.toggle('open');
        if (isOpen) {
            overlay.classList.add('active');
        } else {
            overlay.classList.remove('active');
        }
        console.log('[Chat] Sidebar toggled:', isOpen ? 'aberta' : 'fechada');
    }
}


/**
 * Fecha a sidebar no mobile (se estiver aberta)
 */
function closeSidebarMobile() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebar-overlay');

    if (sidebar && overlay) {
        sidebar.classList.remove('open');
        overlay.classList.remove('active');
        console.log('[Chat] Sidebar fechada');
    }
}


/**
 * Handler para drag and drop de arquivos
 * @param {DragEvent} e - Evento de drop
 */
async function handleDrop(e) {
    const dt = e.dataTransfer;
    const files = dt.files;

    if (!files.length) return;

    console.log('[Chat] Arquivos arrastados:', files.length);

    // Mostrar preview container
    const filePreview = document.getElementById('file-preview');
    if (filePreview) {
        filePreview.hidden = false;
        filePreview.style.display = 'flex';
    }

    // Fazer upload de cada arquivo
    for (const file of files) {
        await uploadFile(file);
    }
}


/**
 * Handler para seleção de arquivos
 * Faz upload via API e exibe preview
 * @param {Event} e - Evento de change do input file
 */
async function handleFileSelect(e) {
    const files = e.target.files;
    if (!files.length) return;

    console.log('[Chat] Arquivos selecionados:', files.length);

    // Mostrar preview container
    const filePreview = document.getElementById('file-preview');
    if (filePreview) {
        filePreview.hidden = false;
        filePreview.style.display = 'flex';
    }

    // Fazer upload de cada arquivo
    for (const file of files) {
        await uploadFile(file);
    }

    // Limpar input para permitir re-selecionar mesmo arquivo
    e.target.value = '';
}


/**
 * Faz upload de um arquivo via API
 * @param {File} file - Arquivo a enviar
 */
async function uploadFile(file) {
    const token = Auth.getToken();
    if (!token) {
        console.error('[Chat] Sem token para upload');
        return;
    }

    // Criar FormData
    const formData = new FormData();
    formData.append('files', file);

    try {
        console.log('[Chat] Enviando arquivo:', file.name);

        const response = await fetch('/api/uploads/', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`
            },
            body: formData
        });

        if (!response.ok) {
            throw new Error(`Erro HTTP: ${response.status}`);
        }

        const data = await response.json();

        if (data.success && data.files.length > 0) {
            // Arquivo enviado com sucesso
            const uploadedFile = data.files[0];
            console.log('[Chat] Arquivo enviado:', uploadedFile.id, uploadedFile.original_name);

            // Adicionar ao array de arquivos pendentes
            pendingFiles.push(uploadedFile);

            // Atualizar preview
            renderFilePreview();
        } else if (data.errors && data.errors.length > 0) {
            // Erros no upload
            console.error('[Chat] Erros no upload:', data.errors);
            alert(`Erro ao enviar arquivo: ${data.errors.join(', ')}`);
        }

    } catch (error) {
        console.error('[Chat] Erro ao fazer upload:', error);
        alert(`Erro ao enviar arquivo: ${error.message}`);
    }
}


/**
 * Renderiza preview dos arquivos pendentes
 */
function renderFilePreview() {
    const filePreview = document.getElementById('file-preview');
    if (!filePreview) return;

    // Limpar preview anterior
    filePreview.innerHTML = '';

    if (pendingFiles.length === 0) {
        filePreview.hidden = true;
        filePreview.style.display = 'none';
        return;
    }

    // Mostrar preview
    filePreview.hidden = false;
    filePreview.style.display = 'flex';

    // Adicionar cada arquivo
    pendingFiles.forEach((file, index) => {
        const fileItem = document.createElement('div');
        fileItem.className = 'file-item';

        // Ícone baseado na extensão
        const icon = getFileIcon(file.extension);

        fileItem.innerHTML = `
            <span class="file-icon">${icon}</span>
            <span class="file-name" title="${file.original_name}">${file.original_name}</span>
            <button type="button" class="remove-file" data-index="${index}" title="Remover arquivo">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" width="16" height="16">
                    <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/>
                </svg>
            </button>
        `;

        // Event listener para remover
        const removeBtn = fileItem.querySelector('.remove-file');
        removeBtn.addEventListener('click', () => removeFile(index));

        filePreview.appendChild(fileItem);
    });
}


/**
 * Remove um arquivo da lista de pendentes
 * @param {number} index - Índice do arquivo a remover
 */
function removeFile(index) {
    console.log('[Chat] Removendo arquivo no índice:', index);

    // Remover do array
    pendingFiles.splice(index, 1);

    // Re-renderizar preview
    renderFilePreview();
}


/**
 * Retorna ícone apropriado para o tipo de arquivo
 * @param {string} extension - Extensão do arquivo
 * @returns {string} Emoji/ícone do arquivo
 */
function getFileIcon(extension) {
    const ext = extension.toLowerCase();

    // Imagens
    if (['.jpg', '.jpeg', '.png', '.gif', '.webp'].includes(ext)) {
        return '🖼️';
    }

    // PDFs
    if (ext === '.pdf') {
        return '📄';
    }

    // Word
    if (['.doc', '.docx'].includes(ext)) {
        return '📝';
    }

    // Código
    if (['.py', '.js', '.ts', '.html', '.css', '.java', '.c', '.cpp', '.go', '.rs'].includes(ext)) {
        return '💻';
    }

    // Texto
    if (['.txt', '.md', '.json', '.xml', '.yaml', '.yml', '.csv'].includes(ext)) {
        return '📃';
    }

    // Áudio
    if (['.mp3', '.wav', '.m4a', '.ogg', '.flac'].includes(ext)) {
        return '🎵';
    }

    // Vídeo
    if (['.mp4', '.webm', '.avi', '.mov'].includes(ext)) {
        return '🎬';
    }

    // Padrão
    return '📎';
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
    connectWebSocket,
    closeSidebarMobile
};

// Também disponibilizar closeSidebarMobile globalmente para uso em outros scripts
window.closeSidebarMobile = closeSidebarMobile;

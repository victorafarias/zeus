/**
 * =====================================================
 * ZEUS - Gerenciador de Conversas
 * CRUD de conversas e renderização na sidebar
 * =====================================================
 */

// Conversa atual
let currentConversation = null;

// Lista de conversas
let conversations = [];


/**
 * Carrega lista de conversas do servidor
 * @returns {Promise<Array>}
 */
async function loadConversations() {
    console.log('[Conversations] Carregando...');

    try {
        const response = await fetch('/api/conversations', {
            headers: Auth.withAuth()
        });

        if (!response.ok) {
            throw new Error('Erro ao carregar conversas');
        }

        const data = await response.json();
        conversations = data.conversations || [];

        console.log('[Conversations] Carregadas:', conversations.length);
        renderConversationsList();

        return conversations;

    } catch (error) {
        console.error('[Conversations] Erro:', error);
        return [];
    }
}


/**
 * Cria uma nova conversa
 * @param {string} title - Título (opcional)
 * @param {string} modelId - ID do modelo
 * @returns {Promise<object|null>}
 */
async function createConversation(title = 'Nova Conversa', modelId = null) {
    console.log('[Conversations] Criando...');

    try {
        const response = await fetch('/api/conversations', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                ...Auth.withAuth()
            },
            body: JSON.stringify({
                title,
                model_id: modelId || Models.getSelectedModel()
            })
        });

        if (!response.ok) {
            throw new Error('Erro ao criar conversa');
        }

        const conversation = await response.json();
        console.log('[Conversations] Criada:', conversation.id);

        // Adicionar no topo da lista
        conversations.unshift({
            id: conversation.id,
            title: conversation.title,
            model_id: conversation.model_id,
            message_count: 0,
            created_at: conversation.created_at,
            updated_at: conversation.updated_at
        });

        renderConversationsList();

        return conversation;

    } catch (error) {
        console.error('[Conversations] Erro ao criar:', error);
        return null;
    }
}


/**
 * Carrega uma conversa específica
 * @param {string} conversationId - ID da conversa
 * @returns {Promise<object|null>}
 */
async function loadConversation(conversationId) {
    console.log('[Conversations] Carregando conversa:', conversationId);

    try {
        const response = await fetch(`/api/conversations/${conversationId}`, {
            headers: Auth.withAuth()
        });

        if (!response.ok) {
            throw new Error('Conversa não encontrada');
        }

        const conversation = await response.json();
        currentConversation = conversation;

        // Atualizar modelo selecionado
        if (conversation.model_id) {
            Models.setSelectedModel(conversation.model_id);
        }

        // Marcar como ativa na lista
        highlightConversation(conversationId);

        return conversation;

    } catch (error) {
        console.error('[Conversations] Erro ao carregar:', error);
        return null;
    }
}


/**
 * Atualiza uma conversa
 * @param {string} conversationId - ID da conversa
 * @param {object} updates - Campos a atualizar
 * @returns {Promise<boolean>}
 */
async function updateConversation(conversationId, updates) {
    try {
        const response = await fetch(`/api/conversations/${conversationId}`, {
            method: 'PUT',
            headers: {
                'Content-Type': 'application/json',
                ...Auth.withAuth()
            },
            body: JSON.stringify(updates)
        });

        if (!response.ok) {
            throw new Error('Erro ao atualizar conversa');
        }

        // Atualizar na lista local
        const index = conversations.findIndex(c => c.id === conversationId);
        if (index >= 0) {
            conversations[index] = { ...conversations[index], ...updates };
            renderConversationsList();
        }

        return true;

    } catch (error) {
        console.error('[Conversations] Erro ao atualizar:', error);
        return false;
    }
}


/**
 * Remove uma conversa
 * @param {string} conversationId - ID da conversa
 * @returns {Promise<boolean>}
 */
async function deleteConversation(conversationId) {
    console.log('[Conversations] Removendo:', conversationId);

    try {
        const response = await fetch(`/api/conversations/${conversationId}`, {
            method: 'DELETE',
            headers: Auth.withAuth()
        });

        if (!response.ok) {
            throw new Error('Erro ao remover conversa');
        }

        // Remover da lista local
        conversations = conversations.filter(c => c.id !== conversationId);
        renderConversationsList();

        // Se era a conversa atual, limpar
        if (currentConversation && currentConversation.id === conversationId) {
            currentConversation = null;
            if (window.Chat) {
                Chat.clearMessages();
            }
        }

        return true;

    } catch (error) {
        console.error('[Conversations] Erro ao remover:', error);
        return false;
    }
}


/**
 * Renderiza lista de conversas na sidebar
 */
function renderConversationsList() {
    const list = document.getElementById('conversations-list');
    if (!list) return;

    // Limpar lista
    list.innerHTML = '';

    if (conversations.length === 0) {
        list.innerHTML = `
            <div class="empty-state" style="padding: 2rem; text-align: center; color: var(--color-text-muted);">
                <p>Nenhuma conversa ainda</p>
                <p style="font-size: 0.8rem;">Clique em "Nova Conversa" para começar</p>
            </div>
        `;
        return;
    }

    conversations.forEach(conv => {
        const item = document.createElement('div');
        item.className = 'conversation-item';
        item.dataset.id = conv.id;

        if (currentConversation && currentConversation.id === conv.id) {
            item.classList.add('active');
        }

        const date = formatDate(conv.updated_at);

        item.innerHTML = `
            <div class="icon">
                <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H6l-2 2V4h16v12z"/>
                </svg>
            </div>
            <div class="conversation-info">
                <div class="conversation-title">${escapeHtml(conv.title)}</div>
                <div class="conversation-date">${date}</div>
            </div>
            <div class="conversation-actions">
                <button class="btn-delete" title="Remover">
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/>
                    </svg>
                </button>
            </div>
        `;

        // Click para selecionar
        item.addEventListener('click', (e) => {
            if (!e.target.closest('.btn-delete')) {
                selectConversation(conv.id);
            }
        });

        // Click para deletar
        const btnDelete = item.querySelector('.btn-delete');
        btnDelete.addEventListener('click', (e) => {
            e.stopPropagation();
            if (confirm('Remover esta conversa?')) {
                deleteConversation(conv.id);
            }
        });

        list.appendChild(item);
    });

    // Restaurar loaders de conversas que estão processando
    // (O Chat.js gerencia o Map processingByConversation)
    if (window.restoreAllProcessingLoaders) {
        window.restoreAllProcessingLoaders();
    }
}


/**
 * Seleciona uma conversa
 * @param {string} conversationId - ID da conversa
 */
async function selectConversation(conversationId) {
    const conversation = await loadConversation(conversationId);

    if (conversation && window.Chat) {
        Chat.loadConversation(conversation);
    }
}


/**
 * Destaca conversa na lista
 * @param {string} conversationId - ID da conversa
 */
function highlightConversation(conversationId) {
    const items = document.querySelectorAll('.conversation-item');
    items.forEach(item => {
        if (item.dataset.id === conversationId) {
            item.classList.add('active');
        } else {
            item.classList.remove('active');
        }
    });
}


/**
 * Retorna a conversa atual
 * @returns {object|null}
 */
function getCurrentConversation() {
    return currentConversation;
}


/**
 * Define a conversa atual
 * @param {object} conversation - Conversa
 */
function setCurrentConversation(conversation) {
    currentConversation = conversation;
    if (conversation) {
        highlightConversation(conversation.id);
    }
}


/**
 * Formata data para exibição
 * @param {string} dateStr - Data ISO
 * @returns {string}
 */
function formatDate(dateStr) {
    const date = new Date(dateStr);
    const now = new Date();
    const diff = now - date;

    // Menos de 1 hora
    if (diff < 3600000) {
        const mins = Math.floor(diff / 60000);
        return mins <= 1 ? 'Agora' : `${mins} min`;
    }

    // Menos de 24 horas
    if (diff < 86400000) {
        const hours = Math.floor(diff / 3600000);
        return `${hours}h atrás`;
    }

    // Menos de 7 dias
    if (diff < 604800000) {
        const days = Math.floor(diff / 86400000);
        return days === 1 ? 'Ontem' : `${days} dias`;
    }

    // Data completa
    return date.toLocaleDateString('pt-BR');
}


/**
 * Escapa HTML para prevenir XSS
 * @param {string} str - String a escapar
 * @returns {string}
 */
function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}


/**
 * Filtra conversas por busca
 * @param {string} query - Termo de busca
 */
function filterConversations(query) {
    query = query.toLowerCase().trim();
    const items = document.querySelectorAll('.conversation-item');

    items.forEach(item => {
        const title = item.querySelector('.conversation-title').textContent.toLowerCase();
        if (title.includes(query) || !query) {
            item.style.display = '';
        } else {
            item.style.display = 'none';
        }
    });
}


/**
 * Inicializa o gerenciador de conversas
 */
function initConversations() {
    console.log('[Conversations] Inicializando...');

    // Carregar conversas
    loadConversations();

    // Botão nova conversa
    const btnNew = document.getElementById('btn-new-chat');
    if (btnNew) {
        btnNew.addEventListener('click', async () => {
            const conv = await createConversation();
            if (conv) {
                selectConversation(conv.id);
            }
            // Fechar sidebar no mobile após criar nova conversa
            closeSidebarMobile();
        });
    }

    // Busca
    const searchInput = document.getElementById('search-conversations');
    if (searchInput) {
        searchInput.addEventListener('input', (e) => {
            filterConversations(e.target.value);
        });
    }
}


// Inicializar quando DOM estiver pronto
document.addEventListener('DOMContentLoaded', function () {
    if (document.getElementById('conversations-list')) {
        initConversations();
    }
});


// Exportar funções
window.Conversations = {
    loadConversations,
    createConversation,
    loadConversation,
    updateConversation,
    deleteConversation,
    getCurrentConversation,
    setCurrentConversation,
    initConversations
};

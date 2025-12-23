/**
 * =====================================================
 * ZEUS - Gerenciador de Modelos
 * Carrega e gerencia seleção de modelos OpenRouter
 * Suporta 3 instâncias: primário, secundário e Mago
 * Usa dropdowns customizados com filtro integrado
 * =====================================================
 */

// Cache de modelos carregados do servidor
let modelsWithToolsCache = [];
let allModelsCache = [];

// Modelos selecionados para cada instância
// Esses valores serão usados como fallback na ordem: 1ª → 2ª → Mago
let selectedModels = {
    primary: 'openai/gpt-4.1-nano',    // 1ª Instância
    secondary: 'openai/gpt-4.1-nano',  // 2ª Instância  
    mago: 'openai/gpt-4.1-nano'        // Mago (modelo poderoso)
};

// Mapeamento de instância para chave
const INSTANCE_MAP = {
    1: 'primary',
    2: 'secondary',
    3: 'mago'
};

// Armazena listas de modelos globalmente para os filtros
let globalModelLists = { withTools: [], all: [] };


/**
 * Carrega lista de modelos do servidor
 * @param {boolean} toolsOnly - Se true, retorna apenas modelos com suporte a tools
 * @returns {Promise<Array>} Lista de modelos disponíveis
 */
async function loadModels(toolsOnly = true) {
    console.log(`[Models] Carregando modelos (tools_only=${toolsOnly})...`);

    try {
        const response = await fetch(`/api/models?tools_only=${toolsOnly}`, {
            headers: Auth.withAuth()
        });

        if (!response.ok) {
            throw new Error('Erro ao carregar modelos');
        }

        const data = await response.json();
        const models = data.models || [];

        console.log(`[Models] Modelos carregados (tools_only=${toolsOnly}):`, models.length);
        return models;

    } catch (error) {
        console.error('[Models] Erro ao carregar modelos:', error);
        return [];
    }
}


/**
 * Carrega ambas as listas de modelos (com tools e todos)
 * @returns {Promise<{withTools: Array, all: Array}>} Objeto com as duas listas
 */
async function loadAllModelLists() {
    console.log('[Models] Carregando listas de modelos...');

    const [withTools, all] = await Promise.all([
        loadModels(true),   // Apenas com tools (para 1ª e 2ª Instância)
        loadModels(false)   // Todos os modelos (para Mago)
    ]);

    modelsWithToolsCache = withTools;
    allModelsCache = all;
    globalModelLists = { withTools, all };

    console.log('[Models] Modelos com tools:', modelsWithToolsCache.length);
    console.log('[Models] Todos os modelos (Mago):', allModelsCache.length);

    return globalModelLists;
}


/**
 * Formata nome do provedor para exibição amigável
 */
function formatProviderName(provider) {
    const names = {
        'openai': 'OpenAI',
        'anthropic': 'Anthropic',
        'google': 'Google',
        'meta-llama': 'Meta Llama',
        'mistralai': 'Mistral AI',
        'cohere': 'Cohere',
        'deepseek': 'DeepSeek'
    };
    return names[provider] || provider.charAt(0).toUpperCase() + provider.slice(1);
}


/**
 * Formata nome do modelo para exibição
 */
function formatModelName(model) {
    let name = model.name || model.id.split('/')[1];
    if (model.context_length) {
        const ctx = Math.round(model.context_length / 1000);
        name += ` (${ctx}k)`;
    }
    return name;
}


/**
 * Renderiza opções no dropdown customizado
 * @param {HTMLElement} optionsContainer - Container das opções (.dropdown-options)
 * @param {Array} models - Lista de modelos
 * @param {string} selectedValue - Valor selecionado atualmente
 * @param {string} filterText - Texto de filtro
 * @param {Function} onSelect - Callback quando uma opção é selecionada
 */
function renderDropdownOptions(optionsContainer, models, selectedValue, filterText = '', onSelect) {
    if (!optionsContainer) return;

    optionsContainer.innerHTML = '';

    // Filtrar modelos
    let filteredModels = models;
    if (filterText.trim()) {
        const searchLower = filterText.toLowerCase();
        filteredModels = models.filter(model => {
            const modelName = (model.name || model.id).toLowerCase();
            return modelName.includes(searchLower);
        });
    }

    if (filteredModels.length === 0) {
        optionsContainer.innerHTML = '<div class="dropdown-no-results">Nenhum modelo encontrado</div>';
        return;
    }

    // Agrupar por provedor
    const providers = {};
    filteredModels.forEach(model => {
        const [provider] = model.id.split('/');
        if (!providers[provider]) {
            providers[provider] = [];
        }
        providers[provider].push(model);
    });

    // Renderizar grupos
    Object.entries(providers).forEach(([provider, providerModels]) => {
        // Header do grupo
        const groupHeader = document.createElement('div');
        groupHeader.className = 'dropdown-option-group';
        groupHeader.textContent = formatProviderName(provider);
        optionsContainer.appendChild(groupHeader);

        // Opções do grupo
        providerModels.forEach(model => {
            const option = document.createElement('div');
            option.className = 'dropdown-option';
            if (model.id === selectedValue) {
                option.classList.add('selected');
            }
            option.textContent = formatModelName(model);
            option.dataset.value = model.id;

            option.addEventListener('click', () => {
                onSelect(model.id, formatModelName(model));
            });

            optionsContainer.appendChild(option);
        });
    });
}


/**
 * Inicializa um dropdown customizado
 * @param {number} instance - Número da instância (1, 2, 3)
 * @param {string} prefix - Prefixo dos IDs ('', 'modal-')
 * @param {Array} models - Lista de modelos para este dropdown
 */
function initCustomDropdown(instance, prefix, models) {
    const key = INSTANCE_MAP[instance];
    const triggerId = `${prefix}trigger-${instance}`;
    const dropdownId = `${prefix}dropdown-${instance}`;
    const filterId = `${prefix}model-filter-${instance}`;
    const optionsId = `${prefix}options-${instance}`;

    const trigger = document.getElementById(triggerId);
    const dropdown = document.getElementById(dropdownId);
    const filter = document.getElementById(filterId);
    const optionsContainer = document.getElementById(optionsId);
    const wrapper = trigger?.closest('.custom-select-wrapper');

    if (!trigger || !dropdown || !optionsContainer) {
        console.log(`[Models] Dropdown ${instance} (${prefix}) não encontrado`);
        return;
    }

    // Atualizar texto do trigger com modelo selecionado
    const updateTriggerText = (text) => {
        const textSpan = trigger.querySelector('.selected-text');
        if (textSpan) textSpan.textContent = text;
    };

    // Encontrar nome do modelo selecionado
    const selectedModel = models.find(m => m.id === selectedModels[key]);
    if (selectedModel) {
        updateTriggerText(formatModelName(selectedModel));
    }

    // Callback de seleção
    const onSelect = (modelId, modelName) => {
        selectedModels[key] = modelId;
        updateTriggerText(modelName);

        // Fechar dropdown
        dropdown.hidden = true;
        wrapper?.classList.remove('open');

        // Limpar filtro
        if (filter) filter.value = '';

        // Salvar e emitir evento (apenas para dropdowns do header)
        if (!prefix) {
            saveModelsToStorage();
            window.dispatchEvent(new CustomEvent('modelsChanged', {
                detail: { instance, modelId, allModels: selectedModels }
            }));
        }

        console.log(`[Models] ${instance}ª Instância (${prefix || 'header'}) alterada para:`, modelId);
    };

    // Renderizar opções iniciais
    renderDropdownOptions(optionsContainer, models, selectedModels[key], '', onSelect);

    // Event: Abrir/fechar dropdown
    trigger.addEventListener('click', (e) => {
        e.stopPropagation();
        const isOpen = !dropdown.hidden;

        // Fechar todos os outros dropdowns primeiro
        document.querySelectorAll('.custom-select-dropdown').forEach(d => {
            d.hidden = true;
            d.closest('.custom-select-wrapper')?.classList.remove('open');
        });

        if (!isOpen) {
            dropdown.hidden = false;
            wrapper?.classList.add('open');
            filter?.focus();
            // Re-renderizar para garantir estado atualizado
            renderDropdownOptions(optionsContainer, models, selectedModels[key], filter?.value || '', onSelect);
        }
    });

    // Event: Filtrar modelos
    if (filter) {
        filter.addEventListener('input', (e) => {
            renderDropdownOptions(optionsContainer, models, selectedModels[key], e.target.value, onSelect);
        });

        // Prevenir fechamento ao clicar no filtro
        filter.addEventListener('click', (e) => e.stopPropagation());
    }
}


/**
 * Inicializa todos os dropdowns do header
 */
function initHeaderDropdowns(modelLists) {
    console.log('[Models] Inicializando dropdowns do header...');

    // 1ª e 2ª Instância: modelos com tools
    initCustomDropdown(1, '', modelLists.withTools);
    initCustomDropdown(2, '', modelLists.withTools);

    // Mago: todos os modelos
    initCustomDropdown(3, '', modelLists.all);
}


/**
 * Inicializa todos os dropdowns do modal
 */
function initModalDropdowns(modelLists) {
    console.log('[Models] Inicializando dropdowns do modal...');

    initCustomDropdown(1, 'modal-', modelLists.withTools);
    initCustomDropdown(2, 'modal-', modelLists.withTools);
    initCustomDropdown(3, 'modal-', modelLists.all);
}


/**
 * Handler para mudança de modelo
 */
function handleModelChange(instance, modelId) {
    const key = INSTANCE_MAP[instance];
    console.log(`[Models] ${instance}ª Instância alterada para:`, modelId);
    selectedModels[key] = modelId;
    saveModelsToStorage();
    window.dispatchEvent(new CustomEvent('modelsChanged', {
        detail: { instance, modelId, allModels: selectedModels }
    }));
}


/**
 * Salva modelos selecionados no localStorage
 */
function saveModelsToStorage() {
    localStorage.setItem('zeus_models', JSON.stringify(selectedModels));
    console.log('[Models] Modelos salvos no localStorage');
}


/**
 * Carrega modelos salvos do localStorage
 */
function loadModelsFromStorage() {
    const saved = localStorage.getItem('zeus_models');
    if (saved) {
        try {
            const parsed = JSON.parse(saved);
            if (parsed.primary) selectedModels.primary = parsed.primary;
            if (parsed.secondary) selectedModels.secondary = parsed.secondary;
            // Compatibilidade: aceitar 'tertiary' antigo
            if (parsed.mago) selectedModels.mago = parsed.mago;
            else if (parsed.tertiary) selectedModels.mago = parsed.tertiary;
            console.log('[Models] Modelos carregados do localStorage');
        } catch (error) {
            console.error('[Models] Erro ao carregar modelos salvos:', error);
        }
    }
}


/**
 * Retorna os modelos atualmente selecionados
 */
function getSelectedModels() {
    return {
        primary: selectedModels.primary,
        secondary: selectedModels.secondary,
        mago: selectedModels.mago
    };
}


/**
 * Retorna modelo de uma instância específica
 */
function getSelectedModel(instance = 1) {
    const key = INSTANCE_MAP[instance] || 'primary';
    return selectedModels[key];
}


/**
 * Define modelo para uma instância específica
 */
function setSelectedModel(modelId, instance = 1) {
    const key = INSTANCE_MAP[instance] || 'primary';
    selectedModels[key] = modelId;
    saveModelsToStorage();
}


/**
 * Inicializa o modal de seleção de modelos
 */
function initModelsModal(modelLists) {
    const modal = document.getElementById('models-modal');
    const btnOpen = document.getElementById('btn-open-models-modal');
    const btnClose = document.getElementById('btn-close-models-modal');
    const btnConfirm = document.getElementById('btn-confirm-models');

    if (!modal) {
        console.log('[Models] Modal não encontrado');
        return;
    }

    // Inicializar dropdowns do modal
    initModalDropdowns(modelLists);

    // Função para fechar o modal
    const closeModal = () => {
        modal.hidden = true;
        modal.style.display = 'none';
        console.log('[Models] Modal fechado');
    };

    // Event: Abrir modal
    if (btnOpen) {
        btnOpen.addEventListener('click', (e) => {
            e.stopPropagation();
            // Sincronizar valores antes de abrir
            syncModalWithState(modelLists);
            // Re-renderizar dropdowns do modal
            initModalDropdowns(modelLists);
            modal.hidden = false;
            modal.style.display = 'flex';
            console.log('[Models] Modal aberto');
        });
    }

    // Event: Fechar modal (botão X)
    if (btnClose) {
        btnClose.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            closeModal();
        });
        // Evento touch para mobile
        btnClose.addEventListener('touchend', (e) => {
            e.preventDefault();
            e.stopPropagation();
            closeModal();
        });
    }

    // Event: Fechar modal (clique no overlay)
    modal.addEventListener('click', (e) => {
        // Apenas fechar se clicar diretamente no overlay (não nos filhos)
        if (e.target === modal) {
            closeModal();
        }
    });

    // Event: Confirmar seleção
    if (btnConfirm) {
        btnConfirm.addEventListener('click', (e) => {
            e.stopPropagation();
            // Salvar no localStorage
            saveModelsToStorage();

            // Sincronizar com dropdowns do header
            syncHeaderWithState(modelLists);

            // Emitir evento de mudança
            window.dispatchEvent(new CustomEvent('modelsChanged', {
                detail: { instance: 'all', allModels: selectedModels }
            }));

            // Fechar modal
            closeModal();

            console.log('[Models] Modelos confirmados:', selectedModels);
        });
    }

    // Prevenir que cliques dentro do modal fechem ele
    const modalContent = modal.querySelector('.modal');
    if (modalContent) {
        modalContent.addEventListener('click', (e) => {
            e.stopPropagation();
        });
    }

    console.log('[Models] Modal inicializado');
}


/**
 * Sincroniza os dropdowns do modal com o estado atual
 */
function syncModalWithState(modelLists) {
    [1, 2, 3].forEach(instance => {
        const key = INSTANCE_MAP[instance];
        const triggerId = `modal-trigger-${instance}`;
        const trigger = document.getElementById(triggerId);
        if (trigger) {
            const models = instance === 3 ? modelLists.all : modelLists.withTools;
            const selectedModel = models.find(m => m.id === selectedModels[key]);
            const textSpan = trigger.querySelector('.selected-text');
            if (textSpan && selectedModel) {
                textSpan.textContent = formatModelName(selectedModel);
            }
        }
    });
}


/**
 * Sincroniza os dropdowns do header com o estado atual
 */
function syncHeaderWithState(modelLists) {
    [1, 2, 3].forEach(instance => {
        const key = INSTANCE_MAP[instance];
        const triggerId = `trigger-${instance}`;
        const trigger = document.getElementById(triggerId);
        if (trigger) {
            const models = instance === 3 ? modelLists.all : modelLists.withTools;
            const selectedModel = models.find(m => m.id === selectedModels[key]);
            const textSpan = trigger.querySelector('.selected-text');
            if (textSpan && selectedModel) {
                textSpan.textContent = formatModelName(selectedModel);
            }
        }
    });
}


/**
 * Inicializa o gerenciador de modelos
 */
async function initModels() {
    console.log('[Models] Inicializando gerenciador de modelos...');

    // Recuperar modelos salvos do localStorage
    loadModelsFromStorage();

    // Carregar listas de modelos do servidor
    const modelLists = await loadAllModelLists();

    // Inicializar dropdowns do header
    initHeaderDropdowns(modelLists);

    // Inicializar modal
    initModelsModal(modelLists);

    console.log('[Models] Inicialização concluída');
}


// Fechar dropdowns ao clicar fora (mas não dentro do modal)
document.addEventListener('click', (e) => {
    // Não fechar se clicar dentro do modal de modelos
    const modelsModal = document.getElementById('models-modal');
    if (modelsModal && modelsModal.contains(e.target)) {
        return;
    }

    document.querySelectorAll('.custom-select-dropdown').forEach(d => {
        d.hidden = true;
        d.closest('.custom-select-wrapper')?.classList.remove('open');
    });
});


// Inicializar quando DOM estiver pronto
document.addEventListener('DOMContentLoaded', function () {
    // Só inicializa se os elementos existirem na página
    if (document.getElementById('trigger-1') || document.getElementById('btn-open-models-modal')) {
        initModels();
    }
});


// Exportar funções para uso global
window.Models = {
    loadModels,
    getSelectedModels,
    getSelectedModel,
    setSelectedModel,
    initModels
};

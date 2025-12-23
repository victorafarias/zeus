/**
 * =====================================================
 * ZEUS - Gerenciador de Modelos
 * Carrega e gerencia seleção de modelos OpenRouter
 * Suporta 3 instâncias: primário, secundário e Mago
 * =====================================================
 */

// Cache de modelos carregados do servidor
// modelsWithTools: apenas modelos com suporte a function calling (para 1ª e 2ª Instância)
// allModels: todos os modelos disponíveis (para Mago)
let modelsWithToolsCache = [];
let allModelsCache = [];

// Modelos selecionados para cada instância
// Esses valores serão usados como fallback na ordem: 1ª → 2ª → Mago
let selectedModels = {
    primary: 'openai/gpt-4.1-nano',    // 1ª Instância
    secondary: 'openai/gpt-4.1-nano',  // 2ª Instância  
    mago: 'openai/gpt-4.1-nano'        // Mago (modelo poderoso)
};

// Referências aos elementos select
let modelSelects = {
    primary: null,
    secondary: null,
    mago: null
};

// Referências aos campos de filtro
let modelFilters = {
    primary: null,
    secondary: null,
    mago: null
};

// Mapeamento de instância para chave
const INSTANCE_MAP = {
    1: 'primary',
    2: 'secondary',
    3: 'mago'
};


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

    // Carregar em paralelo para melhor performance
    const [withTools, all] = await Promise.all([
        loadModels(true),   // Apenas com tools (para 1ª e 2ª Instância)
        loadModels(false)   // Todos os modelos (para Mago)
    ]);

    modelsWithToolsCache = withTools;
    allModelsCache = all;

    console.log('[Models] Modelos com tools:', modelsWithToolsCache.length);
    console.log('[Models] Todos os modelos (Mago):', allModelsCache.length);

    return {
        withTools: modelsWithToolsCache,
        all: allModelsCache
    };
}


/**
 * Formata nome do provedor para exibição amigável
 * @param {string} provider - Nome do provedor (ex: openai, anthropic)
 * @returns {string} Nome formatado para exibição
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
 * Inclui tamanho do contexto em K se disponível
 * @param {object} model - Objeto do modelo
 * @returns {string} Nome formatado com contexto
 */
function formatModelName(model) {
    let name = model.name || model.id.split('/')[1];

    // Adicionar indicador de contexto (ex: 128k)
    if (model.context_length) {
        const ctx = Math.round(model.context_length / 1000);
        name += ` (${ctx}k)`;
    }

    return name;
}


/**
 * Renderiza opções em um único seletor de modelo
 * @param {HTMLSelectElement} selectElement - Elemento select a popular
 * @param {Array} models - Lista de modelos
 * @param {string} selectedValue - Valor previamente selecionado
 * @param {string} filterText - Texto para filtrar modelos (opcional)
 */
function renderModelOptions(selectElement, models, selectedValue, filterText = '') {
    if (!selectElement) {
        return;
    }

    // Limpar opções existentes
    selectElement.innerHTML = '';

    // Filtrar modelos se houver texto de filtro
    let filteredModels = models;
    if (filterText.trim()) {
        const searchLower = filterText.toLowerCase();
        filteredModels = models.filter(model => {
            const modelName = (model.name || model.id).toLowerCase();
            return modelName.includes(searchLower);
        });

        // Garantir que o modelo selecionado esteja na lista, mesmo se não der match no filtro
        // Isso evita que o select mude valor "sozinho" visualmente
        if (selectedValue) {
            const isSelectedInList = filteredModels.some(m => m.id === selectedValue);
            if (!isSelectedInList) {
                // Buscar modelo completo na lista original
                const selectedModelObj = models.find(m => m.id === selectedValue);
                if (selectedModelObj) {
                    // Adicionar no início para destaque
                    filteredModels = [selectedModelObj, ...filteredModels];
                }
            }
        }
    }

    if (filteredModels.length === 0) {
        selectElement.innerHTML = '<option value="">Nenhum modelo encontrado</option>';
        return;
    }

    // Agrupar modelos por provedor para melhor organização
    const providers = {};
    filteredModels.forEach(model => {
        const [provider] = model.id.split('/');
        if (!providers[provider]) {
            providers[provider] = [];
        }
        providers[provider].push(model);
    });

    // Renderizar grupos de modelos (optgroup)
    Object.entries(providers).forEach(([provider, providerModels]) => {
        const optgroup = document.createElement('optgroup');
        optgroup.label = formatProviderName(provider);

        providerModels.forEach(model => {
            const option = document.createElement('option');
            option.value = model.id;
            option.textContent = formatModelName(model);

            // Marcar como selecionado se for o valor salvo
            if (model.id === selectedValue) {
                option.selected = true;
            }

            optgroup.appendChild(option);
        });

        selectElement.appendChild(optgroup);
    });
}


/**
 * Renderiza todos os três seletores de modelo com os modelos carregados
 * 1ª e 2ª Instância: apenas modelos com suporte a tools (function calling)
 * Mago: todos os modelos disponíveis
 * @param {Object} modelLists - Objeto com {withTools: Array, all: Array}
 */
function renderAllModelSelectors(modelLists) {
    console.log('[Models] Renderizando seletores...');
    console.log('[Models] 1ª Instância:', selectedModels.primary);
    console.log('[Models] 2ª Instância:', selectedModels.secondary);
    console.log('[Models] Mago:', selectedModels.mago);

    // Capturar referências aos elementos select
    modelSelects.primary = document.getElementById('model-select-1');
    modelSelects.secondary = document.getElementById('model-select-2');
    modelSelects.mago = document.getElementById('model-select-3');

    // Capturar referências aos campos de filtro
    modelFilters.primary = document.getElementById('model-filter-1');
    modelFilters.secondary = document.getElementById('model-filter-2');
    modelFilters.mago = document.getElementById('model-filter-3');

    // 1ª e 2ª Instância: apenas modelos com suporte a tools
    // (necessário para o agente funcionar corretamente com tool calling)
    renderModelOptions(modelSelects.primary, modelLists.withTools, selectedModels.primary);
    renderModelOptions(modelSelects.secondary, modelLists.withTools, selectedModels.secondary);

    // Mago: todos os modelos (modelo mais poderoso, usado em situações especiais)
    renderModelOptions(modelSelects.mago, modelLists.all, selectedModels.mago);

    // Adicionar event listeners para mudanças de seleção
    if (modelSelects.primary) {
        modelSelects.primary.addEventListener('change', (e) => handleModelChange(1, e.target.value));
    }
    if (modelSelects.secondary) {
        modelSelects.secondary.addEventListener('change', (e) => handleModelChange(2, e.target.value));
    }
    if (modelSelects.mago) {
        modelSelects.mago.addEventListener('change', (e) => handleModelChange(3, e.target.value));
    }

    // Adicionar event listeners para filtros
    setupModelFilters(modelLists);
}


/**
 * Configura os event listeners dos campos de filtro
 * @param {Object} modelLists - Listas de modelos {withTools, all}
 */
function setupModelFilters(modelLists) {
    // Filtro para 1ª Instância
    if (modelFilters.primary) {
        modelFilters.primary.addEventListener('input', (e) => {
            renderModelOptions(
                modelSelects.primary,
                modelLists.withTools,
                selectedModels.primary,
                e.target.value
            );
        });
    }

    // Filtro para 2ª Instância
    if (modelFilters.secondary) {
        modelFilters.secondary.addEventListener('input', (e) => {
            renderModelOptions(
                modelSelects.secondary,
                modelLists.withTools,
                selectedModels.secondary,
                e.target.value
            );
        });
    }

    // Filtro para Mago
    if (modelFilters.mago) {
        modelFilters.mago.addEventListener('input', (e) => {
            renderModelOptions(
                modelSelects.mago,
                modelLists.all,
                selectedModels.mago,
                e.target.value
            );
        });
    }
}


/**
 * Handler para mudança de modelo em qualquer instância
 * Salva seleção no localStorage e emite evento de mudança
 * @param {number} instance - Número da instância (1, 2 ou 3)
 * @param {string} modelId - ID do modelo selecionado
 */
function handleModelChange(instance, modelId) {
    const key = INSTANCE_MAP[instance];

    console.log(`[Models] ${instance}ª Instância alterada para:`, modelId);

    // Atualizar estado
    selectedModels[key] = modelId;

    // Salvar no localStorage
    saveModelsToStorage();

    // Emitir evento customizado para notificar outras partes do sistema
    window.dispatchEvent(new CustomEvent('modelsChanged', {
        detail: {
            instance: instance,
            modelId: modelId,
            allModels: selectedModels
        }
    }));
}


/**
 * Salva modelos selecionados no localStorage
 * Permite persistência entre sessões do navegador
 */
function saveModelsToStorage() {
    localStorage.setItem('zeus_models', JSON.stringify(selectedModels));
    console.log('[Models] Modelos salvos no localStorage');
}


/**
 * Carrega modelos salvos do localStorage
 * Restaura seleções anteriores do usuário
 */
function loadModelsFromStorage() {
    const saved = localStorage.getItem('zeus_models');

    if (saved) {
        try {
            const parsed = JSON.parse(saved);

            // Atualizar apenas as chaves existentes
            if (parsed.primary) {
                selectedModels.primary = parsed.primary;
            }
            if (parsed.secondary) {
                selectedModels.secondary = parsed.secondary;
            }
            // Compatibilidade: aceitar tanto 'tertiary' (antigo) quanto 'mago' (novo)
            if (parsed.mago) {
                selectedModels.mago = parsed.mago;
            } else if (parsed.tertiary) {
                selectedModels.mago = parsed.tertiary;
            }

            console.log('[Models] Modelos carregados do localStorage');
        } catch (error) {
            console.error('[Models] Erro ao carregar modelos salvos:', error);
        }
    }
}


/**
 * Retorna os modelos atualmente selecionados
 * Usado pelo chat.js para enviar ao backend
 * @returns {object} Objeto com primary, secondary e mago
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
 * Mantido para compatibilidade com código legado
 * @param {number} instance - Número da instância (1, 2 ou 3), padrão 1
 * @returns {string} ID do modelo selecionado
 */
function getSelectedModel(instance = 1) {
    const key = INSTANCE_MAP[instance] || 'primary';
    return selectedModels[key];
}


/**
 * Define modelo para uma instância específica
 * @param {string} modelId - ID do modelo
 * @param {number} instance - Número da instância (1, 2 ou 3), padrão 1
 */
function setSelectedModel(modelId, instance = 1) {
    const key = INSTANCE_MAP[instance] || 'primary';
    selectedModels[key] = modelId;

    // Atualizar UI se o select existir
    const select = modelSelects[key];
    if (select) {
        select.value = modelId;
    }

    saveModelsToStorage();
}


/**
 * Inicializa o gerenciador de modelos
 * Carrega modelos salvos e busca lista atualizada do servidor
 */
async function initModels() {
    console.log('[Models] Inicializando gerenciador de modelos...');

    // Recuperar modelos salvos do localStorage
    loadModelsFromStorage();

    // Carregar ambas as listas de modelos do servidor
    // - withTools: para 1ª e 2ª Instância (necessário para tool calling)
    // - all: para Mago (modelo poderoso)
    const modelLists = await loadAllModelLists();

    // Renderizar todos os seletores com as listas apropriadas
    renderAllModelSelectors(modelLists);

    console.log('[Models] Inicialização concluída');
}


// Inicializar quando DOM estiver pronto
document.addEventListener('DOMContentLoaded', function () {
    // Só inicializa se os seletores existirem na página
    if (document.getElementById('model-select-1')) {
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

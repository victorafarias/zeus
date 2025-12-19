/**
 * =====================================================
 * ZEUS - Gerenciador de Modelos
 * Carrega e gerencia seleção de modelos OpenRouter
 * =====================================================
 */

// Cache de modelos
let modelsCache = [];
let selectedModelId = 'openai/gpt-4';

// Elemento do seletor
let modelSelect = null;


/**
 * Carrega lista de modelos do servidor
 * @returns {Promise<Array>} Lista de modelos
 */
async function loadModels() {
    console.log('[Models] Carregando modelos...');

    try {
        const response = await fetch('/api/models?tools_only=true', {
            headers: Auth.withAuth()
        });

        if (!response.ok) {
            throw new Error('Erro ao carregar modelos');
        }

        const data = await response.json();
        modelsCache = data.models || [];

        console.log('[Models] Modelos carregados:', modelsCache.length);
        return modelsCache;

    } catch (error) {
        console.error('[Models] Erro:', error);
        return [];
    }
}


/**
 * Renderiza opções no select de modelos
 * @param {Array} models - Lista de modelos
 */
function renderModelOptions(models) {
    modelSelect = document.getElementById('model-select');
    if (!modelSelect) return;

    // Limpar opções
    modelSelect.innerHTML = '';

    if (models.length === 0) {
        modelSelect.innerHTML = '<option value="">Nenhum modelo disponível</option>';
        return;
    }

    // Agrupar por provedor
    const providers = {};
    models.forEach(model => {
        const [provider] = model.id.split('/');
        if (!providers[provider]) {
            providers[provider] = [];
        }
        providers[provider].push(model);
    });

    // Renderizar grupos
    Object.entries(providers).forEach(([provider, providerModels]) => {
        const optgroup = document.createElement('optgroup');
        optgroup.label = formatProviderName(provider);

        providerModels.forEach(model => {
            const option = document.createElement('option');
            option.value = model.id;
            option.textContent = formatModelName(model);

            // Selecionar modelo salvo ou padrão
            if (model.id === selectedModelId) {
                option.selected = true;
            }

            optgroup.appendChild(option);
        });

        modelSelect.appendChild(optgroup);
    });

    // Event listener para mudança
    modelSelect.addEventListener('change', handleModelChange);
}


/**
 * Formata nome do provedor para exibição
 * @param {string} provider - Nome do provedor
 * @returns {string} Nome formatado
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
 * @param {object} model - Objeto do modelo
 * @returns {string} Nome formatado
 */
function formatModelName(model) {
    let name = model.name || model.id.split('/')[1];

    // Adicionar indicador de contexto
    if (model.context_length) {
        const ctx = Math.round(model.context_length / 1000);
        name += ` (${ctx}k)`;
    }

    return name;
}


/**
 * Handler para mudança de modelo
 * @param {Event} e - Evento de change
 */
function handleModelChange(e) {
    selectedModelId = e.target.value;
    console.log('[Models] Modelo selecionado:', selectedModelId);

    // Salvar no localStorage
    localStorage.setItem('zeus_model', selectedModelId);

    // Emitir evento customizado
    window.dispatchEvent(new CustomEvent('modelChanged', {
        detail: { modelId: selectedModelId }
    }));
}


/**
 * Retorna o modelo atualmente selecionado
 * @returns {string} ID do modelo
 */
function getSelectedModel() {
    return selectedModelId;
}


/**
 * Define o modelo selecionado
 * @param {string} modelId - ID do modelo
 */
function setSelectedModel(modelId) {
    selectedModelId = modelId;

    if (modelSelect) {
        modelSelect.value = modelId;
    }

    localStorage.setItem('zeus_model', modelId);
}


/**
 * Inicializa o gerenciador de modelos
 */
async function initModels() {
    console.log('[Models] Inicializando...');

    // Recuperar modelo salvo
    const savedModel = localStorage.getItem('zeus_model');
    if (savedModel) {
        selectedModelId = savedModel;
    }

    // Carregar e renderizar
    const models = await loadModels();
    renderModelOptions(models);
}


// Inicializar quando DOM estiver pronto
document.addEventListener('DOMContentLoaded', function () {
    // Só inicializa na página de chat
    if (document.getElementById('model-select')) {
        initModels();
    }
});


// Exportar funções
window.Models = {
    loadModels,
    getSelectedModel,
    setSelectedModel,
    initModels
};

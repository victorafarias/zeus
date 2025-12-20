/**
 * =====================================================
 * ZEUS - Gerenciador de Modelos
 * Carrega e gerencia seleção de modelos OpenRouter
 * Suporta 3 instâncias: primário, secundário e terciário
 * =====================================================
 */

// Cache de modelos carregados do servidor
let modelsCache = [];

// Modelos selecionados para cada instância
// Esses valores serão usados como fallback na ordem: 1ª → 2ª → 3ª
let selectedModels = {
    primary: 'openai/gpt-4.1-nano',    // 1ª Instância
    secondary: 'openai/gpt-4.1-nano',  // 2ª Instância  
    tertiary: 'openai/gpt-4.1-nano'    // 3ª Instância
};

// Referências aos elementos select
let modelSelects = {
    primary: null,
    secondary: null,
    tertiary: null
};

// Mapeamento de instância para chave
const INSTANCE_MAP = {
    1: 'primary',
    2: 'secondary',
    3: 'tertiary'
};


/**
 * Carrega lista de modelos do servidor
 * Retorna apenas modelos que suportam tool calling
 * @returns {Promise<Array>} Lista de modelos disponíveis
 */
async function loadModels() {
    console.log('[Models] Carregando modelos do servidor...');

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
        console.error('[Models] Erro ao carregar modelos:', error);
        return [];
    }
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
 */
function renderModelOptions(selectElement, models, selectedValue) {
    if (!selectElement) {
        return;
    }

    // Limpar opções existentes
    selectElement.innerHTML = '';

    if (models.length === 0) {
        selectElement.innerHTML = '<option value="">Nenhum modelo disponível</option>';
        return;
    }

    // Agrupar modelos por provedor para melhor organização
    const providers = {};
    models.forEach(model => {
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
 * @param {Array} models - Lista de modelos disponíveis
 */
function renderAllModelSelectors(models) {
    console.log('[Models] Renderizando seletores...');
    console.log('[Models] 1ª Instância:', selectedModels.primary);
    console.log('[Models] 2ª Instância:', selectedModels.secondary);
    console.log('[Models] 3ª Instância:', selectedModels.tertiary);

    // Capturar referências aos elementos
    modelSelects.primary = document.getElementById('model-select-1');
    modelSelects.secondary = document.getElementById('model-select-2');
    modelSelects.tertiary = document.getElementById('model-select-3');

    // Renderizar cada seletor com seu valor salvo
    renderModelOptions(modelSelects.primary, models, selectedModels.primary);
    renderModelOptions(modelSelects.secondary, models, selectedModels.secondary);
    renderModelOptions(modelSelects.tertiary, models, selectedModels.tertiary);

    // Adicionar event listeners para mudanças
    if (modelSelects.primary) {
        modelSelects.primary.addEventListener('change', (e) => handleModelChange(1, e.target.value));
    }
    if (modelSelects.secondary) {
        modelSelects.secondary.addEventListener('change', (e) => handleModelChange(2, e.target.value));
    }
    if (modelSelects.tertiary) {
        modelSelects.tertiary.addEventListener('change', (e) => handleModelChange(3, e.target.value));
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
            if (parsed.tertiary) {
                selectedModels.tertiary = parsed.tertiary;
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
 * @returns {object} Objeto com primary, secondary e tertiary
 */
function getSelectedModels() {
    return {
        primary: selectedModels.primary,
        secondary: selectedModels.secondary,
        tertiary: selectedModels.tertiary
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

    // Carregar lista de modelos do servidor
    const models = await loadModels();
    
    // Renderizar todos os seletores
    renderAllModelSelectors(models);
    
    console.log('[Models] Inicialização concluída');
}


// Inicializar quando DOM estiver pronto
document.addEventListener('DOMContentLoaded', function() {
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

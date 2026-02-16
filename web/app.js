// ============================================
// PDF Translator - Application Logic
// 连接后端API进行真实翻译
// ============================================

// API基础地址
const API_BASE = '';  // 同源，不需要前缀

// Default prompts
const DEFAULT_SYSTEM_PROMPT = `你是一位精通法语和中文的专业翻译官。
你的任务是将输入的法语文本翻译为中文。
要求：
1. 保持翻译的学术性或文学性，语气灵动自然优雅，表达顺畅准确，确保语句结构完整，优先使用简洁句式，保证行文易懂，保证所有哲学学术术语的准确性，在你觉得重要的哲学学术术语后面加括号，在括号内标注原文并进行一到两句话的解释用于该文本的脚注。
2. 保留原有的格式（如标题、列表）。
3. 直接返回翻译后的中文内容，不要添加任何解释或说明。`;

const DEFAULT_INTEGRATION_PROMPT = `你是一位资深的翻译编辑和校对专家。你将收到同一段法语原文的多个翻译版本。

你的任务是：
1. 仔细比较各个翻译版本的优缺点
2. 综合各版本的优点，取长补短
3. 修正任何翻译错误、格式问题或残留的水印/页脚
4. 输出一个最优的中文翻译

要求：
- 保持学术性和文学性
- 确保术语准确一致
- 语句流畅自然
- 直接输出最终翻译，不要解释`;

const DEFAULT_EDITOR_PROMPT = `你是一位资深的翻译编辑，同时精通法语和中文，拥有丰富的出版编辑经验。

你将收到：
1. 法语原文
2. 用户自己的中文译文（初稿）
3. 多个 AI 模型的翻译版本

## 你的角色

### 角色1：翻译者
- 独立理解原文，判断各译文的准确性
- 识别翻译中的错误（漏译、误译、过译）

### 角色2：严厉的编辑
- 以出版标准审视译文质量
- 检查术语准确性、行文流畅度、风格一致性
- 给出具体的修改建议

## 输出格式

[评审意见]
对用户译文的简要评价：
- 优点：（1-2 句）
- 问题：（列出主要问题，如有）
- 参考：（说明从 AI 译文中借鉴了什么，如有）

[最终译文]
打磨后的最佳译文

## 编辑原则
1. 忠实原文：不得擅自增删内容
2. 尊重作者：保留用户译文的优秀表达
3. 取长补短：综合各版本优点
4. 精益求精：每个词语都要反复推敲
5. 术语一致：保持专业术语翻译的一致性`;

// State
const state = {
    pdfFile: null,
    fileId: null,
    pdfPath: null,
    totalPages: 0,
    startPage: 1,
    endPage: 10,
    currentPage: 1,
    zoom: 1.0,
    mode: 'flash',
    taskId: null,
    translatedContent: {},
    isTranslating: false,
    isFileLoaded: false,
    pollInterval: null,
    history: [],  // 翻译历史
    systemPrompt: DEFAULT_SYSTEM_PROMPT,
    integrationPrompt: DEFAULT_INTEGRATION_PROMPT,
    editorPrompt: DEFAULT_EDITOR_PROMPT,
    // Editor 模式状态
    editor: {
        pdfFile: null,
        pdfFileId: null,
        pdfPath: null,
        pdfTotalPages: 0,
        wordFile: null,
        wordFileId: null,
        wordPath: null,
        wordParagraphCount: 0,
        startPage: 1,
        endPage: 10,
        translationModels: ['x-ai/grok-4.1-fast', 'anthropic/claude-sonnet-4'],
        editorModel: 'anthropic/claude-sonnet-4',
        taskId: null,
        results: null,
        isReady: false
    }
};

// DOM Elements - will be initialized after DOM is ready
let elements = {};

// ============================================
// Theme Management
// ============================================

function setTheme(theme) {
    document.body.setAttribute('data-theme', theme);
    if (elements.themeButtons) {
        elements.themeButtons.forEach(btn => {
            btn.classList.toggle('active', btn.dataset.theme === theme);
        });
    }
    localStorage.setItem('pdf-translator-theme', theme);
}

// ============================================
// View Management
// ============================================

function showView(viewName) {
    if (elements.translateView) {
        elements.translateView.style.display = viewName === 'translate' ? 'flex' : 'none';
    }
    if (elements.compareView) {
        elements.compareView.style.display = viewName === 'compare' ? 'flex' : 'none';
    }
    if (elements.historyView) {
        elements.historyView.style.display = viewName === 'history' ? 'flex' : 'none';
    }
    
    if (elements.navItems) {
        elements.navItems.forEach(item => {
            item.classList.toggle('active', item.dataset.view === viewName);
        });
    }
    
    if (viewName === 'compare' && state.fileId) {
        renderCurrentPage();
    }
    
    if (viewName === 'history') {
        renderHistory();
    }
}

// ============================================
// File Handling
// ============================================

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

async function handleFile(file) {
    console.log('handleFile called with:', file?.name);
    
    if (!file || !file.name.toLowerCase().endsWith('.pdf')) {
        alert('请选择 PDF 文件');
        return;
    }
    
    // 显示上传中状态
    if (elements.uploadArea) {
        elements.uploadArea.innerHTML = `
            <div class="upload-icon spinning-icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M12 2v4m0 12v4M4.93 4.93l2.83 2.83m8.48 8.48l2.83 2.83M2 12h4m12 0h4M4.93 19.07l2.83-2.83m8.48-8.48l2.83-2.83"/>
                </svg>
            </div>
            <h3 class="upload-title">正在上传...</h3>
            <p class="upload-subtitle">请稍候</p>
        `;
    }
    
    try {
        // 上传文件到后端
        const formData = new FormData();
        formData.append('file', file);
        
        console.log('Uploading to:', `${API_BASE}/api/upload`);
        
        const response = await fetch(`${API_BASE}/api/upload`, {
            method: 'POST',
            body: formData
        });
        
        console.log('Response status:', response.status);
        
        if (!response.ok) {
            let errorMsg = '上传失败';
            try {
                const error = await response.json();
                errorMsg = error.error || errorMsg;
            } catch (e) {
                errorMsg = `HTTP ${response.status}`;
            }
            throw new Error(errorMsg);
        }
        
        const data = await response.json();
        console.log('Upload response:', data);
        
        state.pdfFile = file;
        state.fileId = data.file_id;
        state.pdfPath = data.path;
        state.totalPages = data.total_pages;
        state.startPage = 1;
        state.endPage = Math.min(10, state.totalPages);
        state.isFileLoaded = true;
        
        // Update UI
        if (elements.fileName) elements.fileName.textContent = file.name;
        if (elements.fileSize) elements.fileSize.textContent = formatFileSize(file.size);
        if (elements.totalPages) elements.totalPages.textContent = state.totalPages + ' 页';
        if (elements.startPage) {
            elements.startPage.value = 1;
            elements.startPage.max = state.totalPages;
        }
        if (elements.endPage) {
            elements.endPage.value = state.endPage;
            elements.endPage.max = state.totalPages;
        }
        updateRangeInfo();
        
        // Switch panels
        if (elements.uploadSection) elements.uploadSection.style.display = 'none';
        if (elements.configPanel) elements.configPanel.style.display = 'block';
        
        console.log('File uploaded successfully');
    } catch (error) {
        console.error('Error uploading file:', error);
        alert('上传失败: ' + error.message);
        
        // 恢复上传区域
        resetUploadArea();
        state.isFileLoaded = false;
    }
}

function resetUploadArea() {
    if (elements.uploadArea) {
        elements.uploadArea.innerHTML = `
            <div class="upload-icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1">
                    <path d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m6.75 12l-3-3m0 0l-3 3m3-3v6m-1.5-15H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"/>
                </svg>
            </div>
            <h3 class="upload-title">拖放 PDF 文件</h3>
            <p class="upload-subtitle">支持法语学术文献、哲学著作</p>
            <button class="upload-btn" id="selectFileBtn">选择文件</button>
        `;
        // 重新绑定事件
        const newSelectBtn = document.getElementById('selectFileBtn');
        if (newSelectBtn) {
            elements.selectFileBtn = newSelectBtn;
            newSelectBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                elements.fileInput?.click();
            });
        }
    }
}

function removeFile() {
    state.pdfFile = null;
    state.fileId = null;
    state.pdfPath = null;
    state.totalPages = 0;
    state.isFileLoaded = false;
    state.taskId = null;
    state.translatedContent = {};
    
    if (elements.fileInput) elements.fileInput.value = '';
    if (elements.configPanel) elements.configPanel.style.display = 'none';
    if (elements.uploadSection) elements.uploadSection.style.display = 'block';
    if (elements.resultPanel) elements.resultPanel.style.display = 'none';
    if (elements.progressPanel) elements.progressPanel.style.display = 'none';
    
    resetUploadArea();
}

function backToConfig() {
    if (elements.resultPanel) elements.resultPanel.style.display = 'none';
    if (elements.configPanel) elements.configPanel.style.display = 'block';
}

function updateRangeInfo() {
    const start = parseInt(elements.startPage?.value) || 1;
    const end = parseInt(elements.endPage?.value) || state.totalPages;
    const count = Math.max(0, end - start + 1);
    if (elements.rangeInfo) elements.rangeInfo.textContent = `共 ${count} 页`;
    state.startPage = start;
    state.endPage = end;
}

// ============================================
// Translation History
// ============================================

function loadHistory() {
    try {
        const saved = localStorage.getItem('pdf-translator-history');
        state.history = saved ? JSON.parse(saved) : [];
    } catch (e) {
        state.history = [];
    }
}

function saveHistory() {
    try {
        // 只保留最近20条
        const toSave = state.history.slice(0, 20);
        localStorage.setItem('pdf-translator-history', JSON.stringify(toSave));
    } catch (e) {
        console.error('Failed to save history:', e);
    }
}

function addToHistory(taskInfo) {
    const historyItem = {
        id: taskInfo.taskId,
        filename: taskInfo.filename,
        shortName: getShortName(taskInfo.filename),
        model: taskInfo.model,
        modelShort: getModelShortName(taskInfo.model),
        mode: taskInfo.mode,
        startPage: taskInfo.startPage,
        endPage: taskInfo.endPage,
        pageCount: taskInfo.endPage - taskInfo.startPage + 1,
        date: new Date().toISOString(),
        dateStr: formatDate(new Date()),
        results: taskInfo.results,
        fileId: taskInfo.fileId
    };
    
    // 生成显示名称: PDF简写_模型_类型_日期_页数
    historyItem.displayName = `${historyItem.shortName}_${historyItem.modelShort}_${historyItem.mode}_${historyItem.dateStr}_${historyItem.pageCount}页`;
    
    state.history.unshift(historyItem);
    saveHistory();
}

function getShortName(filename) {
    // 取文件名前10个字符作为简写
    const name = filename.replace('.pdf', '').replace('.PDF', '');
    if (name.length <= 10) return name;
    return name.substring(0, 10) + '...';
}

function getModelShortName(model) {
    // 提取模型简称
    const parts = model.split('/');
    const name = parts[parts.length - 1];
    // 常见模型简写
    if (name.includes('gemini-3')) return 'G3F';
    if (name.includes('gemini-2.5-pro')) return 'G25P';
    if (name.includes('gemini-2.5-flash')) return 'G25F';
    if (name.includes('gemini-2.0')) return 'G20F';
    if (name.includes('grok')) return 'Grok';
    if (name.includes('claude')) return 'Claude';
    if (name.includes('gpt')) return 'GPT';
    if (name.includes('deepseek')) return 'DS';
    return name.substring(0, 6);
}

function formatDate(date) {
    const m = (date.getMonth() + 1).toString().padStart(2, '0');
    const d = date.getDate().toString().padStart(2, '0');
    const h = date.getHours().toString().padStart(2, '0');
    const min = date.getMinutes().toString().padStart(2, '0');
    return `${m}${d}_${h}${min}`;
}

function renderHistory() {
    const container = document.getElementById('historyList');
    if (!container) return;
    
    if (state.history.length === 0) {
        container.innerHTML = `
            <div class="history-empty">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <path d="M12 6v6h4.5m4.5 0a9 9 0 11-18 0 9 9 0 0118 0z"/>
                </svg>
                <p>暂无翻译历史</p>
            </div>
        `;
        return;
    }
    
    container.innerHTML = state.history.map((item, index) => `
        <div class="history-item" data-index="${index}">
            <div class="history-icon">
                <svg viewBox="0 0 24 24" fill="currentColor">
                    <path d="M5.625 1.5c-1.036 0-1.875.84-1.875 1.875v17.25c0 1.035.84 1.875 1.875 1.875h12.75c1.035 0 1.875-.84 1.875-1.875V12.75A3.75 3.75 0 0016.5 9h-1.875a1.875 1.875 0 01-1.875-1.875V5.25A3.75 3.75 0 009 1.5H5.625z"/>
                </svg>
            </div>
            <div class="history-info">
                <div class="history-name">${item.displayName}</div>
                <div class="history-meta">
                    <span>${item.filename}</span>
                    <span class="sep">·</span>
                    <span>${new Date(item.date).toLocaleString('zh-CN')}</span>
                </div>
            </div>
            <div class="history-actions">
                <button class="history-btn view-btn" onclick="viewHistoryItem(${index})" title="查看对比">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M2.036 12.322a1.012 1.012 0 010-.639C3.423 7.51 7.36 4.5 12 4.5c4.638 0 8.573 3.007 9.963 7.178.07.207.07.431 0 .639C20.577 16.49 16.64 19.5 12 19.5c-4.638 0-8.573-3.007-9.963-7.178z"/>
                        <path d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/>
                    </svg>
                </button>
                <button class="history-btn download-btn" onclick="showDownloadMenu(event, ${index})" title="下载">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3"/>
                    </svg>
                </button>
                <button class="history-btn delete-btn" onclick="deleteHistoryItem(${index})" title="删除">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M14.74 9l-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 01-2.244 2.077H8.084a2.25 2.25 0 01-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 00-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 013.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 00-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 00-7.5 0"/>
                    </svg>
                </button>
            </div>
        </div>
    `).join('');
}

// 下载菜单
function showDownloadMenu(event, index) {
    event.stopPropagation();
    
    // 移除已有的菜单
    const existingMenu = document.querySelector('.download-menu');
    if (existingMenu) {
        existingMenu.remove();
    }
    
    const item = state.history[index];
    if (!item) return;
    
    const menu = document.createElement('div');
    menu.className = 'download-menu';
    menu.innerHTML = `
        <div class="download-menu-item" onclick="downloadHistoryTxt(${index})">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"/>
            </svg>
            <span>下载 TXT</span>
        </div>
        <div class="download-menu-item" onclick="downloadHistoryMd(${index}, false)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"/>
            </svg>
            <span>下载 MD (译文)</span>
        </div>
        <div class="download-menu-item" onclick="downloadHistoryMd(${index}, true)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M7.5 21L3 16.5m0 0L7.5 12M3 16.5h13.5m0-13.5L21 7.5m0 0L16.5 12M21 7.5H7.5"/>
            </svg>
            <span>下载 MD (双语)</span>
        </div>
        <div class="download-menu-item" onclick="downloadHistoryPdf(${index})">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m.75 12l3 3m0 0l3-3m-3 3v-6m-1.5-9H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z"/>
            </svg>
            <span>下载 PDF</span>
        </div>
    `;
    
    // 定位菜单
    const btn = event.currentTarget;
    const rect = btn.getBoundingClientRect();
    menu.style.position = 'fixed';
    menu.style.top = `${rect.bottom + 5}px`;
    menu.style.right = `${window.innerWidth - rect.right}px`;
    
    document.body.appendChild(menu);
    
    // 点击其他地方关闭菜单
    setTimeout(() => {
        document.addEventListener('click', closeDownloadMenu);
    }, 0);
}

function closeDownloadMenu() {
    const menu = document.querySelector('.download-menu');
    if (menu) {
        menu.remove();
    }
    document.removeEventListener('click', closeDownloadMenu);
}

async function downloadHistoryTxt(index) {
    closeDownloadMenu();
    const item = state.history[index];
    if (!item || !item.results) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/export/txt`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                results: item.results,
                filename: item.displayName
            })
        });
        
        if (!response.ok) throw new Error('导出失败');
        
        const data = await response.json();
        downloadFile(data.content, data.filename);
    } catch (error) {
        console.error('Export error:', error);
        alert('导出失败: ' + error.message);
    }
}

async function downloadHistoryMd(index, bilingual) {
    closeDownloadMenu();
    const item = state.history[index];
    if (!item || !item.results) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/export/md`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                results: item.results,
                filename: item.displayName,
                bilingual: bilingual
            })
        });
        
        if (!response.ok) throw new Error('导出失败');
        
        const data = await response.json();
        downloadFile(data.content, data.filename);
    } catch (error) {
        console.error('Export error:', error);
        alert('导出失败: ' + error.message);
    }
}

async function downloadHistoryPdf(index) {
    closeDownloadMenu();
    const item = state.history[index];
    if (!item || !item.results) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/export/pdf`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                results: item.results,
                filename: item.displayName
            })
        });
        
        if (!response.ok) {
            const err = await response.json();
            throw new Error(err.error || '导出失败');
        }
        
        const data = await response.json();
        
        // 下载base64编码的PDF
        const byteCharacters = atob(data.content);
        const byteNumbers = new Array(byteCharacters.length);
        for (let i = 0; i < byteCharacters.length; i++) {
            byteNumbers[i] = byteCharacters.charCodeAt(i);
        }
        const byteArray = new Uint8Array(byteNumbers);
        const blob = new Blob([byteArray], { type: 'application/pdf' });
        
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = data.filename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    } catch (error) {
        console.error('Export error:', error);
        alert('导出PDF失败: ' + error.message);
    }
}

function viewHistoryItem(index) {
    const item = state.history[index];
    if (!item) return;
    
    // 加载历史记录到当前状态
    state.translatedContent = item.results || {};
    state.startPage = item.startPage;
    state.endPage = item.endPage;
    state.currentPage = item.startPage;
    state.fileId = item.fileId;
    
    // 切换到对比视图
    showView('compare');
}

function deleteHistoryItem(index) {
    if (confirm('确定要删除这条历史记录吗？')) {
        state.history.splice(index, 1);
        saveHistory();
        renderHistory();
    }
}

// ============================================
// Prompt Management
// ============================================

function loadSavedPrompts() {
    try {
        const savedSystem = localStorage.getItem('pdf-translator-system-prompt');
        const savedIntegration = localStorage.getItem('pdf-translator-integration-prompt');
        
        if (savedSystem) state.systemPrompt = savedSystem;
        if (savedIntegration) state.integrationPrompt = savedIntegration;
    } catch (e) {
        console.log('Could not load saved prompts');
    }
}

function savePrompts() {
    try {
        localStorage.setItem('pdf-translator-system-prompt', state.systemPrompt);
        localStorage.setItem('pdf-translator-integration-prompt', state.integrationPrompt);
    } catch (e) {
        console.log('Could not save prompts');
    }
}

function initPromptEditors() {
    // System prompt (Flash mode)
    const systemPromptTextarea = document.getElementById('systemPrompt');
    const promptToggle = document.getElementById('promptToggle');
    const promptEditor = document.getElementById('promptEditor');
    const promptPreview = document.getElementById('promptPreview');
    const resetPrompt = document.getElementById('resetPrompt');
    const savePrompt = document.getElementById('savePrompt');
    
    if (systemPromptTextarea) {
        systemPromptTextarea.value = state.systemPrompt;
    }
    
    if (promptPreview) {
        const previewText = promptPreview.querySelector('.preview-text');
        if (previewText) {
            previewText.textContent = state.systemPrompt.substring(0, 100) + '...';
        }
    }
    
    if (promptToggle && promptEditor && promptPreview) {
        promptToggle.addEventListener('click', () => {
            const isExpanded = promptEditor.style.display !== 'none';
            promptEditor.style.display = isExpanded ? 'none' : 'block';
            promptPreview.style.display = isExpanded ? 'block' : 'none';
            promptToggle.classList.toggle('expanded', !isExpanded);
            promptToggle.querySelector('.toggle-text').textContent = isExpanded ? '展开编辑' : '收起';
        });
    }
    
    if (resetPrompt) {
        resetPrompt.addEventListener('click', () => {
            if (systemPromptTextarea) {
                systemPromptTextarea.value = DEFAULT_SYSTEM_PROMPT;
            }
        });
    }
    
    if (savePrompt) {
        savePrompt.addEventListener('click', () => {
            if (systemPromptTextarea) {
                state.systemPrompt = systemPromptTextarea.value;
                savePrompts();
                // Update preview
                if (promptPreview) {
                    const previewText = promptPreview.querySelector('.preview-text');
                    if (previewText) {
                        previewText.textContent = state.systemPrompt.substring(0, 100) + '...';
                    }
                }
                // Show feedback
                savePrompt.textContent = '已保存 ✓';
                setTimeout(() => { savePrompt.textContent = '保存'; }, 1500);
            }
        });
    }
    
    // Integration prompt (High Quality mode)
    const integrationPromptTextarea = document.getElementById('integrationPrompt');
    const integrationPromptToggle = document.getElementById('integrationPromptToggle');
    const integrationPromptEditor = document.getElementById('integrationPromptEditor');
    const integrationPromptPreview = document.getElementById('integrationPromptPreview');
    const resetIntegrationPrompt = document.getElementById('resetIntegrationPrompt');
    const saveIntegrationPrompt = document.getElementById('saveIntegrationPrompt');
    
    if (integrationPromptTextarea) {
        integrationPromptTextarea.value = state.integrationPrompt;
    }
    
    if (integrationPromptPreview) {
        const previewText = integrationPromptPreview.querySelector('.preview-text');
        if (previewText) {
            previewText.textContent = state.integrationPrompt.substring(0, 100) + '...';
        }
    }
    
    if (integrationPromptToggle && integrationPromptEditor && integrationPromptPreview) {
        integrationPromptToggle.addEventListener('click', () => {
            const isExpanded = integrationPromptEditor.style.display !== 'none';
            integrationPromptEditor.style.display = isExpanded ? 'none' : 'block';
            integrationPromptPreview.style.display = isExpanded ? 'block' : 'none';
            integrationPromptToggle.classList.toggle('expanded', !isExpanded);
            integrationPromptToggle.querySelector('.toggle-text').textContent = isExpanded ? '展开编辑' : '收起';
        });
    }
    
    if (resetIntegrationPrompt) {
        resetIntegrationPrompt.addEventListener('click', () => {
            if (integrationPromptTextarea) {
                integrationPromptTextarea.value = DEFAULT_INTEGRATION_PROMPT;
            }
        });
    }
    
    if (saveIntegrationPrompt) {
        saveIntegrationPrompt.addEventListener('click', () => {
            if (integrationPromptTextarea) {
                state.integrationPrompt = integrationPromptTextarea.value;
                savePrompts();
                // Update preview
                if (integrationPromptPreview) {
                    const previewText = integrationPromptPreview.querySelector('.preview-text');
                    if (previewText) {
                        previewText.textContent = state.integrationPrompt.substring(0, 100) + '...';
                    }
                }
                // Show feedback
                saveIntegrationPrompt.textContent = '已保存 ✓';
                setTimeout(() => { saveIntegrationPrompt.textContent = '保存'; }, 1500);
            }
        });
    }
}

// ============================================
// Translation - Real API
// ============================================

async function startTranslation() {
    if (!state.pdfPath || state.isTranslating) return;
    
    state.isTranslating = true;
    if (elements.configPanel) elements.configPanel.style.display = 'none';
    if (elements.progressPanel) elements.progressPanel.style.display = 'block';
    
    const start = parseInt(elements.startPage?.value) || 1;
    const end = parseInt(elements.endPage?.value) || state.totalPages;
    state.startPage = start;
    state.endPage = end;
    
    if (elements.progressPages) elements.progressPages.textContent = `第 ${start} - ${end} 页`;
    
    // 重置进度
    if (elements.progressPercent) elements.progressPercent.textContent = '0';
    if (elements.completedCount) elements.completedCount.textContent = '0';
    if (elements.totalCount) elements.totalCount.textContent = '...';
    if (elements.progressRing) {
        elements.progressRing.style.strokeDashoffset = 339.292;
    }
    
    try {
        // 获取配置
        const model = elements.modelSelect?.value || 'x-ai/grok-4.1-fast';
        const workers = parseInt(elements.workers?.value) || 5;
        
        // 获取当前提示词（从textarea获取最新值）
        const systemPromptEl = document.getElementById('systemPrompt');
        if (systemPromptEl && systemPromptEl.value) {
            state.systemPrompt = systemPromptEl.value;
        }
        
        // 构建请求体
        const requestBody = {
            pdf_path: state.pdfPath,
            start_page: start,
            end_page: end,
            model: model,
            workers: workers,
            system_prompt: state.systemPrompt
        };
        
        // 如果是高质量模式，添加多模型配置
        if (state.mode === 'high') {
            // 获取整合提示词
            const integrationPromptEl = document.getElementById('integrationPrompt');
            if (integrationPromptEl && integrationPromptEl.value) {
                state.integrationPrompt = integrationPromptEl.value;
            }
            
            // 获取每个模型的独立配置（模型+提示词）
            const modelConfigs = getMultiModelConfigs();
            
            requestBody.multi_model = true;
            requestBody.translation_models = modelConfigs.map(c => c.model);
            requestBody.model_prompts = modelConfigs.map(c => c.prompt);  // 每个模型的独立提示词
            requestBody.integration_model = getIntegrationModel();
            requestBody.integration_prompt = state.integrationPrompt;
        }
        
        // 调用后端API开始翻译
        const response = await fetch(`${API_BASE}/api/translate`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(requestBody)
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || '启动翻译失败');
        }
        
        const data = await response.json();
        state.taskId = data.task_id;
        state.currentModel = model;
        state.translationModels = state.mode === 'high' ? getSelectedMultiModels() : [model];
        state.integrationModel = state.mode === 'high' ? getIntegrationModel() : null;
        console.log('Translation started, task_id:', state.taskId);
        
        // 开始轮询进度
        pollTranslationProgress();
        
    } catch (error) {
        console.error('Translation error:', error);
        alert('翻译启动失败: ' + error.message);
        state.isTranslating = false;
        if (elements.progressPanel) elements.progressPanel.style.display = 'none';
        if (elements.configPanel) elements.configPanel.style.display = 'block';
    }
}

function pollTranslationProgress() {
    if (state.pollInterval) {
        clearInterval(state.pollInterval);
    }
    
    const startTime = Date.now();
    
    state.pollInterval = setInterval(async () => {
        try {
            const response = await fetch(`${API_BASE}/api/task/${state.taskId}`);
            if (!response.ok) {
                throw new Error('获取进度失败');
            }
            
            const task = await response.json();
            console.log('Task status:', task);
            
            // 更新进度UI
            const progress = task.progress || 0;
            
            if (elements.progressRing) {
                const circumference = 2 * Math.PI * 54;
                const offset = circumference - (progress / 100) * circumference;
                elements.progressRing.style.strokeDashoffset = offset;
                elements.progressRing.style.stroke = 'var(--accent)';
            }
            
            if (elements.progressPercent) elements.progressPercent.textContent = progress;
            if (elements.completedCount) elements.completedCount.textContent = task.completed_segments || 0;
            if (elements.totalCount) elements.totalCount.textContent = task.total_segments || '...';
            if (elements.currentTask) {
                elements.currentTask.textContent = task.current_page 
                    ? `正在翻译第 ${task.current_page} 页...` 
                    : '处理中...';
            }
            
            // 估算剩余时间
            if (task.completed_segments > 0 && task.total_segments > 0) {
                const elapsed = (Date.now() - startTime) / 1000;
                const rate = task.completed_segments / elapsed;
                const remaining = Math.round((task.total_segments - task.completed_segments) / rate);
                if (elements.estimatedTime) {
                    elements.estimatedTime.textContent = remaining > 60 
                        ? Math.round(remaining / 60) + ' 分钟'
                        : remaining + ' 秒';
                }
            }
            
            // 检查是否完成
            if (task.status === 'completed') {
                clearInterval(state.pollInterval);
                state.pollInterval = null;
                await onTranslationComplete();
            } else if (task.status === 'error') {
                clearInterval(state.pollInterval);
                state.pollInterval = null;
                throw new Error(task.error || '翻译出错');
            }
            
        } catch (error) {
            console.error('Poll error:', error);
            clearInterval(state.pollInterval);
            state.pollInterval = null;
            alert('翻译过程出错: ' + error.message);
            state.isTranslating = false;
            if (elements.progressPanel) elements.progressPanel.style.display = 'none';
            if (elements.configPanel) elements.configPanel.style.display = 'block';
        }
    }, 1000);
}

async function onTranslationComplete() {
    try {
        // 获取翻译结果
        const response = await fetch(`${API_BASE}/api/task/${state.taskId}/results`);
        if (!response.ok) {
            throw new Error('获取结果失败');
        }
        
        state.translatedContent = await response.json();
        console.log('Translation results:', state.translatedContent);
        
        // 计算统计
        let totalSegments = 0;
        for (const page in state.translatedContent) {
            totalSegments += state.translatedContent[page].translated?.length || 0;
        }
        
        // 添加到历史记录
        addToHistory({
            taskId: state.taskId,
            filename: state.pdfFile?.name || 'unknown.pdf',
            model: state.currentModel || 'unknown',
            mode: state.mode,
            startPage: state.startPage,
            endPage: state.endPage,
            results: state.translatedContent,
            fileId: state.fileId
        });
        
        // 显示结果
        state.isTranslating = false;
        if (elements.progressPanel) elements.progressPanel.style.display = 'none';
        if (elements.resultPanel) elements.resultPanel.style.display = 'block';
        if (elements.resultSummary) {
            elements.resultSummary.textContent = `已翻译 ${state.endPage - state.startPage + 1} 页，共 ${totalSegments} 个段落`;
        }
        
    } catch (error) {
        console.error('Error getting results:', error);
        alert('获取结果失败: ' + error.message);
    }
}

// ============================================
// Compare View - Real PDF Rendering
// ============================================

async function renderCurrentPage() {
    if (!state.fileId) {
        console.log('No file loaded');
        return;
    }
    
    try {
        // 从后端获取PDF页面图片
        const response = await fetch(`${API_BASE}/api/pdf/${state.fileId}/page/${state.currentPage}`);
        if (!response.ok) {
            throw new Error('获取页面失败');
        }
        
        const data = await response.json();
        
        // 显示PDF图片
        const pdfContainer = document.getElementById('pdfContainer');
        if (pdfContainer) {
            pdfContainer.innerHTML = `<img src="${data.image}" alt="Page ${state.currentPage}" style="max-width: 100%; height: auto; box-shadow: 0 4px 24px var(--shadow); transform: scale(${state.zoom}); transform-origin: top center;">`;
        }
        
        // Update navigation
        if (elements.currentPageEl) elements.currentPageEl.textContent = state.currentPage;
        if (elements.totalPagesNav) elements.totalPagesNav.textContent = state.endPage;
        
        // Render translation
        renderTranslation();
        
    } catch (error) {
        console.error('Error rendering page:', error);
        const pdfContainer = document.getElementById('pdfContainer');
        if (pdfContainer) {
            pdfContainer.innerHTML = `<div style="padding: 40px; text-align: center; color: var(--text-muted);">加载页面失败</div>`;
        }
    }
}

function renderTranslation() {
    const pageData = state.translatedContent[state.currentPage];
    
    if (!elements.translationContent) return;
    
    if (!pageData || !pageData.translated || pageData.translated.length === 0) {
        elements.translationContent.innerHTML = `
            <div style="text-align: center; padding: 60px 20px; color: var(--text-muted);">
                <p>此页暂无翻译内容</p>
                <p style="font-size: 13px; margin-top: 8px;">请先完成翻译</p>
            </div>
        `;
        return;
    }
    
    let html = `<div class="page-marker">第 ${state.currentPage} 页</div>`;
    
    pageData.translated.forEach((text) => {
        html += `<p>${text}</p>`;
    });
    
    elements.translationContent.innerHTML = html;
}

function navigatePage(delta) {
    const newPage = state.currentPage + delta;
    if (newPage >= state.startPage && newPage <= state.endPage) {
        state.currentPage = newPage;
        renderCurrentPage();
    }
}

function setZoom(delta) {
    const newZoom = Math.max(0.5, Math.min(2.0, state.zoom + delta));
    if (newZoom !== state.zoom) {
        state.zoom = newZoom;
        if (elements.zoomLevel) elements.zoomLevel.textContent = Math.round(state.zoom * 100) + '%';
        // 对于图片，通过CSS缩放
        const pdfContainer = document.getElementById('pdfContainer');
        if (pdfContainer) {
            const img = pdfContainer.querySelector('img');
            if (img) {
                img.style.transform = `scale(${state.zoom})`;
                img.style.transformOrigin = 'top center';
            }
        }
    }
}

// ============================================
// Download Functions
// ============================================

function downloadTranslated() {
    let content = '';
    
    for (let page = state.startPage; page <= state.endPage; page++) {
        content += `\n========== 第 ${page} 页 ==========\n\n`;
        const pageData = state.translatedContent[page];
        if (pageData && pageData.translated) {
            pageData.translated.forEach(text => {
                content += text + '\n\n';
            });
        }
    }
    
    downloadFile(content, `${state.pdfFile?.name?.replace('.pdf', '') || 'translation'}_translated.txt`);
}

function downloadBilingual() {
    let content = '双语对照版本\n\n';
    
    for (let page = state.startPage; page <= state.endPage; page++) {
        content += `\n========== 第 ${page} 页 ==========\n\n`;
        const pageData = state.translatedContent[page];
        if (pageData && pageData.original && pageData.translated) {
            const maxLen = Math.max(pageData.original.length, pageData.translated.length);
            for (let i = 0; i < maxLen; i++) {
                if (pageData.original[i]) {
                    content += `[原文 ${i + 1}]\n${pageData.original[i]}\n\n`;
                }
                if (pageData.translated[i]) {
                    content += `[译文 ${i + 1}]\n${pageData.translated[i]}\n\n`;
                }
                content += '---\n\n';
            }
        }
    }
    
    downloadFile(content, `${state.pdfFile?.name?.replace('.pdf', '') || 'translation'}_bilingual.txt`);
}

function downloadFile(content, filename) {
    const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

// ============================================
// Event Listeners
// ============================================

function initEventListeners() {
    // Theme
    if (elements.themeButtons) {
        elements.themeButtons.forEach(btn => {
            btn.addEventListener('click', () => setTheme(btn.dataset.theme));
        });
    }
    
    // Navigation
    if (elements.navItems) {
        elements.navItems.forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                showView(item.dataset.view);
            });
        });
    }
    
    // Mode switcher
    if (elements.modeButtons) {
        elements.modeButtons.forEach(btn => {
            btn.addEventListener('click', () => {
                elements.modeButtons.forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                state.mode = btn.dataset.mode;
                
                // 切换配置显示
                const flashConfig = document.getElementById('flashConfig');
                const editorUploadSection = document.getElementById('editorUploadSection');
                const uploadSection = document.getElementById('uploadSection');
                const configPanel = document.getElementById('configPanel');
                const editorConfigPanel = document.getElementById('editorConfigPanel');
                
                if (state.mode === 'editor') {
                    // Editor 模式：显示双文件上传
                    if (uploadSection) uploadSection.style.display = 'none';
                    if (configPanel) configPanel.style.display = 'none';
                    if (editorUploadSection) editorUploadSection.style.display = state.editor.isReady ? 'none' : 'block';
                    if (editorConfigPanel) editorConfigPanel.style.display = state.editor.isReady ? 'block' : 'none';
                    if (flashConfig) flashConfig.style.display = 'none';
                    if (elements.multiModelConfig) elements.multiModelConfig.style.display = 'none';
                } else {
                    // Flash/High 模式
                    if (editorUploadSection) editorUploadSection.style.display = 'none';
                    if (editorConfigPanel) editorConfigPanel.style.display = 'none';
                    
                    // 根据文件加载状态显示
                    if (state.isFileLoaded) {
                        if (uploadSection) uploadSection.style.display = 'none';
                        if (configPanel) configPanel.style.display = 'block';
                    } else {
                        if (uploadSection) uploadSection.style.display = 'block';
                        if (configPanel) configPanel.style.display = 'none';
                    }
                    
                    if (flashConfig) {
                        flashConfig.style.display = state.mode === 'flash' ? 'flex' : 'none';
                    }
                    if (elements.multiModelConfig) {
                        elements.multiModelConfig.style.display = state.mode === 'high' ? 'block' : 'none';
                    }
                }
            });
        });
    }
    
    // File upload - prevent event bubbling
    if (elements.selectFileBtn) {
        elements.selectFileBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            elements.fileInput?.click();
        });
    }
    
    if (elements.uploadArea) {
        elements.uploadArea.addEventListener('click', (e) => {
            // 点击上传区域任意位置都触发文件选择
            if (!e.target.closest('button')) {
                elements.fileInput?.click();
            }
        });
    }
    
    if (elements.fileInput) {
        elements.fileInput.addEventListener('change', (e) => {
            console.log('File input changed');
            const file = e.target.files[0];
            if (file) {
                handleFile(file);
            }
        });
    }
    
    // Drag and drop
    if (elements.uploadArea) {
        elements.uploadArea.addEventListener('dragover', (e) => {
            e.preventDefault();
            e.stopPropagation();
            elements.uploadArea.classList.add('dragover');
        });
        
        elements.uploadArea.addEventListener('dragleave', (e) => {
            e.preventDefault();
            e.stopPropagation();
            elements.uploadArea.classList.remove('dragover');
        });
        
        elements.uploadArea.addEventListener('drop', (e) => {
            e.preventDefault();
            e.stopPropagation();
            elements.uploadArea.classList.remove('dragover');
            const file = e.dataTransfer.files[0];
            if (file) {
                handleFile(file);
            }
        });
    }
    
    // Config
    if (elements.removeFile) {
        elements.removeFile.addEventListener('click', removeFile);
    }
    if (elements.startPage) {
        elements.startPage.addEventListener('input', updateRangeInfo);
    }
    if (elements.endPage) {
        elements.endPage.addEventListener('input', updateRangeInfo);
    }
    if (elements.startBtn) {
        elements.startBtn.addEventListener('click', startTranslation);
    }
    
    // Result actions
    if (elements.viewCompare) {
        elements.viewCompare.addEventListener('click', () => {
            state.currentPage = state.startPage;
            showView('compare');
        });
    }
    if (elements.downloadTranslated) {
        elements.downloadTranslated.addEventListener('click', downloadTranslated);
    }
    if (elements.downloadBilingual) {
        elements.downloadBilingual.addEventListener('click', downloadBilingual);
    }
    if (elements.backToConfig) {
        elements.backToConfig.addEventListener('click', backToConfig);
    }
    
    // Compare view
    if (elements.backToTranslate) {
        elements.backToTranslate.addEventListener('click', () => showView('translate'));
    }
    if (elements.prevPage) {
        elements.prevPage.addEventListener('click', () => navigatePage(-1));
    }
    if (elements.nextPage) {
        elements.nextPage.addEventListener('click', () => navigatePage(1));
    }
    if (elements.zoomOut) {
        elements.zoomOut.addEventListener('click', () => setZoom(-0.1));
    }
    if (elements.zoomIn) {
        elements.zoomIn.addEventListener('click', () => setZoom(0.1));
    }
    
    // Keyboard navigation
    document.addEventListener('keydown', (e) => {
        if (elements.compareView && elements.compareView.style.display !== 'none') {
            if (e.key === 'ArrowLeft') navigatePage(-1);
            if (e.key === 'ArrowRight') navigatePage(1);
            if (e.key === '+' || e.key === '=') setZoom(0.1);
            if (e.key === '-') setZoom(-0.1);
        }
    });
    
    // Multi-model add button
    const addModelBtn = document.getElementById('addModelBtn');
    if (addModelBtn) {
        addModelBtn.addEventListener('click', () => addMultiModel());
    }
    
    // Resizable divider
    initResizableDivider();
}

function initResizableDivider() {
    const divider = document.getElementById('compareDivider');
    const container = document.querySelector('.compare-container');
    const leftPanel = document.querySelector('.compare-panel.original');
    const rightPanel = document.querySelector('.compare-panel.translation');
    
    if (!divider || !container || !leftPanel || !rightPanel) return;
    
    let isResizing = false;
    
    divider.addEventListener('mousedown', () => {
        isResizing = true;
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';
    });
    
    document.addEventListener('mousemove', (e) => {
        if (!isResizing) return;
        
        const containerRect = container.getBoundingClientRect();
        const percentage = ((e.clientX - containerRect.left) / containerRect.width) * 100;
        
        if (percentage > 20 && percentage < 80) {
            leftPanel.style.flex = `0 0 ${percentage}%`;
            rightPanel.style.flex = `0 0 ${100 - percentage}%`;
        }
    });
    
    document.addEventListener('mouseup', () => {
        isResizing = false;
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
    });
}

// ============================================
// Initialize DOM Elements
// ============================================

function initElements() {
    elements = {
        // Views
        translateView: document.getElementById('translateView'),
        compareView: document.getElementById('compareView'),
        historyView: document.getElementById('historyView'),
        
        // Upload
        uploadSection: document.getElementById('uploadSection'),
        uploadArea: document.getElementById('uploadArea'),
        fileInput: document.getElementById('fileInput'),
        selectFileBtn: document.getElementById('selectFileBtn'),
        
        // Config
        configPanel: document.getElementById('configPanel'),
        fileName: document.getElementById('fileName'),
        fileSize: document.getElementById('fileSize'),
        totalPages: document.getElementById('totalPages'),
        removeFile: document.getElementById('removeFile'),
        startPage: document.getElementById('startPage'),
        endPage: document.getElementById('endPage'),
        rangeInfo: document.getElementById('rangeInfo'),
        modelSelect: document.getElementById('modelSelect'),
        workers: document.getElementById('workers'),
        startBtn: document.getElementById('startBtn'),
        
        // Progress
        progressPanel: document.getElementById('progressPanel'),
        progressRing: document.getElementById('progressRing'),
        progressPercent: document.getElementById('progressPercent'),
        currentTask: document.getElementById('currentTask'),
        completedCount: document.getElementById('completedCount'),
        totalCount: document.getElementById('totalCount'),
        estimatedTime: document.getElementById('estimatedTime'),
        progressPages: document.getElementById('progressPages'),
        
        // Result
        resultPanel: document.getElementById('resultPanel'),
        resultSummary: document.getElementById('resultSummary'),
        viewCompare: document.getElementById('viewCompare'),
        downloadTranslated: document.getElementById('downloadTranslated'),
        downloadBilingual: document.getElementById('downloadBilingual'),
        backToConfig: document.getElementById('backToConfig'),
        
        // Compare View
        backToTranslate: document.getElementById('backToTranslate'),
        prevPage: document.getElementById('prevPage'),
        nextPage: document.getElementById('nextPage'),
        currentPageEl: document.getElementById('currentPage'),
        totalPagesNav: document.getElementById('totalPagesNav'),
        zoomOut: document.getElementById('zoomOut'),
        zoomIn: document.getElementById('zoomIn'),
        zoomLevel: document.getElementById('zoomLevel'),
        pdfCanvas: document.getElementById('pdfCanvas'),
        translationContent: document.getElementById('translationContent'),
        
        // Navigation
        navItems: document.querySelectorAll('.nav-item'),
        modeButtons: document.querySelectorAll('.mode-btn'),
        themeButtons: document.querySelectorAll('.theme-btn'),
        multiModelConfig: document.getElementById('multiModelConfig')
    };
}

// ============================================
// Load Available Models
// ============================================

let availableModels = [];
let volcengineModels = [];
let deepseekModels = [];
let customModels = [];
let allModels = [];  // 所有模型的合并列表

async function loadModels() {
    try {
        const response = await fetch(`${API_BASE}/api/models`);
        if (response.ok) {
            const data = await response.json();
            availableModels = data.models || [];
            volcengineModels = data.volcengine_models || [];
            deepseekModels = data.deepseek_models || [];
            customModels = data.custom_models || [];
            
            // 合并所有模型
            allModels = [
                ...availableModels,
                ...volcengineModels,
                ...deepseekModels,
                ...customModels
            ];
            
            // 更新主模型选择器
            if (elements.modelSelect && availableModels.length > 0) {
                elements.modelSelect.innerHTML = buildModelOptions(allModels);
            }
            
            // 更新整合模型选择器
            const integrationSelect = document.getElementById('integrationModel');
            if (integrationSelect && availableModels.length > 0) {
                integrationSelect.innerHTML = buildModelOptions(allModels);
            }
            
            // 初始化多模型列表（默认3个）
            initMultiModelList();
            
            // 初始化 Editor 模型列表
            initEditorModelList();
        }
    } catch (error) {
        console.log('Could not load models from server, using defaults');
    }
}

// 构建模型选项（分组显示）
function buildModelOptions(models, selectedId = null) {
    let html = '';
    
    // 按 provider 分组
    const groups = {};
    models.forEach(m => {
        const provider = m.provider || 'other';
        if (!groups[provider]) groups[provider] = [];
        groups[provider].push(m);
    });
    
    // 提供商显示名称
    const providerNames = {
        'openrouter': 'OpenRouter',
        'volcengine': '火山引擎 (豆包)',
        'deepseek': 'DeepSeek',
        'custom': '自定义模型',
        'other': '其他'
    };
    
    // 按顺序输出分组
    const order = ['openrouter', 'volcengine', 'deepseek', 'custom', 'other'];
    for (const provider of order) {
        if (groups[provider] && groups[provider].length > 0) {
            html += `<optgroup label="${providerNames[provider] || provider}">`;
            groups[provider].forEach(m => {
                const selected = selectedId === m.id ? 'selected' : '';
                const dataAttrs = m.base_url ? `data-base-url="${m.base_url}"` : '';
                html += `<option value="${m.id}" ${selected} ${dataAttrs}>${m.name}</option>`;
            });
            html += `</optgroup>`;
        }
    }
    
    return html;
}

// 添加自定义模型 - 显示模态框
function addCustomModel() {
    showCustomModelModal();
}

// 显示自定义模型配置模态框
function showCustomModelModal() {
    // 如果已存在，先移除
    const existing = document.getElementById('customModelModal');
    if (existing) existing.remove();
    
    const modal = document.createElement('div');
    modal.id = 'customModelModal';
    modal.className = 'modal-overlay';
    modal.innerHTML = `
        <div class="modal-content custom-model-modal">
            <div class="modal-header">
                <h3>添加自定义模型</h3>
                <button class="modal-close" onclick="closeCustomModelModal()">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20">
                        <path d="M6 18L18 6M6 6l12 12"/>
                    </svg>
                </button>
            </div>
            <div class="modal-body">
                <div class="form-group">
                    <label>模型名称 <span class="required">*</span></label>
                    <input type="text" id="customModelName" placeholder="如: doubao-1.5-pro-256k, deepseek-chat">
                    <p class="hint">API 调用时使用的模型名称</p>
                </div>
                <div class="form-group">
                    <label>显示名称</label>
                    <input type="text" id="customModelDisplayName" placeholder="如: 豆包 1.5 Pro">
                    <p class="hint">在下拉菜单中显示的名称（可选）</p>
                </div>
                <div class="form-group">
                    <label>API Base URL <span class="required">*</span></label>
                    <input type="text" id="customModelBaseUrl" placeholder="如: https://ark.cn-beijing.volces.com/api/v3">
                    <p class="hint">模型 API 的基础地址</p>
                </div>
                <div class="form-group">
                    <label>API Key</label>
                    <input type="password" id="customModelApiKey" placeholder="留空则使用默认 API Key">
                    <p class="hint">该模型专用的 API Key（可选）</p>
                </div>
                
                <div class="preset-configs">
                    <p class="preset-title">快速填充：</p>
                    <div class="preset-buttons">
                        <button type="button" class="preset-btn" onclick="fillPreset('volcengine')">
                            🌋 火山引擎
                        </button>
                        <button type="button" class="preset-btn" onclick="fillPreset('deepseek')">
                            🔍 DeepSeek
                        </button>
                        <button type="button" class="preset-btn" onclick="fillPreset('moonshot')">
                            🌙 Moonshot
                        </button>
                        <button type="button" class="preset-btn" onclick="fillPreset('zhipu')">
                            🧠 智谱AI
                        </button>
                    </div>
                </div>
            </div>
            <div class="modal-footer">
                <button type="button" class="btn-secondary" onclick="closeCustomModelModal()">取消</button>
                <button type="button" class="btn-primary" onclick="saveCustomModel()">添加模型</button>
            </div>
        </div>
    `;
    
    document.body.appendChild(modal);
    
    // 点击背景关闭
    modal.addEventListener('click', (e) => {
        if (e.target === modal) closeCustomModelModal();
    });
}

// 关闭模态框
function closeCustomModelModal() {
    const modal = document.getElementById('customModelModal');
    if (modal) modal.remove();
}

// 快速填充预设配置
function fillPreset(provider) {
    const presets = {
        volcengine: {
            baseUrl: 'https://ark.cn-beijing.volces.com/api/v3',
            modelName: 'doubao-1.5-pro-256k',
            displayName: '豆包 1.5 Pro 256K'
        },
        deepseek: {
            baseUrl: 'https://api.deepseek.com/v1',
            modelName: 'deepseek-chat',
            displayName: 'DeepSeek Chat'
        },
        moonshot: {
            baseUrl: 'https://api.moonshot.cn/v1',
            modelName: 'moonshot-v1-128k',
            displayName: 'Moonshot 128K'
        },
        zhipu: {
            baseUrl: 'https://open.bigmodel.cn/api/paas/v4',
            modelName: 'glm-4-flash',
            displayName: '智谱 GLM-4 Flash'
        }
    };
    
    const preset = presets[provider];
    if (preset) {
        document.getElementById('customModelName').value = preset.modelName;
        document.getElementById('customModelDisplayName').value = preset.displayName;
        document.getElementById('customModelBaseUrl').value = preset.baseUrl;
    }
}

// 保存自定义模型
async function saveCustomModel() {
    const modelName = document.getElementById('customModelName').value.trim();
    const displayName = document.getElementById('customModelDisplayName').value.trim();
    const baseUrl = document.getElementById('customModelBaseUrl').value.trim();
    const apiKey = document.getElementById('customModelApiKey').value.trim();
    
    if (!modelName) {
        alert('请输入模型名称');
        return;
    }
    if (!baseUrl) {
        alert('请输入 API Base URL');
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/api/models/custom`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                model: modelName,
                id: modelName,
                name: displayName || modelName,
                base_url: baseUrl,
                api_key: apiKey,
                provider: 'custom'
            })
        });
        
        if (response.ok) {
            closeCustomModelModal();
            await loadModels();  // 重新加载模型列表
            alert('自定义模型添加成功！');
        } else {
            const error = await response.json();
            alert('添加失败: ' + (error.error || '未知错误'));
        }
    } catch (error) {
        alert('添加失败: ' + error.message);
    }
}

// 多模型管理
let multiModelCount = 0;

function initMultiModelList() {
    const container = document.getElementById('multiModelList');
    if (!container) return;
    
    container.innerHTML = '';
    multiModelCount = 0;
    
    // 默认添加3个模型
    addMultiModel();
    addMultiModel();
    addMultiModel();
}

function addMultiModel(defaultValue = null, defaultPrompt = null) {
    const container = document.getElementById('multiModelList');
    if (!container) return;
    
    multiModelCount++;
    const index = multiModelCount;
    
    const item = document.createElement('div');
    item.className = 'multi-model-item';
    item.dataset.index = index;
    
    const options = buildModelOptions(allModels.length > 0 ? allModels : availableModels, defaultValue);
    
    const promptValue = defaultPrompt || DEFAULT_SYSTEM_PROMPT;
    const promptPreview = promptValue.substring(0, 60) + '...';
    
    item.innerHTML = `
        <div class="model-row">
            <span class="model-number">${index}</span>
            <select class="model-select" data-model-index="${index}">
                ${options}
            </select>
            <button type="button" class="prompt-edit-btn" onclick="toggleModelPrompt(${index})" title="编辑提示词">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                    <path d="M16.862 4.487l1.687-1.688a1.875 1.875 0 112.652 2.652L10.582 16.07a4.5 4.5 0 01-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 011.13-1.897l8.932-8.931zm0 0L19.5 7.125"/>
                </svg>
            </button>
            <button type="button" class="remove-model-btn" onclick="removeMultiModel(${index})" title="移除">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <path d="M6 18L18 6M6 6l12 12"/>
                </svg>
            </button>
        </div>
        <div class="model-prompt-section" id="modelPrompt_${index}" style="display: none;">
            <div class="model-prompt-preview">${promptPreview}</div>
            <textarea class="model-prompt-textarea" data-prompt-index="${index}" rows="6" placeholder="输入该模型的提示词...">${promptValue}</textarea>
            <div class="model-prompt-actions">
                <button type="button" class="prompt-btn reset" onclick="resetModelPrompt(${index})">恢复默认</button>
                <button type="button" class="prompt-btn save" onclick="saveModelPrompt(${index})">确定</button>
            </div>
        </div>
    `;
    
    container.appendChild(item);
    updateModelNumbers();
}

function toggleModelPrompt(index) {
    const promptSection = document.getElementById(`modelPrompt_${index}`);
    if (promptSection) {
        const isHidden = promptSection.style.display === 'none';
        promptSection.style.display = isHidden ? 'block' : 'none';
    }
}

function resetModelPrompt(index) {
    const textarea = document.querySelector(`textarea[data-prompt-index="${index}"]`);
    if (textarea) {
        textarea.value = DEFAULT_SYSTEM_PROMPT;
    }
}

function saveModelPrompt(index) {
    const promptSection = document.getElementById(`modelPrompt_${index}`);
    const textarea = document.querySelector(`textarea[data-prompt-index="${index}"]`);
    const preview = promptSection?.querySelector('.model-prompt-preview');
    
    if (textarea && preview) {
        preview.textContent = textarea.value.substring(0, 60) + '...';
    }
    
    if (promptSection) {
        promptSection.style.display = 'none';
    }
}

function removeMultiModel(index) {
    const container = document.getElementById('multiModelList');
    if (!container) return;
    
    const items = container.querySelectorAll('.multi-model-item');
    if (items.length <= 2) {
        alert('至少需要保留2个翻译模型');
        return;
    }
    
    const item = container.querySelector(`.multi-model-item[data-index="${index}"]`);
    if (item) {
        item.remove();
        updateModelNumbers();
    }
}

function updateModelNumbers() {
    const container = document.getElementById('multiModelList');
    if (!container) return;
    
    const items = container.querySelectorAll('.multi-model-item');
    items.forEach((item, i) => {
        const numberSpan = item.querySelector('.model-number');
        if (numberSpan) {
            numberSpan.textContent = i + 1;
        }
    });
}

function getSelectedMultiModels() {
    const container = document.getElementById('multiModelList');
    if (!container) return [];
    
    const selects = container.querySelectorAll('.model-select');
    return Array.from(selects).map(select => select.value);
}

function getMultiModelConfigs() {
    const container = document.getElementById('multiModelList');
    if (!container) return [];
    
    const items = container.querySelectorAll('.multi-model-item');
    return Array.from(items).map(item => {
        const select = item.querySelector('.model-select');
        const textarea = item.querySelector('.model-prompt-textarea');
        return {
            model: select ? select.value : '',
            prompt: textarea ? textarea.value : DEFAULT_SYSTEM_PROMPT
        };
    });
}

function getIntegrationModel() {
    const select = document.getElementById('integrationModel');
    return select ? select.value : 'x-ai/grok-4.1-fast';
}

// ============================================
// Initialize
// ============================================

function init() {
    console.log('Initializing PDF Translator...');
    
    // Initialize DOM elements
    initElements();
    
    // Load saved theme
    const savedTheme = localStorage.getItem('pdf-translator-theme') || 'dark';
    setTheme(savedTheme);
    
    // Load saved prompts
    loadSavedPrompts();
    
    // Load history
    loadHistory();
    
    // Add gradient definition for progress ring
    const svg = document.querySelector('.progress-ring');
    if (svg) {
        const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');
        defs.innerHTML = `
            <linearGradient id="progressGradient" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" style="stop-color:var(--gradient-start)"/>
                <stop offset="100%" style="stop-color:var(--gradient-end)"/>
            </linearGradient>
        `;
        svg.insertBefore(defs, svg.firstChild);
    }
    
    initEventListeners();
    loadModels();
    initPromptEditors();
    
    console.log('PDF Translator initialized');
}

// ============================================
// Editor Mode Functions
// ============================================

function initEditorMode() {
    console.log('Initializing Editor Mode...');
    
    // Editor PDF 上传
    const editorPdfInput = document.getElementById('editorPdfInput');
    const selectEditorPdfBtn = document.getElementById('selectEditorPdfBtn');
    const pdfUploadArea = document.getElementById('pdfUploadArea');
    
    console.log('Editor elements:', {
        editorPdfInput: !!editorPdfInput,
        selectEditorPdfBtn: !!selectEditorPdfBtn,
        pdfUploadArea: !!pdfUploadArea
    });
    
    if (selectEditorPdfBtn) {
        selectEditorPdfBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            console.log('Select PDF button clicked');
            if (editorPdfInput) {
                editorPdfInput.click();
            }
        });
    }
    
    if (pdfUploadArea) {
        pdfUploadArea.addEventListener('click', (e) => {
            if (!e.target.closest('button')) {
                console.log('PDF upload area clicked');
                if (editorPdfInput) {
                    editorPdfInput.click();
                }
            }
        });
    }
    
    if (editorPdfInput) {
        editorPdfInput.addEventListener('change', (e) => {
            console.log('PDF input changed');
            const file = e.target.files[0];
            if (file) handleEditorPdfUpload(file);
        });
    }
    
    // Editor Word 上传
    const editorWordInput = document.getElementById('editorWordInput');
    const selectEditorWordBtn = document.getElementById('selectEditorWordBtn');
    const wordUploadArea = document.getElementById('wordUploadArea');
    
    console.log('Word elements:', {
        editorWordInput: !!editorWordInput,
        selectEditorWordBtn: !!selectEditorWordBtn,
        wordUploadArea: !!wordUploadArea
    });
    
    if (selectEditorWordBtn) {
        selectEditorWordBtn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            console.log('Select Word button clicked');
            if (editorWordInput) {
                editorWordInput.click();
            }
        });
    }
    
    if (wordUploadArea) {
        wordUploadArea.addEventListener('click', (e) => {
            if (!e.target.closest('button')) {
                console.log('Word upload area clicked');
                if (editorWordInput) {
                    editorWordInput.click();
                }
            }
        });
    }
    
    if (editorWordInput) {
        editorWordInput.addEventListener('change', (e) => {
            console.log('Word input changed');
            const file = e.target.files[0];
            if (file) handleEditorWordUpload(file);
        });
    }
    
    // 移除文件按钮
    const removeEditorFiles = document.getElementById('removeEditorFiles');
    if (removeEditorFiles) {
        removeEditorFiles.addEventListener('click', resetEditorMode);
    }
    
    // 开始编辑按钮
    const startEditorBtn = document.getElementById('startEditorBtn');
    if (startEditorBtn) {
        startEditorBtn.addEventListener('click', startEditorTask);
    }
    
    // 添加模型按钮
    const addEditorModelBtn = document.getElementById('addEditorModelBtn');
    if (addEditorModelBtn) {
        addEditorModelBtn.addEventListener('click', addEditorModel);
    }
    
    // 页面范围
    const editorStartPage = document.getElementById('editorStartPage');
    const editorEndPage = document.getElementById('editorEndPage');
    if (editorStartPage) {
        editorStartPage.addEventListener('input', updateEditorRangeInfo);
    }
    if (editorEndPage) {
        editorEndPage.addEventListener('input', updateEditorRangeInfo);
    }
    
    // 提示词编辑
    const editorPromptToggle = document.getElementById('editorPromptToggle');
    if (editorPromptToggle) {
        editorPromptToggle.addEventListener('click', () => {
            const editor = document.getElementById('editorPromptEditor');
            const preview = document.getElementById('editorPromptPreview');
            if (editor && preview) {
                const isHidden = editor.style.display === 'none';
                editor.style.display = isHidden ? 'block' : 'none';
                preview.style.display = isHidden ? 'none' : 'block';
            }
        });
    }
    
    const resetEditorPrompt = document.getElementById('resetEditorPrompt');
    if (resetEditorPrompt) {
        resetEditorPrompt.addEventListener('click', () => {
            const textarea = document.getElementById('editorPrompt');
            if (textarea) {
                textarea.value = DEFAULT_EDITOR_PROMPT;
            }
        });
    }
    
    const saveEditorPrompt = document.getElementById('saveEditorPrompt');
    if (saveEditorPrompt) {
        saveEditorPrompt.addEventListener('click', () => {
            const editor = document.getElementById('editorPromptEditor');
            const preview = document.getElementById('editorPromptPreview');
            const textarea = document.getElementById('editorPrompt');
            if (editor && preview && textarea) {
                editor.style.display = 'none';
                preview.style.display = 'block';
                const previewText = preview.querySelector('.preview-text');
                if (previewText) {
                    previewText.textContent = textarea.value.substring(0, 50) + '...';
                }
            }
        });
    }
    
    // 初始化编辑模型列表
    initEditorModelList();
    
    // 加载默认提示词
    const editorPromptTextarea = document.getElementById('editorPrompt');
    if (editorPromptTextarea) {
        editorPromptTextarea.value = DEFAULT_EDITOR_PROMPT;
    }
}

async function handleEditorPdfUpload(file) {
    if (!file.name.toLowerCase().endsWith('.pdf')) {
        alert('请选择 PDF 文件');
        return;
    }
    
    const statusEl = document.getElementById('pdfUploadStatus');
    if (statusEl) statusEl.innerHTML = '<span class="uploading">上传中...</span>';
    
    try {
        const formData = new FormData();
        formData.append('file', file);
        
        const response = await fetch(`${API_BASE}/api/upload`, {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || '上传失败');
        }
        
        const data = await response.json();
        
        state.editor.pdfFile = file;
        state.editor.pdfFileId = data.file_id;
        state.editor.pdfPath = data.path;
        state.editor.pdfTotalPages = data.total_pages;
        state.editor.endPage = Math.min(10, data.total_pages);
        
        if (statusEl) statusEl.innerHTML = `<span class="success">✓ ${file.name} (${data.total_pages}页)</span>`;
        
        // 更新页面范围
        const startPageEl = document.getElementById('editorStartPage');
        const endPageEl = document.getElementById('editorEndPage');
        if (startPageEl) startPageEl.max = data.total_pages;
        if (endPageEl) {
            endPageEl.max = data.total_pages;
            endPageEl.value = Math.min(10, data.total_pages);
        }
        
        checkEditorReady();
    } catch (error) {
        console.error('PDF upload error:', error);
        if (statusEl) statusEl.innerHTML = `<span class="error">✗ ${error.message}</span>`;
    }
}

async function handleEditorWordUpload(file) {
    if (!file.name.toLowerCase().endsWith('.docx') && !file.name.toLowerCase().endsWith('.doc')) {
        alert('请选择 Word 文件 (.docx)');
        return;
    }
    
    const statusEl = document.getElementById('wordUploadStatus');
    if (statusEl) statusEl.innerHTML = '<span class="uploading">上传中...</span>';
    
    try {
        const formData = new FormData();
        formData.append('file', file);
        
        const response = await fetch(`${API_BASE}/api/editor/upload-word`, {
            method: 'POST',
            body: formData
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || '上传失败');
        }
        
        const data = await response.json();
        
        state.editor.wordFile = file;
        state.editor.wordFileId = data.file_id;
        state.editor.wordPath = data.path;
        state.editor.wordParagraphCount = data.paragraph_count;
        
        if (statusEl) statusEl.innerHTML = `<span class="success">✓ ${file.name} (${data.paragraph_count}段)</span>`;
        
        checkEditorReady();
    } catch (error) {
        console.error('Word upload error:', error);
        if (statusEl) statusEl.innerHTML = `<span class="error">✗ ${error.message}</span>`;
    }
}

function checkEditorReady() {
    state.editor.isReady = state.editor.pdfPath && state.editor.wordPath;
    
    if (state.editor.isReady) {
        // 切换到配置面板
        const editorUploadSection = document.getElementById('editorUploadSection');
        const editorConfigPanel = document.getElementById('editorConfigPanel');
        
        if (editorUploadSection) editorUploadSection.style.display = 'none';
        if (editorConfigPanel) editorConfigPanel.style.display = 'block';
        
        // 更新文件信息显示
        const pdfNameEl = document.getElementById('editorPdfName');
        const pdfMetaEl = document.getElementById('editorPdfMeta');
        const wordNameEl = document.getElementById('editorWordName');
        const wordMetaEl = document.getElementById('editorWordMeta');
        
        if (pdfNameEl) pdfNameEl.textContent = state.editor.pdfFile?.name || 'PDF';
        if (pdfMetaEl) pdfMetaEl.textContent = `${state.editor.pdfTotalPages} 页`;
        if (wordNameEl) wordNameEl.textContent = state.editor.wordFile?.name || 'Word';
        if (wordMetaEl) wordMetaEl.textContent = `${state.editor.wordParagraphCount} 段落`;
        
        updateEditorRangeInfo();
    }
}

function resetEditorMode() {
    state.editor = {
        pdfFile: null,
        pdfFileId: null,
        pdfPath: null,
        pdfTotalPages: 0,
        wordFile: null,
        wordFileId: null,
        wordPath: null,
        wordParagraphCount: 0,
        startPage: 1,
        endPage: 10,
        translationModels: ['x-ai/grok-4.1-fast', 'anthropic/claude-sonnet-4'],
        editorModel: 'anthropic/claude-sonnet-4',
        taskId: null,
        results: null,
        isReady: false
    };
    
    // 重置上传状态
    const pdfStatus = document.getElementById('pdfUploadStatus');
    const wordStatus = document.getElementById('wordUploadStatus');
    if (pdfStatus) pdfStatus.innerHTML = '';
    if (wordStatus) wordStatus.innerHTML = '';
    
    // 重置输入
    const editorPdfInput = document.getElementById('editorPdfInput');
    const editorWordInput = document.getElementById('editorWordInput');
    if (editorPdfInput) editorPdfInput.value = '';
    if (editorWordInput) editorWordInput.value = '';
    
    // 切换回上传面板
    const editorUploadSection = document.getElementById('editorUploadSection');
    const editorConfigPanel = document.getElementById('editorConfigPanel');
    if (editorUploadSection) editorUploadSection.style.display = 'block';
    if (editorConfigPanel) editorConfigPanel.style.display = 'none';
}

function updateEditorRangeInfo() {
    const startEl = document.getElementById('editorStartPage');
    const endEl = document.getElementById('editorEndPage');
    const infoEl = document.getElementById('editorRangeInfo');
    
    const start = parseInt(startEl?.value) || 1;
    const end = parseInt(endEl?.value) || 10;
    const count = Math.max(0, end - start + 1);
    
    if (infoEl) infoEl.textContent = `共 ${count} 页`;
    
    state.editor.startPage = start;
    state.editor.endPage = end;
}

// Editor 模型管理
let editorModelCount = 0;

function initEditorModelList() {
    const container = document.getElementById('editorModelList');
    if (!container) return;
    
    // 如果模型列表为空，等待加载
    const models = allModels.length > 0 ? allModels : availableModels;
    if (models.length === 0) {
        console.log('Models not loaded yet, will retry...');
        return;
    }
    
    container.innerHTML = '';
    editorModelCount = 0;
    
    // 默认添加2个模型，都使用 grok-4.1-fast
    addEditorModel('x-ai/grok-4.1-fast');
    addEditorModel('x-ai/grok-4.1-fast');
    
    // 初始化编辑模型选择器，默认也是 grok-4.1-fast
    const editorModelSelect = document.getElementById('editorModelSelect');
    if (editorModelSelect && models.length > 0) {
        editorModelSelect.innerHTML = buildModelOptions(models, 'x-ai/grok-4.1-fast');
    }
    
    // 初始化对齐模型选择器
    const alignmentModelSelect = document.getElementById('alignmentModelSelect');
    if (alignmentModelSelect && models.length > 0) {
        alignmentModelSelect.innerHTML = buildModelOptions(models, 'x-ai/grok-4.1-fast');
    }
    
    console.log('Editor model list initialized with', models.length, 'models');
}

function addEditorModel(defaultValue = null) {
    const container = document.getElementById('editorModelList');
    if (!container) return;
    
    editorModelCount++;
    const index = editorModelCount;
    
    const item = document.createElement('div');
    item.className = 'editor-model-item';
    item.dataset.index = index;
    
    const models = allModels.length > 0 ? allModels : availableModels;
    const options = buildModelOptions(models, defaultValue);
    
    item.innerHTML = `
        <span class="model-number">${index}</span>
        <select class="model-select" data-editor-model-index="${index}">
            ${options}
        </select>
        <button type="button" class="remove-model-btn" onclick="removeEditorModel(${index})" title="移除">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M6 18L18 6M6 6l12 12"/>
            </svg>
        </button>
    `;
    
    container.appendChild(item);
}

function removeEditorModel(index) {
    const container = document.getElementById('editorModelList');
    if (!container) return;
    
    const items = container.querySelectorAll('.editor-model-item');
    if (items.length <= 1) {
        alert('至少需要1个翻译模型');
        return;
    }
    
    const item = container.querySelector(`.editor-model-item[data-index="${index}"]`);
    if (item) {
        item.remove();
        // 更新编号
        container.querySelectorAll('.editor-model-item').forEach((el, i) => {
            const num = el.querySelector('.model-number');
            if (num) num.textContent = i + 1;
        });
    }
}

function getEditorTranslationModels() {
    const container = document.getElementById('editorModelList');
    if (!container) return [];
    
    const selects = container.querySelectorAll('.model-select');
    return Array.from(selects).map(s => {
        const modelId = s.value;
        // 查找完整的模型配置
        const models = allModels.length > 0 ? allModels : availableModels;
        const modelConfig = models.find(m => m.id === modelId);
        
        if (modelConfig && (modelConfig.base_url || modelConfig.api_key)) {
            // 返回完整配置
            return {
                model: modelId,
                name: modelConfig.name || modelId,
                base_url: modelConfig.base_url || '',
                api_key: modelConfig.api_key || ''
            };
        }
        // 普通模型只返回ID
        return modelId;
    });
}

// 获取单个模型的完整配置
function getModelConfig(modelId) {
    const models = allModels.length > 0 ? allModels : availableModels;
    const modelConfig = models.find(m => m.id === modelId);
    
    if (modelConfig && (modelConfig.base_url || modelConfig.api_key)) {
        return {
            model: modelId,
            name: modelConfig.name || modelId,
            base_url: modelConfig.base_url || '',
            api_key: modelConfig.api_key || ''
        };
    }
    return modelId;
}

async function startEditorTask() {
    if (!state.editor.pdfPath || !state.editor.wordPath) {
        alert('请先上传 PDF 原文和 Word 译文');
        return;
    }
    
    const startBtn = document.getElementById('startEditorBtn');
    if (startBtn) {
        startBtn.disabled = true;
        startBtn.innerHTML = '<span class="btn-text">处理中...</span>';
    }
    
    try {
        const translationModels = getEditorTranslationModels();
        const editorModelSelect = document.getElementById('editorModelSelect');
        const alignmentModelSelect = document.getElementById('alignmentModelSelect');
        const editorPromptTextarea = document.getElementById('editorPrompt');
        const workersEl = document.getElementById('editorWorkers');
        
        // 获取编辑模型和对齐模型的完整配置
        const editorModelId = editorModelSelect?.value || 'x-ai/grok-4.1-fast';
        const alignmentModelId = alignmentModelSelect?.value || 'x-ai/grok-4.1-fast';
        
        const requestData = {
            pdf_path: state.editor.pdfPath,
            word_path: state.editor.wordPath,
            start_page: state.editor.startPage,
            end_page: state.editor.endPage,
            translation_models: translationModels,
            editor_model: getModelConfig(editorModelId),
            alignment_model: getModelConfig(alignmentModelId),
            editor_prompt: editorPromptTextarea?.value || DEFAULT_EDITOR_PROMPT,
            workers: parseInt(workersEl?.value) || 5
        };
        
        const response = await fetch(`${API_BASE}/api/editor/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(requestData)
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || '启动任务失败');
        }
        
        const data = await response.json();
        state.editor.taskId = data.task_id;
        
        // 显示进度面板
        const editorConfigPanel = document.getElementById('editorConfigPanel');
        const progressPanel = document.getElementById('progressPanel');
        if (editorConfigPanel) editorConfigPanel.style.display = 'none';
        if (progressPanel) progressPanel.style.display = 'flex';
        
        // 开始轮询任务状态
        pollEditorTaskStatus();
        
    } catch (error) {
        console.error('Start editor task error:', error);
        alert('启动编辑任务失败: ' + error.message);
    } finally {
        if (startBtn) {
            startBtn.disabled = false;
            startBtn.innerHTML = `
                <span class="btn-text">开始编辑打磨</span>
                <span class="btn-icon">
                    <svg viewBox="0 0 24 24" fill="currentColor" width="20" height="20">
                        <path d="M21.731 2.269a2.625 2.625 0 00-3.712 0l-1.157 1.157 3.712 3.712 1.157-1.157a2.625 2.625 0 000-3.712zM19.513 8.199l-3.712-3.712-12.15 12.15a5.25 5.25 0 00-1.32 2.214l-.8 2.685a.75.75 0 00.933.933l2.685-.8a5.25 5.25 0 002.214-1.32L19.513 8.2z"/>
                    </svg>
                </span>
            `;
        }
    }
}

async function pollEditorTaskStatus() {
    if (!state.editor.taskId) return;
    
    try {
        const response = await fetch(`${API_BASE}/api/editor/task/${state.editor.taskId}`);
        if (!response.ok) return;
        
        const task = await response.json();
        
        // 更新进度显示
        updateProgress(task.progress);
        
        if (elements.completedCount) {
            elements.completedCount.textContent = task.completed_paragraphs || 0;
        }
        if (elements.totalCount) {
            elements.totalCount.textContent = task.total_paragraphs || 0;
        }
        if (elements.currentTask) {
            elements.currentTask.textContent = `编辑打磨中... ${task.completed_paragraphs || 0}/${task.total_paragraphs || 0} 段落`;
        }
        
        if (task.status === 'completed') {
            // 获取结果
            const resultsResponse = await fetch(`${API_BASE}/api/editor/task/${state.editor.taskId}/results`);
            if (resultsResponse.ok) {
                const results = await resultsResponse.json();
                state.editor.results = results;
                showEditorResults(results);
            }
        } else if (task.status === 'error') {
            alert('编辑任务出错: ' + (task.error || '未知错误'));
            const progressPanel = document.getElementById('progressPanel');
            const editorConfigPanel = document.getElementById('editorConfigPanel');
            if (progressPanel) progressPanel.style.display = 'none';
            if (editorConfigPanel) editorConfigPanel.style.display = 'block';
        } else {
            // 继续轮询
            setTimeout(pollEditorTaskStatus, 2000);
        }
    } catch (error) {
        console.error('Poll editor task error:', error);
        setTimeout(pollEditorTaskStatus, 3000);
    }
}

function showEditorResults(results) {
    // 隐藏进度面板
    const progressPanel = document.getElementById('progressPanel');
    if (progressPanel) progressPanel.style.display = 'none';
    
    // 显示结果面板
    const resultPanel = document.getElementById('resultPanel');
    if (resultPanel) resultPanel.style.display = 'flex';
    
    // 更新结果摘要
    const stats = results.stats || {};
    if (elements.resultSummary) {
        elements.resultSummary.textContent = `已处理 ${stats.total || 0} 个段落，编辑 ${stats.edited || 0} 个，AI翻译 ${stats.translated_only || 0} 个`;
    }
    
    // 存储结果用于对比阅读
    state.translatedContent = {};
    for (const para of (results.paragraphs || [])) {
        const page = para.page;
        if (!state.translatedContent[page]) {
            state.translatedContent[page] = { original: [], translated: [] };
        }
        state.translatedContent[page].original.push(para.source_text || '');
        state.translatedContent[page].translated.push(para.final || '');
    }
}

// Start
document.addEventListener('DOMContentLoaded', function() {
    init();
    initEditorMode();
});

// 暴露给全局，供 onclick 使用
window.viewHistoryItem = viewHistoryItem;
window.deleteHistoryItem = deleteHistoryItem;
window.removeMultiModel = removeMultiModel;
window.showDownloadMenu = showDownloadMenu;
window.downloadHistoryTxt = downloadHistoryTxt;
window.downloadHistoryMd = downloadHistoryMd;
window.downloadHistoryPdf = downloadHistoryPdf;
window.toggleModelPrompt = toggleModelPrompt;
window.resetModelPrompt = resetModelPrompt;
window.saveModelPrompt = saveModelPrompt;
window.removeEditorModel = removeEditorModel;

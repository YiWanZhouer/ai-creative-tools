// ═══════════════════════════════════
// shared.js — AI 创意工具箱公共代码
// 供 方案骨架生成器 / 创意方案生成器 共享
// v1.0 | 2026-06-17
// ═══════════════════════════════════

// ── 环境检测 ──
const IS_SERVER_MODE = window.location.protocol === 'http:' || window.location.protocol === 'https:';
const IS_OBSIDIAN = !IS_SERVER_MODE && window.location.protocol !== 'file:';
const SERVER_ENDPOINT = '/api/v1/chat/completions';
const DIRECT_ENDPOINT = 'https://api.deepseek.com/v1/chat/completions';
const PROXY_ENDPOINT = 'http://localhost:8010/v1/chat/completions';

const apiConfig = {
  apiKey: localStorage.getItem('ds_api_key') || '',
  model: localStorage.getItem('ds_model') || 'deepseek-v4-pro',
  temperature: 0.8,
  endpoint: IS_SERVER_MODE ? SERVER_ENDPOINT : (IS_OBSIDIAN ? PROXY_ENDPOINT : DIRECT_ENDPOINT)
};

// ═══════════════════════════════════
// TOAST
// ═══════════════════════════════════
function showToast(msg) {
  const el = document.getElementById('toast');
  if (el) {
    el.textContent = msg;
    el.classList.add('toast--show');
    clearTimeout(el._timeout);
    el._timeout = setTimeout(() => el.classList.remove('toast--show'), 1800);
    return;
  }
  // fallback: dynamic toast
  const existing = document.querySelector('.toast');
  if (existing) existing.remove();
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.textContent = msg;
  toast.style.cssText =
    'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);' +
    'background:var(--primary,#459a77);color:#fff;padding:10px 24px;' +
    'border-radius:20px;font-size:13px;font-weight:500;z-index:9999;' +
    'animation:fadeIn 0.2s ease';
  document.body.appendChild(toast);
  setTimeout(() => { toast.style.opacity = '0'; toast.style.transition = 'opacity 0.3s'; }, 2000);
  setTimeout(() => toast.remove(), 2500);
}

// ═══════════════════════════════════
// SETTINGS MODAL
// ═══════════════════════════════════
function openSettings() {
  const modal = document.getElementById('settingsModal');
  if (!modal) return;
  const input = document.getElementById('apiKeyInput');
  if (!input) return;
  const status = document.getElementById('apiKeyStatus');
  input.value = apiConfig.apiKey;
  const modelSel = document.getElementById('modelSelect');
  if (modelSel) modelSel.value = apiConfig.model;
  input.type = 'password';

  if (IS_SERVER_MODE) {
    input.disabled = true;
    input.placeholder = '✅ 服务器已提供 Key';
    if (modelSel) modelSel.disabled = true;
    if (status) { status.textContent = '✅ 服务器模式 — API Key 由服务器统一管理'; status.className = 'modal__status modal__status--ok'; }
    const testBtn = document.getElementById('btnTestConn');
    if (testBtn) testBtn.style.display = 'none';
  } else if (apiConfig.apiKey) {
    input.disabled = false;
    if (modelSel) modelSel.disabled = false;
    if (status) { status.textContent = '✅ Key 已就绪'; status.className = 'modal__status modal__status--ok'; }
  } else {
    input.disabled = false;
    if (modelSel) modelSel.disabled = false;
    if (status) { status.textContent = '请填入 DeepSeek API Key'; status.className = 'modal__status modal__status--warn'; }
  }
  modal.classList.add('modal-overlay--visible');
  setTimeout(() => input.focus(), 100);
}

function closeSettings() {
  const modal = document.getElementById('settingsModal');
  if (modal) modal.classList.remove('modal-overlay--visible');
}

function toggleKeyVisibility(event) {
  const input = document.getElementById('apiKeyInput');
  if (!input) return;
  const isPassword = input.type === 'password';
  input.type = isPassword ? 'text' : 'password';
  if (event && event.target) event.target.textContent = isPassword ? '🙈' : '👁️';
}

function saveApiKey() {
  if (IS_SERVER_MODE) { showToast('✅ 服务器模式 — 无需手动设置 Key'); return; }
  const input = document.getElementById('apiKeyInput');
  if (!input) return;
  const key = input.value.trim();
  if (!key) { showToast('⚠️ 请输入 API Key'); return; }
  if (!key.startsWith('sk-')) { showToast('⚠️ Key 格式看起来不对（应以 sk- 开头）'); return; }
  apiConfig.apiKey = key;
  const model = (document.getElementById('modelSelect') || {}).value || 'deepseek-v4-pro';
  apiConfig.model = model;
  localStorage.setItem('ds_model', model);
  localStorage.setItem('ds_api_key', key);
  const status = document.getElementById('apiKeyStatus');
  if (status) { status.textContent = '✅ Key 已就绪'; status.className = 'modal__status modal__status--ok'; }
  showToast('✅ API Key 已保存');
  closeSettings();
}

function clearApiKey() {
  apiConfig.apiKey = '';
  apiConfig.model = 'deepseek-v4-pro';
  localStorage.removeItem('ds_model');
  localStorage.removeItem('ds_api_key');
  const modelSel = document.getElementById('modelSelect');
  if (modelSel) modelSel.value = 'deepseek-v4-pro';
  const keyInput = document.getElementById('apiKeyInput');
  if (keyInput) keyInput.value = '';
  const status = document.getElementById('apiKeyStatus');
  if (status) { status.textContent = '请填入 DeepSeek API Key'; status.className = 'modal__status modal__status--warn'; }
  showToast('🗑️ API Key 已清除');
}

// ═══════════════════════════════════
// DEEPSEEK API
// ═══════════════════════════════════
async function callDeepSeek(a, b, c) {
  if (!IS_SERVER_MODE && !apiConfig.apiKey) { openSettings(); throw new Error('API Key 未设置'); }

  let messages, temperature;
  if (Array.isArray(a)) {
    messages = a;
    temperature = (b !== undefined) ? b : 0.8;
  } else {
    messages = [
      { role: 'system', content: a },
      { role: 'user', content: b }
    ];
    temperature = (c !== undefined) ? c : 0.8;
  }

  // 120s timeout — DeepSeek V4 Pro + 4096 max_tokens needs headroom
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 120000);

  let response;
  try {
    const headers = { 'Content-Type': 'application/json' };
    if (!IS_SERVER_MODE) {
      headers['Authorization'] = 'Bearer ' + apiConfig.apiKey;
    }
    response = await fetch(apiConfig.endpoint, {
      method: 'POST',
      headers: headers,
      body: JSON.stringify({ model: apiConfig.model, messages, temperature, max_tokens: 4096 }),
      signal: controller.signal
    });
  } catch (e) {
    clearTimeout(timeoutId);
    if (e.name === 'AbortError') throw new Error('Timeout');
    if (e.message.includes('Failed to fetch') || e.name === 'TypeError') throw new Error('CORS');
    throw new Error('Network: ' + e.message);
  }
  clearTimeout(timeoutId);

  if (!response.ok) {
    if (response.status === 401) throw new Error('KeyInvalid');
    if (response.status === 429) throw new Error('RateLimit');
    const text = await response.text().catch(() => '');
    throw new Error('API: ' + response.status + ' ' + text.slice(0, 200));
  }
  const data = await response.json();
  return data.choices[0].message.content;
}

function formatError(type) {
  switch (type) {
    case 'CORS':
      return '⚠️ 浏览器安全策略阻止了直接调用 DeepSeek API。<br>手机端常见原因：iOS Safari 对跨域请求限制更严格。<br>解决方法：① 使用桌面端 Chrome + CORS 插件 ② 或通过本地代理转发请求。';
    case 'Timeout':
      return '⏰ API 请求超时（120 秒无响应）。<br>可能原因：① DeepSeek 服务端高负载排队 ② 网络不稳定。<br>建议：稍后重试，或切换 Wi-Fi。';
    case 'KeyInvalid':
      return '🔑 API Key 无效（401）。请检查 Key 是否正确，或前往 <a href="https://platform.deepseek.com/api_keys" target="_blank">DeepSeek 开放平台</a> 重新获取。';
    case 'RateLimit':
      return '⏳ API 请求过于频繁（429），请稍后再试。';
    default:
      return '❌ API 调用失败：<code>' + type.replace(/</g, '&lt;') + '</code>';
  }
}

// ═══════════════════════════════════
// CONNECTION TEST
// ═══════════════════════════════════
async function testConnection() {
  const btn = document.getElementById('btnTestConn');
  if (!btn) return;
  const key = (document.getElementById('apiKeyInput') || {}).value || '';
  const model = (document.getElementById('modelSelect') || {}).value || 'deepseek-v4-pro';

  if (IS_SERVER_MODE) {
    showToast('✅ 服务器模式 — 无需手动测试连接');
    return;
  }
  if (!key) { showToast('⚠️ 请先输入 API Key'); return; }
  if (!key.startsWith('sk-')) { showToast('⚠️ Key 格式不对'); return; }

  btn.disabled = true;
  btn.textContent = '⏳ 测试中…';

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 15000);

  try {
    const resp = await fetch(apiConfig.endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + key },
      body: JSON.stringify({ model, messages: [{ role: 'user', content: 'hi' }], max_tokens: 10 }),
      signal: controller.signal
    });
    clearTimeout(timeoutId);
    if (resp.ok) {
      showToast('✅ 连接成功 — ' + model);
    } else if (resp.status === 401) {
      showToast('🔑 Key 无效 (401)');
    } else {
      const t = await resp.text().catch(() => '');
      showToast('❌ ' + resp.status + ': ' + t.slice(0, 60));
    }
  } catch (e) {
    clearTimeout(timeoutId);
    if (e.name === 'AbortError') {
      showToast('⏰ 连接超时（15秒），网络可能不稳定');
    } else {
      showToast('🌐 网络错误，可能需要 CORS 插件');
    }
  }
  btn.disabled = false;
  btn.textContent = '🔗 测试连接';
}

// ═══════════════════════════════════
// AI BUTTON LOADING
// ═══════════════════════════════════
function setAIButtonLoading(btnId, loading) {
  const btn = document.getElementById(btnId);
  if (!btn) return;
  if (loading) {
    btn.disabled = true;
    btn.dataset.origText = btn.textContent;
    btn.innerHTML = '<span class="spinner"></span> 正在思考…';
  } else {
    btn.disabled = false;
    btn.innerHTML = btn.dataset.origText || btn.textContent;
  }
}

// ═══════════════════════════════════
// SIMPLE MARKDOWN → HTML
// ═══════════════════════════════════
function simpleMarkdownToHtml(text) {
  let html = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/\*(.+?)\*/g, '<em>$1</em>');
  html = html.replace(/`(.+?)`/g, '<code>$1</code>');
  html = html.replace(/^### (.+)$/gm, '<h4>$1</h4>');
  html = html.replace(/^## (.+)$/gm, '<h3>$1</h3>');
  html = html.replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>');
  html = html.replace(/^- (.+)$/gm, '<li>$1</li>');
  html = html.replace(/^\d+\. (.+)$/gm, '<li>$1</li>');
  html = html.replace(/(<li>.*?<\/li>)+/gs, '<ul>$&</ul>');
  const paras = html.split(/\n\n+/);
  html = paras.map(p => {
    p = p.trim();
    if (!p) return '';
    if (p.startsWith('<h') || p.startsWith('<ul') || p.startsWith('<blockquote')) return p;
    return '<p>' + p.replace(/\n/g, '<br>') + '</p>';
  }).join('\n');
  return html;
}

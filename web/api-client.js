const CONFIG_KEY = 'barManagerApiConfig';

function normalizeBaseUrl(value) {
  return String(value || '').trim().replace(/\/+$/, '');
}

function readConfig() {
  try {
    const saved = JSON.parse(localStorage.getItem(CONFIG_KEY) || '{}');
    return {
      baseUrl: normalizeBaseUrl(saved.baseUrl),
      ownerKey: String(saved.ownerKey || '').trim(),
    };
  } catch {
    return { baseUrl: '', ownerKey: '' };
  }
}

function saveConfig(config) {
  const normalized = {
    baseUrl: normalizeBaseUrl(config.baseUrl),
    ownerKey: String(config.ownerKey || '').trim(),
  };
  localStorage.setItem(CONFIG_KEY, JSON.stringify(normalized));
  return normalized;
}

class ApiClient {
  constructor(config = readConfig()) {
    this.config = config;
  }

  get isConfigured() {
    return Boolean(this.config.baseUrl && this.config.ownerKey);
  }

  setConfig(next) {
    this.config = saveConfig(next);
  }

  async request(path, options = {}) {
    if (!this.config.baseUrl) {
      throw new Error('Адрес backend не настроен');
    }

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 12000);
    const headers = new Headers(options.headers || {});
    headers.set('Accept', 'application/json');
    if (options.body && !headers.has('Content-Type')) {
      headers.set('Content-Type', 'application/json');
    }
    if (options.authorized !== false && this.config.ownerKey) {
      headers.set('X-Owner-Key', this.config.ownerKey);
    }

    try {
      const response = await fetch(`${this.config.baseUrl}${path}`, {
        ...options,
        headers,
        signal: controller.signal,
      });
      const contentType = response.headers.get('content-type') || '';
      const payload = contentType.includes('application/json')
        ? await response.json()
        : await response.text();
      if (!response.ok) {
        const detail = typeof payload === 'object' && payload?.detail
          ? payload.detail
          : `HTTP ${response.status}`;
        throw new Error(detail);
      }
      return payload;
    } catch (error) {
      if (error?.name === 'AbortError') {
        throw new Error('Сервер не ответил вовремя');
      }
      throw error;
    } finally {
      clearTimeout(timeout);
    }
  }

  health() {
    return this.request('/health', { authorized: false });
  }

  listTasks(status = null) {
    const query = status ? `?status=${encodeURIComponent(status)}` : '';
    return this.request(`/api/tasks${query}`);
  }

  createTask(payload) {
    return this.request('/api/tasks', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  updateTask(taskId, payload) {
    return this.request(`/api/tasks/${encodeURIComponent(taskId)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  }

  listInbox(status = null, limit = 100) {
    const params = new URLSearchParams();
    if (status) params.set('status', status);
    params.set('limit', String(limit));
    return this.request(`/api/inbox?${params.toString()}`);
  }

  getInboxItem(messageId) {
    return this.request(`/api/inbox/${encodeURIComponent(messageId)}`);
  }

  updateInboxItem(messageId, status) {
    return this.request(`/api/inbox/${encodeURIComponent(messageId)}`, {
      method: 'PATCH',
      body: JSON.stringify({ status }),
    });
  }

  createTaskFromInbox(messageId, payload) {
    return this.request(`/api/inbox/${encodeURIComponent(messageId)}/task`, {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  }

  listTelegramChats() {
    return this.request('/api/telegram/chats');
  }

  updateTelegramChat(chatId, payload) {
    return this.request(`/api/telegram/chats/${encodeURIComponent(chatId)}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
  }

  agentChat(message, context = {}) {
    return this.request('/api/agent/chat', {
      method: 'POST',
      body: JSON.stringify({ message, context }),
    });
  }
}

function createField(labelText, input) {
  const wrapper = document.createElement('label');
  wrapper.style.display = 'grid';
  wrapper.style.gap = '6px';
  wrapper.style.marginTop = '12px';
  const label = document.createElement('span');
  label.textContent = labelText;
  label.style.fontSize = '12px';
  label.style.fontWeight = '700';
  label.style.color = 'var(--muted)';
  wrapper.append(label, input);
  return wrapper;
}

function createInput(type, value, placeholder) {
  const input = document.createElement('input');
  input.type = type;
  input.value = value;
  input.placeholder = placeholder;
  input.autocomplete = type === 'password' ? 'new-password' : 'off';
  input.style.width = '100%';
  input.style.padding = '11px 12px';
  input.style.border = '1px solid var(--line)';
  input.style.borderRadius = '12px';
  input.style.background = '#fff';
  return input;
}

function mountSettings(client) {
  const grid = document.querySelector('.settings-grid');
  if (!grid || document.getElementById('apiSettingsCard')) return;

  const card = document.createElement('div');
  card.id = 'apiSettingsCard';
  card.className = 'card settings-card';

  const title = document.createElement('h3');
  title.textContent = 'Сервер и база данных';

  const description = document.createElement('p');
  description.textContent = 'После подключения задачи и Telegram-входящие загружаются из рабочей базы. При временной потере сети изменения задач остаются в локальной очереди.';
  description.style.color = 'var(--muted)';
  description.style.fontSize = '13px';
  description.style.lineHeight = '1.45';

  const urlInput = createInput('url', client.config.baseUrl, 'https://api.gridsside.ru');
  const keyInput = createInput('password', client.config.ownerKey, 'Ключ владельца');
  const statusLine = document.createElement('p');
  statusLine.style.fontSize = '12px';
  statusLine.style.color = 'var(--muted)';
  statusLine.textContent = client.isConfigured ? 'Настройки сохранены на этом устройстве.' : 'Сервер пока не подключён.';

  const actions = document.createElement('div');
  actions.className = 'actions';
  actions.style.marginTop = '14px';

  const saveButton = document.createElement('button');
  saveButton.className = 'btn primary';
  saveButton.type = 'button';
  saveButton.textContent = 'Сохранить';

  const testButton = document.createElement('button');
  testButton.className = 'btn ghost';
  testButton.type = 'button';
  testButton.textContent = 'Проверить соединение';

  saveButton.addEventListener('click', () => {
    client.setConfig({ baseUrl: urlInput.value, ownerKey: keyInput.value });
    statusLine.textContent = client.isConfigured
      ? 'Настройки сохранены. Запускаю синхронизацию…'
      : 'Сервер отключён, используется локальный режим.';
    window.dispatchEvent(new CustomEvent('bar-manager-api-configured'));
  });

  testButton.addEventListener('click', async () => {
    client.setConfig({ baseUrl: urlInput.value, ownerKey: keyInput.value });
    testButton.disabled = true;
    statusLine.textContent = 'Проверяю backend и доступ владельца…';
    try {
      const health = await client.health();
      await Promise.all([client.listTasks(), client.listInbox('new', 1)]);
      statusLine.textContent = `Соединение установлено: ${health.service}.`;
      statusLine.style.color = 'var(--olive)';
      window.dispatchEvent(new CustomEvent('bar-manager-api-configured'));
    } catch (error) {
      statusLine.textContent = `Ошибка: ${error.message}`;
      statusLine.style.color = 'var(--danger)';
    } finally {
      testButton.disabled = false;
    }
  });

  actions.append(saveButton, testButton);
  card.append(
    title,
    description,
    createField('Адрес backend', urlInput),
    createField('Ключ владельца', keyInput),
    statusLine,
    actions,
  );
  grid.append(card);
}

function mountInboxStyles() {
  if (document.querySelector('link[data-bar-manager-inbox-styles]')) return;
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = './inbox.css';
  link.dataset.barManagerInboxStyles = 'true';
  document.head.append(link);
}

export async function initApiClient() {
  const client = new ApiClient();
  if (document.readyState === 'loading') {
    await new Promise(resolve => document.addEventListener('DOMContentLoaded', resolve, { once: true }));
  }
  mountSettings(client);
  mountInboxStyles();
  try {
    const inboxModule = await import('./inbox-ui.js');
    await inboxModule.initInboxUI(client);
  } catch (error) {
    console.error('Inbox UI initialization failed', error);
  }
  return client;
}

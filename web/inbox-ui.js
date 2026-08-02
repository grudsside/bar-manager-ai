const CLASSIFICATION_LABELS = {
  task: 'Возможная задача',
  task_update: 'Обновление задачи',
  writeoff: 'Списание',
  preparation: 'Заготовка',
  information: 'Информация',
  unknown: 'Требует разбора',
};

const STATUS_LABELS = {
  new: 'Новое',
  review: 'На проверке',
  confirmed: 'Задача создана',
  dismissed: 'Без действия',
  ignored: 'Игнорируется',
};

const VENUE_LABELS = {
  oxford: 'Оксфорд',
  sovremennik: 'Современник',
};

let apiClient = null;
let inboxItems = [];
let telegramChats = [];
let selectedInboxId = null;
let currentInboxFilter = 'active';
let loading = false;

export async function initInboxUI(client) {
  apiClient = client;
  prepareStaticInterface();
  bindGlobalEvents();
  renderInboxShell();
  renderChatSettings();
  if (client.isConfigured) await refreshInboxAndChats();
}

function prepareStaticInterface() {
  const telegramSubtitle = document.querySelector('[data-page="telegram"]');
  if (telegramSubtitle) telegramSubtitle.textContent = '✈ Входящие';

  const dashboardSection = dashboardInboxSection();
  if (dashboardSection) {
    const subtitle = dashboardSection.querySelector('.section-head p');
    if (subtitle) subtitle.textContent = 'Новые сообщения из разрешённых рабочих чатов';
    const button = dashboardSection.querySelector('[data-go="telegram"]');
    if (button) button.textContent = 'Открыть входящие';
  }
}

function bindGlobalEvents() {
  window.addEventListener('bar-manager-api-configured', () => refreshInboxAndChats());
  window.addEventListener('online', () => refreshInboxAndChats());
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible' && apiClient?.isConfigured) {
      refreshInboxAndChats(false);
    }
  });
}

async function refreshInboxAndChats(showErrors = true) {
  if (!apiClient?.isConfigured || loading) return;
  loading = true;
  try {
    const [items, chats] = await Promise.all([
      apiClient.listInbox(null, 150),
      apiClient.listTelegramChats(),
    ]);
    inboxItems = Array.isArray(items) ? items : [];
    telegramChats = Array.isArray(chats) ? chats : [];
    ensureSelectedInbox();
    renderInboxShell();
    renderDashboardInbox();
    renderChatSettings();
  } catch (error) {
    if (showErrors) showLocalToast(`Не удалось загрузить входящие: ${error.message}`);
  } finally {
    loading = false;
  }
}

function ensureSelectedInbox() {
  const visible = filteredInboxItems();
  if (!visible.some(item => item.id === selectedInboxId)) {
    selectedInboxId = visible[0]?.id || null;
  }
}

function filteredInboxItems() {
  if (currentInboxFilter === 'active') {
    return inboxItems.filter(item => ['new', 'review'].includes(item.inbox_status));
  }
  if (currentInboxFilter === 'tasks') {
    return inboxItems.filter(item => item.classification === 'task');
  }
  if (currentInboxFilter === 'review') {
    return inboxItems.filter(item => item.inbox_status === 'review');
  }
  return inboxItems;
}

function renderInboxShell() {
  const list = document.getElementById('inboxList');
  const panel = document.getElementById('analysisPanel');
  if (!list || !panel) return;

  if (!apiClient?.isConfigured) {
    list.innerHTML = '<div class="inbox-empty">Подключите backend в настройках, чтобы получать сообщения из рабочих Telegram-чатов.</div>';
    panel.innerHTML = '<div class="eyebrow">Входящие</div><h3>Сервер не подключён</h3><p>После настройки здесь появятся исходные сообщения и ИИ-разбор.</p>';
    renderDashboardInbox();
    return;
  }

  const visible = filteredInboxItems();
  list.innerHTML = `
    <div class="inbox-toolbar">
      ${inboxFilterButton('active', 'Новые', inboxItems.filter(item => ['new', 'review'].includes(item.inbox_status)).length)}
      ${inboxFilterButton('tasks', 'Задачи', inboxItems.filter(item => item.classification === 'task').length)}
      ${inboxFilterButton('review', 'Проверка', inboxItems.filter(item => item.inbox_status === 'review').length)}
      ${inboxFilterButton('all', 'Все', inboxItems.length)}
      <button class="btn small ghost" type="button" data-inbox-refresh>Обновить</button>
    </div>
    <div class="inbox-items">
      ${visible.map(renderInboxListItem).join('') || '<div class="inbox-empty">В этой категории сообщений нет.</div>'}
    </div>
  `;

  list.querySelectorAll('[data-inbox-id]').forEach(element => {
    element.addEventListener('click', () => {
      selectedInboxId = element.dataset.inboxId;
      renderInboxShell();
    });
  });
  list.querySelectorAll('[data-inbox-filter]').forEach(button => {
    button.addEventListener('click', () => {
      currentInboxFilter = button.dataset.inboxFilter;
      ensureSelectedInbox();
      renderInboxShell();
    });
  });
  list.querySelector('[data-inbox-refresh]')?.addEventListener('click', () => refreshInboxAndChats());

  const selected = inboxItems.find(item => item.id === selectedInboxId);
  renderAnalysisPanel(selected || null);
}

function inboxFilterButton(value, label, count) {
  return `<button class="filter ${currentInboxFilter === value ? 'active' : ''}" type="button" data-inbox-filter="${value}">${label} <span>${count}</span></button>`;
}

function renderInboxListItem(item) {
  const selected = item.id === selectedInboxId ? 'active' : '';
  const classification = CLASSIFICATION_LABELS[item.classification] || 'Не разобрано';
  const status = STATUS_LABELS[item.inbox_status] || item.inbox_status;
  const confidence = Number.isFinite(item.confidence)
    ? `${Math.round(item.confidence * 100)}%`
    : '—';
  return `
    <button class="inbox-item ${selected}" type="button" data-inbox-id="${escapeHtml(item.id)}">
      <div class="top">
        <strong>${escapeHtml(item.chat_title)}</strong>
        <span class="time">${formatDateTime(item.message_date || item.created_at)}</span>
      </div>
      <p>${escapeHtml(item.message_text || attachmentDescription(item))}</p>
      <div class="inbox-badges">
        <span class="status ${classificationClass(item.classification)}">${escapeHtml(classification)}</span>
        <span class="status inbox-state">${escapeHtml(status)}</span>
        <small>${confidence}</small>
      </div>
    </button>
  `;
}

function renderAnalysisPanel(item) {
  const panel = document.getElementById('analysisPanel');
  if (!panel) return;
  if (!item) {
    panel.innerHTML = '<div class="eyebrow">ИИ-разбор</div><h3>Выберите сообщение</h3><p>Здесь появятся исходный текст, классификация и предлагаемые действия.</p>';
    return;
  }

  const analysis = item.analysis && typeof item.analysis === 'object' ? item.analysis : {};
  const suggestion = analysis.suggested_task && typeof analysis.suggested_task === 'object'
    ? analysis.suggested_task
    : null;
  const attachments = Array.isArray(item.attachments) ? item.attachments : [];
  const linked = item.linked_task_id
    ? `<div class="result">Задача уже создана: ${escapeHtml(item.linked_task_id)}</div>`
    : '';

  panel.innerHTML = `
    <div class="eyebrow">ИИ-разбор · ${escapeHtml(CLASSIFICATION_LABELS[item.classification] || 'Не определено')}</div>
    <h3>${escapeHtml(analysis.summary || suggestion?.title || 'Новое сообщение')}</h3>
    <div class="source-message">
      <div class="top"><strong>${escapeHtml(item.chat_title)}</strong><span>${formatDateTime(item.message_date || item.created_at)}</span></div>
      <small>${escapeHtml(item.sender_name || 'Автор не определён')}</small>
      <p>${escapeHtml(item.message_text || attachmentDescription(item))}</p>
      ${attachments.length ? `<div class="attachment-summary">Вложения: ${attachments.map(attachment => escapeHtml(attachment.type)).join(', ')}</div>` : ''}
    </div>
    <div class="analysis-meta">
      <div class="box"><label>Категория</label><strong>${escapeHtml(CLASSIFICATION_LABELS[item.classification] || 'Не определена')}</strong></div>
      <div class="box"><label>Уверенность</label><strong>${Number.isFinite(item.confidence) ? `${Math.round(item.confidence * 100)}%` : 'Нет оценки'}</strong></div>
      <div class="box"><label>Заведение</label><strong>${escapeHtml(item.venue_name || VENUE_LABELS[suggestion?.venue_code] || 'Не определено')}</strong></div>
    </div>
    ${suggestion ? renderSuggestedTaskForm(item, suggestion) : renderNonTaskActions(item, analysis)}
    ${linked}
  `;

  bindAnalysisActions(item);
}

function renderSuggestedTaskForm(item, suggestion) {
  const disabled = item.inbox_status === 'confirmed' || Boolean(item.linked_task_id);
  return `
    <div class="suggested-task">
      <h4>Проект задачи</h4>
      <label>Название<input id="inboxTaskTitle" value="${escapeAttribute(suggestion.title || '')}" ${disabled ? 'disabled' : ''}></label>
      <label>Детали<textarea id="inboxTaskDescription" ${disabled ? 'disabled' : ''}>${escapeHtml(suggestion.description || '')}</textarea></label>
      <div class="form-grid">
        <label>Заведение<select id="inboxTaskVenue" ${disabled ? 'disabled' : ''}>
          ${venueOptions(suggestion.venue_code || item.venue_code)}
        </select></label>
        <label>Приоритет<select id="inboxTaskPriority" ${disabled ? 'disabled' : ''}>
          ${priorityOptions(suggestion.priority || 'normal')}
        </select></label>
      </div>
      <label>Срок<input id="inboxTaskDue" type="datetime-local" value="${toDateTimeLocal(suggestion.due_at)}" ${disabled ? 'disabled' : ''}></label>
      <label>Ожидаемый результат<textarea id="inboxTaskResult" ${disabled ? 'disabled' : ''}>${escapeHtml(suggestion.expected_result || '')}</textarea></label>
      ${suggestion.clarification_question ? `<div class="result warning">Нужно уточнить: ${escapeHtml(suggestion.clarification_question)}</div>` : ''}
      <div class="inbox-actions">
        <button class="btn primary" type="button" data-create-inbox-task ${disabled ? 'disabled' : ''}>Создать задачу</button>
        <button class="btn ghost" type="button" data-mark-review ${disabled ? 'disabled' : ''}>На ручную проверку</button>
        <button class="btn ghost" type="button" data-dismiss-inbox ${disabled ? 'disabled' : ''}>Не требует действия</button>
      </div>
    </div>
  `;
}

function renderNonTaskActions(item, analysis) {
  const disabled = ['confirmed', 'dismissed'].includes(item.inbox_status);
  return `
    <div class="box"><label>Краткий вывод</label><strong>${escapeHtml(analysis.summary || 'Сообщение ожидает ручного разбора')}</strong></div>
    ${analysis.needs_review ? '<div class="result warning">ИИ рекомендует проверить сообщение вручную.</div>' : ''}
    <div class="inbox-actions">
      <button class="btn primary" type="button" data-mark-review ${disabled ? 'disabled' : ''}>Оставить на проверке</button>
      <button class="btn ghost" type="button" data-dismiss-inbox ${disabled ? 'disabled' : ''}>Обработано без задачи</button>
    </div>
  `;
}

function bindAnalysisActions(item) {
  document.querySelector('[data-create-inbox-task]')?.addEventListener('click', () => createTaskFromInbox(item));
  document.querySelector('[data-mark-review]')?.addEventListener('click', () => updateInboxStatus(item.id, 'review'));
  document.querySelector('[data-dismiss-inbox]')?.addEventListener('click', () => updateInboxStatus(item.id, 'dismissed'));
}

async function createTaskFromInbox(item) {
  const title = document.getElementById('inboxTaskTitle')?.value.trim();
  if (!title) {
    showLocalToast('Укажите название задачи');
    return;
  }
  const button = document.querySelector('[data-create-inbox-task]');
  if (button) button.disabled = true;
  try {
    const created = await apiClient.createTaskFromInbox(item.id, {
      title,
      description: nullableValue(document.getElementById('inboxTaskDescription')?.value),
      venue_code: nullableValue(document.getElementById('inboxTaskVenue')?.value),
      priority: document.getElementById('inboxTaskPriority')?.value || 'normal',
      due_at: fromDateTimeLocal(document.getElementById('inboxTaskDue')?.value),
      expected_result: nullableValue(document.getElementById('inboxTaskResult')?.value),
    });
    item.inbox_status = 'confirmed';
    item.linked_task_id = created.id;
    showLocalToast('Задача создана из Telegram-входящего');
    window.dispatchEvent(new CustomEvent('bar-manager-api-configured'));
    await refreshInboxAndChats(false);
  } catch (error) {
    showLocalToast(`Не удалось создать задачу: ${error.message}`);
    if (button) button.disabled = false;
  }
}

async function updateInboxStatus(messageId, status) {
  try {
    const updated = await apiClient.updateInboxItem(messageId, status);
    const index = inboxItems.findIndex(item => item.id === messageId);
    if (index >= 0) inboxItems[index] = updated;
    ensureSelectedInbox();
    renderInboxShell();
    renderDashboardInbox();
    showLocalToast(status === 'review' ? 'Сообщение оставлено на проверке' : 'Сообщение обработано без задачи');
  } catch (error) {
    showLocalToast(`Не удалось обновить входящее: ${error.message}`);
  }
}

function renderDashboardInbox() {
  const container = dashboardInboxContainer();
  if (!container) return;
  const active = inboxItems.filter(item => ['new', 'review'].includes(item.inbox_status)).slice(0, 3);
  if (!apiClient?.isConfigured) {
    container.innerHTML = '<div class="result">Подключите backend, чтобы видеть реальные сообщения.</div>';
    return;
  }
  container.innerHTML = active.map(item => `
    <button class="incoming dashboard-incoming" type="button" data-dashboard-inbox="${escapeHtml(item.id)}">
      <div class="top"><span class="chat">${escapeHtml(item.chat_title)}</span><span class="time">${formatDateTime(item.message_date || item.created_at)}</span></div>
      <p>${escapeHtml(item.message_text || attachmentDescription(item))}</p>
      <div class="result">${escapeHtml(CLASSIFICATION_LABELS[item.classification] || 'Требует разбора')} · ${escapeHtml(item.venue_name || 'заведение не определено')}</div>
    </button>
  `).join('') || '<div class="result">Новых входящих нет.</div>';
  container.querySelectorAll('[data-dashboard-inbox]').forEach(button => {
    button.addEventListener('click', () => {
      selectedInboxId = button.dataset.dashboardInbox;
      currentInboxFilter = 'all';
      document.querySelector('[data-page="telegram"]')?.click();
      renderInboxShell();
    });
  });
}

function renderChatSettings() {
  const grid = document.querySelector('.settings-grid');
  if (!grid) return;
  let card = document.getElementById('telegramChatsSettings');
  if (!card) {
    card = document.createElement('div');
    card.id = 'telegramChatsSettings';
    card.className = 'card settings-card telegram-chat-settings';
    grid.append(card);
  }

  if (!apiClient?.isConfigured) {
    card.innerHTML = '<h3>Рабочие Telegram-чаты</h3><p>Сначала подключите backend.</p>';
    return;
  }

  card.innerHTML = `
    <div class="section-head"><div><h3>Рабочие Telegram-чаты</h3><p>Бот только собирает сообщения из разрешённых чатов и не отвечает сотрудникам.</p></div><button class="btn small ghost" type="button" data-chat-refresh>Обновить</button></div>
    <div class="result">Добавьте бота в чат и отправьте любое сообщение. После этого чат появится здесь. Для группового сбора сообщений в BotFather должен быть отключён Privacy Mode.</div>
    <div class="telegram-chat-list">
      ${telegramChats.map(renderChatSetting).join('') || '<p>Обнаруженных чатов пока нет.</p>'}
    </div>
  `;

  card.querySelector('[data-chat-refresh]')?.addEventListener('click', () => refreshInboxAndChats());
  card.querySelectorAll('[data-chat-save]').forEach(button => {
    button.addEventListener('click', () => saveChatSetting(button.dataset.chatSave));
  });
}

function renderChatSetting(chat) {
  const id = String(chat.chat_id);
  return `
    <div class="telegram-chat-row" data-chat-row="${escapeAttribute(id)}">
      <div class="telegram-chat-title"><strong>${escapeHtml(chat.title)}</strong><small>ID: ${escapeHtml(id)}</small></div>
      <label class="compact-check"><input type="checkbox" data-chat-allowed ${chat.allowed ? 'checked' : ''}> Собирать сообщения</label>
      <label>Заведение<select data-chat-venue>${venueOptions(chat.venue_code)}</select></label>
      <label>Назначение<input data-chat-purpose value="${escapeAttribute(chat.purpose || '')}" placeholder="Например: списания бара"></label>
      <button class="btn small primary" type="button" data-chat-save="${escapeAttribute(id)}">Сохранить</button>
    </div>
  `;
}

async function saveChatSetting(chatId) {
  const row = document.querySelector(`[data-chat-row="${cssEscape(chatId)}"]`);
  if (!row) return;
  const button = row.querySelector('[data-chat-save]');
  if (button) button.disabled = true;
  try {
    const updated = await apiClient.updateTelegramChat(chatId, {
      allowed: Boolean(row.querySelector('[data-chat-allowed]')?.checked),
      venue_code: nullableValue(row.querySelector('[data-chat-venue]')?.value),
      purpose: nullableValue(row.querySelector('[data-chat-purpose]')?.value),
    });
    const index = telegramChats.findIndex(chat => String(chat.chat_id) === String(chatId));
    if (index >= 0) telegramChats[index] = updated;
    showLocalToast('Настройки Telegram-чата сохранены');
    renderChatSettings();
  } catch (error) {
    showLocalToast(`Не удалось сохранить чат: ${error.message}`);
    if (button) button.disabled = false;
  }
}

function dashboardInboxSection() {
  return document.querySelector('#dashboard .grid2 > .card.section:last-child');
}

function dashboardInboxContainer() {
  return dashboardInboxSection()?.querySelector('.list') || null;
}

function classificationClass(value) {
  if (value === 'task') return 'new';
  if (value === 'writeoff') return 'waiting';
  if (value === 'preparation') return 'done';
  if (value === 'unknown') return 'urgent';
  return 'work';
}

function attachmentDescription(item) {
  const attachments = Array.isArray(item.attachments) ? item.attachments : [];
  if (!attachments.length) return 'Сообщение без текста';
  return `Вложение: ${attachments.map(attachment => attachment.type).join(', ')}`;
}

function venueOptions(selected) {
  return `
    <option value="" ${!selected ? 'selected' : ''}>Не указано</option>
    <option value="oxford" ${selected === 'oxford' ? 'selected' : ''}>Оксфорд</option>
    <option value="sovremennik" ${selected === 'sovremennik' ? 'selected' : ''}>Современник</option>
  `;
}

function priorityOptions(selected) {
  return [
    ['low', 'Низкий'],
    ['normal', 'Обычный'],
    ['high', 'Высокий'],
    ['critical', 'Критический'],
  ].map(([value, label]) => `<option value="${value}" ${selected === value ? 'selected' : ''}>${label}</option>`).join('');
}

function toDateTimeLocal(value) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 16);
}

function fromDateTimeLocal(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function formatDateTime(value) {
  if (!value) return 'время не указано';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function nullableValue(value) {
  const normalized = String(value || '').trim();
  return normalized || null;
}

function showLocalToast(text) {
  const element = document.getElementById('toast');
  if (!element) return;
  element.textContent = text;
  element.classList.add('show');
  clearTimeout(window.inboxToastTimer);
  window.inboxToastTimer = setTimeout(() => element.classList.remove('show'), 2600);
}

function escapeHtml(value = '') {
  return String(value).replace(/[&<>'"]/g, character => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    "'": '&#39;',
    '"': '&quot;',
  }[character]));
}

function escapeAttribute(value = '') {
  return escapeHtml(value).replace(/`/g, '&#96;');
}

function cssEscape(value) {
  if (window.CSS?.escape) return window.CSS.escape(String(value));
  return String(value).replace(/[^a-zA-Z0-9_-]/g, '\\$&');
}

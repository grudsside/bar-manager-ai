const PAGE_META = {
  dashboard: ['Главная', 'Ваш рабочий центр и контроль сроков'],
  tasks: ['Задачи', 'Все поручения и сроки в одном списке'],
  telegram: ['Telegram-входящие', 'Будущий автоматический разбор разрешённых чатов'],
  assistant: ['ИИ-помощник', 'Планирование, анализ и рабочие решения'],
  notifications: ['Уведомления', 'Push, Telegram-резерв и история событий'],
  schedule: ['Расписание', 'Ваш рабочий график по двум заведениям'],
  settings: ['Настройки', 'Уведомления, интеграции и самостоятельность агента'],
};

const DEFAULT_TASKS = [
  {
    id: 'coffee-report',
    title: 'Подготовить отчёт по ревизии кофе',
    description: 'Сравнить с прошлой неделей и отправить руководителю',
    venue: 'Современник',
    status: 'work',
    priority: 'critical',
    deadline: '2026-07-29T18:00',
    source: 'Вручную',
    createdAt: '2026-07-29T09:00',
  },
  {
    id: 'beer-analysis',
    title: 'Проанализировать безалкогольное пиво',
    description: 'Продажи, остатки и решение по ассортименту',
    venue: 'Оксфорд',
    status: 'new',
    priority: 'high',
    deadline: '2026-07-31T18:00',
    source: 'Telegram',
    createdAt: '2026-07-29T10:06',
  },
  {
    id: 'supplier-prices',
    title: 'Получить обновлённый прайс поставщика',
    description: 'Поставщик обещал прислать новые цены',
    venue: 'Оба',
    status: 'waiting',
    priority: 'normal',
    deadline: '2026-07-30T14:00',
    source: 'Telegram',
    createdAt: '2026-07-27T12:00',
  },
  {
    id: 'beer-expiry',
    title: 'Проверить сроки годности кег',
    description: 'Выделить позиции с остаточным сроком менее 30 и 60 дней',
    venue: 'Оксфорд',
    status: 'new',
    priority: 'normal',
    deadline: '2026-08-01T16:00',
    source: 'Регулярная',
    createdAt: '2026-07-28T09:00',
  },
  {
    id: 'milk-writeoff',
    title: 'Проверить утренние списания молока и сиропов',
    description: 'Сверить сообщения в рабочем чате',
    venue: 'Современник',
    status: 'done',
    priority: 'normal',
    deadline: '2026-07-29T11:00',
    source: 'Telegram',
    createdAt: '2026-07-29T08:00',
  },
];

const INBOX = [
  {
    title: 'Анализ безалкогольного пива',
    venue: 'Оксфорд',
    deadline: 'Пятница, 31 июля',
    result: 'Решение, какие позиции оставить в ассортименте',
    plan: [
      'Получить продажи за выбранный период',
      'Добавить текущие остатки',
      'Рассчитать оборачиваемость',
      'Подготовить рекомендации',
    ],
  },
  {
    title: 'Списание St. Peter’s Plum Porter',
    venue: 'Оксфорд',
    deadline: 'Зафиксировано сегодня',
    result: 'Добавить 2 бутылки в журнал списаний с причиной «повреждение этикетки»',
    plan: [
      'Проверить наличие фотографии',
      'Подтвердить количество',
      'Добавить запись в месячный отчёт',
    ],
  },
  {
    title: 'Заготовка малинового кордиала',
    venue: 'Современник',
    deadline: 'Приготовлено сегодня',
    result: 'Зафиксировать 4 литра заготовки и место хранения',
    plan: [
      'Проверить срок годности',
      'Добавить ответственного сотрудника',
      'Сохранить запись в журнале заготовок',
    ],
  },
  {
    title: 'Сравнение прайсов поставщика',
    venue: 'Оба заведения',
    deadline: 'Срок не указан',
    result: 'Сравнить новый прайс с предыдущим и выделить изменения',
    plan: [
      'Загрузить оба прайса',
      'Сопоставить одинаковые позиции',
      'Рассчитать изменение цен',
      'Подготовить краткий вывод',
    ],
  },
];

const TASK_STORAGE_KEY = 'barManagerTasks';
const PENDING_STORAGE_KEY = 'barManagerPendingOperations';
let tasks = loadTasks();
let currentFilter = 'all';
let currentSearch = '';
let apiClient = null;
let syncInProgress = false;

const apiReady = import('./api-client.js')
  .then(module => module.initApiClient())
  .then(client => {
    apiClient = client;
    if (client.isConfigured) syncWithServer(false);
    return client;
  })
  .catch(error => {
    console.error('API client initialization failed', error);
    return null;
  });

function loadTasks() {
  try {
    const value = JSON.parse(localStorage.getItem(TASK_STORAGE_KEY));
    return Array.isArray(value) && value.length ? value : DEFAULT_TASKS.map(item => ({ ...item }));
  } catch {
    return DEFAULT_TASKS.map(item => ({ ...item }));
  }
}

function saveTasks() {
  localStorage.setItem(TASK_STORAGE_KEY, JSON.stringify(tasks));
}

function loadPendingOperations() {
  try {
    const value = JSON.parse(localStorage.getItem(PENDING_STORAGE_KEY) || '[]');
    return Array.isArray(value) ? value : [];
  } catch {
    return [];
  }
}

function savePendingOperations(operations) {
  localStorage.setItem(PENDING_STORAGE_KEY, JSON.stringify(operations));
}

function queueOperation(operation) {
  const operations = loadPendingOperations();
  if (operation.type === 'update') {
    const existing = operations.find(
      item => item.type === 'update' && item.taskId === operation.taskId,
    );
    if (existing) {
      existing.payload = { ...existing.payload, ...operation.payload };
      existing.createdAt = new Date().toISOString();
      savePendingOperations(operations);
      return;
    }
  }
  operations.push({
    id: `operation-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    createdAt: new Date().toISOString(),
    ...operation,
  });
  savePendingOperations(operations);
}

function showToast(text) {
  const element = document.getElementById('toast');
  element.textContent = text;
  element.classList.add('show');
  clearTimeout(window.toastTimer);
  window.toastTimer = setTimeout(() => element.classList.remove('show'), 2300);
}

function navigate(page) {
  document.querySelectorAll('.page').forEach(element => element.classList.remove('active'));
  document.getElementById(page)?.classList.add('active');
  document.querySelectorAll('[data-page]').forEach(element => {
    element.classList.toggle('active', element.dataset.page === page);
  });
  document.getElementById('pageTitle').textContent = PAGE_META[page][0];
  document.getElementById('pageSubtitle').textContent = PAGE_META[page][1];
  window.scrollTo({ top: 0, behavior: 'smooth' });
  if (page === 'tasks') renderTasks();
}

function statusName(status) {
  return {
    new: 'Новая',
    planned: 'Запланирована',
    work: 'В работе',
    waiting: 'Ожидаю',
    done: 'Выполнена',
    cancelled: 'Отменена',
  }[status] || status;
}

function statusClass(status) {
  if (status === 'planned') return 'new';
  if (status === 'cancelled') return 'waiting';
  return status;
}

function venueClass(venue) {
  if (venue === 'Оксфорд') return 'oxford';
  if (venue === 'Современник') return 'sov';
  return '';
}

function venueCode(venue) {
  if (venue === 'Оксфорд') return 'oxford';
  if (venue === 'Современник') return 'sovremennik';
  return null;
}

function sourceType(source) {
  return {
    Telegram: 'telegram',
    Регулярная: 'recurring',
    Агент: 'agent',
    Файл: 'file',
  }[source] || 'manual';
}

function sourceName(source) {
  return {
    telegram: 'Telegram',
    recurring: 'Регулярная',
    agent: 'Агент',
    file: 'Файл',
    manual: 'Вручную',
  }[source] || 'Вручную';
}

function formatDate(value) {
  if (!value) return 'Без срока';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function toIso(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function isToday(value) {
  if (!value) return false;
  const date = new Date(value);
  const now = new Date();
  return date.getFullYear() === now.getFullYear()
    && date.getMonth() === now.getMonth()
    && date.getDate() === now.getDate();
}

function isOverdue(task) {
  return task.status !== 'done'
    && task.status !== 'cancelled'
    && task.deadline
    && new Date(task.deadline).getTime() < Date.now();
}

function isServerId(value) {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

function toLocalTask(task) {
  return {
    id: task.id,
    title: task.title,
    description: task.description || '',
    venue: task.venue_name || 'Оба',
    status: task.status,
    priority: task.priority,
    deadline: task.due_at,
    source: sourceName(task.source_type),
    createdAt: task.created_at,
    syncedAt: new Date().toISOString(),
  };
}

function toCreatePayload(task) {
  return {
    title: task.title,
    description: task.description || null,
    venue_code: venueCode(task.venue),
    status: task.status,
    priority: task.priority || 'normal',
    due_at: toIso(task.deadline),
    source_type: sourceType(task.source),
    requires_confirmation: false,
  };
}

function replaceTask(tempId, serverTask) {
  const index = tasks.findIndex(task => task.id === tempId);
  if (index >= 0) tasks[index] = toLocalTask(serverTask);
}

async function flushPendingOperations() {
  if (!apiClient?.isConfigured) return;
  const operations = loadPendingOperations();
  if (!operations.length) return;

  const remaining = [];
  for (const operation of operations) {
    try {
      if (operation.type === 'create') {
        const task = tasks.find(item => item.id === operation.tempId);
        if (!task) continue;
        const created = await apiClient.createTask(toCreatePayload(task));
        replaceTask(operation.tempId, created);
      } else if (operation.type === 'update' && isServerId(operation.taskId)) {
        const updated = await apiClient.updateTask(operation.taskId, operation.payload);
        replaceTask(operation.taskId, updated);
      }
    } catch (error) {
      remaining.push(operation);
    }
  }
  savePendingOperations(remaining);
  saveTasks();
}

async function migrateLocalTasks() {
  if (!apiClient?.isConfigured) return;
  const localOnly = tasks.filter(task => String(task.id).startsWith('task-'));
  for (const task of localOnly) {
    try {
      const created = await apiClient.createTask(toCreatePayload(task));
      replaceTask(task.id, created);
    } catch {
      queueOperation({ type: 'create', tempId: task.id });
    }
  }
  saveTasks();
}

async function syncWithServer(showFeedback = true) {
  if (!apiClient?.isConfigured || syncInProgress) return;
  syncInProgress = true;
  try {
    await apiClient.health();
    await flushPendingOperations();
    let remoteTasks = await apiClient.listTasks();
    if (!remoteTasks.length) {
      await migrateLocalTasks();
      remoteTasks = await apiClient.listTasks();
    }
    if (remoteTasks.length) {
      tasks = remoteTasks.map(toLocalTask);
      saveTasks();
      renderTasks();
    }
    if (showFeedback) showToast('Задачи синхронизированы с сервером');
  } catch (error) {
    if (showFeedback) showToast(`Сервер недоступен: ${error.message}`);
  } finally {
    syncInProgress = false;
  }
}

function filteredTasks() {
  return tasks.filter(task => {
    const haystack = `${task.title} ${task.description || ''} ${task.venue}`.toLowerCase();
    const matchSearch = haystack.includes(currentSearch.toLowerCase());
    let matchFilter = true;
    if (currentFilter === 'today') matchFilter = isToday(task.deadline);
    else if (currentFilter === 'work') matchFilter = ['new', 'planned', 'work'].includes(task.status);
    else if (currentFilter === 'waiting') matchFilter = task.status === 'waiting';
    else if (currentFilter === 'done') matchFilter = task.status === 'done';
    return matchSearch && matchFilter;
  });
}

function renderDashboard() {
  const active = tasks
    .filter(task => !['done', 'cancelled'].includes(task.status))
    .sort((left, right) => new Date(left.deadline || '2999') - new Date(right.deadline || '2999'));

  document.getElementById('todayCount').textContent = tasks.filter(
    task => isToday(task.deadline) && !['done', 'cancelled'].includes(task.status),
  ).length;
  document.getElementById('overdueCount').textContent = tasks.filter(isOverdue).length;
  document.getElementById('waitingCount').textContent = tasks.filter(task => task.status === 'waiting').length;
  document.getElementById('dashboardTasks').innerHTML = active.slice(0, 4).map(task => `
    <div class="task">
      <button class="check ${task.status === 'done' ? 'done' : ''}" data-toggle="${task.id}" aria-label="Изменить статус"></button>
      <div>
        <strong>${escapeHtml(task.title)}</strong>
        <div class="meta">
          <span class="tag ${venueClass(task.venue)}">${escapeHtml(task.venue)}</span>
          <span class="tag ${isOverdue(task) ? 'urgent' : ''}">${isOverdue(task) ? 'Просрочено' : formatDate(task.deadline)}</span>
        </div>
      </div>
      <div class="task-time">${statusName(task.status)}</div>
    </div>
  `).join('') || '<div class="result">Активных задач нет.</div>';
  bindTaskActions();
}

function renderTasks() {
  document.getElementById('taskRows').innerHTML = filteredTasks().map(task => `
    <div class="trow">
      <div class="title">
        <strong>${escapeHtml(task.title)}</strong>
        <small>${escapeHtml(task.description || 'Без дополнительного описания')}</small>
      </div>
      <div><span class="tag ${venueClass(task.venue)}">${escapeHtml(task.venue)}</span></div>
      <div><button class="status ${statusClass(task.status)}" data-cycle="${task.id}">${statusName(task.status)}</button></div>
      <div>${formatDate(task.deadline)}</div>
      <div>${escapeHtml(task.source || 'Вручную')}</div>
    </div>
  `).join('') || '<div style="padding:24px;color:var(--muted)">По выбранным условиям задач нет.</div>';
  bindTaskActions();
  renderDashboard();
}

function bindTaskActions() {
  document.querySelectorAll('[data-toggle]').forEach(button => {
    button.onclick = () => toggleTask(button.dataset.toggle);
  });
  document.querySelectorAll('[data-cycle]').forEach(button => {
    button.onclick = () => cycleTask(button.dataset.cycle);
  });
}

async function persistStatus(task) {
  await apiReady;
  if (!apiClient?.isConfigured || !isServerId(task.id)) return;
  try {
    const updated = await apiClient.updateTask(task.id, { status: task.status });
    replaceTask(task.id, updated);
    saveTasks();
    renderTasks();
  } catch {
    queueOperation({ type: 'update', taskId: task.id, payload: { status: task.status } });
    showToast('Статус сохранён локально и ожидает синхронизации');
  }
}

function toggleTask(id) {
  const task = tasks.find(item => item.id === id);
  if (!task) return;
  task.status = task.status === 'done' ? 'work' : 'done';
  saveTasks();
  renderTasks();
  showToast(task.status === 'done' ? 'Задача выполнена' : 'Задача возвращена в работу');
  persistStatus(task);
}

function cycleTask(id) {
  const order = ['new', 'planned', 'work', 'waiting', 'done'];
  const task = tasks.find(item => item.id === id);
  if (!task) return;
  const index = order.indexOf(task.status);
  task.status = order[(index + 1) % order.length];
  saveTasks();
  renderTasks();
  showToast(`Статус: ${statusName(task.status)}`);
  persistStatus(task);
}

async function createTaskFromForm(form) {
  const title = document.getElementById('taskTitle').value.trim();
  if (!title) return;

  const task = {
    id: `task-${Date.now()}`,
    title,
    description: document.getElementById('taskDescription').value.trim(),
    venue: document.getElementById('taskVenue').value,
    status: document.getElementById('taskStatus').value,
    priority: document.getElementById('taskPriority').value,
    deadline: document.getElementById('taskDeadline').value,
    source: 'Вручную',
    createdAt: new Date().toISOString(),
  };

  tasks.unshift(task);
  saveTasks();
  form.reset();
  modal.classList.remove('open');
  renderTasks();

  await apiReady;
  if (!apiClient?.isConfigured) {
    showToast('Задача сохранена на устройстве');
    return;
  }

  try {
    const created = await apiClient.createTask(toCreatePayload(task));
    replaceTask(task.id, created);
    saveTasks();
    renderTasks();
    showToast('Задача сохранена на сервере');
  } catch {
    queueOperation({ type: 'create', tempId: task.id });
    showToast('Задача сохранена локально и ожидает синхронизации');
  }
}

function renderInbox(index = 0) {
  const item = INBOX[index];
  document.getElementById('analysisPanel').innerHTML = `
    <div class="eyebrow">ИИ-разбор</div>
    <h3>${escapeHtml(item.title)}</h3>
    <div class="box"><label>Заведение</label><strong>${escapeHtml(item.venue)}</strong></div>
    <div class="box"><label>Срок</label><strong>${escapeHtml(item.deadline)}</strong></div>
    <div class="box"><label>Ожидаемый результат</label><strong>${escapeHtml(item.result)}</strong></div>
    <div class="box"><label>Предлагаемый план</label><ol>${item.plan.map(step => `<li>${escapeHtml(step)}</li>`).join('')}</ol></div>
    <div style="display:grid;gap:8px">
      <button class="btn primary" id="confirmInbox">Подтвердить</button>
      <button class="btn ghost" id="reviewInbox">Требует проверки</button>
    </div>
  `;
  document.getElementById('confirmInbox').onclick = () => showToast('Запись подтверждена в демонстрационном режиме');
  document.getElementById('reviewInbox').onclick = () => showToast('Сообщение отправлено на ручную проверку');
}

function addMessage(text, type = 'user') {
  const box = document.createElement('div');
  box.className = `msg ${type}`;
  box.textContent = text;
  document.getElementById('messages').appendChild(box);
  box.scrollIntoView({ behavior: 'smooth', block: 'end' });
}

function assistantReply(text) {
  const query = text.toLowerCase();
  if (query.includes('сегодня')) {
    return 'Сегодня приоритетны: отчёт по ревизии кофе, разбор нового поручения по безалкогольному пиву и проверка ответа поставщика. Сначала завершите задачу с ближайшим сроком.';
  }
  if (query.includes('потер') || query.includes('риск') || query.includes('проср')) {
    return 'Проверьте просроченные задачи и ожидания без даты повторного контроля. После подключения backend я буду определять такие риски по актуальной базе.';
  }
  if (query.includes('telegram') || query.includes('телеграм')) {
    return 'В демонстрационных входящих обнаружены: одна новая задача, одно списание и одна заготовка. Реальная обработка включится после подключения Telegram Bot API.';
  }
  if (query.includes('отч')) {
    return 'Я подготовлю отчёт после подключения источника данных или загрузки файла. Сначала проверю период, показатели и требуемый формат результата.';
  }
  return 'Принял запрос. В рабочей версии я сначала найду данные в задачах, Telegram и файлах, затем задам только недостающие уточнения и предложу конкретный план действий.';
}

async function sendAssistant() {
  const input = document.getElementById('assistantInput');
  const text = input.value.trim();
  if (!text) return;
  addMessage(text);
  input.value = '';

  await apiReady;
  if (apiClient?.isConfigured) {
    try {
      const response = await apiClient.agentChat(text, {
        tasks: tasks.slice(0, 30).map(task => ({
          id: task.id,
          title: task.title,
          status: task.status,
          venue: task.venue,
          deadline: task.deadline,
        })),
      });
      addMessage(response.answer, 'ai');
      return;
    } catch (error) {
      addMessage(`Серверный помощник недоступен: ${error.message}. Использую локальный ответ.`, 'ai');
    }
  }
  setTimeout(() => addMessage(assistantReply(text), 'ai'), 180);
}

async function requestNotifications() {
  if (!('Notification' in window)) {
    showToast('Браузер не поддерживает уведомления');
    return false;
  }
  const permission = await Notification.requestPermission();
  if (permission === 'granted') {
    showToast('Разрешение на уведомления получено');
    return true;
  }
  showToast('Уведомления не разрешены');
  return false;
}

async function demoNotification() {
  const allowed = Notification.permission === 'granted' || await requestNotifications();
  if (!allowed) return;
  if ('serviceWorker' in navigator) {
    const registration = await navigator.serviceWorker.ready;
    registration.showNotification('Бар-менеджер AI', {
      body: 'Тест: напоминание о задаче работает на этом устройстве.',
      icon: './icon.svg',
      badge: './icon.svg',
      tag: 'demo-notification',
      data: { url: './' },
    });
  } else {
    new Notification('Бар-менеджер AI', { body: 'Тестовое напоминание' });
  }
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

document.querySelectorAll('[data-page]').forEach(button => {
  button.addEventListener('click', () => navigate(button.dataset.page));
});
document.querySelectorAll('[data-go]').forEach(button => {
  button.addEventListener('click', () => navigate(button.dataset.go));
});
document.querySelectorAll('[data-filter]').forEach(button => {
  button.addEventListener('click', () => {
    currentFilter = button.dataset.filter;
    document.querySelectorAll('[data-filter]').forEach(item => item.classList.toggle('active', item === button));
    renderTasks();
  });
});
document.getElementById('taskSearch').addEventListener('input', event => {
  currentSearch = event.target.value;
  renderTasks();
});

const modal = document.getElementById('taskModal');
document.querySelectorAll('[data-open-task]').forEach(button => {
  button.addEventListener('click', () => modal.classList.add('open'));
});
document.getElementById('closeModal').onclick = () => modal.classList.remove('open');
modal.addEventListener('click', event => {
  if (event.target === modal) modal.classList.remove('open');
});
document.getElementById('taskForm').addEventListener('submit', event => {
  event.preventDefault();
  createTaskFromForm(event.currentTarget);
});
document.getElementById('aiDraft').onclick = () => {
  const title = document.getElementById('taskTitle');
  const description = document.getElementById('taskDescription');
  if (!title.value) title.value = 'Проанализировать рабочее поручение';
  if (!description.value) description.value = 'ИИ-разбор будет подключён после настройки OpenAI API. Сейчас создан демонстрационный черновик.';
  showToast('Подготовлен демонстрационный черновик');
};

document.querySelectorAll('[data-inbox]').forEach(element => {
  element.addEventListener('click', () => {
    document.querySelectorAll('[data-inbox]').forEach(item => item.classList.remove('active'));
    element.classList.add('active');
    renderInbox(Number(element.dataset.inbox));
  });
});

document.getElementById('sendAssistant').onclick = sendAssistant;
document.getElementById('assistantInput').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    sendAssistant();
  }
});
document.querySelectorAll('[data-prompt]').forEach(button => {
  button.addEventListener('click', () => {
    navigate('assistant');
    document.getElementById('assistantInput').value = button.dataset.prompt;
    sendAssistant();
  });
});
document.querySelectorAll('[data-answer]').forEach(button => {
  button.addEventListener('click', () => {
    addMessage(`Уточнение: ${button.dataset.answer}`);
    setTimeout(() => addMessage('Уточнение сохранено. Я обновил бы карточку задачи и план анализа.', 'ai'), 200);
  });
});

document.getElementById('markRead').onclick = () => {
  document.querySelectorAll('.notification').forEach(item => item.classList.remove('unread'));
  document.getElementById('unreadCount').textContent = '0';
  showToast('Все уведомления отмечены прочитанными');
};
document.getElementById('requestPush').onclick = requestNotifications;
document.getElementById('notifyTest').onclick = demoNotification;
document.querySelectorAll('[data-switch]').forEach(button => {
  button.onclick = () => {
    button.classList.toggle('on');
    showToast('Настройка сохранена локально');
  };
});
document.getElementById('editSchedule').onclick = () => showToast('Редактор расписания будет добавлен на следующем этапе');

window.addEventListener('bar-manager-api-configured', () => syncWithServer(true));
window.addEventListener('online', () => syncWithServer(false));

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('./service-worker.js').catch(() => {}));
}

renderInbox(0);
renderTasks();

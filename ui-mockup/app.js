const INITIAL_STATE = Object.freeze({
  materials: [
    {
      id: 101,
      title: "Как маленькие команды используют локальные AI-модели",
      source: "Hacker News",
      domain: "latent.space",
      found: "Сегодня, 07:18",
      age: "2 часа",
      status: "selected",
      score: 91,
      category: "AI-инструменты",
      reason: "Практический разбор с понятными сценариями для небольшой команды.",
      accent: "mint",
    },
    {
      id: 102,
      title: "Новый подход к прототипированию интерфейсов без сборки",
      source: "Hacker News",
      domain: "web.dev",
      found: "Сегодня, 07:24",
      age: "3 часа",
      status: "selected",
      score: 87,
      category: "Дизайн",
      reason: "Есть демонстрация, конкретный результат и полезные ограничения.",
      accent: "sand",
    },
    {
      id: 103,
      title: "Почему автоматизация контента начинается не с генерации",
      source: "Hacker News",
      domain: "every.to",
      found: "Сегодня, 07:31",
      age: "4 часа",
      status: "new",
      score: 78,
      category: "Контент",
      reason: "Ожидает финального решения по полезности для аудитории.",
      accent: "paper",
    },
    {
      id: 104,
      title: "Релиз библиотеки обработки потоков версии 0.4.7",
      source: "Hacker News",
      domain: "github.com",
      found: "Сегодня, 07:36",
      age: "5 часов",
      status: "rejected",
      score: 42,
      category: "Разработка",
      reason: "Технический релиз без прикладного сценария для выбранной аудитории.",
      accent: "slate",
    },
    {
      id: 105,
      title: "Пять способов сократить время на исследование рынка",
      source: "Hacker News",
      domain: "a16z.com",
      found: "Вчера, 19:42",
      age: "14 часов",
      status: "selected",
      score: 84,
      category: "Исследования",
      reason: "Проверяемые методы и ясная польза для продуктовых команд.",
      accent: "amber",
    },
    {
      id: 106,
      title: "Партнёрская программа для облачной инфраструктуры",
      source: "Hacker News",
      domain: "cloudpromo.dev",
      found: "Вчера, 18:11",
      age: "16 часов",
      status: "rejected",
      score: 25,
      category: "Облако",
      reason: "Преимущественно рекламный материал без самостоятельной ценности.",
      accent: "rose",
    },
    {
      id: 107,
      title: "Что меняется в работе редактора с появлением AI-агентов",
      source: "Hacker News",
      domain: "niemanlab.org",
      found: "Вчера, 17:55",
      age: "18 часов",
      status: "new",
      score: 76,
      category: "Редактура",
      reason: "Нужно проверить конкретику кейсов и рекламный риск.",
      accent: "leaf",
    },
    {
      id: 108,
      title: "Открытый набор шаблонов для продуктовой документации",
      source: "Hacker News",
      domain: "docs.directory",
      found: "Вчера, 16:08",
      age: "20 часов",
      status: "selected",
      score: 82,
      category: "Продукт",
      reason: "Готовые примеры можно сразу применить в небольшой команде.",
      accent: "blue",
    },
  ],
  packages: [
    {
      id: 201,
      materialId: 101,
      title: "Локальный AI для команды: с чего начать без дорогой инфраструктуры",
      excerpt: "Небольшой команде не всегда нужен ещё один облачный сервис. Часть ежедневных AI-задач можно перенести на собственные устройства — и сохранить контроль над данными.",
      status: "needs_review",
      created: "Сегодня, 08:04",
      format: "Практический разбор",
      readTime: "2 мин",
      accent: "mint",
    },
    {
      id: 202,
      materialId: 102,
      title: "Интерактивный прототип за вечер — без нового frontend-проекта",
      excerpt: "Когда нужно согласовать логику продукта, полноценная сборка часто только замедляет разговор. Статический HTML уже умеет достаточно для честной проверки сценариев.",
      status: "needs_review",
      created: "Сегодня, 08:11",
      format: "Инструкция",
      readTime: "3 мин",
      accent: "sand",
    },
    {
      id: 203,
      materialId: 105,
      title: "Исследование рынка, которое помещается в один рабочий день",
      excerpt: "Пять источников сигнала, один список допущений и короткая проверка спроса помогают не превращать исследование в бесконечный документ.",
      status: "needs_review",
      created: "Сегодня, 08:19",
      format: "Подборка",
      readTime: "2 мин",
      accent: "amber",
    },
    {
      id: 204,
      materialId: 108,
      title: "Документация, которую команда действительно открывает",
      excerpt: "Хороший шаблон не добавляет бюрократию. Он оставляет только решения, границы и следующий понятный шаг.",
      status: "needs_review",
      created: "Сегодня, 08:26",
      format: "Наблюдение",
      readTime: "1 мин",
      accent: "blue",
    },
    {
      id: 205,
      materialId: 103,
      title: "Автоматизация контента начинается с хорошего отбора",
      excerpt: "Генератор ускоряет выпуск, но не отвечает на главный вопрос: какую тему вообще стоит брать в работу сегодня.",
      status: "approved",
      created: "Вчера, 18:52",
      format: "Разбор",
      readTime: "2 мин",
      accent: "paper",
    },
  ],
  slots: [
    { id: "morning", label: "Утро", window: "08:00—12:00", time: "09:00", packageId: 205, tone: "olive" },
    { id: "day", label: "День", window: "12:00—17:00", time: "14:00", packageId: null, tone: "amber" },
    { id: "evening", label: "Вечер", window: "17:00—22:00", time: "19:00", packageId: null, tone: "forest" },
  ],
  deliveries: [
    { id: 301, title: "Три привычки для спокойного рабочего утра", date: "11 августа", time: "09:00", status: "published", messageId: "tg-1842", attempts: 1, detail: "Доставлено в Telegram за 0,8 секунды." },
    { id: 302, title: "Как подготовить идею для команды за 15 минут", date: "11 августа", time: "14:00", status: "published", messageId: "tg-1847", attempts: 1, detail: "Доставлено в Telegram за 1,1 секунды." },
    { id: 303, title: "Планирование дня без лишнего стресса", date: "11 августа", time: "19:00", status: "published", messageId: "tg-1851", attempts: 1, detail: "Доставлено в Telegram за 0,9 секунды." },
    { id: 304, title: "Инструменты для визуального исследования", date: "10 августа", time: "14:00", status: "failed", messageId: "—", attempts: 2, detail: "Telegram вернул 400: размер изображения превышает допустимый. Нужна замена визуала." },
    { id: 305, title: "Что почитать продуктовой команде", date: "10 августа", time: "09:00", status: "published", messageId: "tg-1829", attempts: 1, detail: "Доставлено в Telegram за 1,0 секунды." },
  ],
  runs: [
    { id: 401, kind: "Поиск материалов", started: "Сегодня, 07:30", duration: "42 сек", status: "completed", result: "Найдено 38 · выбрано 8 · отклонено 12", detail: "Источник Hacker News ответил штатно. 18 материалов уже были известны системе." },
    { id: 402, kind: "Подготовка контента", started: "Сегодня, 08:00", duration: "3 мин 18 сек", status: "completed", result: "Создано 4 пакета", detail: "Тексты и визуальные кандидаты подготовлены для четырёх лучших тем." },
    { id: 403, kind: "Публикация", started: "Сегодня, 09:00", duration: "1,2 сек", status: "completed", result: "Опубликован 1 пост", detail: "Telegram подтвердил доставку. Идентификатор сообщения tg-1864." },
    { id: 404, kind: "Публикация", started: "Вчера, 19:00", duration: "0,4 сек", status: "warning", result: "Слот остался пуст", detail: "К началу вечернего слота не было одобренного пакета. Повторная публикация не выполнялась." },
  ],
  alerts: [
    { id: 501, tone: "amber", title: "Два слота пока свободны", text: "Одобрите ещё два поста, чтобы закрыть план на сегодня." },
  ],
  ui: { materialFilter: "all", reviewFilter: "needs_review" },
});

let state = cloneState(INITIAL_STATE);

const routes = {
  overview: { title: "Сегодня", eyebrow: "Рабочая панель" },
  materials: { title: "Материалы", eyebrow: "Входящий поток" },
  review: { title: "Проверка", eyebrow: "Редакторская очередь" },
  queue: { title: "Очередь публикаций", eyebrow: "План на сегодня" },
  publications: { title: "История публикаций", eyebrow: "Доставка контента" },
  journal: { title: "Журнал работы", eyebrow: "Состояние системы" },
};

const screens = {
  overview: renderOverview,
  materials: renderMaterials,
  review: renderReview,
  queue: renderQueue,
  publications: renderPublications,
  journal: renderJournal,
};

const root = document.querySelector("#screen-root");
const title = document.querySelector("#screen-title");
const eyebrow = document.querySelector("#screen-eyebrow");
const detailLayer = document.querySelector("#detail-layer");
const detailContent = document.querySelector("#detail-content");
const toastRegion = document.querySelector("#toast-region");
let detailOpener = null;

function cloneState(value) {
  return JSON.parse(JSON.stringify(value));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function currentRoute() {
  const candidate = window.location.hash.slice(1);
  return Object.hasOwn(routes, candidate) ? candidate : "overview";
}

function navigate(route) {
  const safeRoute = Object.hasOwn(routes, route) ? route : "overview";
  if (window.location.hash !== `#${safeRoute}`) {
    window.history.pushState(null, "", `#${safeRoute}`);
  }
  render();
}

function render() {
  const route = currentRoute();
  if (window.location.hash !== `#${route}`) {
    window.history.replaceState(null, "", `#${route}`);
  }
  title.textContent = routes[route].title;
  eyebrow.textContent = routes[route].eyebrow;
  document.title = `Postify — ${routes[route].title.toLowerCase()}`;
  root.innerHTML = screens[route]();
  document.querySelectorAll("[data-route]").forEach((link) => {
    if (link.getAttribute("data-route") === route) {
      link.setAttribute("aria-current", "page");
    } else {
      link.removeAttribute("aria-current");
    }
  });
  updateShellCounts();
}

function updateShellCounts() {
  const needsReview = state.packages.filter((item) => item.status === "needs_review").length;
  document.querySelectorAll('[data-nav-count="review"]').forEach((node) => {
    node.textContent = String(needsReview);
  });
}

function statusBadge(status) {
  const labels = {
    new: ["Новый", "blue"],
    selected: ["Выбран", "olive"],
    rejected: ["Отклонён", "danger"],
    needs_review: ["Нужна проверка", "amber"],
    approved: ["Одобрен", "olive"],
    published: ["Опубликован", "olive"],
    failed: ["Ошибка", "danger"],
    completed: ["Завершён", "olive"],
    warning: ["Требует внимания", "amber"],
  };
  const [label, tone] = labels[status] || [status, "blue"];
  return `<span class="badge badge--${tone}"><span class="status-dot"></span>${label}</span>`;
}

function metricCard(label, value, tone, icon, metric = "") {
  return `
    <article class="metric-card metric-card--${tone}">
      <span class="metric-icon" aria-hidden="true">${icon}</span>
      <strong ${metric ? `data-metric="${metric}"` : ""}>${value}</strong>
      <span>${label}</span>
    </article>`;
}

function materialById(id) {
  return state.materials.find((material) => material.id === id);
}

function packageById(id) {
  return state.packages.find((item) => item.id === id);
}

function materialThumb(material, size = "normal") {
  return `<span class="material-thumb material-thumb--${material.accent} material-thumb--${size}" aria-hidden="true"><span>${escapeHtml(material.category.slice(0, 1))}</span></span>`;
}

function contentCard(pkg, compact = false) {
  const material = materialById(pkg.materialId);
  return `
    <article class="content-card ${compact ? "content-card--compact" : ""}">
      ${materialThumb(material, compact ? "small" : "normal")}
      <div class="content-card-copy">
        <div class="content-card-meta">${statusBadge(pkg.status)}<span>${escapeHtml(pkg.created)}</span></div>
        <h3>${escapeHtml(pkg.title)}</h3>
        ${compact ? "" : `<p>${escapeHtml(pkg.excerpt)}</p>`}
        <div class="tag-row"><span>${escapeHtml(pkg.format)}</span><span>${escapeHtml(pkg.readTime)}</span><span>${escapeHtml(material.domain)}</span></div>
      </div>
      <button class="icon-button" type="button" data-action="open-package" data-id="${pkg.id}" aria-label="Открыть пакет «${escapeHtml(pkg.title)}»">→</button>
    </article>`;
}

function timelineSlot(slot) {
  const pkg = slot.packageId ? packageById(slot.packageId) : null;
  return `
    <article class="timeline-slot timeline-slot--${slot.tone}">
      <div class="timeline-marker" aria-hidden="true">${slot.id === "morning" ? "☼" : slot.id === "day" ? "◐" : "☾"}</div>
      <div class="timeline-copy">
        <div class="timeline-head"><div><strong>${slot.label}</strong><span>${slot.window}</span></div><time>${slot.time}</time></div>
        ${pkg ? `<button class="slot-package" type="button" data-action="open-package" data-id="${pkg.id}"><span>${escapeHtml(pkg.title)}</span><small>${escapeHtml(pkg.format)} · готов к публикации</small></button>` : `<div class="slot-empty"><span>Свободный слот</span><small>Одобрите пост — он появится здесь автоматически</small></div>`}
      </div>
    </article>`;
}

function renderOverview() {
  const review = state.packages.filter((item) => item.status === "needs_review");
  const approved = state.packages.filter((item) => item.status === "approved").length;
  const published = state.deliveries.filter((item) => item.status === "published").length;
  const selected = state.materials.filter((item) => item.status === "selected").length;
  return `
    <section class="screen screen--overview" data-screen="overview">
      <div class="dashboard-main">
        <section class="panel flow-panel">
          <div class="panel-head"><div><p class="section-kicker">Контентный конвейер</p><h2 class="panel-title">Сегодняшний поток</h2></div><span class="badge badge--olive">Обновлён в 09:04</span></div>
          <div class="metrics-flow panel-body">
            ${metricCard("Найдено", state.materials.length, "paper", "⌕")}
            <span class="flow-arrow" aria-hidden="true">›</span>
            ${metricCard("Выбрано", selected, "olive", "◇")}
            <span class="flow-arrow" aria-hidden="true">›</span>
            ${metricCard("Нужна проверка", review.length, "amber", "◷", "needs-review")}
            <span class="flow-arrow" aria-hidden="true">›</span>
            ${metricCard("Одобрено", approved, "leaf", "✓")}
            <span class="flow-arrow" aria-hidden="true">›</span>
            ${metricCard("Опубликовано", published, "forest", "↗")}
          </div>
        </section>

        <section class="panel attention-panel">
          <div class="panel-head"><div><p class="section-kicker">Следующее действие</p><h2 class="panel-title">Нужна проверка <span class="title-count">${review.length}</span></h2></div><a class="text-link" href="#review">Открыть очередь →</a></div>
          <div class="content-list panel-body">${review.slice(0, 3).map((item) => contentCard(item, true)).join("")}</div>
        </section>

        <section class="studio-strip">
          <div><span class="studio-symbol">◎</span><span><small>Источники</small><strong>1 активен</strong></span></div>
          <div><span class="studio-symbol">⌁</span><span><small>Правила отбора</small><strong>8 сигналов</strong></span></div>
          <div><span class="studio-symbol">◇</span><span><small>Готовые пакеты</small><strong>${state.packages.length}</strong></span></div>
          <div><span class="studio-symbol">↗</span><span><small>Автопостинг</small><strong class="text-olive">Активен</strong></span></div>
        </section>
      </div>

      <aside class="dashboard-side">
        <section class="panel day-plan">
          <div class="panel-head"><div><p class="section-kicker">12 августа</p><h2 class="panel-title">Ритм дня</h2></div><span class="plan-score">1/3</span></div>
          <div class="timeline panel-body">${state.slots.map(timelineSlot).join("")}</div>
        </section>
        <section class="panel runs-panel">
          <div class="panel-head"><h2 class="panel-title">Последние запуски</h2><a class="text-link" href="#journal">Все →</a></div>
          <div class="run-list panel-body">${state.runs.slice(0, 3).map((run) => `
            <button class="run-mini" type="button" data-action="open-run" data-id="${run.id}">
              <span class="run-play" aria-hidden="true">${run.status === "completed" ? "✓" : "!"}</span>
              <span><strong>${escapeHtml(run.kind)}</strong><small>${escapeHtml(run.started)}</small></span>
              ${statusBadge(run.status)}
            </button>`).join("")}</div>
        </section>
      </aside>
    </section>`;
}

function renderMaterials() {
  const counts = Object.fromEntries(["all", "new", "selected", "rejected"].map((status) => [status, status === "all" ? state.materials.length : state.materials.filter((item) => item.status === status).length]));
  const visible = state.ui.materialFilter === "all" ? state.materials : state.materials.filter((item) => item.status === state.ui.materialFilter);
  return `
    <section class="screen" data-screen="materials">
      <div class="page-intro"><div><h2>Найденные темы</h2><p>Каждое решение сохраняет источник и понятную причину.</p></div><span class="page-stat"><strong>${state.materials.length}</strong><small>за последние сутки</small></span></div>
      <div class="filter-bar" role="toolbar" aria-label="Фильтры материалов">
        ${[["all", "Все"], ["new", "Новые"], ["selected", "Выбраны"], ["rejected", "Отклонены"]].map(([value, label]) => `<button type="button" data-filter="${value}" class="filter-chip ${state.ui.materialFilter === value ? "is-active" : ""}">${label}<span>${counts[value]}</span></button>`).join("")}
        <label class="search-field"><span aria-hidden="true">⌕</span><span class="sr-only">Поиск материалов</span><input type="search" placeholder="Найти тему или источник" data-search="materials"></label>
      </div>
      <div class="materials-table panel">
        <div class="table-head"><span>Материал</span><span>Решение</span><span>Оценка</span><span>Найден</span><span></span></div>
        <div class="table-body">${visible.map((material) => `
          <article class="material-row" data-material-status="${material.status}">
            <div class="material-primary">${materialThumb(material, "small")}<span><strong>${escapeHtml(material.title)}</strong><small>${escapeHtml(material.domain)} · ${escapeHtml(material.category)}</small></span></div>
            <div>${statusBadge(material.status)}<small class="decision-reason">${escapeHtml(material.reason)}</small></div>
            <div class="score"><strong>${material.score}</strong><span>/100</span></div>
            <div><strong class="mobile-label">Найден: </strong>${escapeHtml(material.found)}<small>${escapeHtml(material.age)}</small></div>
            <button class="icon-button" type="button" data-action="open-material" data-id="${material.id}" aria-label="Подробнее о материале «${escapeHtml(material.title)}»">→</button>
          </article>`).join("")}</div>
      </div>
    </section>`;
}

function renderReview() {
  const review = state.packages.filter((item) => item.status === "needs_review");
  return `
    <section class="screen" data-screen="review">
      <div class="review-summary">
        <div><p class="section-kicker">Очередь редактора</p><h2>${review.length ? `Осталось проверить ${review.length}` : "Очередь разобрана"}</h2><p>Проверьте смысл, подачу и визуал перед попаданием в расписание.</p></div>
        <div class="review-ring" style="--progress:${Math.max(18, 100 - review.length * 18)}%"><span><strong data-metric="needs-review">${review.length}</strong><small>пакета</small></span></div>
      </div>
      <div class="review-layout">
        <div class="review-list">${review.map((item) => contentCard(item)).join("") || `<div class="empty-state panel"><div><strong>Всё проверено</strong><p>Новые пакеты появятся после следующего запуска подготовки.</p></div></div>`}</div>
        <aside class="review-guide panel"><p class="section-kicker">Фокус проверки</p><h2 class="panel-title">Три быстрых вопроса</h2><ol><li><span>1</span>Понятна ли польза с первых двух строк?</li><li><span>2</span>Подтверждает ли визуал смысл поста?</li><li><span>3</span>Есть ли честное ограничение или следующий шаг?</li></ol><p class="guide-note">Решение можно изменить до публикации.</p></aside>
      </div>
    </section>`;
}

function renderQueue() {
  const approved = state.packages.filter((item) => item.status === "approved" && !state.slots.some((slot) => slot.packageId === item.id));
  const filled = state.slots.filter((slot) => slot.packageId).length;
  return `
    <section class="screen" data-screen="queue">
      <div class="queue-hero panel">
        <div><p class="section-kicker">План на 12 августа</p><h2>${filled === 3 ? "День полностью собран" : `Заполнено ${filled} из 3 слотов`}</h2><p>${filled === 3 ? "Все публикации готовы к выходу." : "Одобренные посты занимают свободные слоты по порядку."}</p></div>
        <div class="day-progress" aria-label="Заполнено слотов: ${filled} из 3"><span style="--value:${filled / 3 * 100}%"></span><strong>${filled}/3</strong></div>
      </div>
      <div class="queue-layout">
        <section class="panel queue-timeline"><div class="panel-head"><h2 class="panel-title">Расписание</h2><span class="badge">Europe/Moscow</span></div><div class="timeline timeline--large panel-body">${state.slots.map(timelineSlot).join("")}</div></section>
        <aside class="queue-side">
          <section class="panel"><div class="panel-head"><h2 class="panel-title">Одобрено и ждёт</h2><span class="title-count">${approved.length}</span></div><div class="content-list panel-body">${approved.map((item) => contentCard(item, true)).join("") || `<div class="compact-empty"><span>Очередь пуста</span><small>Одобренные посты сразу занимают свободный слот.</small></div>`}</div></section>
          <section class="capacity-note"><span aria-hidden="true">✦</span><div><strong>Качество важнее квоты</strong><p>Если подходящих материалов не хватает, слот останется пустым.</p></div></section>
        </aside>
      </div>
    </section>`;
}

function renderPublications() {
  const published = state.deliveries.filter((item) => item.status === "published").length;
  const failed = state.deliveries.filter((item) => item.status === "failed").length;
  return `
    <section class="screen" data-screen="publications">
      <div class="page-intro"><div><h2>Доставка в Telegram</h2><p>Подтверждённые публикации и объяснимые ошибки в одном месте.</p></div><div class="intro-metrics"><span><strong>${published}</strong><small>доставлено</small></span><span><strong>${failed}</strong><small>нужна проверка</small></span></div></div>
      <div class="filter-bar"><button class="filter-chip is-active" type="button">Все <span>${state.deliveries.length}</span></button><button class="filter-chip" type="button">Опубликованы <span>${published}</span></button><button class="filter-chip" type="button">Ошибки <span>${failed}</span></button></div>
      <div class="publication-list panel">${state.deliveries.map((delivery) => `
        <article class="publication-row">
          <span class="publication-icon publication-icon--${delivery.status}" aria-hidden="true">${delivery.status === "published" ? "↗" : "!"}</span>
          <div class="publication-copy"><strong>${escapeHtml(delivery.title)}</strong><small>${escapeHtml(delivery.date)} · ${escapeHtml(delivery.time)} · Telegram</small></div>
          <div>${statusBadge(delivery.status)}</div>
          <div class="utility-value"><small>Message ID</small><code>${escapeHtml(delivery.messageId)}</code></div>
          <div class="utility-value"><small>Попыток</small><strong>${delivery.attempts}</strong></div>
          <button class="icon-button" type="button" data-action="open-delivery" data-id="${delivery.id}" aria-label="Открыть детали публикации">→</button>
        </article>`).join("")}</div>
    </section>`;
}

function renderJournal() {
  return `
    <section class="screen" data-screen="journal">
      <div class="journal-layout">
        <section class="panel"><div class="panel-head"><div><p class="section-kicker">Операции</p><h2 class="panel-title">Последние запуски</h2></div><button class="button button--quiet" type="button" data-action="new-run">＋ Запустить поиск</button></div><div class="journal-list panel-body">${state.runs.map((run) => `
          <button class="journal-row" type="button" data-action="open-run" data-id="${run.id}">
            <span class="run-play run-play--${run.status}" aria-hidden="true">${run.status === "completed" ? "✓" : "!"}</span>
            <span><strong>${escapeHtml(run.kind)}</strong><small>${escapeHtml(run.started)}</small></span>
            <span class="journal-result">${escapeHtml(run.result)}</span>
            <span class="utility-value"><small>Время</small><strong>${escapeHtml(run.duration)}</strong></span>
            ${statusBadge(run.status)}<span aria-hidden="true">→</span>
          </button>`).join("")}</div></section>
        <aside class="health-card panel"><div class="panel-head"><h2 class="panel-title">Контур системы</h2></div><div class="panel-body health-list"><div><span class="status-dot status-dot--ok"></span><span><strong>База данных</strong><small>Доступна</small></span></div><div><span class="status-dot status-dot--ok"></span><span><strong>Поиск материалов</strong><small>Следующий запуск завтра, 07:30</small></span></div><div><span class="status-dot status-dot--ok"></span><span><strong>Публикация</strong><small>Следующий слот сегодня, 14:00</small></span></div><div><span class="status-dot status-dot--ok"></span><span><strong>Telegram</strong><small>Последняя доставка подтверждена</small></span></div></div></aside>
      </div>
    </section>`;
}

function resetDemo() {
  state = cloneState(INITIAL_STATE);
  render();
  showToast("Демо-данные восстановлены");
}

function openDetail(markup, opener) {
  detailOpener = opener;
  detailContent.innerHTML = markup;
  detailLayer.showModal();
  detailLayer.querySelector("button, textarea")?.focus();
}

function closeDetail() {
  if (detailLayer.open) detailLayer.close();
}

function detailShell(titleText, kicker, body, actions = "") {
  return `
    <article class="detail-sheet">
      <header class="detail-head">
        <div><p class="section-kicker">${escapeHtml(kicker)}</p><h2 id="detail-title">${escapeHtml(titleText)}</h2></div>
        <button class="icon-button" type="button" data-action="close-detail" aria-label="Закрыть">×</button>
      </header>
      <div class="detail-body">${body}</div>
      ${actions ? `<footer class="detail-actions">${actions}</footer>` : ""}
    </article>`;
}

function openPackageDetail(id, opener) {
  const pkg = packageById(id);
  if (!pkg) return;
  const material = materialById(pkg.materialId);
  const body = `
    <div class="detail-visual detail-visual--${material.accent}"><span>${escapeHtml(material.category)}</span><strong>${escapeHtml(pkg.format)}</strong></div>
    <div class="detail-section"><span class="detail-label">Текст публикации</span><h3>${escapeHtml(pkg.title)}</h3><p class="post-lead">${escapeHtml(pkg.excerpt)}</p><p>Главная идея — начать с небольших повторяемых задач, измерить результат и только затем расширять автоматизацию. Такой подход сохраняет контроль и не заставляет команду менять весь процесс сразу.</p><ul><li>выберите один понятный сценарий;</li><li>зафиксируйте критерий полезного результата;</li><li>оставьте человеку финальное решение.</li></ul></div>
    <div class="source-card"><span>Источник</span><strong>${escapeHtml(material.title)}</strong><small>${escapeHtml(material.domain)} · оценка ${material.score}/100</small></div>
    <div id="reject-form-slot"></div>`;
  const actions = pkg.status === "needs_review" ? `
    <button class="button button--danger" type="button" data-action="show-reject-form" data-id="${pkg.id}">Отклонить</button>
    <button class="button button--primary" type="button" data-action="approve-package" data-id="${pkg.id}">✓ Одобрить пост</button>` : `<span class="detail-state">${statusBadge(pkg.status)} Решение уже принято</span>`;
  openDetail(detailShell(pkg.title, "Контентный пакет", body, actions), opener);
}

function openMaterialDetail(id, opener) {
  const material = materialById(id);
  if (!material) return;
  const body = `
    <div class="detail-visual detail-visual--${material.accent}"><span>${escapeHtml(material.category)}</span><strong>${material.score}<small>/100</small></strong></div>
    <div class="detail-facts"><div><span>Источник</span><strong>${escapeHtml(material.source)}</strong></div><div><span>Найден</span><strong>${escapeHtml(material.found)}</strong></div><div><span>Статус</span>${statusBadge(material.status)}</div></div>
    <div class="detail-section"><span class="detail-label">Почему принято такое решение</span><p class="decision-copy">${escapeHtml(material.reason)}</p></div>
    <div class="source-card"><span>Исходный материал</span><strong>${escapeHtml(material.domain)}</strong><small>Ссылка откроется после подключения реального backend</small></div>`;
  openDetail(detailShell(material.title, "Найденный материал", body), opener);
}

function openDeliveryDetail(id, opener) {
  const delivery = state.deliveries.find((item) => item.id === id);
  if (!delivery) return;
  const body = `
    <div class="detail-status-line">${statusBadge(delivery.status)}<span>${escapeHtml(delivery.date)} · ${escapeHtml(delivery.time)}</span></div>
    <div class="detail-section"><span class="detail-label">Публикация</span><h3>${escapeHtml(delivery.title)}</h3><p>${escapeHtml(delivery.detail)}</p></div>
    <div class="detail-facts"><div><span>Площадка</span><strong>Telegram</strong></div><div><span>Message ID</span><strong class="utility">${escapeHtml(delivery.messageId)}</strong></div><div><span>Попыток</span><strong>${delivery.attempts}</strong></div></div>
    <div class="attempt-history"><span class="detail-label">История</span><div><span class="attempt-dot attempt-dot--${delivery.status}"></span><span><strong>${delivery.status === "published" ? "Доставка подтверждена" : "Доставка завершилась ошибкой"}</strong><small>${escapeHtml(delivery.date)}, ${escapeHtml(delivery.time)}</small></span></div></div>`;
  openDetail(detailShell("История попыток", "Доставка контента", body), opener);
}

function openRunDetail(id, opener) {
  const run = state.runs.find((item) => item.id === id);
  if (!run) return;
  const body = `
    <div class="detail-status-line">${statusBadge(run.status)}<span>${escapeHtml(run.started)}</span></div>
    <div class="detail-section"><span class="detail-label">${escapeHtml(run.kind)}</span><h3>${escapeHtml(run.result)}</h3><p>${escapeHtml(run.detail)}</p></div>
    <div class="detail-facts"><div><span>Идентификатор</span><strong class="utility">run-${run.id}</strong></div><div><span>Длительность</span><strong>${escapeHtml(run.duration)}</strong></div><div><span>Среда</span><strong>Production</strong></div></div>
    <div class="log-fragment"><span>07:30:00</span> Запуск создан<br><span>07:30:01</span> Источник доступен<br><span>07:30:42</span> ${escapeHtml(run.result)}<br><span>07:30:42</span> Состояние сохранено</div>`;
  openDetail(detailShell("Подробности запуска", "Журнал системы", body), opener);
}

function showRejectForm(id) {
  const slot = document.querySelector("#reject-form-slot");
  if (!slot) return;
  slot.innerHTML = `
    <div class="reject-form">
      <label for="reject-reason">Почему пост не подходит?</label>
      <textarea id="reject-reason" rows="3" placeholder="Например: слишком общий текст без конкретного примера"></textarea>
      <p class="field-error" id="reject-error" role="alert"></p>
      <button class="button button--danger button--full" type="button" data-action="reject-package" data-id="${id}">Подтвердить отклонение</button>
    </div>`;
  document.querySelector("#reject-reason").focus();
}

function approvePackage(id) {
  const pkg = packageById(id);
  if (!pkg || pkg.status !== "needs_review") return;
  pkg.status = "approved";
  const freeSlot = state.slots.find((slot) => slot.packageId === null);
  if (freeSlot) freeSlot.packageId = pkg.id;
  closeDetail();
  render();
  showToast("Пост одобрен");
}

function rejectPackage(id) {
  const reasonField = document.querySelector("#reject-reason");
  const error = document.querySelector("#reject-error");
  const reason = reasonField?.value.trim() || "";
  if (!reason) {
    error.textContent = "Укажите причину отклонения";
    reasonField?.focus();
    return;
  }
  const pkg = packageById(id);
  if (!pkg || pkg.status !== "needs_review") return;
  pkg.status = "rejected";
  pkg.rejectReason = reason;
  closeDetail();
  render();
  showToast("Пост отклонён");
}

function showToast(message) {
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = message;
  toastRegion.replaceChildren(toast);
  window.setTimeout(() => toast.remove(), 3200);
}

function handleAction(actionNode) {
  const id = Number(actionNode.dataset.id);
  const actions = {
    "open-package": () => openPackageDetail(id, actionNode),
    "open-material": () => openMaterialDetail(id, actionNode),
    "open-delivery": () => openDeliveryDetail(id, actionNode),
    "open-run": () => openRunDetail(id, actionNode),
    "close-detail": closeDetail,
    "show-reject-form": () => showRejectForm(id),
    "approve-package": () => approvePackage(id),
    "reject-package": () => rejectPackage(id),
    "new-run": () => showToast("Демонстрационный запуск создан"),
    "open-mobile-menu": () => openDetail(detailShell("Ещё", "Навигация", `<div class="mobile-menu-sheet"><a href="#publications" data-route="publications">Публикации</a><a href="#journal" data-route="journal">Журнал работы</a><span>Настройки фермы <small>Следующий этап</small></span><span>Аналитика <small>Следующий этап</small></span></div>`), actionNode),
  };
  actions[actionNode.dataset.action]?.();
}

window.addEventListener("hashchange", render);
document.addEventListener("click", (event) => {
  const routeLink = event.target.closest("a[data-route]");
  if (routeLink) {
    event.preventDefault();
    closeDetail();
    navigate(routeLink.dataset.route);
    return;
  }
  const filter = event.target.closest("[data-filter]");
  if (filter) {
    state.ui.materialFilter = filter.dataset.filter;
    render();
    return;
  }
  const actionNode = event.target.closest("[data-action]");
  if (actionNode) handleAction(actionNode);
});
document.querySelector("#demo-reset").addEventListener("click", resetDemo);
detailLayer.addEventListener("close", () => {
  detailOpener?.focus();
  detailOpener = null;
});

if (!window.location.hash || !Object.hasOwn(routes, window.location.hash.slice(1))) {
  navigate("overview");
} else {
  render();
}

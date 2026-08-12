const LABELS = {
  awaiting_review: "Ждёт проверки", approved: "Одобрен", rejected: "Отклонён",
  selected: "Выбран", eligible_for_ai: "Подходит для анализа",
  advertising: "Реклама", out_of_scope: "Вне темы", hiring: "Вакансия",
  technical_without_use: "Технический релиз без практической пользы",
  not_started: "Не начат", processing: "Обрабатывается",
  forecast: "Прогноз", confirmed: "Подтверждён", empty: "Свободно",
  sending: "Отправляется", published: "Опубликовано", failed: "Ошибка",
  retryable: "Можно повторить", uncertain: "Результат не подтверждён",
  available: "Доступно", unavailable: "Недоступно", deleted: "Удалено",
  run_once: "Поиск и подготовка", publish_once: "Публикация", running: "Выполняется",
  succeeded: "Успешно", completed: "Завершено",
  cleanup_completed: "Медиа очищено", cleanup_pending: "Ожидает очистки медиа",
  run_once_failed: "Поиск завершился ошибкой",
  publish_once_failed: "Публикация завершилась ошибкой",
  media_unavailable: "Медиа недоступно",
  telegram_transport_uncertain: "Ответ канала не подтверждён",
  telegram_invalid_response: "Некорректный ответ канала",
  telegram_retryable: "Канал временно недоступен",
  telegram_rejected: "Канал отклонил публикацию",
  stale_sending: "Отправка не завершена",
};

export const escapeHtml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;").replaceAll("'", "&#039;");

export function externalLink(value) {
  const text = escapeHtml(value);
  try {
    const url = new URL(String(value));
    if (url.protocol === "http:" || url.protocol === "https:") {
      return `<a href="${escapeHtml(url.href)}" target="_blank" rel="noopener noreferrer">${text}</a>`;
    }
  } catch (_) { /* invalid API URL stays non-clickable */ }
  return `<span>${text}</span>`;
}

const label = (code) => code ? (LABELS[code] || "Неизвестное состояние") : "—";
const dateTime = (value) => value ? new Intl.DateTimeFormat("ru-RU", {day: "numeric", month: "short", hour: "2-digit", minute: "2-digit"}).format(new Date(value)) : "—";
const statusBadge = (code) => `<span class="status-badge status-badge--${escapeHtml(code || "neutral")}">${escapeHtml(label(code))}</span>`;
const empty = (text) => `<section class="empty-state"><span aria-hidden="true">◇</span><h2>${escapeHtml(text)}</h2><p>Новые данные появятся после следующей операции.</p></section>`;

export function renderOverview(data) {
  return `<section class="screen" data-screen="overview">
    <div class="studio-strip">
      <div><small>Найдено материалов</small><strong data-metric="candidates">${escapeHtml(data.candidate_total)}</strong></div>
      <div><small>Ждут решения</small><strong>${escapeHtml(data.undecided_materials)}</strong></div>
      <div><small>Пакетов сегодня</small><strong>${escapeHtml(data.daily_packages_created)}</strong></div>
    </div>
    <div class="overview-grid">
      <section class="panel"><div class="panel-head"><div><p class="section-kicker">Редакторский поток</p><h2 class="panel-title">Состояние контента</h2></div></div>
        <div class="metric-grid panel-body">
          <article class="metric-card"><span>Выбрано</span><strong>${escapeHtml(data.selected_materials)}</strong></article>
          <article class="metric-card"><span>Ждёт проверки</span><strong>${escapeHtml(data.package_total - data.approved_packages)}</strong></article>
          <article class="metric-card"><span>Одобрено</span><strong>${escapeHtml(data.approved_packages)}</strong></article>
          <article class="metric-card"><span>Опубликовано</span><strong>${escapeHtml(data.published_today)}</strong></article>
        </div>
      </section>
      <section class="panel"><div class="panel-head"><div><p class="section-kicker">Лимиты</p><h2 class="panel-title">Сегодня</h2></div></div>
        <div class="panel-body quiet-list"><p><span>Запущено анализов</span><strong>${escapeHtml(data.daily_analyses_started)}</strong></p><p><span>Создано пакетов</span><strong>${escapeHtml(data.daily_packages_created)}</strong></p></div>
      </section>
    </div>
  </section>`;
}

export function renderMaterials(data) {
  const items = data.items || [];
  if (!items.length) return `<section class="screen" data-screen="materials">${empty("Материалов пока нет")}</section>`;
  return `<section class="screen" data-screen="materials">
    <div class="filter-row" aria-label="Фильтр материалов">${[["all", "Все"], ["selected", "Выбраны"], ["rejected", "Отклонены"]].map(([value, title]) => `<button class="filter-chip" type="button" data-filter="${value}">${title}</button>`).join("")}</div>
    <div class="material-list">${items.map((item) => `<article class="material-row" data-material-status="${escapeHtml(item.decision_status || "new")}">
      <div class="material-source"><span class="source-monogram">${escapeHtml((item.source_name || "?").slice(0, 1))}</span><span>${escapeHtml(item.source_name)}</span></div>
      <div class="material-copy"><small>№ ${escapeHtml(item.candidate_id)} · ${escapeHtml(dateTime(item.discovered_at))}</small><h2>${escapeHtml(item.title)}</h2><p>${escapeHtml(item.decision_explanation || label(item.decision_reason))}</p></div>
      <div class="material-state">${statusBadge(item.decision_status)}<button class="icon-button" type="button" data-action="open-material" data-id="${escapeHtml(item.candidate_id)}" aria-label="Подробнее">→</button></div>
    </article>`).join("")}</div></section>`;
}

export function renderReview(data) {
  const items = data.items || [];
  if (!items.length) return `<section class="screen" data-screen="review">${empty("Пакетов для проверки нет")}</section>`;
  return `<section class="screen" data-screen="review"><div class="review-summary"><p class="section-kicker">Редакторская проверка</p><strong data-metric="needs-review">${items.filter((item) => item.status === "awaiting_review").length}</strong><span>пакетов требуют решения</span></div>
    <div class="review-list">${items.map((item) => `<article class="content-card">
      <div class="material-thumb" aria-hidden="true">P</div><div class="content-card-copy"><div>${statusBadge(item.status)} <small>№ ${escapeHtml(item.package_id)}</small></div><h2>${escapeHtml(item.post_text)}</h2><p>${escapeHtml(item.source_url)}</p></div>
      <button class="icon-button" type="button" data-action="open-package" data-id="${escapeHtml(item.package_id)}" aria-label="Открыть пакет">→</button>
    </article>`).join("")}</div></section>`;
}

export function renderQueue(data) {
  const items = data.items || [];
  if (!items.length) return `<section class="screen" data-screen="queue">${empty("Очередь пока пуста")}</section>`;
  return `<section class="screen" data-screen="queue"><div class="queue-head"><div><p class="section-kicker">Ритм дня</p><h2>План публикаций</h2></div></div><div class="timeline">${items.map((item) => `<article class="timeline-slot"><div class="timeline-marker"></div><time>${escapeHtml(item.slot_time)}</time><div class="slot-package"><strong>Пакет № ${escapeHtml(item.package_id || "—")}</strong><span>${statusBadge(item.assignment_kind)}</span><small>${escapeHtml(item.provider)}</small></div></article>`).join("")}</div></section>`;
}

export function renderPublications(data) {
  const items = data.items || [];
  if (!items.length) return `<section class="screen" data-screen="publications">${empty("Публикаций пока нет")}</section>`;
  return `<section class="screen" data-screen="publications"><div class="table-shell"><div class="table-head"><span>Публикация</span><span>Канал</span><span>Состояние</span><span>Время</span><span></span></div>${items.map((item) => `<article class="table-row"><span><strong>№ ${escapeHtml(item.delivery_id)}</strong><small>Пакет ${escapeHtml(item.package_id)}</small></span><span>${escapeHtml(item.provider || "—")}</span><span>${statusBadge(item.status)}</span><span>${escapeHtml(dateTime(item.confirmed_at || item.sending_started_at))}</span><button class="icon-button" type="button" data-action="open-delivery" data-id="${escapeHtml(item.delivery_id)}" aria-label="Подробности">→</button></article>`).join("")}</div></section>`;
}

export function renderJournal(data) {
  const items = data.items || [];
  if (!items.length) return `<section class="screen" data-screen="journal">${empty("Запусков пока нет")}</section>`;
  return `<section class="screen" data-screen="journal"><div class="journal-toolbar"><div><p class="section-kicker">Операции</p><h2>Последние запуски</h2></div><div><button class="button button--quiet" type="button" data-action="publish-once">Опубликовать один</button><button class="button button--primary" type="button" data-action="new-run">＋ Запустить поиск</button></div></div><div class="journal-list">${items.map((item) => `<button class="journal-row" type="button" data-action="open-run" data-id="${escapeHtml(item.run_id)}"><span class="run-icon">↻</span><span><strong>№ ${escapeHtml(item.run_id)} · ${escapeHtml(label(item.kind))}</strong><small>${escapeHtml(dateTime(item.started_at))}</small></span>${statusBadge(item.status)}<span>${escapeHtml(item.duration ?? "—")} сек.</span><span>→</span></button>`).join("")}</div></section>`;
}

export function renderSettingsPlaceholder() {
  return `<section class="screen" data-screen="settings"><section class="empty-state settings-placeholder"><span aria-hidden="true">⚙</span><h2>Настройки проекта</h2><p>Редактирование настроек появится на следующем этапе. Раздел уже доступен по постоянному адресу.</p></section></section>`;
}

export const screens = {overview: renderOverview, materials: renderMaterials, review: renderReview, queue: renderQueue, publications: renderPublications, journal: renderJournal};
export {dateTime, label, statusBadge};

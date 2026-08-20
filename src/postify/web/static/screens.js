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
  run_once: "Поиск и подготовка", manual_search: "Новый поиск", publish_once: "Публикация", load_more: "Подобрать ещё", retry_analysis: "Повторить анализ", return_to_analysis: "Вернуть в анализ", regenerate_post: "Перегенерировать пост", replace_media: "Заменить медиа", publish_now: "Опубликовать сейчас", retry_delivery: "Повторить отправку", manual: "Вручную", automatic: "Автоматически", running: "Выполняется",
  ui: "Интерфейс", scheduler: "Планировщик",
  succeeded: "Успешно", completed: "Завершено", active: "Активен",
  cleanup_completed: "Медиа очищено", cleanup_pending: "Ожидает очистки медиа",
  run_once_failed: "Поиск завершился ошибкой",
  publish_once_failed: "Публикация завершилась ошибкой",
  media_unavailable: "Медиа недоступно",
  telegram_transport_uncertain: "Ответ канала не подтверждён",
  telegram_invalid_response: "Некорректный ответ канала",
  telegram_retryable: "Канал временно недоступен",
  telegram_rejected: "Канал отклонил публикацию",
  stale_sending: "Отправка не завершена",
  eligible_source_shortage: "Недостаточно подходящих источников",
  content_failures: "Ошибки обработки",
  warning: "Предупреждение", critical: "Критическая ошибка",
  content_attempt_failed: "Ошибка анализа контента",
  codex_output_unavailable: "Ответ Codex недоступен",
  codex_output_not_json: "Codex вернул не JSON",
  codex_output_schema_mismatch: "Ответ Codex не соответствует схеме",
  codex_output_domain_invalid: "Ответ Codex нарушает правила контента",
  codex_output_source_url_forbidden: "Codex добавил запрещённый URL источника",
  review_unresolved: "Сначала разберите текущие пакеты",
  load_more_failed: "Подбор постов завершился ошибкой",
  retry_analysis_failed: "Повторный анализ завершился ошибкой",
  return_to_analysis_failed: "Возврат в анализ завершился ошибкой",
  regenerate_post_failed: "Перегенерация поста завершилась ошибкой",
  replace_media_failed: "Замена медиа завершилась ошибкой",
  publish_now_failed: "Публикация завершилась ошибкой",
  retry_delivery_failed: "Повторная отправка завершилась ошибкой",
  manual_search_failed: "Поиск завершился ошибкой",
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
  const signals = (data.signals || []).map((item) => `<li>${statusBadge(item.severity)} <span>${escapeHtml(label(item.code))}</span><strong>${escapeHtml(item.count)}</strong></li>`).join("") || "<li>Проблем нет</li>";
  const operations = (data.recent_operations || []).map((item) => `<li><span><strong>${escapeHtml(label(item.operation))}</strong><small>${escapeHtml(dateTime(item.finished_at || item.started_at))}</small></span>${statusBadge(item.status)}</li>`).join("") || "<li>Запусков пока нет</li>";
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
        <div class="panel-body quiet-list"><p><span>Автоматические анализы</span><strong>${escapeHtml(data.daily_analyses_started)} / ${escapeHtml(data.automaticAnalysisLimit ?? "—")}</strong></p><p><span>Ручные анализы</span><strong>${escapeHtml(data.manual_analyses_started ?? 0)}</strong></p><p><span>Создано автоматически</span><strong>${escapeHtml(data.daily_packages_created)} / ${escapeHtml(data.automaticPackageLimit ?? "—")}</strong></p><p><span>Создано вручную</span><strong>${escapeHtml(data.manual_packages_created ?? 0)}</strong></p><p><span>Дефицит</span><strong>${escapeHtml(data.deficit ?? 0)}</strong></p><p><span>Готово к доставке</span><strong>${escapeHtml((data.ready_delivery_ids || []).length)}</strong></p><ul class="signal-list">${signals}</ul></div>
      </section>
    </div>
    <section class="panel recent-operations"><div class="panel-head"><div><p class="section-kicker">Журнал</p><h2 class="panel-title">Последние операции</h2></div></div><ul class="operation-summary panel-body">${operations}</ul></section>
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
  const activeItems = items.filter((item) => item.status === "awaiting_review");
  const historyItems = items.filter((item) => item.status !== "awaiting_review");
  const loadState = data.loadMoreState || {status: "default"};
  const unresolvedIds = [...new Set([
    ...activeItems.map((item) => item.package_id),
    ...(loadState.status === "unresolved" ? loadState.unresolvedPackageIds || [] : []),
  ])];
  const unresolved = unresolvedIds.length > 0;
  let loadMore = `<button class="button button--primary" type="button" data-action="load-more"${unresolved ? " disabled aria-describedby=\"review-unresolved\"" : ""}>Подобрать ещё 3 поста</button>`;
  if (loadState.status === "running") loadMore = `<button class="button button--primary" type="button" data-action="load-more" disabled aria-busy="true">Анализируем материалы…</button>`;
  else if (loadState.status === "empty") loadMore = `<button class="button button--quiet" type="button" disabled>Новых материалов нет. Запустите новый поиск.</button>`;
  else if (loadState.status === "failed") loadMore = `<p class="settings-error">Подбор постов завершился ошибкой.</p><button class="button button--primary" type="button" data-action="load-more">Повторить</button>`;
  else if (loadState.status === "unresolved") loadMore = `<button class="button button--primary" type="button" disabled aria-describedby="review-unresolved">Подобрать ещё 3 поста</button>`;
  const unresolvedHint = unresolved ? `<p id="review-unresolved">Сначала одобрите или отклоните пакеты: ${unresolvedIds.map((id) => `№ ${escapeHtml(id)}`).join(", ")}.</p>` : "";
  const cards = (values) => values.map((item) => `<article class="content-card">
      <div class="material-thumb" aria-hidden="true">P</div><div class="content-card-copy"><div>${statusBadge(item.status)} <small>№ ${escapeHtml(item.package_id)}</small></div><h2>${escapeHtml(item.post_text)}</h2><p>${escapeHtml(item.source_url)}</p></div>
      <button class="icon-button" type="button" data-action="open-package" data-id="${escapeHtml(item.package_id)}" aria-label="Открыть пакет">→</button>
    </article>`).join("");
  if (!items.length) return `<section class="screen" data-screen="review">${empty("Пакетов для проверки нет")}<div class="review-load-more">${unresolvedHint}${loadMore}</div></section>`;
  return `<section class="screen" data-screen="review"><div class="review-summary"><p class="section-kicker">Редакторская проверка</p><strong data-metric="needs-review">${unresolvedIds.length}</strong><span>пакетов требуют решения</span>${unresolvedHint}${loadMore}</div>
    <div class="review-list">${cards(activeItems)}</div>${historyItems.length ? `<section class="review-history"><h2>История решений</h2><div class="review-list">${cards(historyItems)}</div></section>` : ""}</section>`;
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
  const operational = data.operational || {};
  const runtime = operational.runtime || {};
  const signalSummary = (operational.signals || []).map((item) => `${label(item.code)}: ${item.count}`).join(" · ") || "Проблем нет";
  const deficitReasons = (operational.deficit_reasons || []).map(label).join(" · ") || "Причин дефицита нет";
  const journal = items.length ? items.map((item) => `<button class="journal-row" type="button" data-action="open-run" data-id="${escapeHtml(item.run_id)}"><span class="run-icon">↻</span><span><strong>№ ${escapeHtml(item.run_id)} · ${escapeHtml(label(item.kind))}</strong><small><span>${escapeHtml(label(item.mode))}</span> · ${escapeHtml(dateTime(item.started_at))}</small></span>${statusBadge(item.status)}<span>${escapeHtml(item.duration ?? "—")} сек.</span><span>→</span></button>`).join("") : empty("Запусков пока нет");
  return `<section class="screen" data-screen="journal"><div class="journal-toolbar"><div><p class="section-kicker">Операции</p><h2>Последние запуски</h2><small>Дефицит: ${escapeHtml(operational.deficit ?? 0)} · ${escapeHtml(signalSummary)} · <span>${escapeHtml(deficitReasons)}</span></small><div class="runtime-state"><span>База данных: ${escapeHtml(label(runtime.database))}</span><span>Планировщик: ${escapeHtml(label(runtime.scheduler))}</span></div></div><div><button class="button button--quiet" type="button" data-action="publish-once">Опубликовать один</button><button class="button button--primary" type="button" data-action="new-run">＋ Запустить поиск</button></div></div><div class="journal-list">${journal}</div></section>`;
}

export const screens = {overview: renderOverview, materials: renderMaterials, review: renderReview, queue: renderQueue, publications: renderPublications, journal: renderJournal};
export {dateTime, label, statusBadge};

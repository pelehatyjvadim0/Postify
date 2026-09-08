const LABELS = {
  planned: "Запланирован", overdue: "Нужен перенос даты",
  packaged: "Пост подготовлен", retry_scheduled: "Ожидает повтора",
  retried: "Передан на повтор", analyzed_not_selected: "Не выбран для поста",
  awaiting_review: "Ждёт проверки", approved: "Одобрен", rejected: "Отклонён",
  selected: "Выбран", eligible_for_ai: "Подходит для поста",
  advertising: "Реклама", out_of_scope: "Вне темы", hiring: "Вакансия",
  technical_without_use: "Технический релиз без практической пользы",
  not_started: "Не начат", processing: "Обрабатывается",
  forecast: "Прогноз", confirmed: "Подтверждён", empty: "Свободно",
  sending: "Отправляется", published: "Опубликовано", failed: "Ошибка",
  retryable: "Можно повторить", uncertain: "Результат не подтверждён",
  available: "Доступно", unavailable: "Недоступно", deleted: "Удалено",
  run_once: "Поиск и подготовка", manual_search: "Новый поиск", publish_once: "Публикация", load_more: "Подобрать ещё", retry_analysis: "Повторить подготовку", return_to_analysis: "Подготовить заново", regenerate_post: "Переписать пост", replace_media: "Заменить вложение", publish_now: "Опубликовать сейчас", retry_delivery: "Повторить отправку", manual: "Вручную", automatic: "Автоматически", running: "Выполняется",
  ui: "Вручную", scheduler: "Автоматически",
  succeeded: "Успешно", completed: "Завершено", active: "Активен",
  cleanup_completed: "Вложение удалено", cleanup_pending: "Вложение ожидает удаления",
  run_once_failed: "Поиск завершился ошибкой",
  publish_once_failed: "Публикация завершилась ошибкой",
  media_unavailable: "Вложение недоступно",
  telegram_transport_uncertain: "Ответ канала не подтверждён",
  telegram_invalid_response: "Некорректный ответ канала",
  telegram_retryable: "Канал временно недоступен",
  telegram_rejected: "Канал отклонил публикацию",
  stale_sending: "Отправка не завершена",
  eligible_source_shortage: "Недостаточно подходящих источников",
  content_failures: "Ошибки обработки",
  warning: "Предупреждение", critical: "Критическая ошибка",
  content_attempt_failed: "Не удалось подготовить пост",
  gemini_not_configured: "Подготовка постов недоступна. Проверьте настройки подключения.",
  gemini_timeout: "Не удалось подготовить пост вовремя. Повторите позже.",
  gemini_access_denied: "Подготовка постов недоступна. Проверьте настройки подключения.",
  gemini_rate_limited: "Достигнут лимит подготовки постов. Попробуйте позже.",
  gemini_unavailable: "Подготовка постов временно недоступна",
  gemini_output_invalid: "Не удалось подготовить пост. Попробуйте ещё раз.",
  generation_capacity_exceeded: "Превышен объём подготовки постов",
  codex_output_unavailable: "Не удалось получить готовый пост",
  codex_failed: "Не удалось подготовить пост",
  codex_output_not_json: "Не удалось подготовить пост. Попробуйте ещё раз.",
  codex_output_schema_mismatch: "Не удалось подготовить пост. Попробуйте ещё раз.",
  codex_output_domain_invalid: "Пост не соответствует правилам отбора",
  codex_output_source_url_forbidden: "В посте обнаружена недопустимая ссылка",
  review_unresolved: "Сначала проверьте текущие посты",
  review_required: "Проверьте готовые посты",
  review_backlog: "Есть посты на проверке",
  package_limit_reached: "Достигнут дневной лимит постов",
  analysis_limit_reached: "Достигнут дневной лимит обработки материалов",
  load_more_failed: "Подбор постов завершился ошибкой",
  retry_analysis_failed: "Не удалось подготовить пост заново",
  return_to_analysis_failed: "Не удалось подготовить пост заново",
  regenerate_post_failed: "Не удалось переписать пост",
  replace_media_failed: "Не удалось заменить вложение",
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
const empty = (text) => `<section class="empty-state"><span aria-hidden="true">◇</span><h2>${escapeHtml(text)}</h2></section>`;
export const sourceName = (value) => ({telegram_group: "Telegram", telegram_account: "Telegram", telegram: "Telegram", telegram_bot: "Telegram"})[value] || value || "Источник";

export function renderJournal(data) {
  const items = data.items || [];
  const journal = items.length ? items.map((item) => `<button class="journal-row" type="button" data-action="open-run" data-id="${escapeHtml(item.run_id)}"><span class="run-icon" aria-hidden="true">↻</span><span><strong>${escapeHtml(label(item.kind))}</strong><small>${escapeHtml(dateTime(item.started_at))}</small></span>${statusBadge(item.status)}<span aria-hidden="true">→</span></button>`).join("") : empty("Действий пока нет");
  return `<section class="screen" data-screen="journal"><div class="journal-list">${journal}</div></section>`;
}

export {dateTime, label, statusBadge};

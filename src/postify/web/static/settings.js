import {escapeHtml} from "./screens.js";

const joinTerms = (values) => (values || []).join(", ");
const checked = (value) => value ? " checked" : "";
const selected = (value, current) => String(value) === String(current) ? " selected" : "";

function input(label, name, value, options = {}) {
  const type = options.type || "text";
  const attrs = [
    `type="${escapeHtml(type)}"`, `name="${escapeHtml(name)}"`,
    `value="${escapeHtml(value ?? "")}"`, options.required ? "required" : "",
    options.min !== undefined ? `min="${escapeHtml(options.min)}"` : "",
    options.max !== undefined ? `max="${escapeHtml(options.max)}"` : "",
    options.step !== undefined ? `step="${escapeHtml(options.step)}"` : "",
    options.placeholder ? `placeholder="${escapeHtml(options.placeholder)}"` : "",
    options.omitEmpty ? "data-omit-empty" : "",
    options.nullEmpty ? "data-null-empty" : "",
    options.array ? "data-array" : "",
    options.multi ? "data-multi" : "",
  ].filter(Boolean).join(" ");
  return `<label class="settings-field"><span>${escapeHtml(label)}</span><input ${attrs}></label>`;
}

function checkbox(label, name, value, options = {}) {
  return `<label class="settings-check"><input type="checkbox" name="${escapeHtml(name)}" value="${escapeHtml(options.value ?? "true")}"${checked(value)}${options.multi ? " data-multi" : ""}><span>${escapeHtml(label)}</span></label>`;
}

function selectField(label, name, current, options, attrs = "") {
  return `<label class="settings-field"><span>${escapeHtml(label)}</span><select name="${escapeHtml(name)}" ${attrs}>${options.map((option) => `<option value="${escapeHtml(option.value)}"${selected(option.value, current)}>${escapeHtml(option.label)}</option>`).join("")}</select></label>`;
}

function savebar() {
  return `<p class="settings-error" data-settings-error role="alert"></p><footer class="settings-savebar" hidden><span>Есть несохранённые изменения</span><button class="button button--primary" type="submit">Сохранить</button></footer>`;
}

function details(key, title, summary, body, open = false) {
  return `<details class="settings-section" name="postify-settings" data-settings-section="${key}"${open ? " open" : ""}><summary><span>${title}</span><small class="settings-summary-current">${escapeHtml(summary)}</small></summary><div class="settings-section-body">${body}</div></details>`;
}

const catalogFor = (providers, kind) => providers?.[kind] || [];
const providerMeta = (providers, kind, code) => catalogFor(providers, kind).find((item) => item.code === code) || {fields: []};

function providerSelect(providers, kind, current) {
  const label = kind === "sources" ? "Провайдер источника" : "Провайдер канала";
  return selectField(label, "provider", current, catalogFor(providers, kind).map((item) => ({value: item.code, label: item.label})), `required data-provider-kind="${kind}"`);
}

export function renderProviderConfiguration(providers, kind, code, configuration = {}) {
  return providerMeta(providers, kind, code).fields.map((field) => input(
    field.label,
    `configuration.${field.name}`,
    configuration[field.name],
    field,
  )).join("");
}

function mainForm(project) {
  return `<form class="settings-form" data-settings-form="main" novalidate><div class="settings-grid">
    ${input("Название проекта", "name", project.name, {required: true})}
    ${input("Тема", "topic", project.topic, {required: true})}
    ${input("Язык", "language", project.language, {required: true})}
    ${input("Аудитория", "audience", project.audience, {required: true})}
    ${input("Часовой пояс", "timezone", project.timezone, {required: true})}
  </div>${savebar()}</form>`;
}

function sourceForm(source, providers, mode = "update") {
  const provider = source.provider || catalogFor(providers, "sources")[0]?.code || "";
  return `<form class="settings-form resource-form" data-settings-form="sources" data-resource="sources" data-resource-id="${escapeHtml(source.id || "")}" data-resource-mode="${mode}"${mode === "create" ? " hidden" : ""} novalidate>
    <div class="resource-heading"><strong>${mode === "create" ? "Новый источник" : escapeHtml(source.name)}</strong>${mode === "update" ? `<button class="button button--quiet" type="button" data-settings-delete>Удалить</button>` : ""}</div>
    <div class="settings-grid">${providerSelect(providers, "sources", provider)}${input("Название источника", "name", source.name, {required: true})}<div class="provider-fields" data-provider-fields>${renderProviderConfiguration(providers, "sources", provider, source.configuration)}</div>${input("Расписание получения", "schedule", source.schedule, {required: true})}</div>
    ${checkbox("Источник включён", "enabled", source.enabled ?? true)}${savebar()}</form>`;
}

function selectionForm(config) {
  const rules = new Set(config.selection_rules || []);
  return `<form class="settings-form" data-settings-form="selection" data-settings-section-api="configuration" novalidate>
    <div class="policy-note"><span>Версия политики</span><strong>${escapeHtml(config.selection_policy_version)}</strong></div>
    <div class="settings-grid">${input("Окно свежести, дней", "selection_freshness_days", config.selection_freshness_days, {type: "number", min: 1, required: true})}${input("Тематические маркеры", "topic_terms", joinTerms(config.topic_terms), {array: true})}${input("Исключающие маркеры", "topic_exclusion_terms", joinTerms(config.topic_exclusion_terms), {array: true})}${input("Маркеры рекламы", "advertising_terms", joinTerms(config.advertising_terms), {array: true})}${input("Маркеры найма", "hiring_terms", joinTerms(config.hiring_terms), {array: true})}${input("Маркеры технического релиза", "technical_release_terms", joinTerms(config.technical_release_terms), {array: true})}${input("Практические маркеры", "practical_terms", joinTerms(config.practical_terms), {array: true})}</div>
    <fieldset class="settings-rule-list"><legend>Отсеивать</legend>${[["advertising", "Рекламу"], ["out_of_scope", "Нерелевантное"], ["hiring", "Найм"], ["technical_without_use", "Технический релиз без пользы"]].map(([value, label]) => checkbox(label, "selection_rules", rules.has(value), {multi: true, value})).join("")}</fieldset>${savebar()}</form>`;
}

function generationForm(config, formats, routes) {
  const selectedFormat = formats.find((format) => format.id === routes[0]?.format_id) || formats[0];
  return `<form class="settings-form" data-settings-form="generation" data-settings-section-api="configuration" novalidate><div class="settings-grid">${input("Дневной лимит анализа", "daily_analysis_limit", config.daily_analysis_limit, {type: "number", min: 1, required: true})}${input("Дневной лимит пакетов", "daily_package_limit", config.daily_package_limit, {type: "number", min: 1, required: true})}${input("Доля свежих, %", "fresh_share_percent", config.fresh_share_percent, {type: "number", min: 0, max: 100, required: true})}${input("Доля резервных, %", "reserve_share_percent", config.reserve_share_percent, {type: "number", min: 0, max: 100, required: true})}${input("Приоритетная свежесть, дней", "priority_freshness_days", config.priority_freshness_days, {type: "number", min: 1, required: true})}</div>${checkbox("Обязательная ручная проверка", "review_required", config.review_required)}${selectedFormat ? `<article class="format-note"><span>${escapeHtml(selectedFormat.kind)}</span><strong>${escapeHtml(selectedFormat.name)}</strong><p>${escapeHtml(selectedFormat.instructions)}</p></article>` : ""}${savebar()}</form>`;
}

function ctaForm(cta, mode = "update") {
  return `<form class="settings-form resource-form" data-settings-form="cta" data-resource="ctas" data-resource-id="${escapeHtml(cta.id || "")}" data-resource-mode="${mode}"${mode === "create" ? " hidden" : ""} novalidate><div class="resource-heading"><strong>${mode === "create" ? "Новый CTA" : escapeHtml(cta.name)}</strong>${mode === "update" ? `<button class="button button--quiet" type="button" data-settings-delete>Удалить</button>` : ""}</div><div class="settings-grid">${input("Название CTA", "name", cta.name, {required: true})}${input("Текст действия", "text", cta.text, {required: true})}${selectField("Режим ссылки", "link_mode", cta.link_mode || "none", [{value: "none", label: "Без ссылки"}, {value: "source", label: "Источник"}, {value: "custom", label: "Заданный URL"}], "required")}${input("Адрес ссылки", "custom_url", cta.custom_url, {nullEmpty: true})}</div>${checkbox("CTA включён", "enabled", cta.enabled ?? true)}${savebar()}</form>`;
}

function channelForm(channel, route, providers, settings, mode = "update") {
  const provider = channel.provider || catalogFor(providers, "channels")[0]?.code || "";
  const meta = providerMeta(providers, "channels", provider);
  const token = meta.secret ? `<div class="secret-field">${input(meta.secret.label, meta.secret.name, "", {type: "password", placeholder: channel.secretConfigured ? "Токен сохранён" : "Введите токен", omitEmpty: true})}<button class="button button--quiet" type="button" data-settings-secret-toggle disabled>Показать токен</button>${channel.secretConfigured ? `<button class="button button--danger-soft" type="button" data-settings-secret-remove>Удалить токен</button>` : ""}</div>` : "";
  const formats = settings.formats.map((item) => ({value: item.id, label: item.name}));
  const channels = settings.channels.map((item) => ({value: item.id, label: item.name}));
  const ctas = [{value: "", label: "Без CTA"}, ...settings.ctas.map((item) => ({value: item.id, label: item.name}))];
  return `<form class="settings-form resource-form" data-settings-form="channels" data-resource="channels" data-resource-id="${escapeHtml(channel.id || "")}" data-resource-mode="${mode}" data-route-id="${escapeHtml(route?.id || "")}"${mode === "create" ? " hidden" : ""} novalidate><div class="resource-heading"><strong>${mode === "create" ? "Новый канал" : escapeHtml(channel.name)}</strong><span class="connection-state">${escapeHtml(channel.connection_status || "не проверен")}</span>${mode === "update" ? `<button class="button button--quiet" type="button" data-settings-delete>Удалить</button>` : ""}</div><div class="settings-grid">${providerSelect(providers, "channels", provider)}${input("Название канала", "name", channel.name, {required: true})}<div class="provider-fields" data-provider-fields>${renderProviderConfiguration(providers, "channels", provider, channel.configuration)}</div></div>${token}${checkbox("Канал включён", "enabled", channel.enabled ?? true)}${mode === "update" ? `<button class="button button--secondary" type="button" data-settings-channel-check>Проверить канал</button>` : ""}${route ? `<fieldset class="route-fields"><legend>Маршрут публикации</legend><div class="settings-grid">${selectField("Формат", "route.format_id", route.format_id, formats, "required")}${selectField("Канал маршрута", "route.channel_id", route.channel_id, channels, "required")}${selectField("CTA маршрута", "route.cta_id", route.cta_id || "", ctas, "data-null-empty")}</div>${checkbox("Маршрут включён", "route.enabled", route.enabled)}</fieldset>` : ""}${savebar()}</form>`;
}

function routeForm(settings) {
  const formats = settings.formats.map((item) => ({value: item.id, label: item.name}));
  const channels = settings.channels.map((item) => ({value: item.id, label: item.name}));
  const ctas = [{value: "", label: "Без CTA"}, ...settings.ctas.map((item) => ({value: item.id, label: item.name}))];
  return `<form class="settings-form resource-form" data-settings-form="route-create" data-resource="routes" data-resource-mode="create" hidden novalidate><div class="resource-heading"><strong>Новый маршрут</strong></div><div class="settings-grid">${selectField("Формат", "format_id", formats[0]?.value || "", formats, "required")}${selectField("Канал маршрута", "channel_id", channels[0]?.value || "", channels, "required")}${selectField("CTA маршрута", "cta_id", "", ctas, "data-null-empty")}</div>${checkbox("Маршрут включён", "enabled", true)}${savebar()}</form>`;
}

function scheduleForm(settings) {
  const source = settings.sources[0] || {};
  const route = settings.routes[0] || {};
  const schedule = route.schedule || {autopublish: false, slots: ["", "", ""]};
  return `<form class="settings-form" data-settings-form="schedule" data-source-id="${escapeHtml(source.id || "")}" data-route-id="${escapeHtml(route.id || "")}" novalidate><div class="timezone-ribbon">Время проекта: <strong>${escapeHtml(settings.project.timezone)}</strong></div><div class="settings-grid">${input("Расписание получения", "source_schedule", source.schedule, {required: true})}${input("Утренний слот", "slots", schedule.slots[0], {type: "time", required: true, multi: true})}${input("Дневной слот", "slots", schedule.slots[1], {type: "time", required: true, multi: true})}${input("Вечерний слот", "slots", schedule.slots[2], {type: "time", required: true, multi: true})}</div>${checkbox("Автопубликация", "autopublish", schedule.autopublish)}${savebar()}</form>`;
}

function advancedForm(config) {
  return `<form class="settings-form" data-settings-form="advanced" data-settings-section-api="configuration" novalidate><div class="settings-grid">${input("Таймаут анализа, секунд", "analysis_timeout_seconds", config.analysis_timeout_seconds, {type: "number", min: 1, required: true})}${input("Предел статьи, байт", "article_max_bytes", config.article_max_bytes, {type: "number", min: 1, required: true})}${input("Предел медиа, байт", "media_max_bytes", config.media_max_bytes, {type: "number", min: 1, required: true})}</div>${savebar()}</form>`;
}

export function renderSettings(settings, providers) {
  const project = settings.project || {};
  const config = project.configuration || {};
  const source = settings.sources?.[0] || {};
  const cta = settings.ctas?.[0] || {};
  const channel = settings.channels?.[0] || {};
  const route = settings.routes?.[0] || {};
  return `<section class="screen settings-screen" data-screen="settings">
    <header class="settings-intro"><p class="section-kicker">Контур редакции</p><p>Меняйте один смысловой блок за раз. Итог секции обновится после ответа Postify.</p></header><div class="settings-accordion">
    ${details("main", "Основное", `${project.name || "Без названия"} · ${project.language || "—"}`, mainForm(project), true)}
    ${details("sources", "Источники", `${settings.sources?.length || 0} · ${source.enabled ? "включёны" : "выключены"}`, `${sourceForm(source, providers)}<button class="button button--secondary add-resource" type="button" data-settings-add="sources">Добавить источник</button>${sourceForm({enabled: true, configuration: {}}, providers, "create")}`)}
    ${details("selection", "Аудитория и отбор", `${config.selection_freshness_days || "—"} дней · ${config.selection_policy_version || "—"}`, selectionForm(config))}
    ${details("generation", "Генерация и форматы", `${config.daily_package_limit || 0} пакета · ${settings.formats?.find((item) => item.id === route.format_id)?.name || "формат не выбран"}`, generationForm(config, settings.formats || [], settings.routes || []))}
    ${details("cta", "CTA", cta.name || "Не настроен", `${ctaForm(cta)}<button class="button button--secondary add-resource" type="button" data-settings-add="ctas">Добавить CTA</button>${ctaForm({enabled: true, link_mode: "none"}, "create")}`)}
    ${details("channels", "Каналы и маршруты", `${channel.name || "Без канала"} · ${channel.connection_status || "не проверен"}`, `${channelForm(channel, route, providers, settings)}<button class="button button--secondary add-resource" type="button" data-settings-add="channels">Добавить канал</button>${channelForm({enabled: true, configuration: {}, secretConfigured: false}, null, providers, settings, "create")}<div class="route-resource-actions"><button class="button button--secondary add-resource" type="button" data-settings-add="routes">Добавить маршрут</button>${route?.id ? `<button class="button button--quiet" type="button" data-settings-route-delete data-route-id="${escapeHtml(route.id)}">Удалить маршрут</button>` : ""}</div>${routeForm(settings)}`)}
    ${details("schedule", "Расписание", `${route.schedule?.slots?.join(" · ") || "Слоты не заданы"} · ${project.timezone || "—"}`, scheduleForm(settings))}
    ${details("advanced", "Дополнительно", `${config.analysis_timeout_seconds || "—"} с · ${config.media_max_bytes || "—"} байт`, advancedForm(config))}
  </div></section>`;
}

function assign(result, path, value) {
  const parts = path.split(".");
  let target = result;
  for (const part of parts.slice(0, -1)) target = target[part] ||= {};
  target[parts.at(-1)] = value;
}

export function serializeSettingsSection(form) {
  const result = {};
  const multi = new Map();
  for (const control of form.elements) {
    if (!control.name || control.disabled || ["submit", "button"].includes(control.type)) continue;
    if (control.dataset.multi !== undefined) {
      if (control.type === "checkbox" && !control.checked) continue;
      const values = multi.get(control.name) || [];
      values.push(control.type === "number" ? Number(control.value) : control.value.trim());
      multi.set(control.name, values);
      continue;
    }
    let value;
    if (control.type === "checkbox") value = control.checked;
    else if (control.type === "number" || (control.tagName === "SELECT" && control.name.endsWith("_id") && control.value)) value = Number(control.value);
    else if (control.dataset.array !== undefined) value = control.value.split(",").map((item) => item.trim()).filter(Boolean);
    else if (control.dataset.nullEmpty !== undefined && !control.value.trim()) value = null;
    else if (control.dataset.omitEmpty !== undefined && !control.value) continue;
    else value = control.value.trim();
    assign(result, control.name, value);
  }
  for (const [name, values] of multi) assign(result, name, values);
  return result;
}

function errorFor(form, message, control = null) {
  const error = form.querySelector("[data-settings-error]");
  if (!error.id) error.id = `settings-error-${form.dataset.settingsForm}-${form.dataset.resourceId || "section"}`;
  error.textContent = message;
  (control || form.querySelector("input, select"))?.setAttribute("aria-describedby", error.id);
  return false;
}

export function validateSettingsSection(form, payload) {
  form.querySelector("[data-settings-error]").textContent = "";
  form.querySelectorAll("[aria-describedby^='settings-error-']").forEach((node) => node.removeAttribute("aria-describedby"));
  if (!form.checkValidity()) return errorFor(form, "Заполните все обязательные поля.", form.querySelector(":invalid"));
  if (form.dataset.settingsForm === "main") {
    try { new Intl.DateTimeFormat("ru", {timeZone: payload.timezone}).format(); }
    catch (_) { return errorFor(form, "Укажите действующий часовой пояс.", form.elements.timezone); }
  }
  if (form.dataset.settingsForm === "generation") {
    if (payload.fresh_share_percent + payload.reserve_share_percent !== 100) return errorFor(form, "Доли свежих и резервных должны составлять 100%.", form.elements.fresh_share_percent);
    if (payload.daily_package_limit > payload.daily_analysis_limit) return errorFor(form, "Лимит пакетов не может превышать лимит анализа.", form.elements.daily_package_limit);
  }
  if (form.dataset.settingsForm === "cta" && payload.link_mode === "custom") {
    try {
      const url = new URL(payload.custom_url || "");
      if (!["http:", "https:"].includes(url.protocol)) throw new Error();
    } catch (_) { return errorFor(form, "Для этого режима нужен абсолютный HTTP(S) URL.", form.elements.custom_url); }
  }
  if (form.dataset.settingsForm === "schedule") {
    const validTime = /^([01]\d|2[0-3]):[0-5]\d$/;
    if (payload.slots.length !== 3 || payload.slots.some((slot) => !validTime.test(slot))) return errorFor(form, "Укажите три корректных времени публикации.", form.elements.slots[0]);
    if (new Set(payload.slots).size !== 3) return errorFor(form, "Три слота публикации должны быть разными.", form.elements.slots[0]);
  }
  if (form.dataset.settingsForm === "channels" && payload.route) {
    for (const field of ["format_id", "channel_id"]) {
      const select = form.elements[`route.${field}`];
      if (!select || ![...select.options].some((option) => option.value === String(payload.route[field]))) return errorFor(form, "Маршрут ссылается на несуществующий объект.", select);
    }
    if (payload.route.cta_id !== null) {
      const cta = form.elements["route.cta_id"];
      if (![...cta.options].some((option) => option.value === String(payload.route.cta_id))) return errorFor(form, "Маршрут ссылается на несуществующий CTA.", cta);
    }
  }
  return true;
}

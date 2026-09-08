import {escapeHtml} from "./screens.js";

const checked = (value) => value ? " checked" : "";
const selected = (value, current) => String(value) === String(current) ? " selected" : "";
const normalizeText = (value) => value.trim().replace(/\s+/g, " ");

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
    options.protocol ? `data-protocol="${escapeHtml(options.protocol)}"` : "",
  ].filter(Boolean).join(" ");
  return `<label class="settings-field"><span>${escapeHtml(label)}</span><input ${attrs}></label>`;
}

function checkbox(label, name, value, options = {}) {
  return `<label class="settings-check"><input type="checkbox" name="${escapeHtml(name)}" value="${escapeHtml(options.value ?? "true")}"${checked(value)}${options.multi ? " data-multi" : ""}><span>${escapeHtml(label)}</span></label>`;
}

function selectField(label, name, current, options, attrs = "") {
  return `<label class="settings-field"><span>${escapeHtml(label)}</span><select name="${escapeHtml(name)}" ${attrs}>${options.map((option) => `<option value="${escapeHtml(option.value)}"${selected(option.value, current)}>${escapeHtml(option.label)}</option>`).join("")}</select></label>`;
}

function scheduleSelect(label, name, current, attrs = "") {
  const options = [
    {value: "*/5 * * * *", label: "Каждые 5 минут"},
    {value: "*/10 * * * *", label: "Каждые 10 минут"},
    {value: "*/15 * * * *", label: "Каждые 15 минут"},
    {value: "*/30 * * * *", label: "Каждые 30 минут"},
    {value: "0 * * * *", label: "Каждый час"},
    {value: "0 */3 * * *", label: "Каждые 3 часа"},
    ...Array.from({length: 24}, (_, hour) => ({value: `0 ${hour} * * *`, label: `Каждый день в ${String(hour).padStart(2, "0")}:00`})),
  ];
  if (current && !options.some((option) => option.value === current)) options.push({value: current, label: "Текущее расписание"});
  return selectField(label, name, current || "0 * * * *", options, attrs);
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
  const label = kind === "sources" ? "Тип источника" : "Тип канала";
  return selectField(label, "provider", current, catalogFor(providers, kind).map((item) => ({value: item.code, label: item.label})), `required data-provider-kind="${kind}"`);
}

export function renderProviderConfiguration(providers, kind, code, configuration = {}) {
  return providerMeta(providers, kind, code).fields.map((field) => input(
    ({"Адрес API": "Адрес источника", "Chat ID": "Адрес канала", "Bot token": "Ключ подключения бота"})[field.label] || field.label,
    `configuration.${field.name}`,
    configuration[field.name],
    field,
  )).join("") + (kind === "sources" && code === "telegram_group" ? '<p>При подключении загрузятся последние 100 сообщений.</p>' : "");
}

function mainForm(project) {
  return `<form class="settings-form" data-settings-form="main" novalidate><div class="settings-grid">
    ${input("Название проекта", "name", project.name, {required: true})}
    ${input("Тема", "topic", project.topic, {required: true})}
    ${input("Язык готового поста", "language", project.language, {required: true})}
    ${input("Аудитория", "audience", project.audience, {required: true})}
    ${input("Часовой пояс", "timezone", project.timezone, {required: true})}
  </div>${savebar()}</form>`;
}

function sourceForm(source, providers, mode = "update") {
  const provider = source.provider || catalogFor(providers, "sources")[0]?.code || "";
  return `<form class="settings-form resource-form" data-settings-form="sources" data-resource="sources" data-resource-id="${escapeHtml(source.id || "")}" data-resource-mode="${mode}"${mode === "create" ? " hidden" : ""} novalidate>
    <div class="resource-heading"><strong>${mode === "create" ? "Новый источник" : escapeHtml(source.name)}</strong>${mode === "update" ? `<button class="button button--quiet" type="button" data-settings-delete>Удалить</button>` : ""}</div>
    <div class="settings-grid">${providerSelect(providers, "sources", provider)}${input("Название источника", "name", source.name, {required: true})}<div class="provider-fields" data-provider-fields>${renderProviderConfiguration(providers, "sources", provider, source.configuration)}</div>${scheduleSelect("Расписание получения", "schedule", source.schedule, "required")}</div>
    ${checkbox("Источник включён", "enabled", source.enabled ?? true)}${savebar()}</form>`;
}

function channelForm(channel, providers, mode = "update") {
  const provider = channel.provider || catalogFor(providers, "channels")[0]?.code || "";
  const meta = providerMeta(providers, "channels", provider);
  const credential = meta.credential || meta.secret;
  const token = credential ? `<div class="secret-field">${input("Ключ подключения бота", credential.name, "", {type: credential.input_type || "password", placeholder: channel.secretConfigured ? "Ключ сохранён" : "Введите ключ подключения", omitEmpty: true})}<button class="button button--quiet" type="button" data-settings-secret-toggle disabled>Показать ключ</button>${channel.secretConfigured ? `<button class="button button--danger-soft" type="button" data-settings-secret-remove>Удалить ключ</button>` : ""}</div>` : "";
  const connectionStatus = channel.connection_status || "не проверен";
  const connectionTone = ["failed", "unavailable"].includes(connectionStatus) ? "failed" : connectionStatus === "ok" ? "ok" : "neutral";
  return `<form class="settings-form resource-form channel-form" data-settings-form="channels" data-resource="channels" data-resource-id="${escapeHtml(channel.id || "")}" data-resource-mode="${mode}"${mode === "create" ? " hidden" : ""} novalidate><div class="resource-heading"><strong>${mode === "create" ? "Новый канал" : escapeHtml(channel.name)}</strong><span class="connection-state connection-state--${connectionTone}">${escapeHtml(({ok: "Подключён", failed: "Не подключён", unavailable: "Недоступен", untested: "Не проверен"})[connectionStatus] || "Не проверен")}</span>${mode === "update" ? `<button class="button button--quiet" type="button" data-settings-delete>Удалить</button>` : ""}</div><div class="settings-grid">${providerSelect(providers, "channels", provider)}${input("Название канала", "name", channel.name, {required: true})}<div class="provider-fields" data-provider-fields>${renderProviderConfiguration(providers, "channels", provider, channel.configuration)}</div></div>${token}<div class="resource-footer">${checkbox("Канал включён", "enabled", channel.enabled ?? true)}${mode === "update" ? `<button class="button button--secondary" type="button" data-settings-channel-check>Проверить канал</button>` : ""}</div>${savebar()}</form>`;
}

function scheduleForm(settings) {
  const sourceFields = settings.sources.map((source) => scheduleSelect(
    settings.sources.length === 1 ? "Расписание получения" : `Расписание получения — ${source.name}`,
    `source_schedule_${source.id}`,
    source.schedule,
    `required data-source-schedule-id="${escapeHtml(source.id)}"`,
  )).join("");
  const comingSoon = `<aside class="coming-soon-card" aria-label="Автопубликация скоро"><span>Скоро</span><div><strong>Автопубликация</strong><p>Настройка автоматического расписания появится позже.</p></div></aside>`;
  if (!sourceFields) return `<p class="resource-empty">Расписание появится после добавления источника.</p>${comingSoon}`;
  return `<form class="settings-form" data-settings-form="schedule" novalidate><div class="timezone-ribbon">Время проекта: <strong>${escapeHtml(settings.project.timezone)}</strong></div><div class="settings-grid">${sourceFields}</div>${comingSoon}${savebar()}</form>`;
}

function advancedForm(config) {
  return `<form class="settings-form" data-settings-form="advanced" data-settings-section-api="configuration" novalidate><div class="settings-grid">${input("Стиль поста", "tone", config.tone || "Нейтральный, естественный", {required: true})}</div>${savebar()}</form>`;
}

export function renderSettings(settings, providers, connections = false) {
  const project = settings.project || {};
  const config = project.configuration || {};
  const sources = settings.sources || [];
  const channels = settings.channels || [];
  const sourceEditors = sources.map((source) => sourceForm(source, providers)).join("") || `<p class="resource-empty">Источники не настроены</p>`;
  const channelEditors = channels.map((channel) => channelForm(channel, providers)).join("") || `<p class="resource-empty">Каналы не настроены</p>`;
  const html = `<section class="screen settings-screen ${connections ? "connections-screen" : ""}" data-screen="${connections ? "connections" : "settings"}">
    <div class="settings-accordion">
    ${!connections ? details("main", "Основное", `${project.name || "Без названия"} · ${project.language || "—"}`, mainForm(project), true) : ""}
    ${connections ? details("sources", "Откуда брать материалы", `${sources.length} · ${sources.filter((item) => item.enabled).length} включено`, `${sourceEditors}<button class="button button--secondary add-resource" type="button" data-settings-add="sources">Добавить источник</button>${sourceForm({enabled: true, configuration: {}}, providers, "create")}`) : ""}
    ${connections ? details("channels", "Куда публиковать", `${channels.length} канала`, `${channelEditors}<button class="button button--secondary add-resource" type="button" data-settings-add="channels">Добавить канал</button>${channelForm({enabled: true, configuration: {}, secretConfigured: false}, providers, "create")}`) : ""}
    ${!connections ? details("schedule", "Расписание", `Получение материалов · ${project.timezone || "—"}`, scheduleForm(settings)) : ""}
    ${!connections ? details("advanced", "Дополнительно", `Стиль поста`, advancedForm(config)) : ""}
  </div></section>`;
  return connections ? html.replaceAll('name="postify-settings"', 'open') : html;
}

function assign(result, path, value) {
  const parts = path.split(".");
  let target = result;
  for (const part of parts.slice(0, -1)) target = target[part] ||= {};
  target[parts.at(-1)] = value;
}

export function serializeSettingsSection(form) {
  if (form.dataset.settingsForm === "schedule") {
    return {
      sources: [...form.querySelectorAll("[data-source-schedule-id]")].map((control) => ({
        id: Number(control.dataset.sourceScheduleId),
        schedule: control.value.trim(),
      })),
    };
  }
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
    else if (control.type === "hidden" && ["true", "false"].includes(control.value)) value = control.value === "true";
    else if (control.dataset.nullEmpty !== undefined && !control.value.trim()) value = null;
    else if (control.type === "number" || (control.tagName === "SELECT" && control.name.endsWith("_id") && control.value)) value = Number(control.value);
    else if (control.dataset.array !== undefined) value = control.value.split(",").map((item) => item.trim()).filter(Boolean);
    else if (control.dataset.omitEmpty !== undefined && !control.value.trim()) continue;
    else value = control.value.trim();
    assign(result, control.name, value);
  }
  for (const [name, values] of multi) assign(result, name, values);
  return result;
}

export function showSettingsError(form, message, control = null) {
  const error = form.querySelector("[data-settings-error]");
  if (!error.id) error.id = `settings-error-${form.dataset.settingsForm}-${form.dataset.resourceId || "section"}`;
  error.textContent = message;
  form.setAttribute("aria-describedby", error.id);
  (control || form.querySelector("input, select"))?.setAttribute("aria-describedby", error.id);
  return false;
}

export function validateSettingsSection(form, payload) {
  form.querySelector("[data-settings-error]").textContent = "";
  form.removeAttribute("aria-describedby");
  form.querySelectorAll("[aria-describedby^='settings-error-']").forEach((node) => node.removeAttribute("aria-describedby"));
  if (!form.checkValidity()) return showSettingsError(form, "Заполните все обязательные поля.", form.querySelector(":invalid"));
  for (const control of form.querySelectorAll('.provider-fields input[type="text"][required]')) {
    if (!normalizeText(control.value)) return showSettingsError(form, "Обязательное поле не может быть пустым.", control);
  }
  for (const control of form.querySelectorAll("[data-protocol]")) {
    try {
      const value = control.value.trim();
      const prefix = `${control.dataset.protocol}://`;
      const authority = value.slice(prefix.length).split(/[/?#]/, 1)[0];
      const url = new URL(value);
      if (!value.toLocaleLowerCase("en-US").startsWith(prefix) || !authority || url.protocol !== `${control.dataset.protocol}:` || !url.host) throw new Error();
    } catch (_) { return showSettingsError(form, "Укажите полный адрес источника, начиная с https://.", control); }
  }
  if (form.dataset.settingsForm === "main") {
    try { new Intl.DateTimeFormat("ru", {timeZone: payload.timezone}).format(); }
    catch (_) { return showSettingsError(form, "Укажите действующий часовой пояс.", form.elements.timezone); }
  }
  return true;
}

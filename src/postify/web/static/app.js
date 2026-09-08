import {
  approvePackage, checkChannel, createResource, deleteResource, getBootstrap,
  getOperation, getOperations, getPackage, getSettings, savePackagePlan, rejectPackage, removeChannelSecret,
  manualSearch, retryAnalysis, returnToAnalysis, regeneratePost, retryDelivery, updateResource, updateSettings,
} from "./api.js";
import {dateTime, escapeHtml, externalLink, label, renderJournal, sourceName, statusBadge} from "./screens.js";
import {renderProviderConfiguration, renderSettings, serializeSettingsSection, showSettingsError, validateSettingsSection} from "./settings.js";

import {loadWorkspace, renderWorkspace, workState, shortTitle} from "./workspace.js";

const ROUTES = {
  review: {title: "Посты", load: loadWorkspace},
  connections: {title: "Подключения", load: getSettings},
  journal: {title: "Журнал работы", load: getOperations},
  settings: {title: "Настройки", load: getSettings},
};

const root = document.querySelector("#screen-root");
const detailLayer = document.querySelector("#detail-layer");
const detailContent = document.querySelector("#detail-content");
const toastRegion = document.querySelector("#toast-region");
let projectId = null;
let currentRoute = "review";
let currentData = null;
let loadController = null;
let operationController = null;
let lastOpener = null;
let providers = {sources: [], channels: []};

const routeName = () => {
  const candidate = location.hash.slice(1) || "review";
  if (["overview", "materials", "queue", "publications"].includes(candidate)) {
    workState.stage = {materials:"source", queue:"plan", publications:"published", overview:"review"}[candidate];
    if (candidate === "queue") workState.view = "calendar";
    return "review";
  }
  return Object.hasOwn(ROUTES, candidate) ? candidate : "review";
};

function updateShell(route) {
  const meta = ROUTES[route];
  document.querySelector("#screen-title").textContent = meta.title;

  document.title = `AutoPostTG — ${meta.title.toLocaleLowerCase("ru")}`;
  document.querySelector('.topbar-actions [data-action="new-run"]').hidden = route !== "review";
  document.querySelectorAll("[data-route]").forEach((link) => {
    const active = link.dataset.route === route;
    link.classList.toggle("is-active", active);
    if (active) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  });
}

const loadingMarkup = (route) => `<section class="screen" data-screen="${route}" data-loading="true" aria-busy="true"><div class="skeleton skeleton--wide"></div><div class="skeleton-grid"><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div></div></section>`;
const errorMarkup = () => `<section class="screen"><section class="empty-state error-state"><span aria-hidden="true">!</span><h2>Не удалось загрузить данные</h2><p>Проверьте подключение к AutoPostTG и повторите запрос.</p><button class="button button--primary" type="button" data-action="retry">Повторить</button></section></section>`;

async function loadRoute() {
  const route = routeName();
  currentRoute = route;
  if (location.hash !== `#${route}`) history.replaceState(null, "", `#${route}`);
  updateShell(route);
  loadController?.abort();
  loadController = new AbortController();
  const {signal} = loadController;

  closeDetail({repaint: false});
  root.innerHTML = loadingMarkup(route);
  try {
    const data = await ROUTES[route].load(projectId, signal);
    if (!signal.aborted && currentRoute === route) {
      currentData = data;
      paintCurrent();
    }
  } catch (error) {
    if (error.name !== "AbortError" && !signal.aborted && currentRoute === route) root.innerHTML = errorMarkup();
  }
}

function paintCurrent() {
  const inline = root.contains(detailContent);
  if (inline) detailLayer.append(detailContent);
  root.innerHTML = ["settings", "connections"].includes(currentRoute)
    ? renderSettings(currentData, providers, currentRoute === "connections")
    : currentRoute === "review" ? renderWorkspace(currentData) : renderJournal(currentData);
  if (inline) root.querySelector("#work-editor")?.replaceChildren(detailContent);
}

async function start() {
  root.innerHTML = loadingMarkup(routeName());
  const controller = new AbortController();
  try {
    const bootstrap = await getBootstrap(controller.signal);
    projectId = bootstrap.activeProject.id;
    providers = bootstrap.providers;
    document.querySelector("#project-name").textContent = bootstrap.activeProject.name;
    document.querySelector(".farm-avatar").textContent = bootstrap.activeProject.name.slice(0, 1).toLocaleUpperCase("ru");
    await loadRoute();
  } catch (error) {
    if (error.name !== "AbortError") root.innerHTML = `<section class="screen">${errorMarkup()}</section>`;
  }
}

function showToast(message) {
  const toast = document.createElement("div");
  toast.className = "toast";
  toast.textContent = message;
  toastRegion.replaceChildren(toast);
  window.setTimeout(() => toast.remove(), 3500);
}

const operationPause = (signal) => new Promise((resolve, reject) => {
  const timer = window.setTimeout(resolve, 250);
  signal.addEventListener("abort", () => {
    window.clearTimeout(timer);
    reject(new DOMException("Aborted", "AbortError"));
  }, {once: true});
});

async function waitForOperation(operationRunId) {
  operationController?.abort();
  operationController = new AbortController();
  const {signal} = operationController;
  while (true) {
    const run = await getOperation(projectId, operationRunId, signal);
    if (run.status !== "running") return run;
    await operationPause(signal);
  }
}

async function finishAcceptedOperation(start) {
  const accepted = await start();
  if (!accepted?.operationRunId) return null;
  const run = await waitForOperation(accepted.operationRunId);
  if (run.status === "failed") throw new Error(run.failure_code || "operation_failed");
  return run;
}

function itemBy(kind, id) {
  const key = {material: "candidate_id", package: "package_id", delivery: "delivery_id", run: "run_id"}[kind];
  const items = currentRoute === "review" && kind === "material" ? currentData.materials : currentRoute === "review" && kind === "delivery" ? currentData.publications : currentData?.items;
  return (items || []).find((item) => String(item[key]) === String(id));
}

function openDetail(title, body, actions, opener) {
  lastOpener = opener;
  detailContent.innerHTML = `<div class="detail-head"><div><h2 id="detail-title">${escapeHtml(title)}</h2></div><button class="icon-button" type="button" data-action="close-detail" aria-label="Закрыть">×</button></div><div class="detail-body">${body}</div>${actions ? `<div class="detail-actions">${actions}</div>` : ""}`;
  const pane = currentRoute === "review" && workState.view === "calendar" && root.querySelector("#work-editor");
  if (pane) pane.replaceChildren(detailContent);
  else { detailLayer.append(detailContent); detailLayer.showModal(); }
  detailContent.querySelector("button")?.focus();
}

function closeDetail({repaint = true} = {}) {
  if (detailContent.querySelector('.rewrite-region[aria-busy="true"]')) return;
  if (detailLayer.open) detailLayer.close();
  else if (root.contains(detailContent)) {
    detailLayer.append(detailContent);
    detailContent.innerHTML = "";
    workState.selected = null;
    workState.editorOpen = false;
    if (repaint) paintCurrent();
  }
  lastOpener?.focus();
  lastOpener = null;
}

async function openPackage(node) {
  if (detailContent.querySelector('.rewrite-region[aria-busy="true"]')) return;
  const packageId = node.dataset.id;
  workState.selected = node.dataset.workKey || `post-${packageId}`;
  workState.editorOpen = workState.view === "calendar";
  paintCurrent();
  node = root.querySelector(`[data-work-key="${workState.selected}"]`) || node;
  root.querySelectorAll("[data-work-key]").forEach(row => row.classList.toggle("is-selected", row.dataset.workKey === workState.selected));
  const summary = itemBy("package", packageId);
  if (!summary) return;
  openDetail(`Пост № ${summary.package_id}`, `<p class="section-kicker">Загрузка…</p>`, "", node);
  try {
    const item = await getPackage(projectId, summary.package_id);
    if (workState.selected !== `post-${summary.package_id}` || currentRoute !== "review") return;
    renderPackage(item, node);
  } catch (_) {
    detailContent.querySelector(".detail-body").innerHTML = `<p class="settings-error">Не удалось загрузить пост.</p>`;
  }
}

function renderPackage(item, node) {
    const delivery = currentData?.publications?.find(entry => entry.package_id === item.package_id);
    const published = item.status === "published" || delivery?.status === "published";
    const manual = published ? "" : item.status === "approved" ? `<div class="detail-action-note"><button class="button button--quiet" type="button" disabled aria-describedby="regenerate-note-${escapeHtml(item.package_id)}">Переписать пост</button><small id="regenerate-note-${escapeHtml(item.package_id)}">Доступно до одобрения</small></div>` : item.status !== "processing" ? `<button class="button button--quiet" type="button" data-action="regenerate-post" data-id="${escapeHtml(item.package_id)}">Переписать пост</button>` : "";
    const actions = (item.status === "awaiting_review" ? `<button class="button button--danger" type="button" data-action="reject-package" data-id="${escapeHtml(item.package_id)}">Отклонить</button><button class="button button--primary" type="button" data-action="approve-package" data-id="${escapeHtml(item.package_id)}"${!item.scheduled_at || !item.route_id ? " disabled" : ""}>✓ Одобрить пост</button>` : item.status === "rejected" ? `<button class="button button--primary" type="button" data-action="return-to-analysis" data-id="${escapeHtml(item.package_id)}">Подготовить заново</button>` : item.status === "failed" && item.attempt_id ? `<button class="button button--primary" type="button" data-action="retry-analysis" data-id="${escapeHtml(item.attempt_id)}">Повторить подготовку</button>` : "") + manual;
    const media = (delivery ? `<p><button class="button button--quiet" data-action="open-delivery" data-id="${delivery.delivery_id}">Результат отправки</button></p>` : "") + (item.media_available ? `<img class="package-media" src="/api/v1/projects/${escapeHtml(projectId)}/media/packages/${escapeHtml(item.package_id)}" alt="Вложение поста № ${escapeHtml(item.package_id)}">` : "");

    openDetail(shortTitle(item.post_text), `<article class="detail-prose">${statusBadge(published ? "published" : item.status)}${media}<div class="rewrite-region"><p class="post-text">${escapeHtml(item.post_text)}</p><div class="rewrite-progress" role="status" hidden>✍️ Пишем новый пост…</div></div>${packagePlanForm({...item, delivery_status: delivery?.status || item.delivery_status, confirmed_at: delivery?.confirmed_at || item.confirmed_at})}<details class="detail-disclosure"><summary>Оригинал</summary><p class="post-text" dir="auto">${escapeHtml(item.original_text || "Оригинал недоступен")}</p>${item.source_url ? externalLink(item.source_url) : ""}</details>${item.analysis ? `<details class="detail-disclosure"><summary>Почему выбран этот материал</summary><p>${escapeHtml(item.analysis)}</p></details>` : ""}</article>`, actions, node);
}

function localPlanTime(date, timezone) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-CA", {timeZone: timezone, year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23"}).formatToParts(date).map(({type, value}) => [type, value]));
  return parts.year + "-" + parts.month + "-" + parts.day + "T" + parts.hour + ":" + parts.minute;
}

function planInstant(value, timezone) {
  const target = Date.parse(value + "Z");
  let instant = target;
  for (let i = 0; i < 4 && Number.isFinite(instant); i++) {
    const shown = Date.parse(localPlanTime(new Date(instant), timezone) + "Z");
    if (shown === target) return new Date(instant);
    instant += target - shown;
  }
  return new Date(NaN);
}

async function rewritePost(node) {
  const form = detailContent.querySelector("[data-package-plan]");
  const draft = {date: form.elements.scheduled_local.value, route: form.elements.route_id.value};
  const region = detailContent.querySelector(".rewrite-region");
  const scrollTop = detailContent.querySelector(".detail-body").scrollTop;
  const controls = [...detailContent.querySelectorAll("button, input, select")].map((control) => [control, control.disabled]);
  region.setAttribute("aria-busy", "true");
  region.querySelector(".rewrite-progress").hidden = false;
  controls.forEach(([control]) => { control.disabled = true; });
  try {
    const before = await getPackage(projectId, node.dataset.id);
    await finishAcceptedOperation(() => regeneratePost(projectId, node.dataset.id));
    const previous = await getPackage(projectId, node.dataset.id);
    if (!previous.replacement_package_id || previous.replacement_package_id === before.replacement_package_id) throw new Error("No new post");
    const item = await getPackage(projectId, previous.replacement_package_id);
    currentData.items = currentData.items.map((entry) => String(entry.package_id) === node.dataset.id ? {...entry, ...item, previous_package_id: Number(node.dataset.id)} : entry);
    workState.selected = `post-${item.package_id}`;
    const opener = lastOpener;
    renderPackage(item, opener);
    const updatedForm = detailContent.querySelector("[data-package-plan]");
    updatedForm.elements.scheduled_local.value = draft.date;
    updatedForm.elements.route_id.value = draft.route;
    detailContent.querySelector(".detail-body").scrollTop = scrollTop;
    paintCurrent();
    lastOpener = root.querySelector('[data-action="open-package"][data-id="' + item.package_id + '"]');
  } catch (_) {
    region.removeAttribute("aria-busy");
    region.querySelector(".rewrite-progress").hidden = true;
    controls.forEach(([control, disabled]) => { control.disabled = disabled; });
    node.disabled = false;
    showToast("Не удалось переписать пост. Попробуйте ещё раз.");
  }
}

function packagePlanForm(item) {
  const displayedAt = item.delivery_status === "published" && item.confirmed_at ? item.confirmed_at : item.scheduled_at;
  const saved = item.scheduled_at ? localPlanTime(new Date(item.scheduled_at), item.timezone) : "";
  const locked = ["published", "processing"].includes(item.status) || ["sending", "uncertain", "published"].includes(item.delivery_status);
  const routes = item.routes || [];
  const planned = Boolean(displayedAt && item.route_id);
  const exact = planned ? new Intl.DateTimeFormat("ru", {timeZone: item.timezone, dateStyle: "long", timeStyle: "short"}).format(new Date(displayedAt)) : "";
  const delta = planned ? new Date(displayedAt).getTime() - Date.now() : 0;
  const absolute = Math.abs(delta);
  const [amount, unit] = absolute >= 86400000 ? [Math.round(delta / 86400000), "day"] : absolute >= 3600000 ? [Math.round(delta / 3600000), "hour"] : [Math.max(delta < 0 ? -1 : 1, Math.round(delta / 60000)), "minute"];
  const relative = planned ? new Intl.RelativeTimeFormat("ru", {numeric: "always"}).format(amount, unit) : "";
  const timing = item.status === "published" || item.delivery_status === "published" ? `Опубликован ${relative}` : `Публикация ${relative}`;
  const summary = planned ? `<ul class="publication-plan-summary"><li>${escapeHtml(timing)}</li><li>${escapeHtml(exact)}</li></ul>` : "<p>Укажите дату и канал, чтобы одобрить пост.</p>";
  const hidden = planned ? " hidden" : "";
  const change = planned && !locked ? `<button class="button button--secondary" type="button" data-action="edit-package-plan">Изменить дату публикации</button>` : "";
  const routeControl = planned ? `<input type="hidden" name="route_id" value="${escapeHtml(item.route_id)}">` : `<label class="settings-field"><span>Канал</span><select name="route_id" required><option value="">Выберите канал</option>${routes.map((route) => `<option value="${escapeHtml(route.id)}"${route.id === item.route_id ? " selected" : ""}>${escapeHtml(route.name)}</option>`).join("")}</select></label>`;
  const form = locked ? "" : `<fieldset class="settings-grid" data-plan-fields${hidden}><label class="settings-field"><span>Дата и время</span><input type="datetime-local" name="scheduled_local" required value="${escapeHtml(saved)}"></label>${routeControl}<div class="plan-confirm-actions"><button class="button button--primary" type="submit">Подтвердить дату</button>${planned ? '<button class="button button--quiet" type="button" data-action="cancel-package-plan">Отмена</button>' : ""}</div></fieldset>`;
  return `<form data-package-plan data-id="${escapeHtml(item.package_id)}" data-timezone="${escapeHtml(item.timezone)}"><h3>План публикации</h3>${summary}${change}${form}<p data-plan-error class="settings-error" role="alert"></p>${item.status === "approved" && !locked ? "<p>После изменения даты пост нужно одобрить заново.</p>" : ""}</form>`;
}

async function savePlan(form) {
  if (!form.reportValidity()) return;
  const error = form.querySelector("[data-plan-error]");
  const date = planInstant(form.elements.scheduled_local.value, form.dataset.timezone);
  if (!Number.isFinite(date.getTime()) || date <= new Date()) {
    error.textContent = "Выберите дату и время в будущем.";
    return;
  }
  const button = form.querySelector('[type="submit"]');
  const scrollTop = detailContent.querySelector(".detail-body").scrollTop;
  const opened = [...detailContent.querySelectorAll(".detail-disclosure")].map((section) => section.open);
  const controls = [...detailContent.querySelectorAll("input, select, button")].map((control) => [control, control.disabled]);
  controls.forEach(([control]) => { control.disabled = true; });
  button.disabled = true;
  button.textContent = "Сохраняем…";
  error.textContent = "";
  let item;
  const payload = {scheduled_at: date.toISOString(), route_id: Number(form.elements.route_id.value)};
  try {
    item = await savePackagePlan(projectId, form.dataset.id, payload);
  } catch (requestError) {
    if (requestError instanceof TypeError) {
      try { item = await savePackagePlan(projectId, form.dataset.id, payload); }
      catch (retryError) { requestError = retryError; }
    }
    if (!item) {
      error.textContent = requestError.code === "invalid_transition"
        ? "План этого поста уже нельзя изменить. Обновите список."
        : requestError.code === "validation_error"
          ? "План не сохранён: проверьте дату и канал."
          : "План не сохранён из-за сбоя соединения. Повторите попытку.";
      controls.forEach(([control, disabled]) => { control.disabled = disabled; });
      button.textContent = "Подтвердить дату";
      return;
    }
  }
  showToast("План сохранён");
  if (!form.isConnected || (!detailLayer.open && !root.contains(form))) return;
  currentData.items = currentData.items.map((entry) => entry.package_id === item.package_id ? {...entry, ...item} : entry);
  try {
    renderPackage(item, lastOpener);
    detailContent.querySelectorAll(".detail-disclosure").forEach((section, index) => { section.open = opened[index]; });
    detailContent.querySelector(".detail-body").scrollTop = scrollTop;
    detailContent.querySelector('[data-action="edit-package-plan"], [data-package-plan] [type="submit"]')?.focus({preventScroll: true});
    paintCurrent();
    lastOpener = root.querySelector('[data-action="open-package"][data-id="' + item.package_id + '"]');
  } catch (_) {
    await loadRoute();
  }
}

function openMaterial(node) {
  if (detailContent.querySelector('.rewrite-region[aria-busy="true"]')) return;
  workState.selected = node.dataset.workKey || `material-${node.dataset.id}`;
  workState.editorOpen = false;
  paintCurrent();
  node = root.querySelector(`[data-work-key="${workState.selected}"]`) || node;
  root.querySelectorAll("[data-work-key]").forEach(row => row.classList.toggle("is-selected", row.dataset.workKey === workState.selected));
  const item = itemBy("material", node.dataset.id);
  if (!item) return;
  const actions = item.retry_attempt_id ? `<button class="button button--primary" type="button" data-action="retry-analysis" data-id="${escapeHtml(item.retry_attempt_id)}">Повторить подготовку</button>` : "";
  openDetail(`Материал № ${item.candidate_id}`, `<article class="detail-prose"><p class="post-text" dir="auto">${escapeHtml(item.original_text || item.title)}</p><dl><dt>Источник</dt><dd>${escapeHtml(sourceName(item.source_name))}</dd><dt>Статус</dt><dd>${statusBadge(item.generation_status || item.decision_status)}</dd>${item.generation_failure_code ? `<dt>Не удалось подготовить пост</dt><dd class="settings-error">${escapeHtml(label(item.generation_failure_code))}</dd>` : ""}${item.decision_status === "rejected" ? `<dt>Причина отказа</dt><dd>${escapeHtml(label(item.decision_reason))}</dd>` : ""}</dl></article>`, actions, node);
}

function openDelivery(node) {
  const item = itemBy("delivery", node.dataset.id);
  if (!item) return;
  const attempts = (item.attempts || []).map((attempt) => `<li><strong>№ ${escapeHtml(attempt.attempt_no)}</strong> ${statusBadge(attempt.outcome)}<span>${escapeHtml(label(attempt.code))}</span><time>${escapeHtml(dateTime(attempt.finished_at))}</time></li>`).join("") || "<li>Завершённых попыток нет</li>";
  const actions = item.status === "retryable" ? `<button class="button button--primary" type="button" data-action="retry-delivery" data-id="${escapeHtml(item.delivery_id)}">Повторить отправку</button>` : "";
  openDetail("Публикация", `<article class="detail-prose"><dl><dt>Канал</dt><dd>${escapeHtml(sourceName(item.channel_name || item.provider))}</dd><dt>Статус</dt><dd>${statusBadge(item.status)}</dd>${item.failure_code ? `<dt>Что случилось</dt><dd>${escapeHtml(label(item.failure_code))}</dd>` : ""}</dl>${item.status === "uncertain" ? "<p>Проверьте канал перед повторной отправкой: пост мог быть опубликован.</p>" : ""}<details class="detail-disclosure"><summary>История отправки</summary><ol class="package-history">${attempts}</ol></details></article>`, actions, node);
}

function openRun(node) {
  const item = itemBy("run", node.dataset.id);
  if (!item) return;
  openDetail(label(item.kind), `<article class="detail-prose"><dl><dt>Статус</dt><dd>${statusBadge(item.status)}</dd><dt>Начало</dt><dd>${escapeHtml(dateTime(item.started_at))}</dd><dt>Обработано материалов</dt><dd>${escapeHtml(item.materials_taken ?? 0)}</dd><dt>Подготовлено постов</dt><dd>${escapeHtml(item.packages_created ?? 0)}</dd>${item.failure_code ? `<dt>Что случилось</dt><dd>${escapeHtml(label(item.failure_code))}</dd>` : ""}</dl></article>`, "", node);
}

async function mutate(node) {
  const action = node.dataset.action;
  node.disabled = true;
  try {
    if (action === "approve-package") {
      await approvePackage(projectId, node.dataset.id);
      closeDetail();
      showToast("Пост одобрен");
    } else if (action === "reject-package") {
      await rejectPackage(projectId, node.dataset.id);
      closeDetail();
      showToast("Пост отклонён");
    } else if (action === "new-run") {
      await finishAcceptedOperation(() => manualSearch(projectId));
      showToast("Поиск завершён");
    } else if (action === "retry-analysis") {
      await finishAcceptedOperation(() => retryAnalysis(projectId, node.dataset.id));
      closeDetail();
      showToast("Пост подготовлен заново");
    } else if (action === "return-to-analysis") {
      await finishAcceptedOperation(() => returnToAnalysis(projectId, node.dataset.id));
      closeDetail();
      showToast("Материал обработан заново");
    } else if (action === "regenerate-post") {
      await rewritePost(node);
      return;
    } else if (action === "retry-delivery") {
      await finishAcceptedOperation(() => retryDelivery(projectId, node.dataset.id));
      closeDetail();
      showToast("Отправка повторяется");
    }
    await loadRoute();
  } catch (_) {
    showToast("Команда не выполнена. Повторите попытку.");
    node.disabled = false;
    if (["new-run", "retry-analysis", "return-to-analysis", "regenerate-post", "retry-delivery"].includes(action)) {
      await loadRoute();
    }
  }
}

function setSettingsBusy(form, busy) {
  form.setAttribute("aria-busy", String(busy));
  form.querySelectorAll("button").forEach((button) => { button.disabled = busy; });
}

async function refreshSettings(message) {
  const openSection = root.querySelector("[data-settings-section][open]")?.dataset.settingsSection;
  currentData = await getSettings(projectId);
  root.innerHTML = renderSettings(currentData, providers, currentRoute === "connections");
  if (openSection !== "main") root.querySelector(`[data-settings-section="${openSection}"]`)?.setAttribute("open", "");
  document.querySelector("#project-name").textContent = currentData.project.name;
  document.querySelector(".farm-avatar").textContent = currentData.project.name.slice(0, 1).toLocaleUpperCase("ru");
  showToast(message);
}

async function saveSettingsForm(form) {
  const payload = serializeSettingsSection(form);
  if (!validateSettingsSection(form, payload)) return;
  setSettingsBusy(form, true);
  try {
    const kind = form.dataset.settingsForm;
    if (kind === "main") {
      await updateSettings(projectId, "main", payload);
    } else if (["selection", "generation", "advanced"].includes(kind)) {
      await updateSettings(projectId, "configuration", payload);
    } else if (form.dataset.resource && kind !== "channels") {
      const resource = form.dataset.resource;
      if (form.dataset.resourceMode === "create") await createResource(projectId, resource, payload);
      else await updateResource(projectId, resource, form.dataset.resourceId, payload);
    } else if (kind === "channels") {
      if (form.dataset.resourceMode === "create") {
        await createResource(projectId, "channels", payload);
      } else {
        await updateResource(projectId, "channels", form.dataset.resourceId, payload);
      }
    } else if (kind === "schedule") {
      await updateSettings(projectId, "schedule", payload);
    }
    await refreshSettings("Настройки сохранены");
  } catch (_) {
    showSettingsError(form, "Не удалось сохранить. Проверьте поля и повторите.", form.querySelector('[type="submit"]'));
    setSettingsBusy(form, false);
  }
}

async function settingsCommand(node) {
  const form = node.closest("form");
  if (node.matches("[data-settings-secret-toggle]")) {
    const token = form.querySelector('input[name="token"]');
    token.type = token.type === "password" ? "text" : "password";
    node.textContent = token.type === "password" ? "Показать ключ" : "Скрыть ключ";
    return;
  }
  if (node.matches("[data-settings-add]")) {
    const create = node.closest("[data-settings-section]").querySelector(`[data-resource="${node.dataset.settingsAdd}"][data-resource-mode="create"]`);
    create.hidden = false;
    create.querySelector(".settings-savebar").hidden = false;
    node.hidden = true;
    create.querySelector("input, select")?.focus();
    return;
  }
  setSettingsBusy(form, true);
  try {
    if (node.matches("[data-settings-delete]")) await deleteResource(projectId, form.dataset.resource, form.dataset.resourceId);
    else if (node.matches("[data-settings-secret-remove]")) await removeChannelSecret(projectId, form.dataset.resourceId);
    else if (node.matches("[data-settings-channel-check]")) {
      const channelId = form.dataset.resourceId;
      const result = await checkChannel(projectId, channelId);
      await refreshSettings(result.connectionStatus === "ok" ? "Канал готов к публикации" : "Проверка завершена");
      if (result.connectionStatus !== "ok") {
        const refreshedForm = root.querySelector(`[data-settings-form="channels"][data-resource-id="${channelId}"]`);
        const checkButton = refreshedForm?.querySelector("[data-settings-channel-check]");
        if (refreshedForm) showSettingsError(refreshedForm, "Не удалось подключиться к каналу. Проверьте ключ подключения и права бота.", checkButton);
      }
      return;
    }
    await refreshSettings("Изменение сохранено");
  } catch (_) {
    showSettingsError(form, "Команда не выполнена. Повторите позже.", node);
    setSettingsBusy(form, false);
  }
}

document.addEventListener("click", (event) => {
  const workControl = event.target.closest("[data-work-view], [data-work-stage], [data-week]");
  if (workControl) {
    if (detailContent.querySelector('.rewrite-region[aria-busy="true"]')) return;
    if (workControl.dataset.workView) { closeDetail({repaint: false}); workState.view = workControl.dataset.workView; workState.selected = null; workState.editorOpen = false; if (workState.view === "calendar") workState.stage = "all"; }
    if (workControl.dataset.workStage) workState.stage = workControl.dataset.workStage;
    if (workControl.dataset.week) workState.week = workControl.dataset.week === "today" ? 0 : workState.week + Number(workControl.dataset.week);
    paintCurrent(); return;
  }
  const node = event.target.closest("[data-action]");
  if (!node) return;
  const action = node.dataset.action;
  if (action === "retry") projectId === null ? start() : loadRoute();
  else if (action === "open-package") openPackage(node);
  else if (action === "open-material") openMaterial(node);
  else if (action === "open-delivery") openDelivery(node);
  else if (action === "open-run") openRun(node);
  else if (action === "close-detail") closeDetail();
  else if (action === "edit-package-plan") { node.hidden = true; detailContent.querySelector("[data-plan-fields]").hidden = false; detailContent.querySelector('[name="scheduled_local"]')?.focus(); }
  else if (action === "cancel-package-plan") { const fields = node.closest("[data-plan-fields]"); fields.hidden = true; detailContent.querySelector('[data-action="edit-package-plan"]').hidden = false; }
  else if (["approve-package", "reject-package", "new-run", "retry-analysis", "return-to-analysis", "regenerate-post", "retry-delivery"].includes(action)) mutate(node);
});

document.addEventListener("submit", (event) => {
  const plan = event.target.closest("[data-package-plan]");
  if (plan) { event.preventDefault(); savePlan(plan); return; }
  const form = event.target.closest("[data-settings-form]");
  if (!form) return;
  event.preventDefault();
  saveSettingsForm(form);
});

document.addEventListener("input", (event) => {
  if (event.target.id === "work-search") {
    workState.query = event.target.value;
    paintCurrent(); root.querySelector("#work-search").focus(); return;
  }
  if (event.target.closest("[data-package-plan]")) {
    const approve = detailContent.querySelector('[data-action="approve-package"]');
    if (approve) approve.disabled = true;
  }
  const form = event.target.closest("[data-settings-form]");
  if (!form) return;
  form.dataset.dirty = "true";
  form.querySelector(".settings-savebar").hidden = false;
  if (event.target.name === "token") form.querySelector("[data-settings-secret-toggle]").disabled = !event.target.value;
});

document.addEventListener("change", (event) => {
  const form = event.target.closest("[data-settings-form]");
  if (!form) return;
  form.dataset.dirty = "true";
  form.querySelector(".settings-savebar").hidden = false;
  if (event.target.matches("[data-provider-kind]")) {
    form.querySelector("[data-provider-fields]").innerHTML = renderProviderConfiguration(providers, event.target.dataset.providerKind, event.target.value, {});
  }
});

document.addEventListener("click", (event) => {
  const node = event.target.closest("[data-settings-add], [data-settings-delete], [data-settings-secret-toggle], [data-settings-secret-remove], [data-settings-channel-check]");
  if (node) settingsCommand(node);
});

detailLayer.addEventListener("cancel", (event) => { if (detailContent.querySelector('.rewrite-region[aria-busy="true"]')) event.preventDefault(); });
detailLayer.addEventListener("click", (event) => { if (event.target === detailLayer) closeDetail(); });
detailLayer.addEventListener("close", () => {
  if (root.contains(detailContent)) return;
  detailContent.innerHTML = "";
  lastOpener?.focus();
  lastOpener = null;
});
window.addEventListener("hashchange", loadRoute);
window.addEventListener("hashchange", () => { if (detailLayer.open) closeDetail(); });
document.querySelector("#today-label").textContent = new Intl.DateTimeFormat("ru-RU", {day: "numeric", month: "long", year: "numeric"}).format(new Date());
start();

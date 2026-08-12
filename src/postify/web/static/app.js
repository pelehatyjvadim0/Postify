import {
  approvePackage, getBootstrap, getDashboard, getMaterials, getOperations,
  getPackages, getPublications, getQueue, publishOnce, rejectPackage, runOnce,
} from "./api.js";
import {dateTime, escapeHtml, externalLink, label, renderSettingsPlaceholder, screens, statusBadge} from "./screens.js";

const ROUTES = {
  overview: {title: "Сегодня", eyebrow: "Рабочая панель", load: getDashboard},
  materials: {title: "Материалы", eyebrow: "Редакторский поток", load: getMaterials},
  review: {title: "Проверка", eyebrow: "Контентные пакеты", load: getPackages},
  queue: {title: "Очередь публикаций", eyebrow: "Ритм дня", load: getQueue},
  publications: {title: "История публикаций", eyebrow: "Доставка", load: getPublications},
  journal: {title: "Журнал работы", eyebrow: "Операции", load: getOperations},
  settings: {title: "Настройки", eyebrow: "Проект"},
};

const root = document.querySelector("#screen-root");
const detailLayer = document.querySelector("#detail-layer");
const detailContent = document.querySelector("#detail-content");
const toastRegion = document.querySelector("#toast-region");
let projectId = null;
let currentRoute = "overview";
let currentData = null;
let loadController = null;
let lastOpener = null;
let materialFilter = "all";

const routeName = () => {
  const candidate = location.hash.slice(1) || "overview";
  return Object.hasOwn(ROUTES, candidate) ? candidate : "overview";
};

function updateShell(route) {
  const meta = ROUTES[route];
  document.querySelector("#screen-title").textContent = meta.title;
  document.querySelector("#screen-eyebrow").textContent = meta.eyebrow;
  document.title = `Postify — ${meta.title.toLocaleLowerCase("ru")}`;
  document.querySelectorAll("[data-route]").forEach((link) => {
    const active = link.dataset.route === route;
    link.classList.toggle("is-active", active);
    if (active) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  });
}

const loadingMarkup = (route) => `<section class="screen" data-screen="${route}" data-loading="true" aria-busy="true"><div class="skeleton skeleton--wide"></div><div class="skeleton-grid"><div class="skeleton"></div><div class="skeleton"></div><div class="skeleton"></div></div></section>`;
const errorMarkup = () => `<section class="screen"><section class="empty-state error-state"><span aria-hidden="true">!</span><h2>Не удалось загрузить данные</h2><p>Проверьте подключение к Postify и повторите запрос.</p><button class="button button--primary" type="button" data-action="retry">Повторить</button></section></section>`;

async function loadRoute() {
  currentRoute = routeName();
  if (location.hash !== `#${currentRoute}`) history.replaceState(null, "", `#${currentRoute}`);
  updateShell(currentRoute);
  loadController?.abort();
  loadController = new AbortController();
  const {signal} = loadController;

  if (currentRoute === "settings") {
    currentData = null;
    root.innerHTML = renderSettingsPlaceholder();
    return;
  }

  root.innerHTML = loadingMarkup(currentRoute);
  try {
    currentData = currentRoute === "materials"
      ? await ROUTES[currentRoute].load(projectId, signal, materialFilter)
      : await ROUTES[currentRoute].load(projectId, signal);
    if (!signal.aborted) root.innerHTML = screens[currentRoute](currentData);
  } catch (error) {
    if (error.name !== "AbortError" && !signal.aborted) root.innerHTML = errorMarkup();
  }
}

async function start() {
  root.innerHTML = loadingMarkup(routeName());
  const controller = new AbortController();
  try {
    const bootstrap = await getBootstrap(controller.signal);
    projectId = bootstrap.activeProject.id;
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

function itemBy(kind, id) {
  const key = {material: "candidate_id", package: "package_id", delivery: "delivery_id", run: "run_id"}[kind];
  return (currentData?.items || []).find((item) => String(item[key]) === String(id));
}

function openDetail(title, body, actions, opener) {
  lastOpener = opener;
  detailContent.innerHTML = `<div class="detail-head"><div><p class="section-kicker">Postify</p><h2 id="detail-title">${escapeHtml(title)}</h2></div><button class="icon-button" type="button" data-action="close-detail" aria-label="Закрыть">×</button></div><div class="detail-body">${body}</div>${actions ? `<div class="detail-actions">${actions}</div>` : ""}`;
  detailLayer.showModal();
  detailContent.querySelector("button")?.focus();
}

function closeDetail() {
  detailLayer.close();
  lastOpener?.focus();
  lastOpener = null;
}

function openPackage(node) {
  const item = itemBy("package", node.dataset.id);
  if (!item) return;
  const actions = item.status === "awaiting_review" ? `<button class="button button--danger" type="button" data-action="show-reject-form" data-id="${escapeHtml(item.package_id)}">Отклонить</button><button class="button button--primary" type="button" data-action="approve-package" data-id="${escapeHtml(item.package_id)}">✓ Одобрить пост</button>` : "";
  openDetail(`Пакет № ${item.package_id}`, `<article class="detail-prose"><p>${escapeHtml(item.post_text)}</p><dl><dt>Статус</dt><dd>${statusBadge(item.status)}</dd><dt>Источник</dt><dd>${externalLink(item.source_url)}</dd><dt>Медиа</dt><dd>${escapeHtml(label(item.media_status))}</dd></dl></article>`, actions, node);
}

function openMaterial(node) {
  const item = itemBy("material", node.dataset.id);
  if (!item) return;
  openDetail(`Материал № ${item.candidate_id}`, `<article class="detail-prose"><h3>${escapeHtml(item.title)}</h3><dl><dt>Источник</dt><dd>${escapeHtml(item.source_name)}</dd><dt>Решение</dt><dd>${statusBadge(item.decision_status)}</dd><dt>Причина</dt><dd>${escapeHtml(label(item.decision_reason))}</dd><dt>Объяснение</dt><dd>${escapeHtml(item.decision_explanation || "—")}</dd><dt>Политика</dt><dd>${escapeHtml(item.policy_version || "—")}</dd></dl></article>`, "", node);
}

function openDelivery(node) {
  const item = itemBy("delivery", node.dataset.id);
  if (!item) return;
  openDetail("История попыток", `<article class="detail-prose"><dl><dt>Публикация</dt><dd>№ ${escapeHtml(item.delivery_id)}</dd><dt>Канал</dt><dd>${escapeHtml(item.provider || "—")}</dd><dt>Попыток</dt><dd>${escapeHtml(item.attempts)}</dd><dt>Результат</dt><dd>${statusBadge(item.status)}</dd><dt>Код</dt><dd>${escapeHtml(label(item.failure_code))}</dd><dt>Описание</dt><dd>${escapeHtml(item.failure_reason || "—")}</dd></dl></article>`, "", node);
}

function openRun(node) {
  const item = itemBy("run", node.dataset.id);
  if (!item) return;
  openDetail("Подробности запуска", `<article class="detail-prose"><dl><dt>Запуск</dt><dd>№ ${escapeHtml(item.run_id)}</dd><dt>Операция</dt><dd>${escapeHtml(label(item.kind))}</dd><dt>Состояние</dt><dd>${statusBadge(item.status)}</dd><dt>Итог</dt><dd>${escapeHtml(label(item.outcome))}</dd><dt>Начало</dt><dd>${escapeHtml(dateTime(item.started_at))}</dd><dt>Длительность</dt><dd>${escapeHtml(item.duration ?? "—")} сек.</dd></dl></article>`, "", node);
}

function openMobileMenu(node) {
  openDetail("Разделы", `<nav class="mobile-more" aria-label="Дополнительная навигация"><a href="#publications">Публикации <span>→</span></a><a href="#journal">Журнал <span>→</span></a><a href="#settings">Настройки <span>→</span></a></nav>`, "", node);
}

function showRejectForm(node) {
  const actions = detailContent.querySelector(".detail-actions");
  actions.innerHTML = `<form class="reject-form" data-reject-form><label for="reject-reason">Причина отклонения</label><textarea id="reject-reason" minlength="3" maxlength="500" required placeholder="Что нужно исправить?"></textarea><button class="button button--danger button--full" type="button" data-action="reject-package" data-id="${escapeHtml(node.dataset.id)}">Подтвердить отклонение</button></form>`;
  actions.querySelector("textarea").focus();
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
      const reason = detailContent.querySelector("#reject-reason")?.value.trim() || "";
      if (reason.length < 3) { showToast("Укажите причину отклонения"); node.disabled = false; return; }
      await rejectPackage(projectId, node.dataset.id, reason);
      closeDetail();
      showToast("Пост отклонён");
    } else if (action === "new-run") {
      await runOnce(projectId);
      showToast("Поиск запущен");
    } else if (action === "publish-once") {
      await publishOnce(projectId);
      showToast("Публикация запущена");
    }
    await loadRoute();
  } catch (_) {
    showToast("Команда не выполнена. Повторите попытку.");
    node.disabled = false;
  }
}

document.addEventListener("click", (event) => {
  const filter = event.target.closest("[data-filter]");
  if (filter) { materialFilter = filter.dataset.filter; loadRoute(); return; }
  const node = event.target.closest("[data-action]");
  if (!node) return;
  const action = node.dataset.action;
  if (action === "retry") projectId === null ? start() : loadRoute();
  else if (action === "open-package") openPackage(node);
  else if (action === "open-material") openMaterial(node);
  else if (action === "open-delivery") openDelivery(node);
  else if (action === "open-run") openRun(node);
  else if (action === "open-mobile-menu") openMobileMenu(node);
  else if (action === "close-detail") closeDetail();
  else if (action === "show-reject-form") showRejectForm(node);
  else if (["approve-package", "reject-package", "new-run", "publish-once"].includes(action)) mutate(node);
});

detailLayer.addEventListener("click", (event) => { if (event.target === detailLayer) closeDetail(); });
detailLayer.addEventListener("close", () => { lastOpener?.focus(); });
window.addEventListener("hashchange", loadRoute);
window.addEventListener("hashchange", () => { if (detailLayer.open) closeDetail(); });
document.querySelector("#today-label").textContent = new Intl.DateTimeFormat("ru-RU", {day: "numeric", month: "long", year: "numeric"}).format(new Date());
start();

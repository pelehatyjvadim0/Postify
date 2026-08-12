# UI v1 HTML Mockup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Собрать автономный интерактивный HTML-прототип шести экранов Postify в утверждённом стиле «Тёплая студия» без backend-зависимостей.

**Architecture:** `ui-mockup/index.html` содержит одну доступную app-shell и контейнеры интерфейса, `ui-mockup/styles.css` — токены, компоненты и адаптивные правила, `ui-mockup/app.js` — неизменяемые исходные демонстрационные данные, локальное состояние, рендер экранов и обработчики действий. Навигация использует hash, а все изменения существуют только в памяти вкладки и сбрасываются при обновлении.

**Tech Stack:** HTML5, CSS3, vanilla JavaScript, pytest, Python Playwright, локальный Google Chrome.

## Global Constraints

- Не обращаться к Postify, PostgreSQL, Telegram и внешним API.
- Не добавлять frontend framework, сборщик или пакетный менеджер.
- Рабочие разделы: «Обзор», «Материалы», «Проверка», «Очередь», «Публикации», «Журнал».
- «Настройки фермы» и «Аналитика» видны только как следующий этап.
- Сохранять визуальный язык «Тёплая студия»: молочный фон, светлые поверхности, глубокий зелёный, оливковые и янтарные акценты.
- Поддерживать desktop, tablet и mobile от 360 px.
- Все интерактивные элементы доступны с клавиатуры; статусы не кодируются только цветом; `prefers-reduced-motion` поддерживается.
- Пользовательские тексты и документация пишутся по-русски.
- Не изменять существующий backend и пользовательские изменения `README.md` и `WAVE_3_HANDOFF.md`.

---

## Карта файлов

- `ui-mockup/index.html` — семантическая оболочка, навигация, области live-status, экран и drawer/dialog.
- `ui-mockup/styles.css` — дизайн-токены, app-shell, компоненты, состояния, три адаптивных режима.
- `ui-mockup/app.js` — fixture-данные, единый `state`, чистые селекторы, render-функции и делегированные события.
- `tests/ui_mockup/test_static_contract.py` — структура, отсутствие сетевых интеграций, тексты будущих разделов и CSS-контракты.
- `tests/ui_mockup/test_browser_flows.py` — hash-навигация, фильтры, approve/reject, раскрытие деталей, reset и responsive overflow.

### Task 1: Доступная оболочка и визуальный фундамент

**Files:**
- Create: `tests/ui_mockup/test_static_contract.py`
- Create: `ui-mockup/index.html`
- Create: `ui-mockup/styles.css`

**Interfaces:**
- Consumes: утверждённая спецификация `docs/superpowers/specs/2026-08-12-ui-v1-html-mockup-design.md`.
- Produces: DOM-точки `#app-nav`, `#farm-switcher`, `#screen-root`, `#demo-reset`, `#detail-layer`, `#toast-region`; CSS-токены `--canvas`, `--surface`, `--ink`, `--forest`, `--olive`, `--amber`.

- [ ] **Step 1: Написать RED-контракт статической оболочки**

```python
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).parents[2]


class IdCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = set()
        self.links = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if "id" in values:
            self.ids.add(values["id"])
        if tag in {"script", "link"}:
            self.links.append(values.get("src") or values.get("href") or "")


def test_mockup_has_accessible_application_shell():
    html = (ROOT / "ui-mockup/index.html").read_text()
    parser = IdCollector()
    parser.feed(html)
    assert {"app-nav", "farm-switcher", "screen-root", "demo-reset", "detail-layer", "toast-region"} <= parser.ids
    assert 'lang="ru"' in html
    assert 'aria-live="polite"' in html
    assert parser.links == ["styles.css", "app.js"]


def test_styles_define_warm_studio_tokens_and_accessibility_rules():
    css = (ROOT / "ui-mockup/styles.css").read_text()
    for token in ("--canvas", "--surface", "--ink", "--forest", "--olive", "--amber"):
        assert token in css
    assert ":focus-visible" in css
    assert "prefers-reduced-motion" in css
    assert "@media (max-width: 767px)" in css
```

- [ ] **Step 2: Запустить тест и подтвердить ожидаемый RED**

Run: `python3 -m pytest tests/ui_mockup/test_static_contract.py -v`

Expected: FAIL, потому что `ui-mockup/index.html` и `ui-mockup/styles.css` ещё не существуют.

- [ ] **Step 3: Реализовать минимальную оболочку и токены**

Создать семантическую страницу с `aside`, `nav`, `main`, кнопкой сброса,
скрытым detail-layer и live-region. В навигации разместить шесть рабочих
ссылок с `href="#<screen>"` и две неактивные строки с подписью «Следующий
этап». В CSS определить точную палитру:

```css
:root {
  --canvas: #f3f0e9;
  --surface: #fffdf8;
  --surface-muted: #f7f4ec;
  --ink: #20221f;
  --ink-muted: #6f726b;
  --forest: #294b38;
  --olive: #72865a;
  --amber: #d79b35;
  --danger: #a95446;
}
```

Сделать desktop app-shell и базовые компоненты: `.panel`, `.button`, `.badge`,
`.status-dot`, `.empty-state`, `.skeleton`, `.toast`.

- [ ] **Step 4: Запустить статический контракт до GREEN**

Run: `python3 -m pytest tests/ui_mockup/test_static_contract.py -v`

Expected: PASS.

- [ ] **Step 5: Зафиксировать фундамент**

```bash
git add ui-mockup/index.html ui-mockup/styles.css tests/ui_mockup/test_static_contract.py
git commit -m "Добавлена оболочка HTML-мокапа Postify"
```

### Task 2: Демонстрационная модель и шесть экранов

**Files:**
- Create: `ui-mockup/app.js`
- Modify: `tests/ui_mockup/test_static_contract.py`
- Create: `tests/ui_mockup/test_browser_flows.py`

**Interfaces:**
- Consumes: DOM-точки Task 1.
- Produces: `INITIAL_STATE`, `state`, `navigate(screen)`, `render()`, `approvePackage(id)`, `rejectPackage(id, reason)`, `resetDemo()`, экраны `overview`, `materials`, `review`, `queue`, `publications`, `journal`.

- [ ] **Step 1: Расширить RED-контракт на данные и маршруты**

```python
def test_script_declares_all_routes_and_stays_off_network():
    script = (ROOT / "ui-mockup/app.js").read_text()
    for route in ("overview", "materials", "review", "queue", "publications", "journal"):
        assert f"{route}:" in script
    for forbidden in ("fetch(", "XMLHttpRequest", "WebSocket", "EventSource"):
        assert forbidden not in script
    assert "INITIAL_STATE" in script
    assert "resetDemo" in script
```

Создать browser fixture, который запускает `python3 -m http.server` на
свободном localhost-порту и открывает страницу через Playwright.

```python
def test_all_working_sections_are_reachable(page):
    page.goto(base_url)
    for route, title in {
        "overview": "Сегодня",
        "materials": "Материалы",
        "review": "Проверка",
        "queue": "Очередь публикаций",
        "publications": "История публикаций",
        "journal": "Журнал работы",
    }.items():
        page.locator(f'[href="#{route}"]').click()
        assert page.locator("h1").inner_text() == title
        assert page.url.endswith(f"#{route}")
```

- [ ] **Step 2: Запустить новые тесты и подтвердить RED**

Run: `python3 -m pytest tests/ui_mockup/test_static_contract.py tests/ui_mockup/test_browser_flows.py -v`

Expected: FAIL из-за отсутствующего `app.js` и неработающих маршрутов.

- [ ] **Step 3: Реализовать данные и независимые render-функции**

В `INITIAL_STATE` создать реалистичные наборы `materials`, `packages`, `slots`,
`deliveries`, `runs` и `alerts`. Не хранить готовую HTML-разметку в данных.
Создать карту рендеров:

```javascript
const screens = {
  overview: renderOverview,
  materials: renderMaterials,
  review: renderReview,
  queue: renderQueue,
  publications: renderPublications,
  journal: renderJournal,
};
```

Каждая функция возвращает один экран и использует общие компоненты
`statusBadge`, `metricCard`, `contentCard`, `timelineSlot`, `detailRow`.
`render()` нормализует неизвестный hash к `overview`, обновляет активную ссылку,
заголовок документа и `#screen-root`.

- [ ] **Step 4: Довести навигацию и экранные контракты до GREEN**

Run: `python3 -m pytest tests/ui_mockup/test_static_contract.py tests/ui_mockup/test_browser_flows.py -v`

Expected: PASS.

- [ ] **Step 5: Зафиксировать экраны**

```bash
git add ui-mockup/app.js tests/ui_mockup/test_static_contract.py tests/ui_mockup/test_browser_flows.py
git commit -m "Добавлены шесть экранов UI-мокапа"
```

### Task 3: Связанные редакторские сценарии

**Files:**
- Modify: `ui-mockup/app.js`
- Modify: `ui-mockup/styles.css`
- Modify: `tests/ui_mockup/test_browser_flows.py`

**Interfaces:**
- Consumes: `state`, render-функции и общий detail-layer Task 2.
- Produces: фильтры `data-filter`, действия `data-action`, доступный dialog/drawer, согласованные локальные счётчики и toast.

- [ ] **Step 1: Написать RED-тесты пользовательских потоков**

```python
def test_approve_updates_review_queue_and_overview(page):
    page.goto(f"{base_url}/#review")
    before = int(page.locator('[data-metric="needs-review"]').inner_text())
    page.locator('[data-action="open-package"]').first.click()
    page.locator('[data-action="approve-package"]').click()
    assert page.get_by_text("Пост одобрен").is_visible()
    page.locator('[href="#overview"]').click()
    assert int(page.locator('[data-metric="needs-review"]').inner_text()) == before - 1


def test_filters_details_and_reset_work(page):
    page.goto(f"{base_url}/#materials")
    page.locator('[data-filter="rejected"]').click()
    assert page.locator('[data-material-status="rejected"]').count() > 0
    assert page.locator('[data-material-status="selected"]').count() == 0
    page.locator('[data-action="open-material"]').first.click()
    assert page.locator("#detail-layer[open]").is_visible()
    page.locator("#demo-reset").click()
    assert page.get_by_text("Демо-данные восстановлены").is_visible()
```

Добавить тест раскрытия ошибки публикации и подробностей запуска, а также
закрытия detail-layer клавишей Escape с возвратом focus на исходную кнопку.

- [ ] **Step 2: Запустить сценарии и подтвердить RED**

Run: `python3 -m pytest tests/ui_mockup/test_browser_flows.py -v`

Expected: FAIL на отсутствующих `data-action`, фильтрах и связанных изменениях состояния.

- [ ] **Step 3: Реализовать делегированные события и локальные переходы**

Один обработчик `click` на app-shell маршрутизирует действия по `data-action`.
Approve переводит пакет `needs_review → approved`, уменьшает очередь проверки,
заполняет первый доступный слот либо оставляет пакет в ожидании. Reject требует
непустую причину и переводит пакет в `rejected`. Фильтры изменяют `state.ui`,
не удаляя fixture-данные. `resetDemo()` создаёт глубокую копию
`INITIAL_STATE`, сохраняет текущий route и перерисовывает интерфейс.

Detail-layer получает `role="dialog"`, `aria-modal="true"`, заголовок через
`aria-labelledby`, focus trap, Escape-close и восстановление focus.

- [ ] **Step 4: Запустить browser flows до GREEN**

Run: `python3 -m pytest tests/ui_mockup/test_browser_flows.py -v`

Expected: PASS.

- [ ] **Step 5: Зафиксировать интерактивность**

```bash
git add ui-mockup/app.js ui-mockup/styles.css tests/ui_mockup/test_browser_flows.py
git commit -m "Добавлены сценарии проверки и планирования контента"
```

### Task 4: Адаптивность и визуальная приёмка

**Files:**
- Modify: `ui-mockup/styles.css`
- Modify: `ui-mockup/app.js`
- Modify: `tests/ui_mockup/test_browser_flows.py`

**Interfaces:**
- Consumes: завершённый прототип Tasks 1–3.
- Produces: desktop/tablet/mobile layout без overflow, контрольные скриншоты во временной директории проверки.

- [ ] **Step 1: Написать RED-проверку контрольных ширин**

```python
@pytest.mark.parametrize("width,height", [(360, 800), (768, 1024), (1440, 1000)])
def test_layout_has_no_horizontal_overflow(page, width, height):
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"{base_url}/#overview")
    overflow = page.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth")
    assert overflow is False
```

На mobile также проверить нижнюю навигацию, полноэкранный detail-layer и
минимальный размер основных интерактивных целей 44 px.

- [ ] **Step 2: Запустить responsive-тест и подтвердить RED**

Run: `python3 -m pytest tests/ui_mockup/test_browser_flows.py -v -k 'overflow or mobile'`

Expected: FAIL до добавления tablet/mobile правил.

- [ ] **Step 3: Реализовать три режима компоновки**

Desktop от 1180 px: sidebar 248 px, основной canvas и двухколоночные области.
Tablet 768–1179 px: компактный sidebar 84 px, одноколоночные панели. Mobile до
767 px: sidebar скрыт, основные рабочие разделы доступны снизу, контент имеет
одну колонку, таблицы превращаются в карточки, detail-layer занимает viewport.

Скрытые подписи mobile-nav не удаляются из accessibility tree. Длинные URL,
заголовки и идентификаторы переносятся через `overflow-wrap: anywhere`.

- [ ] **Step 4: Выполнить полный автоматический gate**

Run: `python3 -m pytest tests/ui_mockup -v`

Expected: PASS без skip.

Run: `git diff --check`

Expected: no output, exit 0.

- [ ] **Step 5: Выполнить визуальную проверку**

Запустить `python3 -m http.server 4173 --directory ui-mockup`, открыть Chrome и
снять overview, review, queue на 1440×1000 и overview/review на 360×800 во
временную директорию. Проверить: соответствие «Тёплой студии», читаемую
иерархию, отсутствие наложений, различимость статусов и один визуальный акцент
«ритм дня». Временные скриншоты не добавлять в Git.

- [ ] **Step 6: Зафиксировать принятый прототип**

```bash
git add ui-mockup/styles.css ui-mockup/app.js tests/ui_mockup/test_browser_flows.py
git commit -m "Завершён адаптивный HTML-мокап Postify"
```

## Финальная проверка границ

- `rg -n "fetch\(|XMLHttpRequest|WebSocket|EventSource" ui-mockup` не находит сетевых вызовов.
- `git diff <base> -- src/postify tests/unit tests/integration tests/e2e` не показывает изменений backend.
- В `git status --short` пользовательские изменения `README.md` и `WAVE_3_HANDOFF.md` сохранены и не входят в UI-коммиты.
- Прямое открытие `ui-mockup/index.html` показывает оболочку; для полной hash-навигации и browser-тестов используется локальный HTTP-сервер.

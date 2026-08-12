# Задача 8 — production frontend шести экранов

## RED

- Contract-тесты переключены с автономного `ui-mockup/` на пакетные ресурсы
  `src/postify/web/static/`: production shell и пять assets отсутствовали.
- Browser fixtures перехватывают `/api/v1/**` и используют реальные формы DTO
  Task 7 с контрольным ID `9001`; добавлены loading, safe error, retry, empty,
  XSS, six-screen data и mutation flows.
- Отдельный regression RED показал, что retry после первоначального отказа
  `/bootstrap` пытался загрузить `/projects/null/materials`.

RED evidence:

```text
uv run pytest -q tests/ui_mockup/test_static_contract.py
# 4 failed: src/postify/web/static/* отсутствовали, package-data не объявлен

uv run pytest -q tests/ui_mockup/test_browser_flows.py -k retry_reloads_bootstrap
# 1 failed: KeyError '/api/v1/projects/null/materials'
```

## GREEN

- Утверждённая оболочка «Тёплая студия» перенесена в packaged static без
  смены логотипа, палитры и responsive-модели 360/768/1440.
- `api.js` владеет единственным `fetch` boundary и resource/command functions
  для `/api/v1`; `screens.js` содержит pure render functions и русские mapping
  доменных кодов; provider отображается из данных ответа.
- `app.js` реализует hash-router, `AbortController`, skeleton/loading, empty,
  безопасный error и retry, делегированные события и refresh после команд.
- Все шесть экранов загружают только свой endpoint. API-текст экранируется до
  вставки в HTML; демонстрационного state/fallback/reset нет.
- Approve/reject вызывают настоящие POST-команды, reject использует компактную
  форму причины. Run-once/publish-once вызывают API и перечитывают журнал.
- Настройки доступны по `#settings` как ясный placeholder; формы и settings API
  намеренно оставлены Task 9. На mobile публикации, журнал и настройки доступны
  через меню «Ещё».
- `pyproject.toml` включает все пять static assets в wheel.

Основные файлы:

- `src/postify/web/static/index.html`
- `src/postify/web/static/styles.css`
- `src/postify/web/static/api.js`
- `src/postify/web/static/screens.js`
- `src/postify/web/static/app.js`
- `tests/ui_mockup/test_static_contract.py`
- `tests/ui_mockup/test_browser_flows.py`
- `pyproject.toml`

## Проверка

```text
uv run pytest -q tests/ui_mockup
# 44 passed

uv run pytest -q tests/unit/web/test_static.py tests/unit/web/test_api.py
# 10 passed

node --check src/postify/web/static/api.js
node --check src/postify/web/static/screens.js
node --check src/postify/web/static/app.js
# exit 0

uv build --wheel --out-dir <temp>
unzip -l <wheel> | rg 'postify/web/static/(index.html|styles.css|app.js|api.js|screens.js)'
# wheel собран, все 5 assets присутствуют

git diff --check
# без вывода
```

Визуально проверены overview 1440×1000 и review 360×800 во временных
скриншотах: наложений и горизонтального overflow нет, логотип и оптическое
выравнивание сохранены. Временные изображения в Git не добавлены.

## Граница следующей задачи

Полноценное чтение и редактирование настроек, source/channel/CTA/route forms и
валидация относятся к Task 9 и в эту задачу не включались.

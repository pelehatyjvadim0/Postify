# Отчёт по Task 11: упаковка, документация и финальный gate

Дата evidence: 2026-08-12. Исходный коммит: `8423107`.
Рабочая ветка: `feature/ui-v1-html-mockup`.

## Результат

Task 11 закрывает поставку локального UI: wheel проверен
вне checkout в fresh venv, миграции и static assets входят в артефакт,
первый UI-запуск идемпотентно создаёт проект. README описывает
установку, миграции, lifecycle ключа, разделы UI, единственного
владельца scheduler, backup и rollback.

По seeded PostgreSQL 16 найдены и исправлены три реальные
регрессии: lifetime Playwright loop в full suite, сериализация immutable
`mappingproxy` в материалах и nullable status filter в списке пакетов.

## Изменённые файлы

- `tests/e2e/test_cli_ui.py`: hermetic installed-wheel e2e;
- `src/postify/web/app.py`: явная раздача `/static`;
- `src/postify/web/services.py`: first-run bootstrap и safe DTO conversion;
- `src/postify/infrastructure/repositories/sqlalchemy_dashboard.py`: типобезопасный
  optional package filter;
- `tests/integration/test_web_component.py`: populated PostgreSQL regressions;
- `tests/ui_mockup/test_browser_flows.py`: module lifetime browser fixture;
- `.env.example`, `README.md`: операторская конфигурация и runbook;
- `docs/development-loop/evidence/2026-08-12-wave-6-red.md`,
  `docs/development-loop/evidence/2026-08-12-wave-6-review.md`,
  `docs/development-loop/runs/2026-08-12-run-006.md`: Wave 6 evidence;
- три малые lint-only правки в `bootstrap_project.py`,
  `test_sqlalchemy_content.py`, `test_process_content.py` закрывают full Ruff
  без изменения тестового поведения.

## TDD и RED evidence

1. Full baseline: `16 failed, 688 passed in 57.37s`; после browser suite
   поздние `asyncio.run()` получали running loop. Минимальный порядок
   browser→API: `1 failed, 73 passed`; reverse: `74 passed`. После module
   fixture оба порядка дали `74 passed`.
2. Новый wheel e2e сначала получил `/static/styles.css` `404`;
   после mount — `/api/v1/bootstrap` `404`; после bootstrap все три
   HTTP endpoint вернули `200`. Первоначальный `SIGTERM` дал код
   `-15` при полном Uvicorn shutdown log; терминальный контракт
   уточнён до `SIGINT`, код `0`.
3. Seeded component RED: materials и packages вернули `503`, прогон
   `2 failed`. После минимальных исправлений: `2 passed in 1.01s`,
   смежные unit: `12 passed`.
4. Первый full Ruff вернул `11` F401. Два import были ненужными;
   девять использовались через dynamic `locals()`. Namespace в тесте
   сделан явным; full и scoped Ruff дали `All checks passed!`.

Полная карта nodes `W6-R1`–`W6-R10` и ловимых мутаций находится
в `docs/development-loop/evidence/2026-08-12-wave-6-red.md`.

## Installed-wheel e2e

Команда:

```sh
env -u DATABASE_URL \
  TEST_DATABASE_URL=postgresql+psycopg://postify_test:postify_test@127.0.0.1:55432/postify_test \
  uv run pytest -q tests/e2e/test_cli_ui.py
```

Тест выполняет `uv build --offline --wheel`, проверяет ZIP-состав,
создаёт fresh temp venv, ставит точно собранный `.whl`, первым
в `PATH` ставит `bin` этого venv, удаляет `PYTHONPATH` и `VIRTUAL_ENV`,
мигрирует схему через `importlib.resources` и запускает absolute
`<temp-venv>/bin/postify` с cwd вне checkout. Проверены:

- 6 static assets;
- Alembic `env.py` и head migration `20260812_07`;
- `/`, `/static/styles.css`, `/api/v1/bootstrap` — HTTP `200`;
- active project ID `1`;
- graceful `SIGINT`, exit code `0`;
- случайная схема PostgreSQL удаляется в `finally`.

## Визуальная приёмка

Абсолютный пут к игнорируемым артефактам:

`/home/user/Рабочий стол/Postify/.worktrees/ui-v1-html-mockup/tmp/task11-visual/`

На migrated и seeded PostgreSQL 16 созданы `3 candidates / 3 packages /
1 delivery / 2 operations / 1 route`. Сняты все семь разделов в
desktop `1440×1000` и mobile `360×800`, а также loading `1440×1000` и
error/retry `360×800`. Дополнительно проверены:

- forms канала и маршрута в Настройках;
- видимый logo и выравнивание desktop sidebar/main grid;
- retry в error state;
- `scrollWidth <= clientWidth` во всех 14 route screenshots;
- чистый финальный capture без warning/error output.

Ключевые файлы: `contact-sheet-desktop.png`,
`contact-sheet-mobile.png`, `desktop-01-overview.png`–`desktop-07-settings.png`,
`mobile-01-overview.png`–`mobile-07-settings.png`,
`state-loading-materials-1440.png`, `state-error-materials-360.png`.

Первый capture settings успел снять skeleton; первый loading capture дал
Playwright `CancelledError` при close. Ожидание route marker, новая Page
на каждый route и завершение held request убрали шум; capture
повторён полностью. Visual schema после приёмки удалена.

## Финальный gate

Все команды выполнялись на чистом одноразовом PostgreSQL 16
`postify-task11-pg16`, port `127.0.0.1:55432`, без `DATABASE_URL` из
внешнего environment:

```sh
env -u DATABASE_URL \
  TEST_DATABASE_URL=postgresql+psycopg://postify_test:postify_test@127.0.0.1:55432/postify_test \
  uv run pytest -q
uv run python -m compileall -q src
uv run ruff check .
uv run ruff check <все изменённые Python-файлы>
uv lock --check
git diff --check
```

Промежуточный full gate после исправлений: `707 passed in
62.55s (0:01:02)`, stdout/stderr без warnings. Финальные свежие
результаты на точном pre-commit tree:

- full PostgreSQL 16 pytest: `707 passed in 61.70s (0:01:01)`, чисто;
- installed-wheel e2e: `1 passed in 3.14s`, чисто;
- compileall: exit `0`, stdout/stderr пусты;
- full Ruff: `All checks passed!`;
- scoped Ruff по всем изменённым Python-файлам: `All checks passed!`;
- `uv lock --check`: `Resolved 43 packages in 0.70ms`;
- `git diff --check`: exit `0`, stdout/stderr пусты.

## Шум, cleanup и ограничения

- Начальный full baseline был шумным: `16 failed` и warning о
  unawaited coroutines. Финальный full gate обязан быть чистым;
  warnings не фильтровались.
- После всех финальных gates одноразовый container
  `postify-task11-pg16` удалён, а port `55432` освобождён. Удалены
  только одноразовые тестовые данные без recovery requirement.
- UI не имеет authentication; public bind не рекомендован без
  отдельного reverse proxy/auth design.
- Web scheduler и legacy systemd timers нельзя запускать одновременно.
- Ротация `POSTIFY_SECRET_KEY` требует backup и повторный ввод
  секретов; автоматической re-encryption нет.
- Аналитика, видеосервис и повторный live Telegram preflight в Task 11
  не входили.
- Независимый review исполнитель сам себе не выдавал; решение
  о приёмке остаётся за root.
- Push, merge и удаление worktree не выполнялись.

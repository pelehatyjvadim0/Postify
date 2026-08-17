# Gate-review Wave 6

Актуальный итог 2026-08-17: **APPROVED для продукта `497746a` на evidence
boundary `e6af284`**. Управляющие результаты находятся в финальной секции
«Синхронизация по quality/07».
Ниже сохранены исторические факты Task 11; финальная remediation-секция в конце
заменяет прежние числа и недолговечную ссылку на `tmp/`.

Дата: 2026-08-12. База Task 11: `8423107`. Этот файл фиксирует
автоматические и визуальные gate-факты. Независимый code review
исполнитель Task 11 сам себе не выдавал; решение о приёмке остаётся
за root.

## Трассировка и мутации

Nodes `W6-R1`–`W6-R11` описаны в `2026-08-12-wave-6-red.md`.
Проверены нагрузочные мутации: потеря `/static` mount,
пропуск bootstrap, reliance on checkout, session-scoped Playwright, глубокая
сериализация `mappingproxy`, untyped `NULL` status и потеря wheel assets.
Каждая из них имеет наблюдаемый RED и последующий GREEN.

## Автоматические gates

| Gate | Результат | Шум |
| --- | --- | --- |
| Full PostgreSQL 16 pytest | `707 passed in 61.70s` | Нет |
| Installed-wheel e2e | `1 passed in 3.14s` | Нет |
| Hostile ambient review fix | RED `1 failed in 3.26s` → initial GREEN `1 passed in 3.32s`; final `1 passed in 3.24s` | Нет в GREEN |
| Component regressions | RED `2 failed` → GREEN `2 passed` | Нет |
| Browser-order regression | RED `1 failed, 73 passed` → GREEN `74 passed` | RED имел expected unawaited warning; GREEN чист |
| `compileall` | exit `0` | Нет |
| Scoped Ruff | `All checks passed!` | Нет |
| Full Ruff | RED `11 errors` → `All checks passed!` | Нет в финале |
| `uv lock --check` | `Resolved 43 packages` | Нет |
| `git diff --check` | exit `0` | Нет |

Review fix изменил только installed-wheel e2e и evidence. Production
не менялся, поэтому full `707 passed` не повторялся. Повторены
целевой wheel e2e, compileall, full/scoped Ruff, lock и diff-check.
Visual acceptance не повторялась, так как production UI не менялся.

## Визуальная приёмка

Источник: migrated и seeded PostgreSQL 16, синтетические данные
`3 candidates / 3 packages / 1 delivery / 2 operations / 1 route`.

- desktop `1440×1000`: Обзор, Материалы, Проверка, Очередь,
  Публикации, Журнал, Настройки;
- mobile `360×800`: те же семь разделов;
- settings: `8` accordion sections, одна открыта, проверены forms
  канала и маршрута;
- отдельно: loading `1440×1000`, error/retry `360×800`;
- для всех 14 разделов: `scrollWidth <= clientWidth`;
- desktop: logo видим, main stage не пересекает sidebar grid;
- финальный capture output чист. Ранний capture давал шумный
  Playwright `CancelledError` при закрытии удерживаемого loading request;
  lifecycle capture исправлен, прогон повторён без шума.

Артефакты: `tmp/task11-visual/` (игнорируется Git), включая
`contact-sheet-desktop.png`, `contact-sheet-mobile.png`, 14 поэкранных PNG,
`state-loading-materials-1440.png` и `state-error-materials-360.png`.

## Эксплуатационные ограничения

- UI не имеет аутентификации; default `127.0.0.1` не следует менять
  на public bind без отдельного reverse proxy/auth design.
- Web scheduler и legacy systemd timers не запускаются одновременно;
  точные disable commands есть в README.
- Ротация `POSTIFY_SECRET_KEY` требует backup и повторный ввод
  секретов; автоматической re-encryption нет.
- Аналитика и видеосервис не входят в Wave 6.
- В Task 11 не выполнялся повторный live Telegram preflight.

Push, merge и удаление worktree не выполнялись.

## Финальная remediation-проверка — 2026-08-17

Закрыты все findings `final-rereview.md`: scheduled command несёт `route_id`,
retry reservation ограничен persisted route/channel, accepted slots атомарно
создают queued jobs с lease/ack/recovery, а Journal и attempt DTO/UI показывают
полный operational/code/reason контракт. Дополнительно проверены executable
операторские команды `.env` и `pg_dump`.

| Gate | Свежий результат |
| --- | --- |
| PostgreSQL 16 full `pytest -q` | `741 passed in 51.85s` после visual follow-up перед evidence commit |
| Focused backend/recovery/route | `37 passed in 5.20s` |
| Browser | `77 passed in 30.36s` (первый запуск с несуществующим `TMPDIR` дал setup errors; каталог создан, exact command повторён GREEN) |
| Installed wheel вне checkout | `1 passed in 3.44s` |
| Ruff / compileall / lock | exit `0`; `All checks passed!`; `Resolved 43 packages` |
| JavaScript / diff | все exit `0` |
| PostgreSQL boundary | сервер сообщает PostgreSQL `16.14`; schema-only `pg_dump` с преобразованным libpq URL exit `0` |

Durable visual evidence: `evidence/artifacts/2026-08-12-wave-6/manifest.json`.
Manifest содержит `14` ready PNG (7 desktop `1440×1000`, 7 mobile
`360×800`) и loading/error PNG, SHA-256/byte size, viewport state и
`scrollWidth/clientWidth`. Все `16` записей имеют
`horizontal_overflow=false`. Команда capture записана в manifest и
воспроизводится из repository root.

Verdict: **APPROVED**. Это не разрешает merge/push/cleanup; эти lifecycle
действия остались вне scope.

## Синхронизация по `quality/07` — 2026-08-17

После предыдущей remediation-проверки capture/manifest-контракт был исправлен
в `e6af284`, без изменения product behavior после `497746a`. Все 14
детерминированных gates затем выполнены на `e6af284`; их `command.log` являются
актуальным источником чисел:

| Gate | Команда | Результат |
| --- | --- | --- |
| PostgreSQL 16 full | `uv run pytest -q` | `741 passed in 51.10s` |
| Focused backend | `uv run pytest -p no:cacheprovider -q tests/integration/test_project_runtime_configuration.py tests/integration/test_web_component.py tests/integration/test_web_operation_ownership.py` | `12 passed in 2.03s` |
| Browser | `uv run pytest -p no:cacheprovider -q tests/ui_mockup/test_browser_flows.py` | `77 passed in 28.51s` |
| Installed wheel | `uv run pytest -p no:cacheprovider -q tests/e2e/test_cli_ui.py` | `1 passed in 3.08s` |
| Ruff | `uv run ruff check .` | `All checks passed!` |
| Compile | `uv run python -m compileall -q src` | exit `0`, без вывода |
| Lock | `uv lock --check` | exit `0`; `Resolved 43 packages in 0.87ms` |
| JavaScript | четыре `node --check` для `api.js`, `screens.js`, `settings.js`, `app.js` | все exit `0` |
| Diff | `git diff --check`; `git diff --check 9ce37da..HEAD` | оба exit `0` |
| Visual | `uv run python adws/adw_modules/visual_evidence.py docs/development-loop/evidence/artifacts/2026-08-12-wave-6/manifest.json` | 16 PNG валидны |

Factory передал test gates отдельный `TEST_DATABASE_URL` на loopback cluster;
секретов в command logs нет. Trace-backed setup:

```sh
/usr/lib/postgresql/16/bin/initdb -D /dev/shm/postify-sssf-pg16 --username=postify_gate --auth=trust --encoding=UTF8 --no-locale
mkdir -p /dev/shm/postify-sssf-pg16-socket
/usr/lib/postgresql/16/bin/pg_ctl -D /dev/shm/postify-sssf-pg16 -l /dev/shm/postify-sssf-pg16.log -o "-h 127.0.0.1 -p 55434 -k /dev/shm/postify-sssf-pg16-socket" start
```

Первая попытка старта без socket-каталога была неуспешной; показанная команда
является успешной. Сервер подтвердил PostgreSQL `16.14` и принимал соединения
только на `127.0.0.1:55434`.

Durable manifest:
`docs/development-loop/evidence/artifacts/2026-08-12-wave-6/manifest.json`.
Он ссылается на 7 desktop и 7 mobile ready PNG, `desktop-loading.png` и
`mobile-error.png`; все файлы существуют, hashes/размеры совпадают, все 16
overflow checks отрицательны. Quality gate валидировал уже созданные
артефакты; воспроизводимая capture-команда хранится в manifest.

Независимый review в
`adws/adw_data/sessions/0b38d798/context_handoff/review.md` выдал `APPROVED` на
`e6af284`; durable acceptance record —
`.superpowers/sdd/2026-08-12-ui-backend-settings/final-rereview-3.md`.
Merge, push, main-branch validation, worktree deletion и cleanup не доказаны и
не заявляются.

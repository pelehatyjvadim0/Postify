# Gate-review Wave 6

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

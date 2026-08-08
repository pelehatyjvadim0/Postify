# Task 4C: атомарность repository

## Статус

Готово. Реализованы persisted credits для retry и атомарные terminal outcomes.

## Изменённые файлы

- `src/postify/domain/content/quota.py` — чистый helper списания credit заранее известного tier.
- `src/postify/infrastructure/repositories/sqlalchemy_content.py` — retry quota, полный AI batch и единые транзакции terminal package.

## Проверки

| Команда | Результат |
| --- | --- |
| Focused PostgreSQL, 6 узлов | `6 passed, 8 deselected` |
| `pytest tests -q -m integration` | `41 passed, 323 deselected` |
| `pytest tests -q -m 'not integration'` | `323 passed, 41 deselected` |
| `python -m compileall -q src` | успешно |
| `ruff check src` | успешно |
| `uv lock --check` | успешно |
| `git diff --check` | успешно |

## Самопроверка

- Retry меняет оба credit до allocation новых candidates и только при занятом slot.
- Batch сохраняет analysis всех topics; невыбранные и не поместившиеся selected attempts terminalized как `analyzed_not_selected`.
- Создание package, history и дневной budget остаются в одной transaction под row lock.
- Complete/fail блокируют package, обновляют package и связанный attempt, добавляют history и коммитят только после всех операций.
- Terminal operation допускается только из `processing`, поэтому второй concurrent worker не может переписать outcome.
- SQL exception делает rollback всего соответствующего изменения.

## Замечания

Свежий независимый review выявил guard конкурентного terminal transition; guard добавлен, а полный gate повторно пройден.

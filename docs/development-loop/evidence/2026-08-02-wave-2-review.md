# Независимое review Wave 2

## Граница проверки

- Проверен диапазон `b025f9d..f85fbb2` в worktree `wave-2-selection-decisions`.
- До review кода прочитаны спецификация, план, RED-доказательство и контур разработки.
- В новых тестах нет `skip`, `xfail` или `importorskip`; исходный RED был поведенческим, а не следствием окружения, как подтверждает RED-evidence и повторный PostgreSQL gate.

## Трассировка и мутации

Трассировка покрывает все требования дизайна: профиль и его валидацию, четыре независимых отказа, консервативный fallback, freshness-сигнал, независимость от HN-метрик, атомарный журнал, import → selection, CLI и wheel. Тесты проверяют наблюдаемое поведение, а не внутренние реализации; отдельные мутации применялись только к точным файлам и после каждого запуска файл был восстановлен.

| № | Точная временная мутация | Команда проверки | Результат |
| --- | --- | --- | --- |
| 1 | fallback `selected/eligible_for_ai` заменён на `rejected/advertising` | `uv run pytest tests/unit/domain/candidates/test_selection.py::test_title_only_candidate_is_selected_conservatively tests/unit/domain/candidates/test_selection.py::test_absent_positive_topic_term_does_not_prove_rejection -q` | RED: 2 failed |
| 2 | stale-кандидат немедленно получает `rejected/out_of_scope` | `uv run pytest tests/unit/domain/candidates/test_selection.py::test_old_candidate_is_selected_and_records_stale_signal -q` | RED: 1 failed |
| 3 | правило `advertising` добавлено перед `profile.rules` | `uv run pytest tests/unit/domain/candidates/test_selection.py::test_disabled_rule_has_no_effect -q` | RED: 1 failed |
| 4 | `profile.topic_exclusion_terms` заменён на `("рецепт", "кулинария")` | `uv run pytest tests/unit/domain/candidates/test_selection.py::test_profile_changes_niche_without_code_changes -q` | RED: 1 failed |
| 5 | ветка `HIRING` отключена условием `and False` | `uv run pytest tests/unit/domain/candidates/test_selection.py::test_each_enabled_rule_produces_its_explainable_rejection -q` | RED: 1 failed, 3 passed |
| 6 | добавлено чтение `candidate.raw_payload["points"]` и отказ при значении > 1000 | `uv run pytest tests/unit/domain/candidates/test_selection.py::test_hn_raw_metrics_cannot_change_domain_decision -q` | RED: 1 failed |
| 7 | сохраняемая `policy_version` заменена на константу | `TEST_DATABASE_URL='postgresql+psycopg://user@127.0.0.1:55432/postify_test' uv run pytest tests/integration/infrastructure/test_sqlalchemy_decisions.py::test_save_new_persists_every_decision_field_exactly_and_commits_one_batch -q` | RED: 1 failed |
| 8 | unique-ограничение изменено с `(candidate_id)` на `(candidate_id, reason)` | та же переменная БД и `...::test_save_new_is_immutable_and_idempotent_without_overwrite -q` | RED: 1 failed |
| 9 | `ON CONFLICT DO NOTHING` заменён на `DO UPDATE status='rejected'` | та же переменная БД и `...::test_save_new_is_immutable_and_idempotent_without_overwrite -q` | RED: 1 failed |
| 10 | удалён `session.commit()` | та же переменная БД и `...::test_save_new_persists_every_decision_field_exactly_and_commits_one_batch -q` | RED: 1 failed |
| 11 | в `find_undecided` добавлен `.limit(1)` | та же переменная БД и `...::test_find_undecided_returns_all_runs_in_candidate_id_order_with_exact_domain_fields -q` | RED: 1 failed |
| 12 | в `RunOnce.execute()` порядок изменён на selection → import | `uv run pytest tests/unit/application/jobs/test_run_once.py::test_run_once_executes_import_then_selection_and_returns_both_results -q` | RED: 1 failed |
| 13 | обработчик `ValueError` в CLI завершался без `_fail` | `uv run pytest tests/e2e/test_cli_run_once.py::test_run_once_does_not_hide_selection_contract_error_or_leak_candidate -q` | RED: 1 failed |
| 14 | после миграции отдельной schema до `20260802_02` файл `20260802_02_add_candidate_decisions.py` временно удалён, wheel собран в чистом `build/` и установлен в новый venv | `migrations_at_head(Settings(...))` из установленного wheel против schema на исходном head | RED: код 1 (`False`); wheel содержит только `20260801_01` |

Для №14 первоначальные изменения `package-data` не считались мутацией: `.py` является модулем пакета и setuptools всё равно включал его в wheel. Корректная проверка выполнена только после удаления generated `build/` и `*.egg-info`, временного удаления самой миграции и явной проверки содержимого нового wheel. Исходник, schema и временные артефакты затем восстановлены/удалены.

Итог mutation gate: **14/14 RED**.

## Полные проверки после восстановления

```text
uv run pytest -m "not integration" -q
153 passed, 21 deselected

TEST_DATABASE_URL='postgresql+psycopg://user@127.0.0.1:55432/postify_test' uv run pytest -m integration -q
21 passed, 153 deselected

uv run python -m compileall -q src
git diff --check
```

## Findings

### Important — `CandidateDecision` фактически изменяем

`CandidateDecision` объявлен `frozen`, но `__post_init__` сохраняет обычный вложенный `dict` в `signals`. Любой вызывающий код может изменить и вложенные, и верхнеуровневые сигналы уже созданного решения до записи:

```text
decision.signals["freshness"]["state"] = "stale"
decision.signals["injected"] = "yes"
# оба изменения успешно применяются
```

Это нарушает инвариант неизменяемого решения и позволяет изменить объяснимый журнал после оценки. Текущий тест доказывает только независимость от входного словаря, но не неизменяемость самого решения. Нужны recursive immutable signals (либо другой неизменяемый JSON-представитель) и тест запрета прямой и вложенной мутации.

### Important — продублирована lifecycle-механика import boundary

`open_importer` и добавленный `open_run_once` независимо создают/закрывают engine и HTTP client, создают `HnAlgoliaCandidateSource` и `sessionmaker`. Это один повторённый operational block в двух сценариях. По `code-structure` общая механика должна быть выделена в composable service/helper с явными ресурсами; actions должны оставлять у себя только составление import либо import → selection. Сейчас будущая правка lifecycle, timeout или source-wiring легко разойдётся между двумя путями. Отдельных тестов lifecycle `open_run_once` (успех, ошибка конструктора, ошибка выполнения) также нет.

## Вывод

- Critical: 0.
- Important: 2.
- Minor: 0.
- Переход к live acceptance: **не готов**. Нужен fix-loop для обоих Important, новых RED-тестов и повторного независимого review.

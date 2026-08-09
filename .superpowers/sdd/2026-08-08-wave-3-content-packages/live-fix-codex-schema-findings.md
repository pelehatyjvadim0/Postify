# Live fix: совместимость Codex Structured Outputs schema

## Причина

Две разрешённые operator preflight попытки безопасно завершились
`codex_failed`. Санитизированная диагностика исключила auth, entitlement,
rate и network; подтвердила schema/model boundary.

Official Structured Outputs compatibility не допускает ключи
`allOf`, `not`, `dependentRequired`, `dependentSchemas`, `if`, `then`, `else`.
Текущая `CodexContentAnalyzer._schema` использует
`allOf` и `if/then/else`, поэтому strict schema отклоняется до запуска
анализа.

## RED evidence

База: `3dbab2c`. Production не изменялся. Существующий generated-schema
node `test_codex_writes_strict_schema_and_explicit_complete_batch_prompt`
усилен без дублирования behavioral contract. До compatibility assertion он
подтверждает:

- exact top-level/topic `required` и `additionalProperties=false`;
- exact article count bounds и field bounds;
- `selected=true` требует non-empty `post_text`/`media_query`;
- `selected=false` требует оба `null`;
- обе обратные комбинации отклоняются.

После этих GREEN assertions рекурсивная compatibility-проверка даёт
RED с точным множеством `{"allOf", "if", "then", "else"}`. Она не
требует конкретной поддерживаемой композиции.

- Baseline non-integration: `327 passed, 42 deselected`.
- Focused node: `1 failed`.
- Codex adapter file: `1 failed, 15 passed`.
- Retained non-integration: `326 passed, 43 deselected`.
- Full non-integration: `1 failed, 326 passed, 42 deselected`.

Сеть и настоящий Codex в RED-проходе не вызывались.

## GREEN evidence

На базе `f7cfea250888fcfd793b2f79a8fa1a02d6e2da6d` условная часть схемы
переведена в `items.anyOf` с двумя закрытыми object-ветками:

- `selected=true` требует непустые `post_text` и `media_query`;
- `selected=false` требует для обоих полей `null`;
- в каждой ветке сохранены все шесть required-полей, `additionalProperties=false`
  и прежние bounds для `attempt_id`, `analysis`, `usefulness`;
- root остаётся object, а `topics` сохраняет точные `minItems`/`maxItems`.

Ни один из unsupported composition keywords не остаётся в сериализованной
схеме. Runtime parser и domain validation не менялись; их покрывает retained
набор адаптера, включая complete-batch selected/unselected outcomes.

Локальные команды без реального `codex exec` и без сетевых вызовов:

- focused node: `1 passed`;
- `tests/unit/adapters/ai/test_codex_content_analyzer.py`: `16 passed`;
- `uv run pytest -m 'not integration' -q`: `327 passed, 42 deselected`;
- `TEST_DATABASE_URL=postgresql+psycopg://user@127.0.0.1:55432/postify_test uv run pytest -m integration -q`:
  `42 passed, 327 deselected`;
- `uv run python -m compileall -q src`, `uv run ruff check src`,
  `uv lock --check`, `git diff --check`: GREEN.

## Operator preflight GREEN

После `5ea09b2` авторизованный production preflight завершился:

```text
CODEX_PREFLIGHT_OK topics=1 selected=0 schema=strict cleanup=ok
```

Использованы production flags `--ephemeral --sandbox read-only`
`--ignore-user-config --ignore-rules --skip-git-repo-check`. Временная
директория была вне repository и удалена; raw output и stderr не печатались.
Это не отменяет ранее зафиксированные schema failures: они предшествовали
двум исправлениям и остаются частью evidence.

Fresh round 2 re-review: **Approved**, замечаний нет.

## Round 2: typed discriminator leaf

После fix `579b74d` live preflight всё ещё завершается
`400 invalid_json_schema` до analysis. В sanitized diagnostic `anyOf` упомянут
только в context path `items` / branch `0`; признаков запрета
`anyOf`, root-ошибки или не-object type нет. Это локализует
несовместимость в leaf `selected` первой object-ветки.

Текущие leaves равны `{"const": true}` и `{"const": false}`. Для
current Structured Outputs validator discriminator обязан быть самодостаточно
типизирован: `{"type": "boolean", "const": true/false}`.

Existing generated-schema node усилен только двумя literal expectations.
Он даёт точный RED: actual `{"const": true}` не содержит
`{"type": "boolean"}`. Все прежние compatibility, strictness, bounds и
selected/nonselected behavioral assertions сохранены.

- Baseline non-integration: `327 passed, 42 deselected`.
- Focused node: `1 failed`.
- Codex adapter file: `1 failed, 15 passed`.
- Retained non-integration: `326 passed, 43 deselected`.
- Full non-integration: `1 failed, 326 passed, 42 deselected`.

Production не изменялся; сеть и настоящий Codex в RED-проходе не
вызывались.

## Round 2 GREEN evidence

На базе `9d5021da17ce84e3a37efe82fe242bd4cfe6c905` изменены только оба
discriminator leaves: selected branch использует
`{"type": "boolean", "const": true}`, unselected branch —
`{"type": "boolean", "const": false}`. Остальная schema, runtime parser и
domain validation не менялись.

Локальная верификация без реального `codex exec` и без сетевых вызовов:

- focused node: `1 passed`;
- `tests/unit/adapters/ai/test_codex_content_analyzer.py`: `16 passed`;
- `uv run pytest -m 'not integration' -q`: `327 passed, 42 deselected`;
- `TEST_DATABASE_URL=postgresql+psycopg://user@127.0.0.1:55432/postify_test uv run pytest -m integration -q`:
  `42 passed, 327 deselected`;
- `uv run python -m compileall -q src`, `uv run ruff check src`,
  `uv lock --check`, `git diff --check`: GREEN.

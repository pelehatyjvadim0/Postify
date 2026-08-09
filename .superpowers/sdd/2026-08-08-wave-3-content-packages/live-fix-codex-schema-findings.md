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

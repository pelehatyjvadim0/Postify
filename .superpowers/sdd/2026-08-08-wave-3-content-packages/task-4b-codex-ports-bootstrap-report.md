# Отчёт Task 4B

## Статус

Production-срез завершён с concerns. Fix round 1 зафиксирован
только RED-tests/evidence; пять findings требуют production GREEN.

## Изменённые файлы

- `src/postify/adapters/ai/codex_content_analyzer.py`
- `src/postify/application/ports/__init__.py`
- `src/postify/application/ports/article_extractor.py`
- `src/postify/application/ports/content_analyzer.py`
- `src/postify/application/ports/content_repository.py`
- `src/postify/application/ports/media_provider.py`
- `src/postify/application/content/process_content.py`
- `src/postify/application/content/review_content.py`
- `src/postify/bootstrap.py`

## Проверки

- RED: `uv run pytest tests/unit/adapters/ai/test_codex_content_analyzer.py tests/unit/application/content/test_ports.py -q` — `12 failed, 5 passed`.
- Focused GREEN: та же команда — `17 passed`.
- Adapter regression: `uv run pytest tests/unit/adapters/ai tests/unit/adapters/http tests/unit/adapters/articles tests/unit/adapters/media -q` — `74 passed`.
- Full non-integration: `uv run pytest -q -m 'not integration'` — `5 failed, 304 passed, 41 deselected`; все пять — известные RED Task 4C для `selected` в domain-модели и ProcessContent.
- `uv run python -m compileall -q src` — exit 0.
- `uv run ruff check src` — `All checks passed!`.
- `uv lock --check` — `Resolved 34 packages`.
- `git diff --check` — exit 0.

## Самопроверка

- Codex получает уникальный invocation directory, schema и raw output удаляются после запуска; production bootstrap передаёт временный системный каталог вне repository/media.
- Аргументы Codex используют read-only sandbox, отключение user/rules config и repository check; runner вызывается без shell и с timeout.
- Schema ограничивает top-level и outcomes, требует ровно один outcome на входную статью и поле `selected`; prompt содержит полный текст и русские продуктовые правила.
- Application actions зависят от публичных Protocol, bootstrap разделяет один URL policy между HTTP article/media adapters и production transport.

## Concerns

- Оба прежних concern теперь входят в fix round 1: прямой
  legacy work mode запрещён, `selected` должен дойти до domain.
- ProcessContent и DB outcome orchestration остаются Task 4C.

## RED fix round 1

- База: `a1343e1`; production не изменялся.
- Baseline Task 4B: `17 passed`.
- Task 4B после regression-tests: `8 failed, 14 passed`.
- Retained Task 4B: `14 passed, 8 deselected`.
- Full non-integration: `13 failed, 301 passed, 41 deselected`: ровно
  8 Task 4B fix round 1 и 5 ранее известных Task 4C.
- Ruff для изменённых tests и `git diff --check` — успешно.

Новые/усиленные RED: hardened invocation, nullable schema,
concurrent invocation при совпадающих roots, selected/nonselected parser,
cleanup failure, typed `PackageDraft` и два bootstrap collision cases.
Существующий domain RED усилен проверкой полного `batch.topics` и
`requested_attempt_ids`, без нового дублирующего node.

Контракты fix round: invocation всегда unique child даже при
`repository_cwd == work_dir`; `selected=false` сохраняет analysis/usefulness
и имеет `null` post/media; cleanup failure возвращает только
санитизированный `CodexAnalysisError`; bootstrap либо выбирает root
вне repository/media, либо санитизированно отказывает до runner;
`PackageDraft` задан как application-port DTO с domain `ExtractedArticle`.

## GREEN fix round 1

- `uv run pytest tests/unit/adapters/ai/test_codex_content_analyzer.py tests/unit/application/content/test_ports.py -q` — `22 passed`.
- `uv run pytest tests/unit/adapters/ai/test_codex_content_analyzer.py tests/unit/domain/content/test_models.py tests/unit/application/content/test_ports.py -q` — `41 passed`.
- `uv run pytest tests/unit/application/content/test_process_content.py -q` — `8 passed`.
- `uv run pytest tests/unit/adapters/ai tests/unit/adapters/http tests/unit/adapters/articles tests/unit/adapters/media tests/unit/domain/content -q` — `99 passed`.
- `uv run pytest -q -m 'not integration'` — `314 passed, 41 deselected`.
- `uv run python -m compileall -q src` — exit 0.
- `uv run ruff check src` — `All checks passed!`.
- `uv lock --check` — `Resolved 34 packages`.
- `git diff --check` — exit 0.

### Самопроверка fix round 1

- Каждый вызов Codex создаёт unique child directory и удаляет его; ошибка cleanup не может вернуть успешный batch и нормализуется без детали filesystem.
- `AnalyzedTopic` сохраняет selected/nonselected outcome; невыбранный outcome требует `null` package fields, batch требует все запрошенные IDs и ограничивает только выбранные topics.
- Bootstrap выбирает candidate work root только вне repository и media, иначе отказывает до запуска runner.
- `PackageDraft` перенесён в public application port с точным типом article; SQL-запросы и repository orchestration не менялись.

### Concerns fix round 1

Нет открытых concerns в scope fix round. Minor о falsy injected transport/policy намеренно не менялся, согласно findings.

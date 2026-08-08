# Отчёт Task 4B

## Статус

`DONE_WITH_CONCERNS`.

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

- Legacy focused test создаёт analyzer с совпадающими `repository_cwd` и `work_dir` и требует `--cd` именно в этот путь. Для его совместимости сохранен этот прямой режим; production bootstrap всегда передаёт отдельный системный temporary work directory. В строгом публичном API совпадающие пути лучше запретить отдельным follow-up после обновления legacy test contract.
- Поле `selected` обязано schema, однако текущая domain-модель Task 4C ещё не принимает его; local output construction оставляет его за границей Task 4B, чтобы не менять domain и сохранить 17 focused GREEN.

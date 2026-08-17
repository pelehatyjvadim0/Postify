# Независимое ревью Wave 3

Проверяющий: свежая Terra 5.6 High. База ревью:
`wave-3-content-packages@eeaaa0b`. Порядок соблюдён: сначала
трассировка/тесты и обратные мутации, затем полный GREEN, только после этого
производственный код. Production и тесты в этом проходе не менялись.

## Трассировка и тестовый барьер

RED-доказательство связывает все 12 design mutation gates с точными node ID.
Новые tests используют `httpx.MockTransport`, подменяемый runner Codex и
тестовую PostgreSQL; сети и настоящего Codex не было. Границы лимитов,
credits, retry, concurrency, review, CLI, media, rollback и wheel имеют
целевые unit/integration nodes.

До review-mutations фактически выполнено:

| Команда | Результат |
| --- | --- |
| `.venv/bin/pytest -q -m 'not integration'` | `243 passed, 35 deselected` |
| `TEST_DATABASE_URL=postgresql+psycopg://user@127.0.0.1:55432/postify_test .venv/bin/pytest -q -m integration` | `35 passed, 243 deselected` |

## Обратные мутации

После каждой временной правки исходник восстановлен точной обратной правкой;
до создания этого evidence `git status --short` и `git diff --check` были
пусты. В таблице приведён фактический узкий запуск.

| № | Точная временная мутация | Узкий запуск | Результат |
| ---: | --- | --- | --- |
| 1 | В `sqlalchemy_content.py` добавлены `+ 1` к свободным analysis и package slots | claim limit, concurrent claim, concurrent package reservation | `3 failed` |
| 2 | Persisted `QuotaState(*credits)` заменён на новый `QuotaState()` | `test_postgresql_weighted_claim_persists_exact_54_6_over_five_days` | `1 failed`: `55 != 54` |
| 3 | Убрана проверка дублирующихся `attempt_id` в `BatchAnalysis` | `test_batch_rejects_duplicate_or_unknown_attempt_ids` | `1 failed`: `DID NOT RAISE` |
| 4 | В `ProcessContent` в AI input вместо article body передан title | partial article failure + Codex argv/body | `1 failed, 1 passed` |
| 5 | Retry назначен через 5, а не 6 часов | два article-failure action node | `1 failed, 1 passed` |
| 6 | Завершение package всегда ставит `approved` | review policy, invalid review transition, matrix | `1 failed, 11 passed` |
| 7 | Отключён запрет source URL в `ContentPackage` | URL-in-post + CLI show | `1 failed, 1 passed` |
| 8 | Список article image candidates заменён пустым, forcing Wikimedia first | priority/fallback/path media nodes | `3 failed` |
| 9 | Media delete перенесён до DB reject | reject ordering, failed delete, TTL cleanup | `2 failed, 1 passed` |
| 10 | `CodexAnalysisError` получил `done.stderr` | stable Codex failure node | `1 failed`: раскрыт `TOKEN-DO-NOT-LEAK` |
| 11 | Добавлен `commit()` после INSERT package и до history | package-history rollback + claim rollback | `1 failed, 1 passed` |
| 12 | Файл миграции временно исключен из сборки wheel | wheel head node на чистом build | `1 failed`: файл отсутствует в wheel |

Итог основных gates: **12/12 дали RED**.

### Выжившие предварительные мутации — пробелы evidence

1. В gate 10 замена ветки исключения runner на
   `raise CodexAnalysisError(str(e))` пережила
   `test_codex_failure_exposes_stable_code_without_stdout_stderr_or_prompt`:
   node проверяет только `CompletedProcess(returncode != 0)`, а не exception
   из runner. Текущий production не раскрывает это сообщение, но тест не
   доказывает контракт для этой ветки. Нужен RED node с runner, бросающим
   секретосодержащее исключение.
2. В gate 12 изменение `pyproject.toml` и первое временное переименование
   миграции пережили тест при уже существующих `build/` и
   `src/postify.egg-info`: setuptools упаковал stale копию. После изоляции
   этих подтверждённо генерируемых артефактов и повторного точного
   переименования тот же node дал RED. Нужна изолированная/предварительно
   очищенная сборка внутри теста, иначе evidence wheel зависит от состояния
   рабочей директории.

Оба пробела классифицированы как **Important**: формально основная мутация
после очистки поймана, но первоначальный test barrier не доказывал свой
инвариант во всех проверяемых ветках.

## Полный GREEN после восстановления

| Команда | Результат |
| --- | --- |
| `.venv/bin/pytest -q -m 'not integration'` | `243 passed, 35 deselected` |
| `TEST_DATABASE_URL=postgresql+psycopg://user@127.0.0.1:55432/postify_test .venv/bin/pytest -q -m integration` | `35 passed, 243 deselected` |
| `.venv/bin/python -m compileall -q src` | GREEN |
| `ruff check src` | `All checks passed!` |
| `git diff --check` | GREEN |

`ruff` отсутствует в `.venv`, но доступен в PATH (`ruff 0.15.13`); это
инструментальное расхождение, не результат проверки кода.

## Production review

### Critical

1. **SSRF и лимиты загрузки не реализованы.**
   `HttpArticleExtractor.extract` без проверки схемы, host/IP/DNS или policy
   вызывает `client.get(url)` ([http_article_extractor.py](../../../src/postify/adapters/articles/http_article_extractor.py#L59)), а
   `LocalMediaProvider.acquire` аналогично загружает URL из HTML/Wikimedia
   ([local_media_provider.py](../../../src/postify/adapters/media/local_media_provider.py#L24)).
   Любой selected URL или `og:image` может обратиться к loopback/private/link-local
   адресу. Оба адаптера сначала полностью материализуют `r.content`, и только
   затем сравнивают длину с лимитом ([article](../../../src/postify/adapters/articles/http_article_extractor.py#L65),
   [media](../../../src/postify/adapters/media/local_media_provider.py#L36));
   значит `CONTENT_*_MAX_BYTES` не ограничивает сетевую загрузку и память.
   Нет tests для SSRF, redirect policy или stream/Content-Length size boundary.

### Important

1. **Retry не участвует в persisted 90/10 credits.**
   Claim берёт due retries до новых кандидатов ([sqlalchemy_content.py](../../../src/postify/infrastructure/repositories/sqlalchemy_content.py#L63)),
   но назначает им tier без `choose_tier` ([sqlalchemy_content.py](../../../src/postify/infrastructure/repositories/sqlalchemy_content.py#L70))
   и сохраняет credits, изменённые только циклом новых candidates
   ([sqlalchemy_content.py](../../../src/postify/infrastructure/repositories/sqlalchemy_content.py#L110)).
   Это прямо нарушает дизайн: retry занимает слот и участвует в credits по
   текущей свежести. PostgreSQL test проверяет retry и 54/6 раздельно, но не
   их композицию.
2. **Завершение package и его history не атомарны.**
   `complete_package` и `fail_package` сначала commit-ят update в `_execute`,
   затем в другом session/commit пишут history
   ([sqlalchemy_content.py](../../../src/postify/infrastructure/repositories/sqlalchemy_content.py#L259)).
   Крэш/SQL failure между ними оставляет смену status/media без обязательной
   истории. Нужен один repository transaction и integration failure test.
3. **Нет объявленных application ports и нет документированного отклонения.**
   План требует `article_extractor.py`, `content_analyzer.py`,
   `content_repository.py`, `media_provider.py`; в
   `src/postify/application/ports/` их нет. `ProcessContent` принимает
   неаннотированные concrete-зависимости ([process_content.py](../../../src/postify/application/content/process_content.py#L24)),
   а RED evidence фиксирует только отклонения тестовых файлов. Это нарушает
   утверждённую границу actions/ports/adapters и не объяснено как допустимое
   архитектурное отклонение.
4. **Codex temp/schema не безопасны как заявленный контракт.**
   Output и schema создаются прямо в media dir; schema имеет постоянное имя,
   а raw output/schema не удаляются ([codex_content_analyzer.py](../../../src/postify/adapters/ai/codex_content_analyzer.py#L27)).
   Схема `{"type":"object"}` ничего не ограничивает. Нет cleanup и tests
   для concurrent temp files/strict schema. Это расходится с требованием
   безопасных temp/schema и оставляет raw article context на диске.
5. **Два Important пробела test evidence из раздела «Выжившие предварительные
   мутации».**

### Minor

1. HTML parser собирает любой `p` наряду с `article` и `main`, поэтому не
   реализует заявленное предпочтение `article → main → meaningful paragraphs`;
   текущие tests не покрывают страницу, где все три источника одновременно.
2. `get_package` читает package и history двумя SELECT без snapshot/lock
   ([sqlalchemy_content.py](../../../src/postify/infrastructure/repositories/sqlalchemy_content.py#L307));
   concurrent review может вернуть несогласованный audit view.

## Решение

**Возврат в fix-loop обязателен.** Есть один Critical и несколько Important;
Wave 3 нельзя закрывать, переходить к live proof, merge или удалению ветки.
После исправлений нужны новые RED nodes для всех findings, повторная
независимая проверка мутаций и полный GREEN.

## Final fix-wave review: CLI error boundary

Whole-branch review `b88ba02..caf37fd` подтвердил закрытие 12/12
mutation gates и оставил один Important: `run-once` не нормализует
`RuntimeError` из content pipeline и cleanup. На базе `caf37fd` добавлен
один RED node через реальную Typer-команду и fake `open_run_once`
boundary. Он отдельно давит на execute и cleanup внутри одного node.

Baseline non-integration: `323 passed, 42 deselected`; focused:
`1 failed`; retained: `323 passed, 43 deselected`; полный non-integration:
`1 failed, 323 passed, 42 deselected`. RED возник по ожидаемой причине:
CLI не печатает стабильное operator message и оставляет raw
`RuntimeError` на CliRunner boundary. Production в RED-коммите не менялся;
после GREEN допускается ровно один scoped re-review.

## Wikimedia live fix: завершение

Fresh re-review `418ec2a..ab3df25` одобрил MIME fix без
Critical/Important/Minor: единственный Commons request сохраняется и выбирает
только URL с strict MIME whitelist `image/jpeg`, `image/png` или `image/webp`.
Live query через production transport подтвердил допустимый URL без его вывода.

Контроллер подтвердил полный GREEN: non-integration `327 passed, 42 deselected`;
`TEST_DATABASE_URL=postgresql+psycopg://user@127.0.0.1:55432/postify_test .venv/bin/pytest -q -m integration`
— `42 passed, 327 deselected in 6.87s`; также GREEN `compileall`, `ruff`,
`uv lock --check` и `git diff --check`.

## Codex schema: финальное live evidence

После `5ea09b2` авторизованный production preflight вернул
`CODEX_PREFLIGHT_OK topics=1 selected=0 schema=strict cleanup=ok`. Запуск
использовал production flags `--ephemeral --sandbox read-only`
`--ignore-user-config --ignore-rules --skip-git-repo-check`; временная
директория вне repository удалена, raw output и stderr не печатались.
Предыдущие schema failures честно сохранены в отдельном live-fix evidence как
основание двух исправлений. Fresh round 2 re-review: **Approved**, замечаний
нет.

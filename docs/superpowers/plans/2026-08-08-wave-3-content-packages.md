# Wave 3: план реализации контентных пакетов

> **Обязательный процесс:** `docs/development-loop/README.md` 0.4. Sol 5.6 High
> создаёт RED без production-кода; Terra 5.6 Medium доводит до GREEN; свежая Terra
> 5.6 High сначала проверяет тесты и мутации, затем код.

**Цель:** за один проверяемый переход добавить квотируемую очередь selected,
извлечение статьи, пакетный анализ Codex, до трёх полных пакетов и CLI review.

**База:** `main@b88ba02`. Retained baseline: 160 non-integration GREEN; после запуска
изолированного PostgreSQL 16 — 26 integration GREEN.

## Нагрузка и риски

| Параметр | Оценка |
| --- | --- |
| Поведение | квоты, retry, анализ, медиа, review и история |
| Границы | PostgreSQL, HTTP статьи, Codex subprocess, Wikimedia, filesystem, CLI |
| Неизвестности | конкурентная квота, частичные сбои, качество HTML, формат Codex |
| Компоненты | config, domain, application, adapters, repository, migration, bootstrap, CLI |
| Глубина | claim → fetch/extract → analyze → media → package → review |
| Параллелизм | только внешние fetch после атомарного claim; остальное последовательно |
| Доказательство | чистые unit, PostgreSQL concurrency, CLI, мутации, live preflight |

Главный риск — не объём кода, а согласованность зафиксированного DB-состояния с
нетранзакционными HTTP/subprocess/filesystem-границами. Каждая граница возвращает
типизированный результат; application action единолично владеет переходами и retry.

## Карта production-файлов

Создать:

- `src/postify/domain/content/models.py` — attempts, AI result, package/status/history, quota credits;
- `src/postify/domain/content/quota.py` — чистый weighted-credit scheduler;
- `src/postify/application/ports/article_extractor.py`;
- `src/postify/application/ports/content_analyzer.py`;
- `src/postify/application/ports/content_repository.py`;
- `src/postify/application/ports/media_provider.py`;
- `src/postify/application/content/process_content.py` — основной action;
- `src/postify/application/content/review_content.py` — list/show/approve/reject actions;
- `src/postify/adapters/articles/http_article_extractor.py`;
- `src/postify/adapters/ai/codex_content_analyzer.py`;
- `src/postify/adapters/media/local_media_provider.py`;
- `src/postify/adapters/media/wikimedia.py`;
- `src/postify/infrastructure/repositories/sqlalchemy_content.py`;
- `src/postify/infrastructure/database/migrations/versions/20260808_03_add_content_packages.py`.

Изменить:

- `.env.example`, `README.md`, `pyproject.toml` при необходимости package data/dependency;
- `src/postify/config.py`, `bootstrap.py`, `cli.py`;
- `src/postify/application/jobs/run_once.py`;
- `src/postify/infrastructure/database/models.py`;
- retained test helpers, которым нужны новые обязательные Settings.

Точные package-файлы `__init__.py` можно добавлять без отдельного обоснования. Иное
отклонение сначала фиксируется в RED evidence.

## Карта тестов

Создать:

- `tests/unit/domain/content/test_models.py`;
- `tests/unit/domain/content/test_quota.py`;
- `tests/unit/application/content/test_process_content.py`;
- `tests/unit/application/content/test_review_content.py`;
- `tests/unit/adapters/articles/test_http_article_extractor.py`;
- `tests/unit/adapters/ai/test_codex_content_analyzer.py`;
- `tests/unit/adapters/media/test_local_media_provider.py`;
- `tests/unit/adapters/media/test_wikimedia.py`;
- `tests/integration/infrastructure/test_sqlalchemy_content.py`.

Изменить:

- `tests/unit/config/test_settings.py`;
- `tests/unit/application/jobs/test_run_once.py`;
- `tests/integration/test_migrations.py`;
- `tests/integration/test_import_component.py`;
- `tests/e2e/test_cli_run_once.py`;
- при необходимости `tests/integration/conftest.py` без скрытия недоступной БД.

## Контракты

```python
class ArticleExtractor(Protocol):
    def extract(self, url: str) -> ExtractedArticle: ...

class ContentAnalyzer(Protocol):
    def analyze(self, articles: Sequence[AnalysisInput], package_limit: int) -> BatchAnalysis: ...

class MediaProvider(Protocol):
    def acquire(self, article: ExtractedArticle, query: str) -> StoredMedia: ...
    def delete(self, local_path: str) -> None: ...
    def cleanup(self, *, older_than: datetime, protected_paths: set[str]) -> int: ...

class ContentRepository(Protocol):
    def claim(self, *, now: datetime, day: date, limits: ContentLimits) -> Sequence[ClaimedAttempt]: ...
    def schedule_article_retry(self, attempt_id: int, *, retry_at: datetime, now: datetime) -> None: ...
    def fail_attempt(self, attempt_id: int, *, code: FailureCode, now: datetime) -> None: ...
    def save_extracted(self, attempt_id: int, article: ExtractedArticle) -> None: ...
    def save_analysis_and_create_packages(...) -> Sequence[PackageDraft]: ...
    def complete_package(...) -> ContentPackage: ...
    def fail_package(...) -> None: ...
    def active_media_paths(self) -> set[str]: ...
    def list_packages(self) -> Sequence[ContentPackage]: ...
    def get_package(self, package_id: int) -> ContentPackage: ...
    def approve(self, package_id: int, *, now: datetime) -> ContentPackage: ...
    def reject(self, package_id: int, *, now: datetime) -> ContentPackage: ...
```

Repository-методы не вызывают HTTP, Codex или filesystem. `ProcessContent` оркестрирует
политику, а адаптеры остаются малыми composable-возможностями.

## Задача 1: Sol 5.6 High создаёт RED

Production-код запрещён. Разрешены только tests и
`docs/development-loop/evidence/2026-08-08-wave-3-red.md`.

- [ ] Снова выполнить retained baseline и отделить его от новых nodes.
- [ ] Доказать валидацию всех `CONTENT_*`: обязательность, положительные лимиты,
  package <= analysis, сумма долей 100, абсолютный media dir.
- [ ] Чистыми тестами доказать 54/6 за 60 слотов, непостоянную дневную раскладку
  и сохранение credit при пустом классе.
- [ ] Доказать доменные инварианты attempts, AI batch, package и допустимых переходов.
- [ ] Проверить action: 12-й лимит, не более трёх пакетов, частичные article-сбои,
  Codex-сбой, media-сбой, review-required/auto-review и безопасные failure codes.
- [ ] Проверить article adapter: реальный текст из `article`/`main`, fallback, короткий текст,
  MIME/size, порядок image candidates, абсолютизацию URL.
- [ ] Проверить Codex adapter: полный article marker в stdin; schema/output file; нет shell, model hardcode,
  repository cwd, stdout/stderr и утечки ошибки; невалидный JSON/состав batch отклоняется.
- [ ] Проверить media: строгий article → Wikimedia fallback, MIME/size, UUID-имя, containment,
  atomic write, reject, повтор неудавшегося delete, TTL и защиту активных путей.
- [ ] В PostgreSQL доказать схему/downgrade, точное persistence, суточные бюджеты, 54/6,
  retry до/после 6 часов, терминальный второй сбой, no duplicate и два конкурентных claim.
- [ ] Доказать атомарную историю review, отказ недопустимого перехода и полную выдачу CLI.
- [ ] Связать run-once в порядке import → selection → cleanup → content; ошибки не скрываются как
  успех и не раскрывают данные.
- [ ] Доказать, что wheel содержит migration head.
- [ ] Записать requirement → node ID → причину RED → mutation и отдельно подтвердить,
  что retained nodes GREEN, а новые падают не из-за сети, Codex, PostgreSQL или dependency.

Коммит: `Спроектировал RED-тесты контентных пакетов`.

## Задача 2: Terra 5.6 Medium реализует домен и claim

- [ ] Добавить Settings и `.env.example`.
- [ ] Реализовать immutable-модели, статусы, переходы, AI batch и weighted-credit без I/O.
- [ ] Добавить миграцию и PostgreSQL repository с `FOR UPDATE`/`SKIP LOCKED`, суточным row lock,
  уникальностями, именованными constraints, commit/rollback.
- [ ] Запустить focused domain/config/integration GREEN.

Коммиты по завершённым вертикальным срезам с понятными русскими именами.

## Задача 3: Terra 5.6 Medium реализует адаптеры

- [ ] Реализовать HTML extraction на стандартном parser без запуска сети в тестах.
- [ ] Реализовать Codex subprocess по фактической локальной CLI-справке; модель не указывать.
- [ ] Реализовать Wikimedia search и локальное медиа с валидацией и безопасной записью.
- [ ] Довести focused adapter nodes до GREEN.

## Задача 4: Terra 5.6 Medium связывает action, run-once и CLI

- [ ] `ProcessContent` выполняет cleanup, claim, частичное extraction, один AI batch, package/media
  и точно завершает каждую попытку.
- [ ] Package budget резервируется атомарно; невалидный AI ID или URL в post не создаёт пакет.
- [ ] `ReviewContent` не дублирует filesystem-механику, а вызывает `MediaProvider.delete` после DB-transition.
- [ ] `RunOnce` после отбора вызывает content action; bootstrap делит HTTP/engine lifecycle без утечек.
- [ ] CLI печатает счётчи run-once и даёт полный content review без traceback/секретов.
- [ ] Обновить README: Wave 3 готова, но Telegram/UI нет.
- [ ] Выполнить полный GREEN, compileall, `ruff check src`, `git diff --check`, wheel-проверку.

## Задача 5: свежая Terra 5.6 High проводит ворота

Сначала тесты и мутации, затем production-код. Любая выжившая критичная мутация
или Critical/Important возвращают Sol → Terra Medium → Terra High.

Обязательные mutation gates:

1. analysis limit 12 за локальный день и package limit 3 переживают повторный/конкурентный run;
2. за пять полных дней ровно 54/6, а один день даёт не всегда 11/1; долг после пустого
   класса погашается;
3. повторный и два конкурентных claim не создают дубль кандидата/попытки/пакета;
4. Codex-промпт и persistence содержат marker только из article body, а не только HN title/snippet;
5. retry не claim-ится до 6 часов, claim-ится при `retry_at <= now`, съедает слот и второй сбой
   терминален;
6. review-required даёт `awaiting_review`, auto-review — `approved`, а недопустимый approve/reject не
   меняет статус/историю;
7. post не содержит source URL, но show возвращает URL, context, analysis, post, media и history;
8. media строго проходит og/twitter → article → Wikimedia, локально сохраняется с MIME/size/safe path;
9. активное медиа не удаляется после генерации и TTL; reject удаляет; orphan/rejected старше 48 часов
   удаляется, а моложе — нет;
10. network/extraction/Codex/filesystem/SQL ошибки не сохраняют и не печатают секреты, но
    оставляют наблюдаемое восстанавливаемое состояние;
11. rollback claim/package/history не теряет бюджет и не создаёт частичных строк;
12. wheel находит новый Alembic head вне checkout.

Каждая мутация применяется по одной, вызывает узкий RED и полностью восстанавливается.
Результат записывается в `docs/development-loop/evidence/2026-08-08-wave-3-review.md`.

## Задача 6: live proof, merge и чистое завершение

- [ ] На disposable PostgreSQL 16 доказать migration, квоту, due retry, package/history и review.
- [ ] Без запроса к модели проверить `codex --version` и нужные `codex exec --help` flags.
- [ ] После явного подтверждения оператора выполнить один изолированный живой `codex exec`
  с малой схемой; не печатать auth и не хардкодить модель.
- [ ] Отдельно проверить article и Wikimedia HTTP-границы без изменения внешних данных.
- [ ] Обновить `docs/development-loop/runs/2026-08-08-run-002.md` и метрики README контура только
  по фактическим данным.
- [ ] Слить accepted feature-ветку в `main` без push.
- [ ] На `main` повторить full gate: non-integration, integration, compileall, `ruff check src`,
  `git diff --check`, wheel.
- [ ] Только после GREEN удалить feature-ветку/worktree, build/dist/egg-info, `.venv`, pytest/Python caches
  и disposable PostgreSQL container; `.env` и пользовательские media не удалять.
- [ ] Подтвердить `main`, итоговый commit, пустой `git status --porcelain` и отсуттвие push.

## Критерии приёмки

- [ ] Все 12 mutation gates дают RED; ни одна мутация не выживает.
- [ ] Новые RED не зависят от сети, живого Codex или недоступной БД.
- [ ] Суточные лимиты, 54/6, retry, concurrency и review доказаны на PostgreSQL.
- [ ] Каждый успешный пакет полон и имеет локальное валидное media; активное media не удаляется.
- [ ] Ни один кандидат не анализируется по title/snippet без article text.
- [ ] CLI даёт полную ручную проверку и безопасные ошибки.
- [ ] Telegram, UI, AI-image generation и переоценка Wave 2 отсутствуют.
- [ ] Terra High не имеет Critical/Important; полный gate зелёный на merged `main`.
- [ ] Run log заполнен фактами; репозиторий чист.

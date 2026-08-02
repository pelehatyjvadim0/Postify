# План реализации волны 1: импорт HN Algolia

> **Для агентных исполнителей:** выполнять задачи строго последовательно через TDD. Перед следующей волной обязателен свежий reviewer Terra 5.6 high: сначала тесты и критичные мутации, затем код.

**Цель:** команда `postify run-once` получает кандидатов HN Algolia, сохраняет новые записи в PostgreSQL и безопасно пропускает дубли; `start`, `status` и `stop` безопасно управляют system unit'ами.

**Архитектура:** CLI собирает зависимости в `bootstrap.py`. Сценарий импорта зависит от порта источника и порта репозитория; HTTPX и SQLAlchemy остаются на внешних границах. Идемпотентность хранения обеспечивает ограничение PostgreSQL на `(source_name, source_id)`.

**Стек:** Python 3.12, uv, Typer, Pydantic Settings, HTTPX, SQLAlchemy, Psycopg, Alembic, PostgreSQL 16, Pytest, systemd.

## Общие ограничения

- Docker и контейнеры не используются.
- Секреты не попадают в Git; в репозитории хранится только `.env.example`.
- Ниша и поисковый запрос не зашиваются в адаптер: `HN_QUERY` приходит из конфигурации текущей фермы.
- Модульные и CLI-тесты не обращаются к сети, PostgreSQL и systemd.
- Интеграционные тесты используют только отдельную обязательную `TEST_DATABASE_URL`. В обязательной проверке волны отсутствие переменной — ошибка, а не `skip`; CI поднимает чистую PostgreSQL 16 для этого набора.
- Каждый тестовый пример проходит цикл «красный по ожидаемой причине → минимальный зелёный код». Тест, который падает из-за отсутствия `pyproject.toml` или зависимости вместо проверяемого контракта, не считается красным TDD-тестом.
- Код и новые файлы добавляются только для работающего сценария этой волны. Не создаются заготовки будущих генератора, Telegram или наблюдаемости.
- Локальные коммиты допустимы; отправка в GitHub требует отдельного подтверждения пользователя.

## Операционное условие

HN Algolia — выбранный первый источник; все его параметры поиска приходят из конфигурации. До задачи 5 оператор предоставляет абсолютные пути к Python-окружению и `EnvironmentFile`, системного пользователя службы, три времени с часовым поясом, `POSTGRESQL_SYSTEMD_UNIT` и явное значение владения БД: `dedicated` либо `shared_allowed`. Используются system unit'ы. `postify start` и `stop` выполняют команды PostgreSQL только при одном из этих явно указанных значений; при `shared_allowed` оператор подтверждает остановку общего экземпляра для всех клиентов.

## Карта файлов волны

Создаются только файлы, нужные для импорта, хранения и его проверки:

```text
pyproject.toml
uv.lock
.env.example
alembic.ini
src/postify/infrastructure/database/migrations/env.py
src/postify/infrastructure/database/migrations/versions/*_create_candidates.py
src/postify/__init__.py
src/postify/config.py
src/postify/bootstrap.py
src/postify/cli.py
src/postify/domain/candidates/models.py
src/postify/application/ports/candidate_source.py
src/postify/application/ports/candidate_repository.py
src/postify/application/ingestion/import_candidates.py
src/postify/adapters/sources/hn_algolia.py
src/postify/infrastructure/database/engine.py
src/postify/infrastructure/database/models.py
src/postify/infrastructure/repositories/sqlalchemy_candidates.py
src/postify/infrastructure/systemd.py
deploy/systemd/postify-run-once.service
deploy/systemd/postify-run-once.timer
scripts/install-systemd.sh
tests/unit/config/test_settings.py
tests/unit/domain/candidates/test_models.py
tests/unit/application/ingestion/test_import_candidates.py
tests/unit/adapters/sources/test_hn_algolia.py
tests/unit/infrastructure/test_systemd.py
tests/integration/conftest.py
tests/integration/test_migrations.py
tests/integration/infrastructure/test_sqlalchemy_candidates.py
tests/integration/test_import_component.py
tests/e2e/test_cli_run_once.py
tests/e2e/test_systemd_installer.py
```

Изменяется `README.md`: после успешного завершения волны добавить инструкцию `uv sync`, настройку `.env`, миграцию, разовый запуск и установку system unit'ов. Не обещать отбор, генерацию, Telegram или расширенный `status`.

## Контракты

```python
@dataclass(frozen=True, slots=True)
class Candidate:
    source_name: str
    source_id: str
    title: str
    url: str
    discovered_at: datetime
    raw_payload: Mapping[str, Any]

@dataclass(frozen=True, slots=True)
class ImportResult:
    received: int
    created: int
    duplicates: int

class CandidateSource(Protocol):
    def fetch(self) -> Sequence[Candidate]: ...

class CandidateRepository(Protocol):
    def save_new(self, candidates: Sequence[Candidate]) -> int: ...
```

`Candidate` отклоняет пустые или состоящие из пробелов строковые поля, URL без схемы `http`/`https` и хоста, а также наивное время; он хранит независимую JSON-совместимую копию `raw_payload`. `ImportCandidates.execute()` вызывает источник и репозиторий ровно по одному разу, возвращает `duplicates = received - created` и отклоняет число созданных записей вне диапазона от нуля до числа полученных. Репозиторий не изменяет существующую запись при конфликте.

### Задача 1: окружение и конфигурация

**Файлы:** `pyproject.toml`, `uv.lock`, `.env.example`, `src/postify/__init__.py`, `src/postify/config.py`, `tests/unit/config/test_settings.py`.

- [ ] Создать минимальный `pyproject.toml` с Python `>=3.12`, runtime-зависимостями `alembic`, `httpx`, `psycopg[binary]`, `pydantic-settings`, `sqlalchemy`, `typer`, dev-зависимостью `pytest` и entry point `postify = "postify.cli:app"`; выполнить `uv lock && uv sync --all-groups`. Это подготовка инструмента, а не зелёная реализация контракта.
- [ ] Написать красные тесты `Settings` в `tests/unit/config/test_settings.py`: URL PostgreSQL, `HN_QUERY`, `HN_TAGS`, `HN_HITS_PER_PAGE`, `POSTGRESQL_SYSTEMD_UNIT`, режим владения и расписание читаются из окружения; окружение приоритетнее переданному `.env`; отсутствие `DATABASE_URL`, неверный DSN, имя unit'а не вида `*.service` и иной режим владения дают ошибку валидации. Запустить `uv run pytest tests/unit/config/test_settings.py -v`; ожидание — импорт `postify.config` отсутствует.
- [ ] Реализовать минимальный `Settings` с этими полями. В `.env.example` указать только образцы `DATABASE_URL`, HN-параметров, `POSTGRESQL_SYSTEMD_UNIT=postgresql.service`, режима владения, расписания и адреса Algolia без секретов.
- [ ] Повторно выполнить тот же тест; ожидание — PASS.
- [ ] Закоммитить каркас понятным русским сообщением.

### Задача 2: доменный контракт и порты

**Файлы:** `src/postify/domain/candidates/models.py`, `src/postify/application/ports/candidate_source.py`, `src/postify/application/ports/candidate_repository.py`, `tests/unit/domain/candidates/test_models.py`.

- [ ] Написать красные тесты: каждый обязательный строковый атрибут отвергает пустое и пробельное значение; URL без схемы или хоста отвергается; наивный `discovered_at` отвергается; UTC-время и корректный URL принимаются; мутация исходного словаря после создания кандидата не меняет его payload. Запустить `uv run pytest tests/unit/domain/candidates/test_models.py -v`; ожидание — ошибка импорта модели.
- [ ] Реализовать `Candidate`, `CandidateValidationError` и два порта через `typing.Protocol`, без импортов HTTPX и SQLAlchemy.
- [ ] Повторно выполнить тесты; ожидание — PASS.
- [ ] Закоммитить доменный контракт понятным русским сообщением.

### Задача 3: сценарий импорта и HN Algolia

**Файлы:** `src/postify/application/ingestion/import_candidates.py`, `src/postify/adapters/sources/hn_algolia.py`, `tests/unit/application/ingestion/test_import_candidates.py`, `tests/unit/adapters/sources/test_hn_algolia.py`.

- [ ] Написать красные тесты сценария с подставными портами: три полученных кандидата и два сохранённых дают `ImportResult(3, 2, 1)`; источник и репозиторий вызваны ровно раз; создано `-1` или `4` при трёх полученных вызывает `ValueError`. Запустить тест сценария; ожидание — ошибка импорта.
- [ ] Написать красные тесты адаптера на `httpx.MockTransport`: запрос содержит конфигурационные `HN_TAGS`, `HN_HITS_PER_PAGE` и `HN_QUERY`; корректный hit преобразуется в UTC-кандидат; `story_url` используется при отсутствии `url`; смешанный ответ оставляет только валидные hit; hit без обязательного поля или с неверным временем пропускается; не-JSON, 429/5xx и timeout дают нормализованную ошибку источника. Параметры двух профилей дают разные запросы.
- [ ] Реализовать минимальные `ImportCandidates` и `HnAlgoliaCandidateSource`. Адаптер принимает готовый `httpx.Client`, URL и запрос явно, вызывает `raise_for_status()` и не меняет `raw_payload`.
- [ ] Запустить оба набора: `uv run pytest tests/unit/application/ingestion tests/unit/adapters/sources -v`; ожидание — PASS без сети.
- [ ] Закоммитить импорт понятным русским сообщением.

### Задача 4: миграция PostgreSQL и идемпотентный репозиторий

**Файлы:** `alembic.ini` (только разработка), `src/postify/infrastructure/database/migrations/env.py`, `src/postify/infrastructure/database/migrations/versions/*_create_candidates.py`, `src/postify/infrastructure/database/engine.py`, `src/postify/infrastructure/database/models.py`, `src/postify/infrastructure/repositories/sqlalchemy_candidates.py`, `tests/integration/conftest.py`, `tests/integration/infrastructure/test_sqlalchemy_candidates.py`.

- [ ] Написать красную интеграционную фикстуру: она требует `TEST_DATABASE_URL`, создаёт уникальную схему/БД, передаёт этот URL в Alembic явно через `POSTIFY_ALEMBIC_DATABASE_URL`, применяет миграции только туда и удаляет только свой ресурс. Несовпадение тестового URL с URL разработки обязательно. В проверке волны отсутствие переменной завершается ошибкой конфигурации, а не `skip`.
- [ ] Написать красные миграционные тесты: на пустой тестовой БД выполнить `base → head`, проверить JSONB и именованное уникальное ограничение, затем `downgrade base` и повторный `upgrade head`. Написать красные тесты репозитория: первая сессия фиксирует запись и видна второй; повторный вызов, дубли `[A, A, B]` и одновременные вставки из двух независимых сессий создают ровно одну запись на ключ; конфликт не перезаписывает поля; ошибка сериализации payload делает rollback и не ломает следующее валидное сохранение.
- [ ] Реализовать `target_metadata`, источник URL и транзакции Alembic, модель, миграцию и репозиторий. Миграции хранятся только в `src/postify/infrastructure/database/migrations/`, входят в wheel; корневой `alembic.ini` направлен в тот же каталог и служит только разработке. Runtime находит migration scripts через package resources. Использовать PostgreSQL-вставку с `on_conflict_do_nothing` по именованному ограничению и `RETURNING` для точного числа созданных записей.
- [ ] Написать компонентный тест: `httpx.MockTransport` + настоящий PostgreSQL + `open_importer` создают строку из одного JSON-hit, а повтор возвращает `created=0`; systemd в тест не вызывается. Повторно выполнить `TEST_DATABASE_URL=… uv run pytest -m integration -v`; ожидание — PASS. Не выполнять миграции и очистку на `DATABASE_URL` разработки.
- [ ] Закоммитить хранение понятным русским сообщением.

### Задача 5: CLI и systemd

**Файлы:** `src/postify/bootstrap.py`, `src/postify/cli.py`, `src/postify/infrastructure/systemd.py`, `deploy/systemd/postify-run-once.service`, `deploy/systemd/postify-run-once.timer`, `scripts/install-systemd.sh`, `tests/unit/infrastructure/test_systemd.py`, `tests/e2e/test_cli_run_once.py`, `tests/e2e/test_systemd_installer.py`.

- [ ] Написать красные CLI-тесты с подставными фабриками: успешный `run-once` печатает `Получено: 3; новых: 2; дубликатов: 1`; ошибка источника даёт ненулевой код и понятное сообщение без traceback; `start` вызывает в порядке «валидация → запуск PostgreSQL-unit → ожидание БД → проверка миграций → включение timer» и при ошибке миграции не включает timer; `stop` вызывает «отключение и остановка timer → ожидание завершения активной задачи до timeout → остановка PostgreSQL-unit», а при timeout не останавливает БД; `status` показывает PostgreSQL-unit, доступность БД, состояние timer, последнее и следующее срабатывание, число кандидатов и последний результат задачи. Настоящие HTTP-клиент, БД и systemctl не создаются.
- [ ] Написать красные тесты контроллера: все вызовы `systemctl` передаются списком аргументов без `shell=True`; PostgreSQL-unit берётся из `Settings`; `wait_for_run_once()` не вызывает остановку service и имеет конечный timeout; ошибка systemctl не скрывается. Написать тест установщика с подставными `install`, `systemctl` и `systemd-analyze`: он создаёт system unit'ы с абсолютными `ExecStart`, `WorkingDirectory`, `EnvironmentFile`, `User`, `Group`, `After/Wants=network-online.target`, `TimeoutStartSec`, `SyslogIdentifier` и `Persistent=true`; отклоняет пустое, многострочное и незаменённое расписание; проверяет календарь и unit-файлы, затем вызывает `daemon-reload`.
- [ ] Реализовать контекстный `open_importer(settings)`, который закрывает HTTP-клиент и engine при успехе и исключении, команды `run-once`, `start`, `status`, `stop` и тонкий `SystemdController`. `start` не включает timer, если PostgreSQL, БД или миграции не готовы. `stop` не убивает активную задачу, а ждёт её с timeout; при timeout PostgreSQL остаётся запущенным и команда завершается ошибкой. Известная ошибка источника даёт ненулевой код. Unit `postify-run-once.service` имеет `Type=oneshot`, абсолютные пути и `EnvironmentFile`; timer запускает именно его. Установщик работает только в system-режиме и не исполняет shell-код из `.env`.
- [ ] Запустить `uv run pytest tests/unit/infrastructure tests/e2e -v`; ожидание — PASS без настоящего systemctl.
- [ ] Закоммитить CLI и запуск понятным русским сообщением.

### Задача 6: полная проверка, README и ревью волны

**Файлы:** `README.md`.

- [ ] Запустить `uv run pytest -m "not integration" -v`, затем `TEST_DATABASE_URL=… uv run pytest -m integration -v`, `POSTIFY_ALEMBIC_DATABASE_URL="$TEST_DATABASE_URL" uv run alembic upgrade head`, `POSTIFY_ALEMBIC_DATABASE_URL="$TEST_DATABASE_URL" uv run alembic check`, `uv run python -m compileall -q src` и `git diff --check`. Дополнительно собрать wheel, установить его в чистое временное venv и из `/tmp` проверить `migrations_at_head()` на временном PostgreSQL 16. Все команды должны завершиться с кодом 0.
- [ ] Обновить README только проверяемой инструкцией разового импорта.
- [ ] Передать весь diff свежему reviewer Terra 5.6 high. Он сначала проверяет тесты, временно внося и откатывая мутации: убрать проверку пробельного поля, не вызвать `raise_for_status`, заменить запрос конфигурации строкой `AI`, убрать `on_conflict_do_nothing`, поменять порядок `stop`, включить timer до проверки БД. Каждая мутация обязана сделать соответствующий тест красным.
- [ ] После успешной проверки тестов тот же reviewer проверяет код: границы зависимостей, транзакцию, отсутствие лишних файлов и честность обработки ошибки.
- [ ] Устранить замечания, повторить полный набор и закоммитить завершённую волну понятным русским сообщением. Только после этого разрешена работа над планом волны 2.

## Вне объёма

Отбор, журнал решений, генератор, визуал, Telegram, очередь, расширенный `status` и долговечный журнал ошибок не создаются в этой волне.

# План реализации волны 1: импорт HN Algolia

> **Для агентных исполнителей:** обязательный навык — `superpowers:executing-plans`. Шаги отмечаются чекбоксами и выполняются последовательно.

**Цель:** по команде `postify run-once` получать кандидатов HN Algolia, сохранять новые записи в PostgreSQL и безопасно пропускать дубли; подготовить локальный запуск задачи через systemd timer.

**Архитектура:** синхронный CLI собирает зависимости в `bootstrap.py`. Сценарий импорта зависит только от портов источника и репозитория; HTTPX и SQLAlchemy остаются в адаптерах и инфраструктуре. Уникальная пара `source_name` и `source_id` гарантирует идемпотентность хранения.

**Стек:** Python 3.12, uv, Typer, Pydantic Settings, HTTPX, SQLAlchemy, Psycopg, Alembic, PostgreSQL 16, Pytest, systemd.

## Общие ограничения

- Локальная Ubuntu и будущий VPS используют одинаковый код; отличаются только `.env`, системный пользователь и путь к окружению.
- Docker и контейнеры не используются.
- Секреты не добавляются в Git; в репозитории хранится только `.env.example`.
- Код пишется через TDD: сначала падающий тест, затем минимальная реализация.
- Во время модульных и CLI-тестов запрещены реальные запросы в Algolia, Telegram, systemd и PostgreSQL.
- Каждая команда Git фиксируется локально; отправка в GitHub требует отдельного подтверждения пользователя.

---

## Карта файлов волны

Создаются только эти файлы. Другие каталоги из целевой архитектуры пока не создаются.

```text
pyproject.toml
.env.example
alembic.ini
migrations/env.py
migrations/versions/*_create_candidates.py
deploy/systemd/postify-run-once.service
deploy/systemd/postify-run-once.timer
scripts/install-systemd.sh
src/postify/__init__.py
src/postify/config.py
src/postify/bootstrap.py
src/postify/cli.py
src/postify/domain/candidates/models.py
src/postify/application/ports/candidate_source.py
src/postify/application/ports/candidate_repository.py
src/postify/application/ingestion/import_candidates.py
src/postify/application/jobs/run_once.py
src/postify/adapters/sources/hn_algolia.py
src/postify/infrastructure/database/engine.py
src/postify/infrastructure/database/models.py
src/postify/infrastructure/repositories/sqlalchemy_candidates.py
src/postify/infrastructure/systemd.py
tests/unit/domain/candidates/test_models.py
tests/unit/application/ingestion/test_import_candidates.py
tests/unit/adapters/sources/test_hn_algolia.py
tests/integration/infrastructure/test_sqlalchemy_candidates.py
tests/e2e/test_cli_run_once.py
```

Изменяются существующие файлы:

```text
.gitignore  — добавить исключения виртуального окружения, кэшей, локальных журналов и `.env`, не затрагивая уже заданные правила.
README.md   — добавить короткий раздел установки и проверки первой волны после успешной реализации.
```

## Контракт данных

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
```

`Candidate` не допускает пустые `source_name`, `source_id`, `title` или `url`. Поле `discovered_at` обязано быть timezone-aware. Репозиторий хранит запись один раз по уникальной паре `(source_name, source_id)`.

## Задача 1: каркас проекта и конфигурация

**Файлы:**

- Создать: `pyproject.toml`, `.env.example`, `src/postify/__init__.py`, `src/postify/config.py`.
- Изменить: `.gitignore`.

**Интерфейсы:**

- Производит `Settings` с полями `database_url: PostgresDsn`, `hn_algolia_url: HttpUrl`, `systemd_unit_directory: Path` и `systemctl_command: str`.
- `Settings()` читает `.env`, но явные переменные среды имеют приоритет.

- [ ] **Шаг 1: Написать падающий тест конфигурации в новом `tests/unit/domain/candidates/test_models.py` не следует.**

Тест конфигурации добавляется в `tests/e2e/test_cli_run_once.py`, потому что он проверяет точку входа. В начале файла поместить:

```python
from postify.config import Settings

def test_settings_reads_database_url_from_environment(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://postify:secret@localhost:5432/postify")
    settings = Settings(_env_file=None)
    assert str(settings.database_url).startswith("postgresql+psycopg://postify:")
```

- [ ] **Шаг 2: Запустить тест и убедиться, что он падает.**

Запустить: `uv run pytest tests/e2e/test_cli_run_once.py::test_settings_reads_database_url_from_environment -v`.

Ожидание: ошибка импорта `postify.config` до реализации.

- [ ] **Шаг 3: Добавить минимальную конфигурацию и зависимости.**

В `pyproject.toml` объявить Python `>=3.12`, пакеты `alembic`, `httpx`, `psycopg[binary]`, `pydantic-settings`, `sqlalchemy`, `typer` и группу разработки с `pytest`. Точка входа должна быть `postify = "postify.cli:app"`.

В `config.py` определить:

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    database_url: PostgresDsn
    hn_algolia_url: HttpUrl = "https://hn.algolia.com/api/v1/search_by_date"
    systemd_unit_directory: Path = Path("/etc/systemd/system")
    systemctl_command: str = "systemctl"
```

В `.env.example` оставить `DATABASE_URL=postgresql+psycopg://postify:change-me@localhost:5432/postify`; не добавлять рабочие токены.

- [ ] **Шаг 4: Повторно запустить тест.**

Запустить: `uv sync --all-groups && uv run pytest tests/e2e/test_cli_run_once.py::test_settings_reads_database_url_from_environment -v`.

Ожидание: PASS.

- [ ] **Шаг 5: Зафиксировать каркас.**

```bash
git add pyproject.toml uv.lock .env.example .gitignore src/postify/__init__.py src/postify/config.py tests/e2e/test_cli_run_once.py
git commit -m "Подготовил конфигурацию первой волны"
```

## Задача 2: доменная модель и порты импорта

**Файлы:**

- Создать: `src/postify/domain/candidates/models.py`, `src/postify/application/ports/candidate_source.py`, `src/postify/application/ports/candidate_repository.py`, `tests/unit/domain/candidates/test_models.py`.

**Интерфейсы:**

- Производит `Candidate` и `CandidateValidationError`.
- Производит протоколы `CandidateSource.fetch() -> Sequence[Candidate]` и `CandidateRepository.save_new(candidates: Sequence[Candidate]) -> int`.

- [ ] **Шаг 1: Написать падающие тесты инвариантов.**

```python
def test_candidate_rejects_empty_source_id():
    with pytest.raises(CandidateValidationError, match="source_id"):
        Candidate("hn_algolia", "", "Title", "https://example.com", aware_datetime, {})

def test_candidate_rejects_naive_discovered_at():
    with pytest.raises(CandidateValidationError, match="discovered_at"):
        Candidate("hn_algolia", "42", "Title", "https://example.com", datetime(2026, 8, 1), {})
```

- [ ] **Шаг 2: Запустить тесты и убедиться, что они падают.**

Запустить: `uv run pytest tests/unit/domain/candidates/test_models.py -v`.

Ожидание: ошибка импорта `Candidate`.

- [ ] **Шаг 3: Реализовать минимальную модель и порты.**

`Candidate.__post_init__` проверяет четыре строковых идентификатора и timezone-aware дату; `raw_payload` не изменяется моделью. Порты определяются через `typing.Protocol`, без импорта HTTPX или SQLAlchemy.

- [ ] **Шаг 4: Повторно запустить тесты.**

Запустить: `uv run pytest tests/unit/domain/candidates/test_models.py -v`.

Ожидание: PASS.

- [ ] **Шаг 5: Зафиксировать доменный контракт.**

```bash
git add src/postify/domain/candidates/models.py src/postify/application/ports tests/unit/domain/candidates/test_models.py
git commit -m "Добавил модель кандидата и порты импорта"
```

## Задача 3: сценарий импорта и адаптер HN Algolia

**Файлы:**

- Создать: `src/postify/application/ingestion/import_candidates.py`, `src/postify/application/jobs/run_once.py`, `src/postify/adapters/sources/hn_algolia.py`, `tests/unit/application/ingestion/test_import_candidates.py`, `tests/unit/adapters/sources/test_hn_algolia.py`.

**Интерфейсы:**

- Потребляет порты из задачи 2.
- Производит `ImportCandidates.execute() -> ImportResult`, `run_once(importer: ImportCandidates) -> ImportResult` и `HnAlgoliaCandidateSource`.
- `HnAlgoliaCandidateSource.fetch()` отправляет `GET` на `hn_algolia_url` с параметрами `tags=story`, `query=AI`, `hitsPerPage=100`.

- [ ] **Шаг 1: Написать падающий тест сценария с подставными портами.**

```python
def test_import_candidates_reports_created_and_duplicates():
    source = FakeSource([candidate_a, candidate_b, candidate_c])
    repository = FakeRepository(created=2)
    assert ImportCandidates(source, repository).execute() == ImportResult(3, 2, 1)
```

- [ ] **Шаг 2: Запустить тест и убедиться, что он падает.**

Запустить: `uv run pytest tests/unit/application/ingestion/test_import_candidates.py -v`.

Ожидание: ошибка импорта `ImportCandidates`.

- [ ] **Шаг 3: Написать падающий тест преобразования ответа Algolia.**

```python
def test_fetch_maps_algolia_hit_to_candidate(httpx_mock_transport):
    source = HnAlgoliaCandidateSource(httpx.Client(transport=httpx_mock_transport), settings)
    candidate = source.fetch()[0]
    assert (candidate.source_name, candidate.source_id) == ("hn_algolia", "123")
    assert candidate.url == "https://example.com/tool"
```

Транспорт возвращает JSON с одним `hit`: `objectID`, `title`, `url`, `created_at_i`. Второй тест проверяет, что `story_url` применяется, когда у `hit` нет `url`.

- [ ] **Шаг 4: Реализовать сценарий и адаптер.**

`ImportCandidates.execute()` вызывает источник ровно один раз, передаёт всю последовательность в `save_new()` и возвращает `duplicates = len(candidates) - created`; отрицательное значение `created` или значение больше числа кандидатов вызывает `ValueError`.

`HnAlgoliaCandidateSource` принимает готовый `httpx.Client` и URL строкой. Он вызывает `response.raise_for_status()`, пропускает записи без `objectID`, заголовка или URL и переводит `created_at_i` в UTC `datetime`.

- [ ] **Шаг 5: Запустить тесты сценария и адаптера.**

Запустить: `uv run pytest tests/unit/application/ingestion tests/unit/adapters/sources -v`.

Ожидание: PASS, без сетевых обращений.

- [ ] **Шаг 6: Зафиксировать импорт HN Algolia.**

```bash
git add src/postify/application/ingestion src/postify/application/jobs src/postify/adapters/sources tests/unit/application tests/unit/adapters
git commit -m "Добавил импорт кандидатов из HN Algolia"
```

## Задача 4: PostgreSQL, миграция и идемпотентный репозиторий

**Файлы:**

- Создать: `alembic.ini`, `migrations/env.py`, `migrations/versions/*_create_candidates.py`, `src/postify/infrastructure/database/engine.py`, `src/postify/infrastructure/database/models.py`, `src/postify/infrastructure/repositories/sqlalchemy_candidates.py`, `tests/integration/infrastructure/test_sqlalchemy_candidates.py`.

**Интерфейсы:**

- Потребляет `Candidate` и `CandidateRepository`.
- Производит `create_engine_from_settings(settings: Settings) -> Engine` и `SqlAlchemyCandidateRepository(session_factory)`.
- Таблица `candidates`: `id`, `source_name`, `source_id`, `title`, `url`, `discovered_at`, `raw_payload`, `created_at`; уникальный индекс на `source_name, source_id`.

- [ ] **Шаг 1: Написать падающий интеграционный тест повторного сохранения.**

```python
def test_save_new_inserts_candidate_once(session_factory):
    repository = SqlAlchemyCandidateRepository(session_factory)
    assert repository.save_new([candidate_a]) == 1
    assert repository.save_new([candidate_a]) == 0
```

Фикстура применяет миграции к PostgreSQL из `TEST_DATABASE_URL`. Если переменная не задана, тест помечается `skip`, не подменяет PostgreSQL SQLite-базой.

- [ ] **Шаг 2: Запустить интеграционный тест и убедиться, что он падает.**

Запустить: `TEST_DATABASE_URL="$DATABASE_URL" uv run pytest tests/integration/infrastructure/test_sqlalchemy_candidates.py -v`.

Ожидание: ошибка импорта репозитория до реализации.

- [ ] **Шаг 3: Реализовать схему, миграцию и репозиторий.**

Модель SQLAlchemy использует `JSONB` для исходного payload. `save_new()` строит PostgreSQL-вставку SQLAlchemy с `on_conflict_do_nothing(index_elements=["source_name", "source_id"])` и возвращает число добавленных строк. Миграция Alembic создаёт таблицу и уникальное ограничение с теми же именами.

- [ ] **Шаг 4: Применить миграцию и повторно запустить тест.**

Запустить: `uv run alembic upgrade head && TEST_DATABASE_URL="$DATABASE_URL" uv run pytest tests/integration/infrastructure/test_sqlalchemy_candidates.py -v`.

Ожидание: PASS; второй вызов `save_new()` возвращает ноль.

- [ ] **Шаг 5: Зафиксировать слой хранения.**

```bash
git add alembic.ini migrations src/postify/infrastructure/database src/postify/infrastructure/repositories tests/integration/infrastructure
git commit -m "Добавил хранение кандидатов в PostgreSQL"
```

## Задача 5: CLI, systemd и сборка зависимостей

**Файлы:**

- Создать: `src/postify/bootstrap.py`, `src/postify/cli.py`, `src/postify/infrastructure/systemd.py`, `deploy/systemd/postify-run-once.service`, `deploy/systemd/postify-run-once.timer`, `scripts/install-systemd.sh`.
- Дополнить: `tests/e2e/test_cli_run_once.py`.

**Интерфейсы:**

- Производит Typer-приложение `app` с командами `run-once`, `start`, `status`, `stop`.
- `build_importer(settings: Settings) -> ImportCandidates` собирает HTTP-клиент, Algolia-адаптер и SQLAlchemy-репозиторий.
- `SystemdController` предоставляет `enable_and_start_timer()`, `stop_and_disable_timer()` и `timer_status() -> str`.

- [ ] **Шаг 1: Написать падающие CLI-тесты с подставным контроллером.**

```python
def test_start_enables_timer(monkeypatch):
    controller = FakeSystemdController()
    monkeypatch.setattr("postify.cli.build_systemd_controller", lambda _: controller)
    result = CliRunner().invoke(app, ["start"])
    assert result.exit_code == 0
    assert controller.enabled is True

def test_run_once_prints_import_result(monkeypatch):
    monkeypatch.setattr("postify.cli.build_importer", lambda _: FakeImporter(ImportResult(3, 2, 1)))
    result = CliRunner().invoke(app, ["run-once"])
    assert result.output == "Получено: 3; новых: 2; дубликатов: 1\\n"
```

- [ ] **Шаг 2: Запустить CLI-тесты и убедиться, что они падают.**

Запустить: `uv run pytest tests/e2e/test_cli_run_once.py -v`.

Ожидание: ошибка импорта `app` до реализации команд.

- [ ] **Шаг 3: Реализовать минимальные команды и unit-файлы.**

`run-once` вызывает `run_once(build_importer(Settings()))` и печатает точную строку из теста. `start` включает и запускает `postify-run-once.timer`; `stop` останавливает и отключает его; `status` печатает состояние timer. Контроллер вызывает `subprocess.run([command, "enable", "--now", "postify-run-once.timer"], check=True, text=True, capture_output=True)` и аналогичные списки аргументов для остановки и статуса; `shell=True` не используется.

Сервис systemd запускает `postify run-once` с `Type=oneshot` и читает настройки приложения из `EnvironmentFile`. В timer-файле используется литерал `@POSTIFY_ON_CALENDAR@`; скрипт установки принимает путь к `.env`, читает из него обязательную переменную `POSTIFY_ON_CALENDAR`, подставляет её в копируемый timer и вызывает `systemctl daemon-reload`. Так systemd получает валидный `OnCalendar`, а расписание остаётся конфигурацией среды. Скрипт не требует и не содержит паролей.

- [ ] **Шаг 4: Запустить CLI-тесты.**

Запустить: `uv run pytest tests/e2e/test_cli_run_once.py -v`.

Ожидание: PASS и отсутствие настоящих вызовов systemd.

- [ ] **Шаг 5: Зафиксировать управляемый запуск.**

```bash
git add src/postify/bootstrap.py src/postify/cli.py src/postify/infrastructure/systemd.py deploy/systemd scripts/install-systemd.sh tests/e2e/test_cli_run_once.py
git commit -m "Добавил команды и запуск задачи через systemd"
```

## Задача 6: полная проверка и документация

**Файлы:**

- Изменить: `README.md`.

- [ ] **Шаг 1: Добавить в README короткую инструкцию.**

Указать `uv sync --all-groups`, настройку `.env` из `.env.example`, миграцию `uv run alembic upgrade head`, разовый импорт `uv run postify run-once` и установку timer через `scripts/install-systemd.sh`. Не включать реальные значения `DATABASE_URL` или токены.

- [ ] **Шаг 2: Запустить весь набор тестов.**

Запустить: `uv run pytest -v`.

Ожидание: все модульные и CLI-тесты проходят; PostgreSQL-интеграционный тест либо проходит при заданном `TEST_DATABASE_URL`, либо явно отмечен `SKIPPED`.

- [ ] **Шаг 3: Проверить форматирование и конфигурацию пакета.**

Запустить: `uv run python -m compileall -q src && uv run alembic check && git diff --check`.

Ожидание: все команды завершаются с кодом 0.

- [ ] **Шаг 4: Зафиксировать завершение волны.**

```bash
git add README.md
git commit -m "Описал запуск первой волны Postify"
```

## Самопроверка плана

- Импорт из HN Algolia: задачи 2–3.
- PostgreSQL, миграции и дедупликация: задача 4.
- `run-once`, CLI и systemd timer: задача 5.
- Локальная документация и проверка: задача 6.
- Telegram, генератор, очередь публикаций, журнал ошибок и видеосервис не входят в эту волну и не получают файлов заранее.

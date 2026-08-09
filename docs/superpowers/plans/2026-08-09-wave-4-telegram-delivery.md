# Wave 4: доставка в Telegram — план реализации

> **Для агентных исполнителей:** ОБЯЗАТЕЛЬНЫЙ SUB-SKILL: использовать `superpowers:subagent-driven-development` для реализации плана по задачам. Все шаги отслеживаются через checkbox (`- [ ]`).

**Цель:** атомарно доставлять не более одного готового `approved` контентного пакета за запуск в один настроенный Telegram-канал, сохраняя подтверждённый `message_id` либо безопасный объяснимый исход без автоматического риска дубля.

**Архитектура:** отдельный application action владеет выбором пакета, переходами, классификацией исходов, retry-политикой и cleanup; узкий Telegram adapter владеет только HTTP/multipart-контрактом Bot API и возвращает типизированный результат. PostgreSQL-репозиторий атомарно резервирует FIFO-пакет через `FOR UPDATE SKIP LOCKED`, хранит одну доставку на пакет и append-only историю завершённых попыток; systemd запускает отдельную CLI-команду `publish-once` по трём значениям `OnCalendar`.

**Стек:** Python 3.12+, dataclasses/Protocol, Typer, pydantic-settings, httpx, SQLAlchemy + PostgreSQL, Alembic, pytest, POSIX sh, systemd.

## Общие ограничения

- База перехода: `main/spec@96bde416cabcca0bb80ebc209291b5b2ac292622`; весь код Wave 4 остаётся в `feature/wave-4-telegram-delivery` и не отправляется на GitHub.
- Строго TDD: сначала отдельный Sol 5.6 High создаёт и запускает весь RED-пакет без production-кода; каждый RED обязан быть вызван отсутствующим поведением, а не окружением или ошибкой теста.
- После подтверждённого RED отдельный Terra 5.6 Medium пишет минимальный GREEN; controller не пишет production-код.
- Свежая Terra 5.6 High сначала независимо проверяет тесты и мутации, затем код; до финальных gates должно остаться `0 Critical` и `0 Important`, каждый `Minor` заносится в ledger.
- В доставку попадают только `approved` пакеты, FIFO по `content_packages.id`, не более одного нового пакета за запуск.
- Telegram Bot API не предоставляет client idempotency key: timeout, transport error после начала запроса, потерянный ответ и stale `sending` дают `uncertain`, который никогда не ретраится автоматически.
- Повторный запуск не вызывает Telegram для `published`, `failed` и `uncertain`; только `retryable` может быть зарезервирован повторно.
- `published` и переход пакета `approved → published` допустимы только после ответа Telegram `ok=true` с целочисленным `message_id`.
- Локальное медиа удаляется только после committed confirmation; ошибка удаления не отменяет публикацию, а следующий запуск повторяет только cleanup без нового HTTP-вызова.
- Ошибки и CLI не раскрывают bot token, полный Bot API URL, текст поста, содержимое файла и внутренний путь за пределами необходимого безопасного кода.
- Настройки окружения: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `TELEGRAM_TIMEOUT_SECONDS`, `TELEGRAM_ON_CALENDAR_MORNING`, `TELEGRAM_ON_CALENDAR_DAY`, `TELEGRAM_ON_CALENDAR_EVENING`; все обязательны, timeout строго положительный, три schedule непустые.
- В scope не входят UI, форматы текста, тематики, аналитика, другие площадки, универсальный outbox/multichannel и дефекты `content list`/cron `.env`, если RED Wave 4 не докажет прямую блокировку.
- Документация, сообщения коммитов и operator-facing сообщения пишутся по-русски; секреты в evidence не записываются.
- Baseline: 327 non-integration и 42 integration tests; финальная проверка обязана включить обе группы, `compileall`, `ruff` при наличии, `uv lock --check`, `git diff --check`, migration upgrade/downgrade и wheel/install границы.

---

## Карта файлов

- `src/postify/domain/delivery/models.py` — только состояния, запрос/подтверждение, claim/result и типизированная безопасная ошибка публикации.
- `src/postify/application/ports/telegram_publisher.py` — узкий протокол внешней публикации.
- `src/postify/application/ports/delivery_repository.py` — транзакционные операции доставки; никаких HTTP/filesystem деталей.
- `src/postify/application/delivery/publish_content.py` — единственная оркестрация бизнес-переходов и cleanup-first политика.
- `src/postify/adapters/telegram/bot_api.py` — чтение локального файла, `sendPhoto` multipart, разбор Telegram JSON, классификация безопасных исходов.
- `src/postify/infrastructure/repositories/sqlalchemy_delivery.py` — PostgreSQL claim, confirmation, попытки и rollback.
- `src/postify/infrastructure/database/migrations/versions/20260809_04_add_telegram_deliveries.py` — только таблицы Wave 4 и расширение допустимого package status до `published` на уровне поведения приложения.
- `src/postify/config.py`, `src/postify/bootstrap.py`, `src/postify/cli.py` — валидация до БД/сети, composition root и `publish-once`.
- `deploy/systemd/postify-publish-once.service`, `deploy/systemd/postify-publish-once.timer`, `scripts/install-systemd.sh` — отдельный delivery job и атомарная установка/rollback четырёх unit-файлов.
- `.env.example`, `pyproject.toml` package-data и тесты — эксплуатационный/упаковочный контракт.
- `docs/development-loop/evidence/2026-08-09-wave-4-red.md`, `docs/development-loop/evidence/2026-08-09-wave-4-review.md`, `docs/development-loop/runs/2026-08-09-run-003.md` — русские доказательства без заявления о приёмке до live preflight.

## Точные интерфейсы между задачами

```python
# src/postify/domain/delivery/models.py
class DeliveryStatus(StrEnum):
    SENDING = "sending"
    RETRYABLE = "retryable"
    PUBLISHED = "published"
    FAILED = "failed"
    UNCERTAIN = "uncertain"

class PublishFailureKind(StrEnum):
    RETRYABLE = "retryable"
    FAILED = "failed"
    UNCERTAIN = "uncertain"

@dataclass(frozen=True, slots=True)
class DeliveryClaim:
    delivery_id: int
    package_id: int
    attempt_no: int
    post_text: str
    media_path: str
    media_mime: str

@dataclass(frozen=True, slots=True)
class TelegramMessage:
    message_id: int

class TelegramPublishError(RuntimeError):
    def __init__(self, *, code: str, reason: str, kind: PublishFailureKind): ...

@dataclass(frozen=True, slots=True)
class PublishContentResult:
    outcome: Literal["empty", "published", "retryable", "failed", "uncertain", "cleanup_completed", "cleanup_pending"]
    package_id: int | None = None
    message_id: int | None = None
```

```python
# src/postify/application/ports/telegram_publisher.py
class TelegramPublisher(Protocol):
    def publish(self, claim: DeliveryClaim) -> TelegramMessage: ...

# src/postify/application/ports/delivery_repository.py
class DeliveryRepository(Protocol):
    def mark_stale_sending_uncertain(self, *, stale_before: datetime, now: datetime) -> int: ...
    def pending_cleanup(self) -> DeliveryClaim | None: ...
    def reserve_next(self, *, now: datetime) -> DeliveryClaim | None: ...
    def record_failure(self, claim: DeliveryClaim, *, kind: PublishFailureKind, code: str, reason: str, now: datetime) -> None: ...
    def confirm_published(self, claim: DeliveryClaim, *, message_id: int, now: datetime) -> None: ...
    def mark_media_deleted(self, delivery_id: int, *, now: datetime) -> None: ...
```

`TelegramPublishError.reason` — уже санитизированный operator-safe код/текст; application слой не включает в него входной exception. `mark_stale_sending_uncertain` создаёт attempt с текущим `attempt_no`, `outcome='uncertain'`, `code='stale_sending'`; `reserve_next` увеличивает attempt number только для `retryable`.

---

### Task 1: полный RED-пакет и трассировка требований

**Файлы:**
- Создать: `tests/unit/domain/delivery/test_models.py`
- Создать: `tests/unit/application/delivery/test_publish_content.py`
- Создать: `tests/unit/adapters/telegram/test_bot_api.py`
- Создать: `tests/integration/infrastructure/test_sqlalchemy_delivery.py`
- Изменить: `tests/integration/test_migrations.py`
- Изменить: `tests/unit/config/test_settings.py`
- Создать: `tests/e2e/test_cli_publish_once.py`
- Изменить: `tests/e2e/test_systemd_installer.py`
- Создать: `tests/unit/infrastructure/test_delivery_wheel.py`
- Создать: `docs/development-loop/evidence/2026-08-09-wave-4-red.md`

**Интерфейсы:** использует только точные интерфейсы из раздела выше; production-файлы не создаёт. Выдаёт hermetic RED-пакет, таблицу `requirement → test → ожидаемая причина RED → mutation` и команды воспроизведения.

- [ ] **Шаг 1: написать unit RED для domain/action.**

В тестах использовать in-memory fake repository/publisher/media с наблюдаемыми реальными состояниями. Обязательные сценарии: пустой слот; cleanup-first; cleanup success/failure без publisher; success confirmation; отсутствие `published` до confirmation; typed `retryable`/`failed`/`uncertain`; stale sending; повторный `published`/`failed`/`uncertain` без publisher. Минимальная форма ключевого теста:

```python
def test_confirmation_is_committed_before_media_delete() -> None:
    events: list[str] = []
    action = PublishContent(
        repository=RepositoryFake(events, claim=approved_claim()),
        publisher=PublisherFake(events, message_id=731),
        media=MediaFake(events),
        timeout_seconds=10,
        clock=lambda: NOW,
    )

    result = action.execute()

    assert result == PublishContentResult("published", package_id=41, message_id=731)
    assert events == ["reserve:41", "telegram:41", "commit:731", "delete:/media/41.png", "deleted:11"]
```

- [ ] **Шаг 2: написать HTTP RED реального adapter contract.**

Через `httpx.MockTransport` и настоящий временный PNG проверить endpoint `/bot<TOKEN>/sendPhoto`, multipart-поля `chat_id`, `caption`, `photo` с basename/MIME/байтами, JSON `ok=true/result.message_id`; отдельные литеральные fixtures для `ok=false 429`, `ok=false 400`, malformed/missing/non-int `message_id`, pre-request file error и transport timeout. В assertions и exception text убедиться, что отсутствуют token, URL, caption и file bytes.

- [ ] **Шаг 3: написать PostgreSQL RED.**

Seed helper вставляет реальные candidate/attempt/package строки. Проверить: FIFO только `approved`; один claim за вызов; два concurrent claim получают разные package; unique `package_id`; `retryable` повторяется с `attempt_no + 1`; `published`/`failed`/`uncertain` не claim; stale `sending → uncertain`; confirmation одним commit сохраняет delivery/attempt/message_id/package `published`; trigger failure откатывает всё; failed confirmation не даёт удалить media; cleanup marker сохраняется отдельно.

```python
with ThreadPoolExecutor(max_workers=2) as executor:
    claims = list(executor.map(lambda _: repository.reserve_next(now=NOW), range(2)))
assert {claim.package_id for claim in claims if claim is not None} == {first_id, second_id}
assert len([claim for claim in claims if claim is not None]) == 2
```

- [ ] **Шаг 4: расширить migration RED.**

Проверить точные таблицы `telegram_deliveries` и `telegram_delivery_attempts`, named unique/FK/check constraints, timezone columns, nullable правила, upgrade `20260808_03 → head`, downgrade `head → 20260808_03`, сохранность Wave 3 таблиц и повторный upgrade.

- [ ] **Шаг 5: написать config/CLI/systemd/wheel RED.**

Config: все шесть `TELEGRAM_*`, timeout `> 0`, три непустых calendar. CLI: settings validation происходит до `open_publisher`, нормализованные русские ошибки без secret; каждый outcome печатает безопасный итог. Installer: ровно три publish calendar, отдельные publish units, `ExecStart=... publish-once`, verify до copy, rollback всех четырёх unit при каждом fail/signal; wheel содержит новый Alembic head и новые delivery modules/templates.

- [ ] **Шаг 6: запустить каждый новый тестовый файл отдельно и подтвердить правильный RED.**

Запускать через `uv run pytest <file> -q`; imports новых production-модулей выполнять внутри тестов, чтобы каждый тест был `FAILED`, а не collection error. Для integration использовать безопасный профиль:

```bash
env -u DATABASE_URL TEST_DATABASE_URL="$TEST_DATABASE_URL" uv run pytest tests/integration/infrastructure/test_sqlalchemy_delivery.py tests/integration/test_migrations.py -q
```

Ожидание: новые assertions падают только потому, что интерфейс/схема/команда отсутствуют; существующие baseline-тесты остаются GREEN.

- [ ] **Шаг 7: выполнить mutation map вручную на отсутствующем поведении и записать evidence.**

Минимум 18 мутаций: wrong status filter, reverse FIFO, remove SKIP LOCKED, remove unique, reserve two, confirm without message_id, package published before Telegram, auto-retry uncertain, retry terminal, skip stale conversion, delete before commit, call Telegram during cleanup, omit attempt, leak token, wrong multipart field, accept malformed JSON, hardcode schedules, omit wheel/migration rollback. Для каждой — конкретный тест и исходный RED.

- [ ] **Шаг 8: commit только RED-пакета.**

```bash
git add -f tests docs/development-loop/evidence/2026-08-09-wave-4-red.md
git commit -m "Добавлены RED-доказательства доставки в Telegram"
```

---

### Task 2: доменная модель, порты и минимальный application action

**Файлы:**
- Создать: `src/postify/domain/delivery/__init__.py`
- Создать: `src/postify/domain/delivery/models.py`
- Создать: `src/postify/application/ports/telegram_publisher.py`
- Создать: `src/postify/application/ports/delivery_repository.py`
- Создать: `src/postify/application/delivery/__init__.py`
- Создать: `src/postify/application/delivery/publish_content.py`
- Изменить: `src/postify/domain/content/models.py`
- Test: `tests/unit/domain/delivery/test_models.py`
- Test: `tests/unit/application/delivery/test_publish_content.py`

**Интерфейсы:** производит точные типы/Protocol из общего раздела. `PublishContent(repository, publisher, media, *, timeout_seconds, clock).execute() -> PublishContentResult`.

- [ ] **Шаг 1: повторно запустить domain/action RED и сохранить failure output в report.**

```bash
uv run pytest tests/unit/domain/delivery/test_models.py tests/unit/application/delivery/test_publish_content.py -q
```

- [ ] **Шаг 2: реализовать минимальные dataclass/enum/Protocol.**

`TelegramPublishError` принимает только `code`, `reason`, `kind`; проверяет непустые безопасные строки. Добавить `PackageStatus.PUBLISHED` и единственный допустимый переход `approved → published`.

- [ ] **Шаг 3: реализовать cleanup-first и state routing.**

Алгоритм `execute`: вычислить `now`; вызвать stale conversion с `now - timedelta(seconds=timeout_seconds)`; если есть pending cleanup — вызвать `media.delete`, затем `mark_media_deleted` и вернуть cleanup outcome; иначе reserve one; при пустом claim вернуть empty; publish; typed exception передать в `record_failure`; success передать в `confirm_published`; только после возврата commit вызвать delete и mark. Cleanup error не вызывает `record_failure` и не меняет published.

- [ ] **Шаг 4: запустить targeted GREEN и весь non-integration smoke.**

```bash
uv run pytest tests/unit/domain/delivery/test_models.py tests/unit/application/delivery/test_publish_content.py -q
uv run pytest -m 'not integration' -q
```

- [ ] **Шаг 5: commit.**

```bash
git add src/postify/domain src/postify/application tests/unit/domain/delivery tests/unit/application/delivery
git commit -m "Добавлена оркестрация подтверждённой Telegram-доставки"
```

---

### Task 3: атомарная PostgreSQL-очередь и Alembic

**Файлы:**
- Создать: `src/postify/infrastructure/repositories/sqlalchemy_delivery.py`
- Создать: `src/postify/infrastructure/database/migrations/versions/20260809_04_add_telegram_deliveries.py`
- Изменить: `tests/integration/infrastructure/test_sqlalchemy_delivery.py`
- Изменить: `tests/integration/test_migrations.py`

**Интерфейсы:** реализует `DeliveryRepository`; использует `DeliveryClaim`, `DeliveryStatus`, `PublishFailureKind`. Таблица delivery содержит `package_id UNIQUE`, `status`, `attempt_no`, `message_id`, `sending_started_at`, `confirmed_at`, `media_deleted_at`, `failure_code`, `failure_reason`, timestamps. Attempt содержит `delivery_id`, `attempt_no`, `outcome`, safe code/reason, `started_at`, `finished_at`, `message_id`, UNIQUE `(delivery_id, attempt_no)`.

- [ ] **Шаг 1: подтвердить PostgreSQL/migration RED на доступной test DB.**

```bash
env -u DATABASE_URL TEST_DATABASE_URL="$TEST_DATABASE_URL" uv run pytest tests/integration/infrastructure/test_sqlalchemy_delivery.py tests/integration/test_migrations.py -q
```

- [ ] **Шаг 2: создать точную migration с named constraints и симметричным downgrade.**

Использовать имена `uq_telegram_deliveries_package_id`, `fk_telegram_deliveries_package_id_content_packages`, `ck_telegram_deliveries_status`, `uq_telegram_delivery_attempts_delivery_id_attempt_no`, `fk_telegram_delivery_attempts_delivery_id_telegram_deliveries`, `ck_telegram_delivery_attempts_outcome`. Downgrade удаляет сначала attempts, затем deliveries и не меняет Wave 3.

- [ ] **Шаг 3: реализовать transactional claim.**

Одной транзакцией: сначала FIFO `approved` без delivery или с `retryable`, `ORDER BY p.id FOR UPDATE OF p SKIP LOCKED LIMIT 1`; new row INSERT sending attempt_no=1 либо retryable row UPDATE sending/attempt_no+1. Не создавать attempt до исхода внешнего вызова.

- [ ] **Шаг 4: реализовать terminal writes и rollback.**

`record_failure` блокирует delivery, требует совпадения delivery/package/attempt и `sending`, добавляет одну attempt row и обновляет status/code/reason. `confirm_published` дополнительно требует `type(message_id) is int and message_id > 0`, атомарно пишет attempt `published`, delivery confirmation и package status/history `published`. Любая SQL ошибка rollback всей операции.

- [ ] **Шаг 5: реализовать stale/cleanup queries.**

Stale conversion обрабатывает все `sending_started_at < stale_before` транзакционно и добавляет uncertain attempt; pending cleanup возвращает старейший published с `media_deleted_at IS NULL`; marker меняет только delivery/package media deletion timestamps и не меняет confirmation.

- [ ] **Шаг 6: targeted и полная integration GREEN.**

```bash
env -u DATABASE_URL TEST_DATABASE_URL="$TEST_DATABASE_URL" uv run pytest tests/integration/infrastructure/test_sqlalchemy_delivery.py tests/integration/test_migrations.py -q
env -u DATABASE_URL TEST_DATABASE_URL="$TEST_DATABASE_URL" uv run pytest -m integration -q
```

- [ ] **Шаг 7: commit.**

```bash
git add src/postify/infrastructure tests/integration
git commit -m "Добавлена атомарная очередь Telegram-доставки"
```

---

### Task 4: реальный Telegram Bot API adapter

**Файлы:**
- Создать: `src/postify/adapters/telegram/__init__.py`
- Создать: `src/postify/adapters/telegram/bot_api.py`
- Test: `tests/unit/adapters/telegram/test_bot_api.py`

**Интерфейсы:** `TelegramBotApiPublisher(client, *, bot_token, chat_id).publish(claim) -> TelegramMessage`. Endpoint строится локально, наружу и в exception не возвращается.

- [ ] **Шаг 1: подтвердить adapter RED.**

```bash
uv run pytest tests/unit/adapters/telegram/test_bot_api.py -q
```

- [ ] **Шаг 2: реализовать один multipart `sendPhoto`.**

Открывать `claim.media_path` в `rb`; отправлять `data={"chat_id": chat_id, "caption": claim.post_text}` и `files={"photo": (Path(...).name, stream, claim.media_mime)}`. Не добавлять parse mode, source URL, retries, analytics или общий provider abstraction.

- [ ] **Шаг 3: реализовать минимальную типизированную классификацию.**

Локальные `OSError` до HTTP: `retryable`, code `media_unavailable`; `httpx.TimeoutException`/`TransportError`: `uncertain`, code `telegram_transport_uncertain`; HTTP/JSON `ok=false` с `429` или `>=500`: `retryable`, с прочими кодами: `failed`; malformed success/missing/non-int message ID: `uncertain`. Все reasons — фиксированные русские безопасные строки без interpolation response/request.

- [ ] **Шаг 4: targeted GREEN и token scan.**

```bash
uv run pytest tests/unit/adapters/telegram/test_bot_api.py -q
rg -n 'bot_token|TELEGRAM_BOT_TOKEN' src/postify/adapters/telegram tests/unit/adapters/telegram
```

Второй запуск анализируется вручную: token участвует только в private URL construction/test setup, не в `str(error)`, logging или repr результата.

- [ ] **Шаг 5: commit.**

```bash
git add src/postify/adapters/telegram tests/unit/adapters/telegram
git commit -m "Добавлен безопасный адаптер Telegram Bot API"
```

---

### Task 5: конфигурация, composition root и CLI `publish-once`

**Файлы:**
- Изменить: `src/postify/config.py`
- Изменить: `src/postify/bootstrap.py`
- Изменить: `src/postify/cli.py`
- Изменить: `.env.example`
- Test: `tests/unit/config/test_settings.py`
- Test: `tests/e2e/test_cli_publish_once.py`

**Интерфейсы:** `open_publish_once(settings)` создаёт engine/session factory, `httpx.Client(timeout=settings.telegram_timeout_seconds)`, repository, adapter, `LocalMediaProvider` только для `delete`, action; context manager всегда закрывает client/engine. CLI command называется `publish-once`.

- [ ] **Шаг 1: подтвердить config/CLI RED.**

```bash
uv run pytest tests/unit/config/test_settings.py tests/e2e/test_cli_publish_once.py -q
```

- [ ] **Шаг 2: добавить шесть обязательных settings и валидацию до boundary.**

Bot token хранится как `SecretStr`; chat ID — непустая строка; timeout `Field(gt=0)`; schedules `Field(min_length=1)`. Общая model validation не обращается к БД/HTTP.

- [ ] **Шаг 3: собрать action в отдельном context manager.**

Не добавлять доставку в `RunOnce`: import/selection/content остаются независимыми. Использовать существующий `LocalMediaProvider.delete`; Wikimedia dependency для delivery передать `None`, потому что acquire не вызывается.

- [ ] **Шаг 4: добавить CLI outcome contract и безопасные ошибки.**

Успех печатает один из фиксированных итогов (`Слот пуст`, `Опубликован пакет N; message_id=M`, `Cleanup завершён для пакета N`, `Cleanup ожидает повтора для пакета N`, безопасный исход retryable/failed/uncertain). `ValidationError` даёт `Некорректная конфигурация Telegram`; SQL/HTTP/filesystem/domain errors дают `Не удалось выполнить Telegram-доставку`; traceback/secret отсутствуют.

- [ ] **Шаг 5: обновить `.env.example` только новыми `TELEGRAM_*` именами без real values.**

Использовать `change_me`, тестовый chat ID, timeout и три ежедневных выражения; не менять текущий контентный формат или известный cron defect.

- [ ] **Шаг 6: targeted GREEN и full non-integration.**

```bash
uv run pytest tests/unit/config/test_settings.py tests/e2e/test_cli_publish_once.py -q
uv run pytest -m 'not integration' -q
```

- [ ] **Шаг 7: commit.**

```bash
git add src/postify/config.py src/postify/bootstrap.py src/postify/cli.py .env.example tests
git commit -m "Подключена команда разовой Telegram-публикации"
```

---

### Task 6: отдельный systemd delivery job и wheel/install contract

**Файлы:**
- Создать: `deploy/systemd/postify-publish-once.service`
- Создать: `deploy/systemd/postify-publish-once.timer`
- Изменить: `scripts/install-systemd.sh`
- Изменить: `tests/e2e/test_systemd_installer.py`
- Создать: `tests/unit/infrastructure/test_delivery_wheel.py`
- При необходимости изменить: `pyproject.toml`

**Интерфейсы:** installer принимает существующие параметры и ровно три `--on-calendar`, рендерит их в publish timer; import pair сохраняется без изменения семантики. Transactional target set — четыре unit-файла; backup/restore и повторный `daemon-reload` покрывают любую частичную установку.

- [ ] **Шаг 1: подтвердить systemd/wheel RED.**

```bash
uv run pytest tests/e2e/test_systemd_installer.py tests/unit/infrastructure/test_delivery_wheel.py -q
```

- [ ] **Шаг 2: создать delivery templates.**

Service: `Type=oneshot`, тот же user/group/workdir/env, `ExecStart=@PYTHON@ -m postify.cli publish-once`, `TimeoutStartSec=15min`, `SyslogIdentifier=postify-publish`. Timer: ровно три `OnCalendar`, timezone, persistent, `Unit=postify-publish-once.service`.

- [ ] **Шаг 3: расширить installer atomic rollback.**

Render/`systemd-analyze calendar` всех трёх значений и `systemd-analyze verify` четырёх файлов происходят до первого copy. Backup flags и cleanup восстанавливают/удаляют каждый из четырёх targets при signal, copy failure или daemon-reload failure.

- [ ] **Шаг 4: доказать wheel из чистой копии.**

Тест строит wheel offline после исключения build/dist/egg-info/caches и проверяет наличие migration head и всех новых Python delivery modules. Systemd templates остаются repo deployment assets и проверяются installer e2e, а не обязаны находиться в wheel.

- [ ] **Шаг 5: targeted GREEN.**

```bash
uv run pytest tests/e2e/test_systemd_installer.py tests/unit/infrastructure/test_delivery_wheel.py -q
```

- [ ] **Шаг 6: commit.**

```bash
git add deploy/systemd scripts/install-systemd.sh pyproject.toml tests
git commit -m "Добавлено расписание Telegram-публикаций"
```

---

### Task 7: независимый review, mutation gate, полный gate и evidence

**Файлы:**
- Изменить: `docs/development-loop/evidence/2026-08-09-wave-4-red.md`
- Создать: `docs/development-loop/evidence/2026-08-09-wave-4-review.md`
- Создать: `docs/development-loop/runs/2026-08-09-run-003.md`
- Изменить только при доказанной необходимости: тесты/production-файлы из задач 1–6

**Интерфейсы:** Terra 5.6 High получает diff от `96bde41`, RED evidence, plan и ledger; сначала выдаёт verdict по requirement trace/mutations/tests, после их исправления — отдельный code verdict. Все Critical/Important возвращаются Terra Medium implementer; Minor фиксируются в ledger и review doc.

- [ ] **Шаг 1: выполнить независимый test/mutation review.**

Reviewer обязан для каждой из минимум 18 mutation показать конкретный тест и проверить, что слабая реализация действительно даёт RED. Отдельно проверить, что tests не assert-ят mock вместо action outcome, не вычисляют expected через production helper и не зависят от порядка потоков без DB invariant.

- [ ] **Шаг 2: исправить все Critical/Important через implementer и провести scoped re-review.**

Каждый fix начинается новым failing regression/mutation test; report содержит RED command/output, затем GREEN command/output и commit. Повторять до `0 Critical`, `0 Important`; Minor записать как `deferred` с техническим ruling.

- [ ] **Шаг 3: выполнить отдельный code review и тот же fix loop.**

Проверить transaction boundaries, race behavior, token redaction, file safety, no auto-retry uncertainty, migration downgrade, systemd rollback и отсутствие scope creep.

- [ ] **Шаг 4: полный non-integration gate.**

```bash
uv run pytest -m 'not integration' -q
```

- [ ] **Шаг 5: полный integration gate на PostgreSQL из `../../.env.smoke-real`.**

Считать только `TEST_DATABASE_URL`, не печатая URL; если профиль задаёт только безопасный smoke `DATABASE_URL`, локально переназначить его в `TEST_DATABASE_URL` и обязательно убрать `DATABASE_URL` из test process:

```bash
set -a
. ../../.env.smoke-real
set +a
test_url=${TEST_DATABASE_URL:-${DATABASE_URL:-}}
env -u DATABASE_URL TEST_DATABASE_URL="$test_url" uv run pytest -m integration -q
unset test_url
```

- [ ] **Шаг 6: migration upgrade/downgrade gate в изолированной schema.**

Запустить targeted migration test, который делает `20260808_03 → head → 20260808_03 → head`; не направлять Alembic в production database и не печатать DSN.

- [ ] **Шаг 7: статические/packaging gates.**

```bash
uv run python -m compileall -q src tests
if uv run ruff --version >/dev/null 2>&1; then uv run ruff check .; fi
uv lock --check
git diff --check 96bde41..HEAD
uv run pytest tests/unit/infrastructure/test_delivery_wheel.py tests/e2e/test_systemd_installer.py -q
```

- [ ] **Шаг 8: проверить live Telegram preflight credentials только как факт.**

Загрузить `../../.env.smoke-real` без вывода значений и напечатать только `NAME=present|missing` для шести `TELEGRAM_*`. При отсутствии token/chat ID/schedules/timeout записать точный pending gate, закончить остальные документы и не объявлять Wave принятой.

- [ ] **Шаг 9: если credentials присутствуют, провести разрешённый live preflight.**

На отдельной изолированной smoke schema создать специально одобренный пакет с временным локальным PNG; выполнить реальный `publish-once`; проверить в БД integer `message_id`, delivery/attempt/package `published`, отсутствие media; повторить `publish-once` и доказать неизменный attempt count/message_id и отсутствие второго claim. В evidence записывать только IDs, статусы, counts и timestamps — без token/chat ID/URL/текста.

- [ ] **Шаг 10: обновить русские evidence/review/run документы.**

Run 003 содержит `Sₙ`, целевой `Sₙ₊₁`, базовый/итоговый commits, команды и counts, mutation efficiency, agent runs, iterations/returns, причины потерь, фактические файлы, live status и точный pending gate. Если live не выполнен: статус `preflight pending`, не `принят`; merge/main cleanup поля остаются `не выполнено — ожидается live preflight и решение корневого оркестратора`.

- [ ] **Шаг 11: финальный commit документации и чистая проверка ветки.**

```bash
git add -f docs/development-loop/evidence/2026-08-09-wave-4-red.md docs/development-loop/evidence/2026-08-09-wave-4-review.md docs/development-loop/runs/2026-08-09-run-003.md
git commit -m "Зафиксированы доказательства Wave 4"
git status --short
git log --oneline 96bde41..HEAD
```

Ожидание: tracked status чистый; игнорируемые SDD artifacts не коммитятся; ветка/worktree сохраняются для финальной интеграции корневым агентом; GitHub push, merge в `main`, удаление ветки/worktree не выполняются.

---

## Self-review плана

- Покрытие спецификации: approved-only/FIFO/one-slot — задачи 1/3; три configurable slots — 1/5/6; exact multipart — 1/4; concurrency/idempotency/stale uncertainty — 1/2/3; message ID/attempts/reasons — 1/3; commit-before-delete/retry cleanup — 1/2/3; secret safety — 1/4/5; migration/wheel/install rollback — 1/3/6; independent review/mutations/live — 7.
- Границы проверены: нет UI, текстовых форматов, аналитики, других площадок, универсального outbox и исправлений Wave 3.
- Placeholder scan: `TBD`, `TODO`, «реализовать позже», «добавить подходящую обработку» отсутствуют; каждый шаг содержит точный результат/команду/контракт.
- Согласованность типов: action, ports, repository и adapter используют одни `DeliveryClaim`, `TelegramMessage`, `TelegramPublishError`, `PublishFailureKind`, `PublishContentResult`; status literals совпадают с migration checks.
- Риск недоказуемой exactly-once снят: uncertain terminal и stale policy явно тестируются; live preflight не подменяется hermetic GREEN.

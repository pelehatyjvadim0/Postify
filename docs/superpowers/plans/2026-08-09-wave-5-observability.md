# Wave 5 Observability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Дать оператору одной командой `postify status` долговечный и безопасный ответ о созданных сущностях, доставках, дефиците трёх публикаций и эксплуатационных проблемах.

**Architecture:** Существующие PostgreSQL-таблицы остаются источником истины. Одна новая таблица `operation_runs` хранит lifecycle двух CLI-операций; отдельный read-only `REPEATABLE READ` repository строит raw snapshot, application action вычисляет deficit/signals, CLI независимо собирает systemd и форматирует фиксированный отчёт.

**Tech Stack:** Python 3.12, dataclasses/StrEnum, Typer, SQLAlchemy 2, PostgreSQL 16, Alembic, pytest, uv, Ruff.

## Global Constraints

- База перехода: `efe959c`; design commits `f5a8feb`, `1826bc9`.
- Соблюдать TDD и `docs/development-loop/README.md`; production появляется только после сохранённого RED.
- Кодирование следует `code-structure`: product policy остаётся в actions, общий lifecycle двух операций выделяется один раз, SQL не попадает в CLI.
- `postify status` строго read-only: не создаёт `operation_runs` и не меняет ни одной строки.
- Не менять Telegram reserve/retry/uncertain/confirmation/cleanup semantics и HTTP adapter.
- Не добавлять UI, Wave 6, формат текста, темы, источники, площадки, Prometheus, dashboard, metrics/event service или JSON payload журнала.
- Ни один вывод/exception/evidence не содержит DSN, Telegram token/chat ID, source URL, post text, media path или Telegram response.
- Документация и человекочитаемые commit messages — только на русском; push/merge/cleanup запрещены.
- Дневная цель равна `3`; локальный день определяется `POSTIFY_TIMEZONE`; recent lists ограничены `10`, агрегаты учитывают все строки.
- Integration запускается только через `../../.env.smoke-real` с `DATABASE_URL` unset.

## Карта файлов и ответственности

- `src/postify/domain/observability/models.py` — неизменяемые operation/snapshot/report типы, deficit taxonomy и безопасные signal codes.
- `src/postify/application/ports/operation_run_repository.py` — write-port lifecycle журнала.
- `src/postify/application/ports/operational_status_repository.py` — read-port одного согласованного snapshot.
- `src/postify/application/observability/record_operation.py` — общий lifecycle wrapper двух action без доменной логики Telegram/import.
- `src/postify/application/observability/show_status.py` — локальный день, deficit и operational signal policy.
- `src/postify/infrastructure/repositories/sqlalchemy_operation_runs.py` — атомарные start/succeed/fail.
- `src/postify/infrastructure/repositories/sqlalchemy_operational_status.py` — только SELECT в одной read-only repeatable-read транзакции.
- `src/postify/infrastructure/database/migrations/versions/20260809_05_add_operation_runs.py` — одна новая таблица и named constraints.
- `src/postify/bootstrap.py` — composition roots observed actions и status action.
- `src/postify/cli.py` — независимые safe systemd probes и детерминированный renderer.
- Новые tests разделяются по этим границам; существующий status e2e обновляется без ослабления start/stop tests.

---

### Task 1: Полный RED-пакет, trace и mutation map

**Files:**
- Create: `tests/unit/domain/observability/test_models.py`
- Create: `tests/unit/application/observability/test_record_operation.py`
- Create: `tests/unit/application/observability/test_show_status.py`
- Create: `tests/integration/infrastructure/test_sqlalchemy_observability.py`
- Modify: `tests/integration/test_migrations.py`
- Create: `tests/e2e/test_cli_status.py`
- Modify: `tests/e2e/test_cli_run_once.py`
- Create: `tests/unit/infrastructure/test_observability_wheel.py`
- Create: `docs/development-loop/evidence/2026-08-09-wave-5-red.md`

**Interfaces fixed by RED:**
- `OperationKind`: `RUN_ONCE`, `PUBLISH_ONCE`; `OperationStatus`: `RUNNING`, `SUCCEEDED`, `FAILED`.
- `OperationRunRepository.start(operation, *, now) -> int`, `.succeed(run_id, *, outcome, now) -> None`, `.fail(run_id, *, failure_code, now) -> None`.
- `RecordedAction(action, repository, *, operation, success_outcome, failure_code, clock).execute() -> T`; `success_outcome` accepts a fixed string or `Callable[[T], str]`.
- `OperationalStatusRepository.snapshot(*, day, day_start, day_end, limit=10) -> RawOperationalSnapshot`.
- `ShowOperationalStatus(repository, *, timezone, daily_target, analysis_limit, package_limit, clock).execute(runtime: RuntimeSnapshot) -> StatusReport`.
- `open_operational_status(settings)` yields `ShowOperationalStatus`; `open_run_once` and `open_publish_once` yield the observed action with unchanged `.execute()` result.

- [ ] **Step 1: написать domain/application RED без production imports at collection.**

Tests импортируют отсутствующие модули внутри test/helper и доказывают:

```python
def test_deficit_uses_only_today_published_and_claimable_ready():
    snapshot = raw_snapshot(published_today=1, delivery_ready=1)
    report = assess(snapshot, daily_target=3)
    assert report.deficit == 1

def test_status_is_pure_and_returns_all_applicable_reasons_in_fixed_order():
    snapshot = raw_snapshot(
        delivery_uncertain_ids=(7,), awaiting_review_ids=(4,),
        analyses_started=5, analysis_limit=5,
    )
    assert report(snapshot).deficit_reasons == (
        "delivery_blocked", "review_backlog", "analysis_limit_reached"
    )

def test_recorded_action_preserves_result_and_saves_safe_outcome():
    result = RecordedAction(...).execute()
    assert result is expected_result
    assert events == [("start", "publish_once"), ("succeed", "empty")]

def test_failure_journal_error_never_masks_original_exception():
    with pytest.raises(SourceFailure, match="original"):
        RecordedAction(failing_action, failing_journal, ...).execute()
```

Mutation table обязана включать минимум: wrong target; UTC-day вместо local-day; published package вместо confirmed delivery; failed/uncertain как ready; одна причина вместо всех восьми; unknown status silently ignored; newest limit reversed; arbitrary exception stored; start after action; success before action; journal failure masks original; status writes row.

- [ ] **Step 2: подтвердить hermetic RED.**

Run:

```bash
uv run pytest tests/unit/domain/observability tests/unit/application/observability -q
uv run pytest tests/e2e/test_cli_status.py tests/e2e/test_cli_run_once.py -q
```

Expected: новые tests падают только из-за отсутствующих observability types/actions/bootstrap/CLI contracts; существующие start/stop сценарии остаются GREEN. Зафиксировать counts и причины каждого RED.

- [ ] **Step 3: написать PostgreSQL/migration/wheel RED.**

Integration обязана проверить named schema, terminal consistency, double-terminal rejection, rollback, repeatable-read consistency при конкурентной записи, точные grouped counts/IDs, ready predicate, local-day interval, newest ten и отсутствие writes. Migration test делает `04 → 05 → 04 → 05` и проверяет сохранность Wave 4 fixture. Wheel test строит clean wheel offline и ищет все новые модули/head.

- [ ] **Step 4: подтвердить PostgreSQL RED безопасно.**

```bash
set -a
. ../../.env.smoke-real
set +a
test_url=${TEST_DATABASE_URL:-${DATABASE_URL:-}}
env -u DATABASE_URL TEST_DATABASE_URL="$test_url" uv run pytest \
  tests/integration/infrastructure/test_sqlalchemy_observability.py \
  tests/integration/test_migrations.py -q
unset test_url
uv run pytest tests/unit/infrastructure/test_observability_wheel.py -q
```

Expected: observability production/migration отсутствуют; pre-existing migration cases проходят. DSN не выводится.

- [ ] **Step 5: заполнить русский RED evidence.**

Таблица содержит для каждого design requirement: test ID, точную причину RED, mutation и ожидаемый wrong outcome. Отдельно записать baseline `390/59`, environment-safe commands и запрет production changes.

- [ ] **Step 6: self-review RED и commit.**

Проверить: assertions наблюдают public results/DB invariants, а не mocks; expected не вычисляется production helper; concurrent test синхронизирован DB invariant/barrier; tests не требуют systemd/Telegram/network; production diff пуст.

```bash
git add tests
git add -f docs/development-loop/evidence/2026-08-09-wave-5-red.md
git commit -m "Добавлены RED-доказательства наблюдаемости Wave 5"
```

---

### Task 2: Domain report, deficit taxonomy и signal policy

**Files:**
- Create: `src/postify/domain/observability/__init__.py`
- Create: `src/postify/domain/observability/models.py`
- Create: `src/postify/application/ports/operational_status_repository.py`
- Create: `src/postify/application/observability/__init__.py`
- Create: `src/postify/application/observability/show_status.py`
- Test: `tests/unit/domain/observability/test_models.py`
- Test: `tests/unit/application/observability/test_show_status.py`

**Interfaces:**
- `RawOperationalSnapshot` содержит fixed state counts, issue IDs, daily usage, `published_today`, `delivery_ready`, selected/undecided backlogs и three recent tuples.
- `RuntimeSnapshot` содержит пять safe unit states (`postgresql`, import/publish timer, import/publish service), timer timestamps и `probe_failed_units`.
- `StatusReport` содержит snapshot, `local_day`, `daily_target`, `coverage`, `deficit`, ordered `DeficitReason` и ordered `OperationalSignal`.

- [ ] **Step 1: повторить targeted RED и сохранить вывод.**

```bash
uv run pytest tests/unit/domain/observability/test_models.py \
  tests/unit/application/observability/test_show_status.py -q
```

- [ ] **Step 2: реализовать минимальные immutable types и validation.**

Все counts неотрицательны, IDs положительны, timestamps timezone-aware. Fixed enums/codes не принимают произвольный текст. Не создавать generic metrics, serialization или provider abstraction.

- [ ] **Step 3: реализовать `ShowOperationalStatus.execute`.**

Вычислить `[local midnight, next midnight)` в configured zone, запросить один snapshot, затем:

```python
coverage = snapshot.published_today + snapshot.delivery_ready
deficit = max(self.daily_target - coverage, 0)
```

Добавить все восемь причин только при deficit, в порядке design spec. Signals строятся из точных issue IDs/counts и runtime state; healthy выдаёт пустой tuple, который renderer превращает в `Проблем нет`.

- [ ] **Step 4: targeted GREEN и mutation spot checks.**

```bash
uv run pytest tests/unit/domain/observability/test_models.py \
  tests/unit/application/observability/test_show_status.py -q
```

Временно локально изменить target на 2, включить uncertain в ready и вернуть только первую deficit reason: каждая мутация обязана дать RED; изменения откатить через `apply_patch`.

- [ ] **Step 5: commit.**

```bash
git add src/postify/domain/observability src/postify/application/observability \
  src/postify/application/ports/operational_status_repository.py
git commit -m "Добавлена модель эксплуатационного состояния Postify"
```

---

### Task 3: Долговечный lifecycle operation runs

**Files:**
- Create: `src/postify/application/ports/operation_run_repository.py`
- Create: `src/postify/application/observability/record_operation.py`
- Create: `src/postify/infrastructure/repositories/sqlalchemy_operation_runs.py`
- Create: `src/postify/infrastructure/database/migrations/versions/20260809_05_add_operation_runs.py`
- Modify: `src/postify/bootstrap.py`
- Test: `tests/unit/application/observability/test_record_operation.py`
- Test: `tests/integration/infrastructure/test_sqlalchemy_observability.py`
- Test: `tests/integration/test_migrations.py`

**Interfaces:**
- `RecordedAction[T].execute() -> T` вызывает ровно один underlying `.execute()`.
- Repository terminal update использует `WHERE id=:id AND status='running'`; `rowcount != 1` даёт safe `InvalidOperationRunTransition` и rollback.
- `open_run_once`: outcome fixed `completed`, failure `run_once_failed`.
- `open_publish_once`: outcome `result.outcome`, failure `publish_once_failed`.

- [ ] **Step 1: повторить unit/integration RED.**

Использовать безопасный `TEST_DATABASE_URL` recipe из Task 1; expected missing migration/repository/wrapper.

- [ ] **Step 2: создать migration с named constraints и симметричным downgrade.**

Точные имена: `ck_operation_runs_operation`, `ck_operation_runs_status`,
`ck_operation_runs_terminal_fields`. Terminal check требует coherent nullable
fields и `btrim` непустого outcome/failure. Down revision `20260809_04`;
downgrade удаляет только `operation_runs`.

- [ ] **Step 3: реализовать repository транзакции.**

`start` вставляет/commit `running`; `succeed`/`fail` блокируют logical transition одним conditional update, проверяют rowcount и commit. На любом исключении rollback. Никаких exception strings или result payload.

- [ ] **Step 4: реализовать общий `RecordedAction`.**

Start всегда до action. На success terminal journal error передаётся вызывающему коду и underlying action не повторяется. На underlying error failure journaling выполняется один раз; его ошибка подавляется только для сохранения исходного exception. `KeyboardInterrupt`/`SystemExit` не превращаются в failed — строка остаётся `running`.

- [ ] **Step 5: подключить оба composition root без изменения action constructors.**

Использовать уже существующий `session_factory` каждого context manager. Не менять `PublishContent`, Telegram adapter, delivery repository и CLI outcome text.

- [ ] **Step 6: targeted/full GREEN и commit.**

```bash
uv run pytest tests/unit/application/observability/test_record_operation.py \
  tests/unit/bootstrap -q
env -u DATABASE_URL TEST_DATABASE_URL="$test_url" uv run pytest \
  tests/integration/infrastructure/test_sqlalchemy_observability.py \
  tests/integration/test_migrations.py -q
git add src/postify/application src/postify/infrastructure src/postify/bootstrap.py
git commit -m "Добавлен долговечный журнал запусков Postify"
```

---

### Task 4: PostgreSQL operational snapshot

**Files:**
- Create: `src/postify/infrastructure/repositories/sqlalchemy_operational_status.py`
- Modify: `src/postify/bootstrap.py`
- Test: `tests/integration/infrastructure/test_sqlalchemy_observability.py`

**Interfaces:**
- `snapshot(day, day_start, day_end, limit=10)` выполняет только SELECT и возвращает все поля `RawOperationalSnapshot`.
- `open_operational_status(settings)` создаёт engine/session factory, action и всегда `engine.dispose()`.

- [ ] **Step 1: выполнить scoped RED для snapshot cases.**

Expected: missing repository/open function; migration tests уже GREEN после Task 3.

- [ ] **Step 2: реализовать одну read-only repeatable-read транзакцию.**

Начать transaction с isolation `REPEATABLE READ`, установить `READ ONLY`, выполнить grouped queries и commit/rollback без writes. Все `ORDER BY` явные. Recent packages, attempts и runs — `ORDER BY created/finished/id DESC LIMIT :limit`; attempts join delivery для package ID.

- [ ] **Step 3: реализовать точные predicates.**

`ready`: package `approved` и delivery отсутствует либо `retryable`.
`published_today`: delivery `published`, `confirmed_at >= day_start` и `< day_end`.
`selected_without_attempt`: selected decision без любой content attempt.
Issue IDs берутся по всем строкам, но ограничиваются первыми десятью только после отдельного total count. Unknown states сохраняются grouped, не фильтруются.

- [ ] **Step 4: доказать consistency/no-write mutations.**

Concurrent writer вставляет/terminalizes data между двумя repository SELECT; snapshot видит либо полностью old, либо полностью new state. Мутации без `REPEATABLE READ`, без `READ ONLY`, wrong ready join, inclusive day end и ASC recent должны дать RED.

- [ ] **Step 5: targeted/full integration GREEN и commit.**

```bash
env -u DATABASE_URL TEST_DATABASE_URL="$test_url" uv run pytest \
  tests/integration/infrastructure/test_sqlalchemy_observability.py -q
env -u DATABASE_URL TEST_DATABASE_URL="$test_url" uv run pytest -m integration -q
git add src/postify/infrastructure/repositories/sqlalchemy_operational_status.py \
  src/postify/bootstrap.py
git commit -m "Добавлен согласованный снимок состояния Postify"
```

---

### Task 5: Расширенный CLI `status`

**Files:**
- Modify: `src/postify/cli.py`
- Modify: `tests/e2e/test_cli_run_once.py`
- Test: `tests/e2e/test_cli_status.py`

**Interfaces:**
- `_probe_runtime(systemd, settings) -> RuntimeSnapshot` вызывает каждый unit независимо и сохраняет только safe state/properties или имя неудавшейся unit.
- `_render_status(report) -> tuple[str, ...]` возвращает фиксированные строки без I/O; command печатает их по порядку.
- DB readiness/migration failure печатает partial system facts + fixed critical signal и завершает code `1`; полный DB report — code `0` даже при сохранённых operational warnings.

- [ ] **Step 1: выполнить CLI RED.**

```bash
uv run pytest tests/e2e/test_cli_status.py tests/e2e/test_cli_run_once.py -q
```

- [ ] **Step 2: разделить safe probes и renderer.**

Проверить PostgreSQL unit, оба timer и оба service. Ошибка одной команды не прекращает остальные. Не переносить stderr/exception text. Renderer печатает sections System/Entities/Recent packages/Delivery/Plan/Runs/Problems, zero counts и ISO local timestamps; recent empty печатает `—`.

- [ ] **Step 3: собрать command с partial error contract.**

`Settings` validation до boundaries. После runtime probes: readiness, migrations head, затем `open_operational_status`. SQL/OSError нормализуются в `Не удалось получить состояние Postify`; traceback/DSN отсутствуют. TelegramSettings не создаётся, сеть не вызывается.

- [ ] **Step 4: доказать status read-only и безопасность.**

E2E fake repository считает calls: ровно один `.snapshot`, ни одного operation write. Повтор command даёт byte-identical output при fixed clock/state. Secret sentinel во всех fake exceptions/data не появляется. Partial systemd failure сохраняет complete DB sections.

- [ ] **Step 5: full non-integration GREEN и commit.**

```bash
uv run pytest tests/e2e/test_cli_status.py tests/e2e/test_cli_run_once.py -q
uv run pytest -m 'not integration' -q
git add src/postify/cli.py tests/e2e
git commit -m "Расширена команда состояния Postify"
```

---

### Task 6: Packaging, документация capability и independent review loop

**Files:**
- Modify: `tests/unit/infrastructure/test_observability_wheel.py`
- Modify: `README.md`
- Create: `docs/development-loop/evidence/2026-08-09-wave-5-review.md`
- Create: `docs/development-loop/runs/2026-08-09-run-004.md`
- Modify при находках: только Wave 5 production/tests.

**Interfaces:** clean wheel содержит domain/application/ports/repositories/migration head; README описывает фактический status, а не будущую аналитику.

- [ ] **Step 1: выполнить wheel RED/GREEN и scoped static gates.**

```bash
uv run pytest tests/unit/infrastructure/test_observability_wheel.py \
  tests/unit/infrastructure/test_delivery_wheel.py -q
uv run python -m compileall -q src tests
uv run ruff check src tests/unit/domain/observability \
  tests/unit/application/observability tests/integration/infrastructure/test_sqlalchemy_observability.py \
  tests/e2e/test_cli_status.py tests/unit/infrastructure/test_observability_wheel.py
uv lock --check
```

- [ ] **Step 2: fresh Terra High test/mutation review.**

Reviewer получает diff `efe959c..HEAD`, spec, plan, RED evidence. Сначала проверяет tests/mutations и фактически выполняет representative mutations: target/day/ready, all reasons, unknown state, journal ordering/masking, repeatable read, status write, newest ten, secret leak. Verdict отдельно `Critical/Important/Minor`.

- [ ] **Step 3: исправить Critical/Important через TDD и повторять test review до нуля.**

Каждая находка: новый failing regression/mutation test, RED output, minimal fix, GREEN output, commit. Minor либо исправить, либо дать конкретный technical ruling в review evidence.

- [ ] **Step 4: fresh scoped production review после test gate.**

Проверить transaction isolation/read-only, terminal races, original exception preservation, no Telegram semantic change, resource cleanup, fixed codes/output, timezone/day boundary, SQL ordering, migration rollback, wheel и scope. Повторять TDD fix/re-review до `0 Critical`, `0 Important`.

- [ ] **Step 5: обновить README после доказанного GREEN.**

Отметить Wave 4 Telegram и Wave 5 observability как реализованные, описать sections `status` и то, что команда не требует Telegram credentials/не вызывает Telegram. Не описывать UI/analytics как готовые.

- [ ] **Step 6: commit review-ready code/docs.**

```bash
git add README.md src tests
git commit -m "Подготовлена наблюдаемость Postify к приёмке"
```

---

### Task 7: Полный gate, live smoke и evidence run-004

**Files:**
- Modify: `docs/development-loop/evidence/2026-08-09-wave-5-red.md`
- Create/Modify: `docs/development-loop/evidence/2026-08-09-wave-5-review.md`
- Create/Modify: `docs/development-loop/runs/2026-08-09-run-004.md`

- [ ] **Step 1: full hermetic gates.**

```bash
uv run pytest -m 'not integration' -q
set -a
. ../../.env.smoke-real
set +a
test_url=${TEST_DATABASE_URL:-${DATABASE_URL:-}}
env -u DATABASE_URL TEST_DATABASE_URL="$test_url" uv run pytest -m integration -q
unset test_url
uv run python -m compileall -q src tests
changed_python=$(git diff --name-only efe959c..HEAD -- 'src/**/*.py' 'tests/**/*.py')
uv run ruff check src $changed_python
unset changed_python
uv lock --check
git diff --check efe959c..HEAD
uv run pytest tests/unit/infrastructure/test_observability_wheel.py \
  tests/unit/infrastructure/test_delivery_wheel.py tests/e2e/test_cli_status.py -q
uv run postify --help
uv run postify status --help
```

Expected: baseline растёт от `390/59`, все новые counts фиксируются в evidence; ни один URL/secret не выводится.

- [ ] **Step 2: isolated migration rollback/re-upgrade.**

Targeted integration test создаёт fixture Wave 4 и выполняет `20260809_04 → head → 20260809_04 → head`, проверяя package/delivery/attempt/message ID до и после. Не направлять Alembic в live database для destructive rollback.

- [ ] **Step 3: live upgrade и pre-state на существующей smoke DB.**

Загрузить `../../.env.smoke-real`, не печатать URL/credentials. Safe SQL выводит только Alembic revision, package ID/status, delivery status/attempt count/message ID. Подтвердить package `1`, `published`, attempts `1`, `message_id=6`, затем upgrade `04 → 05`.

- [ ] **Step 4: live empty `publish-once` доказывает operation journal.**

Передать Telegram token/chat/timeout только process environment. Выполнить реальный CLI на уже published package 1. Ожидание: `Слот пуст`, Telegram publisher method не вызывается по DB predicate, появляется один `operation_runs` `publish_once/succeeded/empty`; delivery status, attempt count `1` и message ID `6` неизменны. Никакие значения credentials не печатать.

- [ ] **Step 5: live `status` и строгий no-write proof.**

Снять safe row counts/checksums до command; выполнить `postify status`; увидеть package `1`, delivery attempt `1/published/message_id=6`, run `publish_once/succeeded/empty`, deficit и signals. Повторить status. После каждого вызова все table counts и хранимые поля, включая `operation_runs`, byte/logically identical. Systemd-unavailable допустим только как safe signal; DB report обязателен.

- [ ] **Step 6: live data preservation и isolated rollback evidence.**

На live DB не выполнять destructive downgrade, если она используется последующими wave. Сохранность live Wave 4 данных доказывается upgrade/status; downgrade/re-upgrade — изолированным integration test Task 7.2. Если root отдельно разрешит live downgrade, выполнить его только после snapshot и восстановить head, зафиксировав удаление только Wave 5 operation rows.

- [ ] **Step 7: заполнить review/evidence/run-004.**

На русском записать: `Sₙ`, целевой/доказанный `Sₙ₊₁`, commits, commands/counts, trace coverage, mutation efficiency, reviewer verdicts, agent runs, iterations/returns и loss classes, фактические files/diff, live IDs/statuses/timestamps без secrets, rollback и pending root merge/main gate. Статус до live — не принят; после live — `готов к решению root`, не merged/cleaned.

- [ ] **Step 8: force-add ignored docs, final commit и clean tracked status.**

```bash
git add -f docs/development-loop/evidence/2026-08-09-wave-5-red.md \
  docs/development-loop/evidence/2026-08-09-wave-5-review.md \
  docs/development-loop/runs/2026-08-09-run-004.md
git commit -m "Зафиксированы доказательства наблюдаемости Wave 5"
git status --short
git log --oneline efe959c..HEAD
```

Ожидание: tracked status чистый; `.venv`/caches ignored; push, merge, main gate, branch/worktree deletion не выполняются.

---

## Self-review плана

- Spec coverage: operation lifecycle — Tasks 1/3; immutable/read-only snapshot — 1/2/4; entity states/history — 1/4/5; eight deficit reasons — 1/2; systemd/DB signals and partial errors — 2/5; migration/wheel — 1/3/6; live package 1/message 6/no-write — 7.
- Scope: нет UI, форматов, новых источников/площадок, delivery changes, generic events/metrics или внешней аналитики.
- Placeholder scan: каждый production/test/doc шаг содержит точный файл, интерфейс, command и ожидаемый observable result; отложенных реализационных решений нет.
- Type consistency: `RecordedAction`, два repository ports, `RawOperationalSnapshot`, `RuntimeSnapshot`, `StatusReport` и `ShowOperationalStatus` названы одинаково во всех задачах.
- Safety: integration URL не выводится и всегда идёт как `TEST_DATABASE_URL` при unset `DATABASE_URL`; live Telegram не вызывается из-за пустой claim queue; `status` не пишет никогда.

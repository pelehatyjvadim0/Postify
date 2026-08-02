# Wave 2: план реализации отбора и журнала решений

> **Для агентных исполнителей:** ОБЯЗАТЕЛЬНЫЙ ПРОЦЕСС — docs/development-loop/README.md версии 0.4. Sol 5.6 High создаёт полный RED-пакет; Terra 5.6 Medium реализует его; свежая Terra 5.6 High проверяет тесты и мутации до ревью кода.

**Цель:** каждый импортированный кандидат получает объяснимое неизменяемое решение selected либо rejected, а run-once восстанавливает отбор после частичного сбоя.

**Архитектура:** чистая доменная политика применяет внешний профиль фермы и не знает об HN или SQL. Прикладной сценарий загружает все записи без решения и атомарно сохраняет журнал через порт. Общий сценарий run-once последовательно выполняет импорт и отбор.

**Стек:** Python 3.12, Pydantic Settings, Typer, SQLAlchemy 2, PostgreSQL 16 JSONB, Alembic, Pytest, uv.

## Общие ограничения

- Базовое состояние Sₙ: main@e8370b9; Wave 1 импортирует кандидатов без решений.
- Целевое состояние Sₙ₊₁: после успешного run-once каждый кандидат имеет одно объяснимое решение; следующий запуск восстанавливает разрыв между импортом и отбором.
- selected — допуск к будущему AI-анализу, не готовность к публикации.
- Статуса reserve нет; недостаток данных и возраст сами по себе не создают отказ.
- Реклама, явная нерелевантность, найм и технический релиз без практического применения — независимо включаемые правила.
- Профиль задаёт версию, язык, аудиторию, порядок правил, словари и окно свежести.
- Домен не читает raw_payload, HN points/num_comments, окружение или пользовательские метрики.
- AI, партия 90/10, UI, переоценка, генерация и публикация не входят в Wave 2.
- Интеграционные тесты требуют отдельную TEST_DATABASE_URL и не используют skip.
- GitHub не используется без подтверждения. Коммиты называются по-русски.

## Атомарность и нагрузка

| Параметр | Оценка |
| --- | --- |
| Поведение | профиль, бинарная политика, журнал, последовательный run-once |
| Внешние границы | PostgreSQL и упаковка миграции |
| Неизвестности | качество консервативного RED и конкурентного журнала |
| Компоненты | config, domain, application, repository, migration, bootstrap, CLI |
| Глубина | профиль → домен → порт → PostgreSQL → orchestration → CLI |
| Параллелизм | отсутствует: общая модель данных и последовательный gate |
| Доказательство | тесты + мутации + живой PostgreSQL-сценарий |

Это один переход: без журнала доменное решение не наблюдаемо после завершения процесса, а без политики журнал не имеет рабочего смысла. AI для доказательства не требуется.

## Карта файлов

Создать:

- src/postify/domain/candidates/statuses.py — статусы, причины, решение;
- src/postify/domain/candidates/selection.py — профиль и чистая политика;
- src/postify/application/ports/decision_repository.py — DTO и порт;
- src/postify/application/selection/select_candidates.py — обработка без решений;
- src/postify/application/jobs/run_once.py — import → selection;
- src/postify/infrastructure/repositories/sqlalchemy_decisions.py — PostgreSQL;
- src/postify/infrastructure/database/migrations/versions/20260802_02_add_candidate_decisions.py;
- четыре новых тестовых файла из утверждённой спецификации;
- docs/development-loop/evidence/2026-08-02-wave-2-red.md;
- docs/development-loop/evidence/2026-08-02-wave-2-review.md.

Изменить:

- .env.example, README.md;
- src/postify/config.py, bootstrap.py, cli.py;
- src/postify/infrastructure/database/models.py;
- tests/unit/config/test_settings.py;
- tests/integration/test_migrations.py;
- tests/e2e/test_cli_run_once.py.

## Контракты

~~~python
type JsonValue = (
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
)

class DecisionStatus(StrEnum):
    SELECTED = "selected"
    REJECTED = "rejected"

class DecisionReason(StrEnum):
    ELIGIBLE_FOR_AI = "eligible_for_ai"
    ADVERTISING = "advertising"
    OUT_OF_SCOPE = "out_of_scope"
    HIRING = "hiring"
    TECHNICAL_WITHOUT_USE = "technical_without_use"

class RejectionRule(StrEnum):
    ADVERTISING = "advertising"
    OUT_OF_SCOPE = "out_of_scope"
    HIRING = "hiring"
    TECHNICAL_WITHOUT_USE = "technical_without_use"

@dataclass(frozen=True, slots=True)
class CandidateDecision:
    candidate_id: int
    status: DecisionStatus
    reason: DecisionReason
    explanation: str
    signals: Mapping[str, JsonValue]
    policy_version: str
    decided_at: datetime
~~~

~~~python
@dataclass(frozen=True, slots=True)
class SelectionProfile:
    version: str
    language: str
    audience: str
    rules: tuple[RejectionRule, ...]
    topic_terms: tuple[str, ...]
    topic_exclusion_terms: tuple[str, ...]
    advertising_terms: tuple[str, ...]
    hiring_terms: tuple[str, ...]
    technical_release_terms: tuple[str, ...]
    practical_terms: tuple[str, ...]
    freshness_window: timedelta

def evaluate_candidate(
    candidate_id: int,
    candidate: Candidate,
    profile: SelectionProfile,
    *,
    now: datetime,
) -> CandidateDecision: ...
~~~

Правила проверяются в порядке profile.rules. Совпадение выполняется по нормализованным title и URL с Unicode-границами слова. OUT_OF_SCOPE срабатывает только по topic_exclusion_terms. Отсутствие topic_terms не является отказом. TECHNICAL_WITHOUT_USE требует маркер релиза и отсутствие практического маркера.

~~~python
@dataclass(frozen=True, slots=True)
class StoredCandidate:
    id: int
    candidate: Candidate

class DecisionRepository(Protocol):
    def find_undecided(self) -> Sequence[StoredCandidate]: ...
    def save_new(self, decisions: Sequence[CandidateDecision]) -> set[int]: ...

@dataclass(frozen=True, slots=True)
class SelectionResult:
    examined: int
    selected: int
    rejected: int
    conflicts: int

class SelectCandidates:
    def __init__(
        self,
        repository: DecisionRepository,
        profile: SelectionProfile,
        clock: Callable[[], datetime],
    ) -> None: ...
    def execute(self) -> SelectionResult: ...

@dataclass(frozen=True, slots=True)
class RunOnceResult:
    import_result: ImportResult
    selection_result: SelectionResult

class RunOnce:
    def __init__(self, importer: ImportCandidates, selector: SelectCandidates) -> None: ...
    def execute(self) -> RunOnceResult: ...
~~~

save_new возвращает candidate_id, созданные данным вызовом. Конкурентно созданные решения не входят в результат.

### Задача 1: Sol 5.6 High создаёт RED-пакет

**Файлы:** все тесты Wave 2 и docs/development-loop/evidence/2026-08-02-wave-2-red.md. Production-файлы запрещены.

- [ ] Добавить конфигурационные тесты: обязательные поля, порядок правил, CSV-нормализация, неизвестное правило, пустой словарь включённого правила, дубли без учёта регистра, freshness_days <= 0.

~~~python
configured = Settings(**base_values, selection_rules="advertising,hiring")
assert configured.selection_rules == ("advertising", "hiring")
with pytest.raises(ValidationError):
    Settings(**base_values, selection_rules="advertising,unknown")
~~~

- [ ] Добавить доменные тесты с двумя несвязанными профилями developer_tools и cooking. Проверить четыре отказа, отключение правила, порядок правил, Unicode/регистр/пробелы, URL, title-only, старый материал, отсутствие положительного термина, технический релиз с практическим кейсом, timezone-aware now и независимую копию signals.

~~~python
assert evaluate_candidate(title_only, conservative_profile, now=NOW).status is DecisionStatus.SELECTED
assert evaluate_candidate(old_candidate, conservative_profile, now=NOW).status is DecisionStatus.SELECTED
assert technical_with_use.reason is DecisionReason.ELIGIBLE_FOR_AI
assert technical_without_use.reason is DecisionReason.TECHNICAL_WITHOUT_USE
~~~

- [ ] Доказать независимость от HN: два равных кандидата с разными points/num_comments в raw_payload дают одинаковое решение.
- [ ] Добавить прикладные тесты: пустой набор, смешанные решения, конкурентно сохранённое подмножество, неизвестный ID от репозитория и исключение evaluator.

~~~python
assert selector.execute() == SelectionResult(examined=3, selected=1, rejected=1, conflicts=1)
assert repository.saved_candidate_ids == [11, 12, 13]
~~~

- [ ] Добавить тест RunOnce: events строго равен ["import", "selection"]; ошибка импорта не запускает selection; ошибка selection возникает после успешного импорта.
- [ ] Добавить миграционные и PostgreSQL-тесты: JSONB signals, именованные FK/unique/check, head → 20260801_01 → head, ordered find_undecided, точные поля, no overwrite, реальное двухпоточное пересечение INSERT, один commit пакета, явный rollback с повторным использованием session.
- [ ] Изменить CLI-тест: fake RunOnce вместо fake importer; сохранить start/status/stop без регрессий.

~~~text
Получено: 3; новых: 2; дубликатов: 1; проверено: 4; selected: 3; rejected: 1; конфликты: 0
~~~

- [ ] Проверить ошибки профиля, selection и SQL: ненулевой код, нет traceback, raw_payload и словарей профиля.
- [ ] Записать трассировку требования → node ID → причина RED → мутация для всех 14 mutation gates.
- [ ] Запустить RED:

~~~bash
uv run pytest tests/unit/config/test_settings.py tests/unit/domain/candidates/test_selection.py tests/unit/application/selection/test_select_candidates.py tests/unit/application/jobs/test_run_once.py tests/e2e/test_cli_run_once.py -v
TEST_DATABASE_URL="$TEST_DATABASE_URL" uv run pytest tests/integration/test_migrations.py tests/integration/infrastructure/test_sqlalchemy_decisions.py -v
~~~

Ожидание: новые узлы RED из-за отсутствующего поведения; сохранённые Wave 1 узлы GREEN. Ошибка зависимости, фикстуры или PostgreSQL не считается корректным RED.

- [ ] Закоммитить только тесты и evidence: Спроектировал RED-тесты отбора.

### Задача 2: Terra 5.6 Medium реализует профиль и домен

**Файлы:** создать statuses.py и selection.py; изменить config.py и .env.example.

- [ ] Запустить focused RED для Settings и domain.
- [ ] Добавить обязательные внешние поля selection_policy_version, language, audience, rules, словари и selection_freshness_days.
- [ ] Pydantic преобразует CSV в нормализованные immutable tuple, сохраняет порядок правил, отвергает unknown/duplicates/empty active dictionary.
- [ ] Реализовать чистую политику: casefold, схлопывание пробелов, экранированные Unicode-границы, порядок профиля, generic signals fresh/stale, глубокая копия signals.
- [ ] Не читать raw_payload и не использовать fallback reject. Объяснение соответствует фактически первой сработавшей причине.
- [ ] Запустить focused GREEN.
- [ ] Временно сделать старость отказом и удалить title-only fallback; каждый узкий тест обязан стать RED. Восстановить файлы.
- [ ] Закоммитить: Добавил универсальные правила отбора.

### Задача 3: Terra 5.6 Medium реализует PostgreSQL-журнал

**Файлы:** создать decision_repository.py, sqlalchemy_decisions.py и миграцию; изменить models.py.

- [ ] Запустить PostgreSQL RED.
- [ ] Создать candidate_decisions: BigInteger id и candidate_id, String status/reason/policy_version, Text explanation, JSONB signals, timezone decided_at.
- [ ] Использовать ограничения fk_candidate_decisions_candidate_id_candidates, uq_candidate_decisions_candidate_id, ck_candidate_decisions_status. Check допускает только selected/rejected; downgrade удаляет только новую таблицу.
- [ ] find_undecided использует outer join, decision.id IS NULL и порядок CandidateModel.id; наружу возвращает доменный Candidate.
- [ ] save_new выполняет один PostgreSQL INSERT с ON CONFLICT DO NOTHING по unique, RETURNING candidate_id, один commit и явный rollback.
- [ ] Запустить integration GREEN без skip.
- [ ] Закоммитить: Сохранил неизменяемый журнал решений.

### Задача 4: Terra 5.6 Medium связывает run-once

**Файлы:** создать select_candidates.py и application/jobs/run_once.py; изменить bootstrap.py и cli.py.

- [ ] Запустить application/CLI RED.
- [ ] SelectCandidates вызывает clock один раз, оценивает все undecided, вызывает save_new один раз и считает только возвращённые IDs.
- [ ] Соблюсти examined == selected + rejected + conflicts; неизвестный возвращённый ID даёт ValueError.
- [ ] RunOnce вызывает importer и selector по одному разу строго последовательно и не скрывает исключения.
- [ ] open_run_once создаёт один engine, session factory и HTTP client; закрывает client и engine при успехе, ошибке конструктора и ошибке выполнения.
- [ ] Профиль создаётся из уже проверенного Settings до yield.
- [ ] CLI печатает точную строку RED-контракта и нормализует известные ошибки без утечки данных.
- [ ] Запустить application/CLI GREEN и весь неинтеграционный набор.
- [ ] Закоммитить: Подключил отбор к разовому запуску.

### Задача 5: Terra 5.6 Medium завершает GREEN и README

- [ ] Выполнить:

~~~bash
uv run pytest -m "not integration" -v
TEST_DATABASE_URL="$TEST_DATABASE_URL" uv run pytest -m integration -v
uv run python -m compileall -q src
git diff --check
~~~

- [ ] Собрать wheel, установить в новый временный venv и из /tmp доказать наличие add_candidate_decisions в package resources.

~~~bash
uv build
POSTIFY_WAVE2_VENV_ROOT="$(mktemp -d)"
python3.12 -m venv "$POSTIFY_WAVE2_VENV_ROOT/venv"
"$POSTIFY_WAVE2_VENV_ROOT/venv/bin/pip" install dist/postify-*.whl
cd /tmp
"$POSTIFY_WAVE2_VENV_ROOT/venv/bin/python" -c 'from importlib.resources import files; p = files("postify.infrastructure.database.migrations.versions"); assert any("add_candidate_decisions" in item.name for item in p.iterdir())'
~~~
- [ ] Обновить README без удаления продуктового контекста: Wave 2 готова; профиль универсален; selected/rejected объяснимы; AI, контент и Telegram не готовы.
- [ ] Повторить полный GREEN и закоммитить: Описал отбор второй волны.

### Задача 6: свежая Terra 5.6 High проводит независимые ворота

- [ ] Сначала проверить трассировку RED. Critical/Important пробел возвращает пакет в fix-loop до code review.
- [ ] По одной применить все 14 мутаций из design, выполнить узкий тест, записать RED, полностью восстановить изменение.
- [ ] Любая выжившая мутация — Important.
- [ ] После восстановления выполнить полный unit/e2e/integration GREEN и git diff --check.
- [ ] Затем проверить код: зависимости, отсутствие HN/AI hardcode, конфигурацию, порядок правил, неизменяемость, транзакции, concurrency, lifecycle, CLI, wheel и scope.
- [ ] Исправлять до нуля Critical/Important, повторяя узкие и полные проверки.
- [ ] Записать evidence и закоммитить: Проверил доказательства второй волны.

### Задача 7: принять, слить и чисто завершить Wave 2

- [ ] На disposable PostgreSQL 16 применить миграции, создать нейтральные кандидаты для selected и четырёх отказов, выполнить настоящий selection дважды.
- [ ] Доказать по SQL: одно неизменяемое решение на кандидата; второй запуск не создаёт решений; сеть/systemd не нужны.
- [ ] Записать docs/development-loop/runs/2026-08-02-run-001.md: Sₙ/Sₙ₊₁, коммиты, команды, время, агенты, возвраты, мутации, bottleneck, live proof и решения Wave 3. Неизвестное отметить «не измерено».
- [ ] Обновить наблюдения/ёмкость development-loop только по измеренным данным. Изменение процесса потребует версии и Excalidraw в одном коммите.
- [ ] Слить принятую ветку в main без push.
- [ ] На main повторить полный GREEN, compileall и diff check.
- [ ] Только после GREEN удалить worktree/ветку и созданные .venv, build, dist, egg-info, pytest/Python caches. Не удалять .env и пользовательские данные.
- [ ] Подтвердить main и пустой git status --porcelain. Только тогда статус Wave 2 — принят.

## Самопроверка плана

- [x] Каждое продуктовое правило имеет тест и mutation gate.
- [x] Каждый интерфейс определён до использования следующей задачей.
- [x] PostgreSQL rollback, concurrency, downgrade и wheel имеют доказательства.
- [x] Нет AI, UI, reserve, HN scoring или hardcoded niche.
- [x] Приёмка включает merge, GREEN на main, очистку и журнал запуска.

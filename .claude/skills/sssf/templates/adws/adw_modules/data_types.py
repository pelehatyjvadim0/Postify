"""Конкретные типы данных для системы SSSF ADW.

ПРАВИЛО (правило четырёх параметров): любая функция, принимающая более 4
параметров, должна принимать вместо них ОДИН из этих объектов. Образец —
AgentCall и PhaseParams.

Каждый вызов агента объявляет конкретный тип вывода — подкласс EnvelopeBase —
по которому разбирается его итоговый JSON-ответ. Нетипизированные передачи
данных не допускаются.
"""

from __future__ import annotations

from typing import Any, Callable, Literal, Optional, Type

from pydantic import BaseModel, Field, ValidationInfo, field_validator

PhaseKind = Literal["engineer", "agent", "code"]
PhaseStatus = Literal["queued", "running", "success", "fail"]


# ── Фазы ─────────────────────────────────────────────────────────────────────

class PhaseParams(BaseModel):
    """Всё, что нужно run.phase(). Передаётся одним объектом, а не разрозненными параметрами."""

    name: str                       # короткий идентификатор, уникальный в запуске: "plan", "build"
    kind: PhaseKind                 # дорожка, в которой отображается блок
    owner: str                      # имя инженера, "git" или имя агента из конфигурации
    description: str                # ОБЯЗАТЕЛЬНО: что и зачем делает эта фаза — см. ниже
    retries: int = 0                # фазы агентов: повторы при сбое gate через continue

    @field_validator("description")
    @classmethod
    def _description_must_be_earned(cls, value: str, info: ValidationInfo) -> str:
        """Название фазы идентифицирует её, а описание объясняет. Нужны оба.

        Описание — единственное предложение о цели, которое показывают трасса,
        консоль и блок фазы в UI; остальное — идентификаторы, статусы и время.
        `commit_plan: "Commit the plan"` не сообщает читателю ничего нового,
        поэтому такое повторение отклоняется так же, как пустое описание. Это
        намеренно ошибка при создании: она возникает до открытия фазы, а не
        после того, как запуск уже попал в трассу.
        """
        text = " ".join(value.split())
        name = str(info.data.get("name", "?"))
        if not text:
            raise ValueError(
                f"phase {name!r}: description is required — one sentence on what this "
                f"phase does and why. It is what the trace and the UI show.")
        if text.rstrip(".").casefold() == name.replace("_", " ").casefold():
            raise ValueError(
                f"phase {name!r}: description {text!r} only restates the phase name — "
                f"say what it does and why instead.")
        return text


class Phase(BaseModel):
    """Сохранённая запись фазы: PhaseParams плюс жизненный цикл."""

    phase_id: str
    adw_id: str
    seq: int
    params: PhaseParams
    status: PhaseStatus = "fail"    # успех нужно заслужить
    attempt: int = 0
    error: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None


# ── Конверты (типы вывода агента) ────────────────────────────────────────────

class EnvelopeBase(BaseModel):
    """Основа итогового JSON-ответа каждого агента. Типы вывода расширяют её."""

    status: Literal["success", "fail"]
    summary: str = ""
    artifacts: list[str] = Field(default_factory=list)
    notes_for_next_agent: str = ""


class GenericOutput(EnvelopeBase):
    pass


class PlanOutput(EnvelopeBase):
    # Тема коммита PLAN — файл спецификации, написанный планировщиком, а не
    # описанная в нём реализация. commit_message каждого агента относится к его
    # собственному результату, поэтому цепочка с коммитом на каждом шаге не
    # использует слова одного агента для diff другого.
    commit_message: str = ""


class BuildOutput(EnvelopeBase):
    changed_files: list[str] = Field(default_factory=list)
    commit_message: str = ""        # используется фазой git commit


class ScoutFinding(BaseModel):
    file: str
    note: str = ""


class ScoutOutput(EnvelopeBase):
    findings: list[ScoutFinding] = Field(default_factory=list)


class ReviewFinding(BaseModel):
    """Один пункт из запроса (или плана) и информация о его наличии."""

    requirement: str                # требование словами автора запроса
    met: bool
    evidence: str = ""              # где это находится или чего не хватает


class ReviewOutput(EnvelopeBase):
    """Подтверждение, что реализовано запрошенное, а не результат запуска тестов."""

    approved: bool = False
    findings: list[ReviewFinding] = Field(default_factory=list)
    blocking: list[str] = Field(default_factory=list)   # что нужно изменить до одобрения


class DocumentOutput(EnvelopeBase):
    """Где находится описание завершённого изменения."""

    document_path: str = ""         # документ в репозитории, например app_docs/<adw_id>_<slug>.md
    documented_files: list[str] = Field(default_factory=list)
    commit_message: str = ""


# ── Детерминированные блоки качества ─────────────────────────────────────────

QualityArea = Literal["frontend", "backend"]
QualityOperation = Literal["lint", "typecheck", "build"]


class QualityCheckSpec(BaseModel):
    """Одна детерминированная команда проверки качества."""

    name: str
    area: QualityArea
    operation: QualityOperation
    argv: list[str]
    timeout_seconds: int = 120


class QualityCheckResult(BaseModel):
    """Собранные свидетельства работы одной команды проверки качества."""

    name: str
    area: QualityArea
    operation: QualityOperation
    command: str
    returncode: int
    passed: bool
    duration_seconds: float
    output_artifact: str
    # Конец stdout+stderr дословно и без разбора. Сбой должен вернуться к
    # разработчику в конверте, а тот не может открыть непереданный ему лог —
    # поэтому свидетельства идут вместе с ним. Формат намеренно сырой: каждый
    # runner оформляет ошибки по-разному, и общий парсер уверенно ошибался бы.
    # Полный лог всегда находится в output_artifact.
    output_tail: str = ""


class QualityResult(BaseModel):
    """Итог блока качества: все выполненные проверки и вердикт."""

    passed: bool
    checks: list[QualityCheckResult] = Field(default_factory=list)
    failures: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)


# ── Сбор изменений (git diff, детерминированный) ──────────────────────────────

class ChangeCapture(BaseModel):
    """Всё, что нужно documentation.capture(). Один объект, не разрозненные параметры."""

    base: str = "main"              # ref, относительно которого измеряется работа
    max_diff_lines: int = 2000      # artifact diff обрезается после этого лимита
    include_untracked: bool = True  # новый файл тоже является частью изменения


class BaseRef(BaseModel):
    """Коммит, от которого измеряется изменение, и причина выбора.

        `reason` — строка, показываемая в трассе. Diff настолько надёжен,
        насколько надёжна его точка отсчёта, поэтому ADW записывает этот выбор,
        а не вынуждает читателя догадываться.
    """

    ref: str                        # что было запрошено: "main" или зафиксированный sha
    commit: str                     # коммит, относительно которого реально создан diff
    reason: str = ""

    @property
    def label(self) -> str:
        """Форма отображения: именованный ref без изменений, raw sha — сокращённый."""
        if len(self.ref) == 40 and all(c in "0123456789abcdef" for c in self.ref):
            return self.ref[:7]
        return self.ref


class ChangeSet(BaseModel):
    """Что изменилось с базового коммита — только факты git, без оценок."""

    base: BaseRef
    files: list[str] = Field(default_factory=list)
    untracked: list[str] = Field(default_factory=list)
    insertions: int = 0
    deletions: int = 0
    stat: str = ""                  # вывод `git diff --stat` дословно
    diff_path: str = ""             # полный diff, записанный в context_handoff/
    truncated: bool = False

    @property
    def empty(self) -> bool:
        return not (self.files or self.untracked)


class ChangesOutput(EnvelopeBase):
    """ChangeSet в форме конверта, чтобы его можно было передать агенту напрямую.

    Та же идея адаптера, что и у VerifyOutput: код вычисляет diff, а агент,
    документирующий изменения, получает его через единый механизм передачи.
    """

    base: str = ""                  # "<ref> @ <commit> — <reason>"
    changed_files: list[str] = Field(default_factory=list)
    insertions: int = 0
    deletions: int = 0
    stat: str = ""
    diff_path: str = ""             # здесь находится полный diff


class VerifyOutput(EnvelopeBase):
    """Детерминированный результат в форме конверта, который может получить агент.

    Агенты передают друг другу типизированные конверты; блоки кода возвращают
    QualityResult. Это адаптер, поэтому сбой lint или тестов возвращается к
    разработчику тем же путём, что и отчёт агента-тестировщика; разницу знает
    только скрипт ADW.
    """

    passed: bool = False
    failures: list[str] = Field(default_factory=list)


# ── Вызовы агентов ──────────────────────────────────────────────────────────

class GateCheck(BaseModel):
    """Один объект, проверенный gate, и найденный результат.

    `note` содержит свидетельство: "exists, 2.1KB", "exit 0", "not in the diff".
    При проваленной проверке оно же служит причиной, которую сообщают агенту.
    """

    item: str                       # что проверялось: путь, команда, тест
    ok: bool
    note: str = ""


class GateReport(BaseModel):
    """Что возвращает каждый gate: выполненные проверки. Нарушения выводятся из них.

    Описание остаётся однострочным для каждого объекта: `report.check(...)`
    добавляет проверку и возвращает self, поэтому gate — это цикл и return.
    """

    checks: list[GateCheck] = Field(default_factory=list)

    def check(self, item: str, ok: bool, note: str = "") -> "GateReport":
        self.checks.append(GateCheck(item=item, ok=ok, note=note))
        return self

    @property
    def violations(self) -> list[str]:
        return [f"{c.item}: {c.note or 'failed'}" for c in self.checks if not c.ok]

    @property
    def passed(self) -> bool:
        return not self.violations


class AgentCall(BaseModel):
    """Один вызов агента: prompt на входе, типизированный конверт на выходе, gate проверены."""

    model_config = {"arbitrary_types_allowed": True}

    output_type: Type[EnvelopeBase]
    prompt: str
    previous: Optional[EnvelopeBase] = None
    gates: list[Callable] = Field(default_factory=list)   # gate(envelope, run) -> list[str]


# ── Конфигурация ─────────────────────────────────────────────────────────────

class PromptEngineering(BaseModel):
    system: str                     # путь к system.md
    user: str                       # путь к user.md


class AgentConfig(BaseModel):
    name: str
    coding_agent: Literal["pi", "claude_code"] = "pi"
    model: str = "google/gemini-3.6-flash"
    thinking: str = "medium"        # off | minimal | low | medium | high | xhigh | max
    color: str = ""                 # hex-цвет дорожки агента в UI
    purpose: str = ""
    prompt_engineering: PromptEngineering
    harness_engineering: list[str] = Field(default_factory=list)
    tools: Optional[list[str]] = None    # allowlist; None = можно использовать все инструменты
    # Что этот агент может ИЗМЕНЯТЬ в репозитории; проверяется кодом после
    # каждого вызова (см. adw_modules/permissions.py). `tools` не выражает это:
    # `bash` запускает что угодно, а `write` работает с любым путём, поэтому
    # список возможностей агента — лишь намерение, которое никто не проверяет.
    #   None  -> без ограничений, кроме общих `protected_files`
    #   []    -> только чтение: нельзя менять отслеживаемые файлы
    #   [...] -> только эти пути. Завершающий "/" — префикс каталога; "*" —
    #            glob; всё остальное — точный путь.
    writes: Optional[list[str]] = None


class ConfigDefaults(BaseModel):
    coding_agent: Literal["pi", "claude_code"] = "pi"
    model: str = "google/gemini-3.6-flash"
    thinking: str = "medium"
    color: str = ""
    harness_engineering: list[str] = Field(default_factory=list)
    tools: Optional[list[str]] = None    # общий allowlist; None = можно использовать все инструменты
    # Запрещено каждому агенту, который не указал эти пути в собственном `writes`.
    # По умолчанию это код самой фабрики: агент не должен иметь возможности
    # менять механизм, определяющий успешность его работы.
    protected_files: list[str] = Field(default_factory=lambda: [
        "adws/adw_modules/", "adws/adw_sssf_config/", "adws/adw_*.py",
    ])
    data_dir: str = "adws/adw_data"


class ObservabilityConfig(BaseModel):
    db: str = "adws/adw_data/sssf.db"
    poll_ms: int = 500


class SSSFConfig(BaseModel):
    defaults: ConfigDefaults = Field(default_factory=ConfigDefaults)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    agents: list[AgentConfig] = Field(default_factory=list)


# ── Трассировка ──────────────────────────────────────────────────────────────

class EventRecord(BaseModel):
    """Одно событие трассировки, всегда записываемое для adw_id + фазы."""

    adw_id: str
    phase_id: str = ""
    type: str                       # phase_start | agent_start | tool_call | handoff | gate_pass | gate_fail | log | agent_end | phase_end | error
    name: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    parent_id: str = ""
    tokens: Optional[int] = None
    # Span: оба поля задаются, когда событие занимает реальное время (вызов
    # инструмента), чтобы UI расположил его на временной оси без разбора JSON
    # payload. Если поля не заданы, tracer проставляет started_at при записи.
    started_at: Optional[str] = None
    ended_at: Optional[str] = None


# ── Интерфейс кодового агента Pi ─────────────────────────────────────────────

class PiRequest(BaseModel):
    """Всё, что нужно одному неинтерактивному запуску pi."""

    prompt: str
    system_prompt: str
    model: str                      # шаблон реестра, разрешаемый в provider + id
    thinking: str = "medium"
    session_id: str                 # pi --session-id: создаёт или продолжает сессию
    session_dir: str
    raw_output_path: str            # здесь сохраняется поток JSONL
    tools: Optional[list[str]] = None
    extensions: list[str] = Field(default_factory=list)
    cwd: str = "."                  # задаётся из run.repo_root — корень кодовой базы для агентов


class UsageBreakdown(BaseModel):
    """Токены и их стоимость в долларах по компонентам, суммированные за вызов.

    В точности повторяет форму `usage` у pi, поэтому числа согласуются с его
    отчётом: `input` НЕ включает чтение cache, которое тарифицируется отдельно
    и дешевле; сложите их, чтобы узнать размер отправленного prompt.
    """
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    # Токены размышления. Это НЕ пятый компонент: по данным всех сессий на
    # диске reasoning всегда <= output, а четыре компонента выше всегда дают
    # totalTokens; следовательно, reasoning — доля размышления в output и
    # тарифицируется по ставке output. Отражайте его внутри output, не добавляя.
    reasoning_tokens: int = 0
    total_tokens: int = 0
    input_cost: float = 0.0
    output_cost: float = 0.0
    cache_read_cost: float = 0.0
    cache_write_cost: float = 0.0
    total_cost: float = 0.0

    def add_turn(self, usage: dict, total_tokens: int) -> None:
        """Добавить один объект usage из pi `message_end`.

        `total_tokens` передаётся вместо повторного вычисления: вызывающий код
        уже считает его способом pi (totalTokens либо сумма компонентов).
        """
        cost = usage.get("cost") or {}
        self.input_tokens += usage.get("input") or 0
        self.output_tokens += usage.get("output") or 0
        self.cache_read_tokens += usage.get("cacheRead") or 0
        self.cache_write_tokens += usage.get("cacheWrite") or 0
        self.reasoning_tokens += usage.get("reasoning") or 0
        self.total_tokens += total_tokens
        self.input_cost += cost.get("input") or 0.0
        self.output_cost += cost.get("output") or 0.0
        self.cache_read_cost += cost.get("cacheRead") or 0.0
        self.cache_write_cost += cost.get("cacheWrite") or 0.0
        self.total_cost += cost.get("total") or 0.0

    def merge(self, other: "UsageBreakdown") -> None:
        """Добавить usage другого вызова: фаза с повторами платит несколько раз."""
        for field in self.model_fields:
            setattr(self, field, getattr(self, field) + getattr(other, field))


class PiResult(BaseModel):
    text: str = ""
    returncode: int = 0
    session_id: str = ""
    tokens: int = 0
    cost: float = 0.0
    usage: UsageBreakdown = Field(default_factory=UsageBreakdown)
    # Заполненность контекста после ПОСЛЕДНЕГО хода, а не сумма. `tokens`
    # тарифицирует каждый ход; здесь — текущая заполненность окна, которую
    # полоса контекста визуализатора сравнивает с `context_window`.
    context_tokens: int = 0
    context_window: int = 0         # 0, когда реестр не задаёт предел

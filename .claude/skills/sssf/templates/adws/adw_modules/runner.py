"""Объект Run: конфигурация + adw_id + agent_map + tracer + console, связанные один раз.

`run.phase(PhaseParams(...))` — ЕДИНСТВЕННЫЙ примитив фазы: контекстный менеджер
для всех трёх типов (инженер, агент, код). Успех нужно заслужить: каждая фаза
по умолчанию завершается fail; только чистый выход меняет его (фазам агентов
также нужны разобранный конверт и успешные gate, проверяемые внутри ph.call).
"""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path

from . import agents, git_helper
from .console import Console
from .data_types import AgentCall, EnvelopeBase, EventRecord, Phase, PhaseParams
from .utils import ensure_dir, now_iso


class PhaseHandle:
    def __init__(self, run: "Run", phase: Phase):
        self.run = run
        self.phase = phase

    def log(self, **payload) -> None:
        self.run.tracer.event(EventRecord(adw_id=self.run.adw_id,
                                          phase_id=self.phase.phase_id,
                                          type="log", name=self.phase.params.name,
                                          payload=payload))
        self.run.console.note(", ".join(f"{k}: {v}" for k, v in payload.items()))
        if self.phase.params.kind == "engineer" and "input" in payload:
            self.run.tracer.session_request(self.run.adw_id, str(payload["input"]))

    def call(self, call: AgentCall) -> EnvelopeBase:
        if self.phase.params.kind != "agent":
            raise RuntimeError("ph.call() is only valid inside an agent phase")
        return agents.execute(self.run, self.phase, call)


class Run:
    def __init__(self, cfg, adw_id: str, tracer, engineer: str):
        self.cfg = cfg
        self.adw_id = adw_id
        self.tracer = tracer
        self.console = Console(tracer, adw_id)
        self.engineer = engineer
        self.phases: list[Phase] = []
        self.tokens = 0
        self.cost = 0.0
        self._seq = tracer.max_phase_seq(adw_id)   # присоединённый запуск продолжает последовательность
        self.repo_root = git_helper.repo_root()    # здесь запускаются для работы все агенты
        self.session_dir = ensure_dir(Path(cfg.defaults.data_dir) / "sessions" / adw_id)
        self.context_handoff_dir = ensure_dir(self.session_dir / "context_handoff")
        self._agent_map_path = self.session_dir / "agent_map.json"
        self.agent_map: dict = (json.loads(self._agent_map_path.read_text())
                                if self._agent_map_path.exists() else {})

    # ── Карта агентов (adw_id -> id сессии кодового агента для каждого агента) ─
    def save_agent_map(self, agent: str, entry: dict) -> None:
        self.agent_map[agent] = entry
        self._agent_map_path.write_text(json.dumps(self.agent_map, indent=2))

    # ── Usage (итоги запуска повторяют накопленные tracer в sqlite) ──────────
    def add_usage(self, tokens: int, cost: float) -> None:
        self.tokens += tokens
        self.cost += cost
        self.tracer.session_add_usage(self.adw_id, tokens, cost)

    # ── Примитив фазы ───────────────────────────────────────────────────────
    @contextmanager
    def phase(self, params: PhaseParams):
        self._seq += 1
        phase = Phase(phase_id=f"{self.adw_id}_{self._seq:02d}_{params.name}",
                      adw_id=self.adw_id, seq=self._seq, params=params,
                      status="running", started_at=now_iso())
        self.phases.append(phase)
        self.tracer.phase_upsert(phase)
        self.tracer.event(EventRecord(adw_id=self.adw_id, phase_id=phase.phase_id,
                                      type="phase_start", name=params.name,
                                      payload={"kind": params.kind, "owner": params.owner,
                                               "description": params.description}))
        self.console.phase_started(phase)
        clock = time.monotonic()
        try:
            yield PhaseHandle(self, phase)
        except BaseException as error:
            phase.status = "fail"                      # успех нужно заслужить
            phase.error = str(error)[:1000]
            phase.ended_at = now_iso()
            self.tracer.event(EventRecord(adw_id=self.adw_id, phase_id=phase.phase_id,
                                          type="error", name=params.name,
                                          payload={"error": phase.error}))
            self.tracer.event(EventRecord(adw_id=self.adw_id, phase_id=phase.phase_id,
                                          type="phase_end", name=params.name,
                                          payload={"status": "fail"}))
            self.tracer.phase_upsert(phase)
            self.tracer.session_finish(self.adw_id, ok=False)
            self.console.phase_ended(phase, time.monotonic() - clock)
            self.console.session_finished(False, self.tokens, self.cost,
                                          self.cfg.observability.db)
            raise
        else:
            phase.status = "success"
            phase.ended_at = now_iso()
            self.tracer.event(EventRecord(adw_id=self.adw_id, phase_id=phase.phase_id,
                                          type="phase_end", name=params.name,
                                          payload={"status": "success"}))
            self.tracer.phase_upsert(phase)
            self.console.phase_ended(phase, time.monotonic() - clock)

    # ── Результат запуска ───────────────────────────────────────────────────
    def finish(self, accepted: bool = True, reason: str = "") -> int:
        """Завершить запуск и вернуть его код выхода. Вызывать ровно один раз.

        Здесь два критерия, а не один. Все фазы должны пройти И должно быть
        выполнено собственное условие приёмки ADW. Вопросы намеренно разные:
        фаза тестирования, запустившая набор тестов, сделала свою работу, даже
        если тесты завершились с ошибками; значит, ФАЗА успешна, а ЗАПУСК — нет.

        Это заменяет свойство `succeeded`, отвечавшее только на первый вопрос.
        Поскольку оно имело побочные эффекты, оно записывало статус сессии и
        выводило баннер до вычисления вызывающим кодом `and test.passed`.
        Запуск с непрошедшими тестами записывался успешным в db, терминале и UI,
        но завершался с кодом 1. Читатель трассы видел успех; правду видел лишь
        CI, проверяющий `$?`. Теперь один вызов одновременно определяет db,
        баннер и код выхода, поэтому они не могут расходиться.
        """
        phases_ok = bool(self.phases) and all(p.status == "success" for p in self.phases)
        ok = phases_ok and accepted
        if phases_ok and not accepted:
            note = reason or "the run's acceptance criterion was not met"
            self.tracer.event(EventRecord(
                adw_id=self.adw_id,
                phase_id=self.phases[-1].phase_id if self.phases else "",
                type="error", name="not_accepted", payload={"reason": note}))
            self.console.note(f"not accepted: {note}")
        self.tracer.session_finish(self.adw_id, ok=ok)
        self.console.session_finished(ok, self.tokens, self.cost, self.cfg.observability.db)
        return 0 if ok else 1

"""Жизненный цикл сессии: закрепить или создать adw_id, построить объект Run.

`ensure(cfg, adw_id)` присоединяется к существующей сессии или создаёт её
ровно под этим id (закреплённые id обеспечивают повторяемые запуски); без id
создаётся и печатается новый, чтобы следующий ADW мог его использовать.
"""

from __future__ import annotations

import os
import signal
import sys
from pathlib import Path

from .data_types import SSSFConfig
from .runner import Run
from .tracer import Tracer
from .utils import engineer_name, new_id


def _finalize_when_killed(run: Run) -> None:
    """Принудительно остановленный запуск всё равно закрывает собственную трассу.

    Стандартная обработка SIGTERM в Python завершает процесс без развёртывания
    стека, поэтому `just kill` (или любой `kill <pid>`) навсегда оставил бы
    сессию в статусе `running` и с открытыми строками процессов: трасса заявляла
    бы о работе, которая уже остановлена. Преобразование сигнала в SystemExit
    завершает сессию здесь и даёт контекстному менеджеру фазы записать её сбой.
    """
    def handler(signum, _frame):
        run.tracer.session_finish(run.adw_id, ok=False)   # также закрывает строки процессов
        raise SystemExit(128 + signum)

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, handler)


def ensure(cfg: SSSFConfig, adw_id: str | None = None) -> Run:
    adw_id = adw_id or new_id(8)
    tracer = Tracer(cfg.observability.db,
                    f"{cfg.defaults.data_dir}/sessions/{adw_id}/events.jsonl")
    run = Run(cfg=cfg, adw_id=adw_id, tracer=tracer, engineer=engineer_name())
    tracer.session_start(adw_id, run.engineer, adw_name=Path(sys.argv[0]).stem)
    # Этот процесс и есть запуск. Записываем его до открытия фазы, чтобы запуск,
    # зависший на первом вызове агента, всё ещё можно было остановить по adw_id.
    tracer.process_start(adw_id, "adw", "", os.getpid(),
                         " ".join([Path(sys.argv[0]).name, *sys.argv[1:]]))
    _finalize_when_killed(run)
    run.console.session_started(adw_id, run.engineer)
    return run

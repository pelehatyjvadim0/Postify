"""Интерфейс Claude Code — ЗАГЛУШКА в v1. Пока фабрика поддерживает только Pi.

Схема конфигурации принимает `coding_agent: claude_code`, поэтому на уровне
схемы ничего не ломается, но выбор этого значения вызовет исключение, пока в v2
не будет реализован этот интерфейс
(`claude -p --output-format stream-json --resume <session_id>`).
"""

from __future__ import annotations


def run(*args, **kwargs):
    raise NotImplementedError(
        "coding_agent 'claude_code' is not implemented in v1 — SSSF v1 runs the "
        "Pi coding agent only. Set coding_agent: pi (or omit it) in sssf.config.yaml."
    )

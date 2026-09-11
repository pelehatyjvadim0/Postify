from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ProjectRule:
    id: int
    project_id: int
    text: str
    severity: str = "block"
    enabled: bool = True
    origin: str = "manual"
    position: int = 0

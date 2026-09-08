from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from postify.domain.content.models import AnalysisInput, BatchAnalysis


@dataclass(frozen=True, slots=True)
class GenerationBrief:
    topic: str
    language: str
    audience: str
    format_instructions: str
    source_language: str = "ar"
    tone: str = "Нейтральный"


class ContentAnalyzer(Protocol):
    def analyze(
        self,
        articles: Sequence[AnalysisInput],
        package_limit: int,
        brief: GenerationBrief | None = None,
    ) -> BatchAnalysis: ...

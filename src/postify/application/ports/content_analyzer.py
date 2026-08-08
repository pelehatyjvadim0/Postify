from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from postify.domain.content.models import AnalysisInput, BatchAnalysis


class ContentAnalyzer(Protocol):
    def analyze(
        self, articles: Sequence[AnalysisInput], package_limit: int
    ) -> BatchAnalysis: ...

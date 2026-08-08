from __future__ import annotations

from dataclasses import dataclass

from postify.application.ingestion.import_candidates import (
    ImportCandidates,
    ImportResult,
)
from postify.application.selection.select_candidates import (
    SelectCandidates,
    SelectionResult,
)


@dataclass(frozen=True, slots=True)
class RunOnceResult:
    import_result: ImportResult
    selection_result: SelectionResult
    content_result: object | None = None


class RunOnce:
    def __init__(
        self, importer: ImportCandidates, selector: SelectCandidates, content=None
    ) -> None:
        self._importer = importer
        self._selector = selector
        self._content = content

    def execute(self) -> RunOnceResult:
        import_result = self._importer.execute()
        selection_result = self._selector.execute()
        content_result = self._content.execute() if self._content else None
        return RunOnceResult(
            import_result=import_result,
            selection_result=selection_result,
            content_result=content_result,
        )

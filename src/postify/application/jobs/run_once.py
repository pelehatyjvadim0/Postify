from __future__ import annotations

from dataclasses import dataclass



@dataclass(frozen=True, slots=True)
class RunOnceResult:
    import_result: object
    content_result: object | None = None


class RunOnce:
    def __init__(
        self, importer, content=None
    ) -> None:
        self._importer = importer
        self._content = content

    def execute(self) -> RunOnceResult:
        import_result = self._importer.execute()
        content_result = self.process_content()
        return RunOnceResult(
            import_result=import_result,
            content_result=content_result,
        )

    def process_content(self):
        """Run only the shared content stage after an owner command chose its target."""
        return self._content.execute() if self._content else None

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceImportResult:
    source_id: int
    outcome: str
    received: int = 0
    created: int = 0
    duplicates: int = 0
    failure_code: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectImportResult:
    sources: tuple[SourceImportResult, ...]

    @property
    def received(self) -> int:
        return sum(item.received for item in self.sources)

    @property
    def created(self) -> int:
        return sum(item.created for item in self.sources)

    @property
    def duplicates(self) -> int:
        return sum(item.duplicates for item in self.sources)


class ImportProjectSources:
    def __init__(self, connections, action_factory) -> None:
        self._connections = tuple(item for item in connections if item.enabled)
        self._action_factory = action_factory

    def execute(self) -> ProjectImportResult:
        results: list[SourceImportResult] = []
        for connection in self._connections:
            try:
                result = self._action_factory(connection).execute()
                results.append(
                    SourceImportResult(
                        connection.id,
                        "completed",
                        result.received,
                        result.created,
                        result.duplicates,
                    )
                )
            except Exception:
                results.append(
                    SourceImportResult(
                        connection.id, "failed", failure_code="source_failed"
                    )
                )
        if results and all(item.outcome == "failed" for item in results):
            raise RuntimeError("Все источники недоступны")
        return ProjectImportResult(tuple(results))

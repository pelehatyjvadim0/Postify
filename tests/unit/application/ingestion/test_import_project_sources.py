import pytest

from postify.application.ingestion.import_candidates import ImportResult
from postify.application.ingestion.import_project_sources import ImportProjectSources
from postify.domain.projects.models import SourceConnection


class ImportAction:
    def __init__(self, result=None, error=None) -> None:
        self.result = result
        self.error = error

    def execute(self):
        if self.error is not None:
            raise self.error
        return self.result


def source(id: int, provider: str = "hn_algolia") -> SourceConnection:
    return SourceConnection(
        id,
        1,
        provider,
        f"Источник {id}",
        True,
        {"query": "python", "tags": "story", "hits": 10},
        "0 7 * * *",
    )


def test_import_continues_after_one_source_failure() -> None:
    actions = {
        1: ImportAction(error=RuntimeError("source unavailable")),
        2: ImportAction(result=ImportResult(3, 2, 1)),
    }
    result = ImportProjectSources(
        (source(1), source(2)), lambda connection: actions[connection.id]
    ).execute()

    assert (result.received, result.created, result.duplicates) == (3, 2, 1)
    assert [item.outcome for item in result.sources] == ["failed", "completed"]
    assert result.sources[0].failure_code == "source_failed"


def test_import_ignores_disabled_sources() -> None:
    disabled = SourceConnection(
        1,
        1,
        "hn_algolia",
        "Выключен",
        False,
        {"query": "python", "tags": "story", "hits": 10},
        "0 7 * * *",
    )

    result = ImportProjectSources((disabled,), lambda connection: None).execute()

    assert result.sources == ()
    assert result.created == 0


def test_import_raises_safe_error_when_every_enabled_source_fails() -> None:
    action = ImportProjectSources(
        (source(1), source(2)),
        lambda connection: ImportAction(error=RuntimeError(f"secret-{connection.id}")),
    )

    with pytest.raises(RuntimeError, match="Все источники недоступны") as captured:
        action.execute()

    assert "secret" not in str(captured.value)

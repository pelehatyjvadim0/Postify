from __future__ import annotations

from dataclasses import dataclass

import pytest

from postify.application.ingestion.import_candidates import ImportResult


def _run_once_api():
    from postify.application.jobs.run_once import RunOnce, RunOnceResult
    from postify.application.selection.select_candidates import SelectionResult

    return RunOnce, RunOnceResult, SelectionResult


@dataclass
class RecordingStep:
    name: str
    events: list[str]
    result: object | None = None
    error: Exception | None = None

    def execute(self):
        self.events.append(self.name)
        if self.error is not None:
            raise self.error
        return self.result


def test_run_once_executes_import_then_selection_and_returns_both_results() -> None:
    # Поломка (mutation 12): отбор запускается до импорта или один этап вызывается повторно.
    RunOnce, RunOnceResult, SelectionResult = _run_once_api()
    events: list[str] = []
    import_result = ImportResult(received=3, created=2, duplicates=1)
    selection_result = SelectionResult(examined=4, selected=3, rejected=1, conflicts=0)
    importer = RecordingStep("import", events, import_result)
    selector = RecordingStep("selection", events, selection_result)

    result = RunOnce(importer, selector).execute()

    assert result == RunOnceResult(import_result=import_result, selection_result=selection_result)
    assert events == ["import", "selection"]


def test_import_error_prevents_selection() -> None:
    # Поломка: после незавершённого импорта всё равно начинается отбор.
    RunOnce, _, SelectionResult = _run_once_api()
    events: list[str] = []
    importer = RecordingStep("import", events, error=RuntimeError("импорт не завершён"))
    selector = RecordingStep(
        "selection",
        events,
        SelectionResult(examined=0, selected=0, rejected=0, conflicts=0),
    )

    with pytest.raises(RuntimeError, match="импорт не завершён"):
        RunOnce(importer, selector).execute()

    assert events == ["import"]


def test_selection_error_propagates_after_successful_import() -> None:
    # Поломка (mutation 13): ошибка отбора скрывается после уже завершённого импорта.
    RunOnce, _, _ = _run_once_api()
    events: list[str] = []
    importer = RecordingStep(
        "import",
        events,
        ImportResult(received=2, created=2, duplicates=0),
    )
    selector = RecordingStep(
        "selection",
        events,
        error=RuntimeError("решения не сохранены"),
    )

    with pytest.raises(RuntimeError, match="решения не сохранены"):
        RunOnce(importer, selector).execute()

    assert events == ["import", "selection"]

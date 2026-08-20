from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest


STARTED = datetime(2026, 8, 9, 9, tzinfo=UTC)
FINISHED = STARTED + timedelta(seconds=3)


def _api():
    # RED API импортируется только при выполнении test.
    from postify.application.observability.record_operation import RecordedAction
    from postify.domain.observability.models import OperationKind

    return RecordedAction, OperationKind


class SourceFailure(RuntimeError):
    pass


class JournalFailure(RuntimeError):
    pass


class FakeAction:
    def __init__(
        self,
        events: list[tuple[object, ...]],
        *,
        result: object | None = None,
        error: Exception | None = None,
    ) -> None:
        self.events = events
        self.result = result
        self.error = error

    def execute(self):
        self.events.append(("action",))
        if self.error is not None:
            raise self.error
        return self.result


class FakeJournal:
    def __init__(
        self,
        events: list[tuple[object, ...]],
        *,
        start_error: Exception | None = None,
        succeed_error: Exception | None = None,
        fail_error: Exception | None = None,
    ) -> None:
        self.events = events
        self.start_error = start_error
        self.succeed_error = succeed_error
        self.fail_error = fail_error

    def start(
        self,
        operation,
        *,
        now: datetime,
        mode: str = "automatic",
        actor: str = "scheduler",
    ) -> int:
        self.events.append(("start", operation.value, mode, actor, now))
        if self.start_error is not None:
            raise self.start_error
        return 41

    def succeed(
        self, run_id: int, *, outcome: str, now: datetime, **metadata: object
    ) -> None:
        event: tuple[object, ...] = ("succeed", run_id, outcome, now)
        if metadata:
            event += (metadata,)
        self.events.append(event)
        if self.succeed_error is not None:
            raise self.succeed_error

    def fail(
        self, run_id: int, *, failure_code: str, now: datetime, **metadata: object
    ) -> None:
        event: tuple[object, ...] = ("fail", run_id, failure_code, now)
        if metadata:
            event += (metadata,)
        self.events.append(event)
        if self.fail_error is not None:
            raise self.fail_error


def _clock(*values: datetime):
    moments = iter(values)
    return lambda: next(moments)


def _recorded(
    action: FakeAction,
    journal: FakeJournal,
    *,
    operation: str = "publish_once",
    success_outcome: str | Any = "empty",
    failure_code: str = "publish_once_failed",
    result_metadata=None,
):
    RecordedAction, OperationKind = _api()
    kind = {
        "run_once": OperationKind.RUN_ONCE,
        "publish_once": OperationKind.PUBLISH_ONCE,
    }[operation]
    return RecordedAction(
        action,
        journal,
        operation=kind,
        success_outcome=success_outcome,
        failure_code=failure_code,
        result_metadata=result_metadata,
        clock=_clock(STARTED, FINISHED),
    )


def test_recorded_action_preserves_result_and_saves_safe_outcome() -> None:
    # Поломка: start идёт после action, result подменяется или outcome не финализируется.
    events: list[tuple[object, ...]] = []
    expected_result = object()
    recorded = _recorded(
        FakeAction(events, result=expected_result),
        FakeJournal(events),
    )

    result = recorded.execute()

    assert result is expected_result
    assert events == [
        ("start", "publish_once", "automatic", "scheduler", STARTED),
        ("action",),
        ("succeed", 41, "empty", FINISHED),
    ]


def test_callable_success_outcome_uses_result_without_replacing_it() -> None:
    # Поломка: publish result не преобразуется в safe persisted outcome.
    events: list[tuple[object, ...]] = []
    expected_result = object()
    seen: list[object] = []

    def outcome(result: object) -> str:
        seen.append(result)
        return "cleanup_pending"

    result = _recorded(
        FakeAction(events, result=expected_result),
        FakeJournal(events),
        success_outcome=outcome,
    ).execute()

    assert result is expected_result
    assert seen == [expected_result]
    assert events[-1] == ("succeed", 41, "cleanup_pending", FINISHED)


def test_action_failure_saves_only_fixed_code_and_reraises_original_exception() -> None:
    # Поломка: в failure journal попадают exception text, URL, token или новое исключение.
    events: list[tuple[object, ...]] = []
    original = SourceFailure(
        "original https://private.invalid 123456:SENTINEL-TOKEN /media/private.png"
    )
    recorded = _recorded(
        FakeAction(events, error=original),
        FakeJournal(events),
    )

    with pytest.raises(SourceFailure, match="original") as raised:
        recorded.execute()

    assert raised.value is original
    assert events == [
        ("start", "publish_once", "automatic", "scheduler", STARTED),
        ("action",),
        ("fail", 41, "publish_once_failed", FINISHED),
    ]
    persisted = repr(events[-1])
    assert "private.invalid" not in persisted
    assert "SENTINEL" not in persisted
    assert "private.png" not in persisted


def test_failure_journal_error_never_masks_original_exception() -> None:
    # Поломка: failure journal error маскирует исходный Telegram/source failure.
    events: list[tuple[object, ...]] = []
    original = SourceFailure("original")
    recorded = _recorded(
        FakeAction(events, error=original),
        FakeJournal(events, fail_error=JournalFailure("journal unavailable")),
    )

    with pytest.raises(SourceFailure, match="original") as raised:
        recorded.execute()

    assert raised.value is original
    assert events[-1] == ("fail", 41, "publish_once_failed", FINISHED)


def test_start_failure_prevents_underlying_action() -> None:
    # Поломка: action запускается без долговечной running-строки.
    events: list[tuple[object, ...]] = []
    recorded = _recorded(
        FakeAction(events, result=object()),
        FakeJournal(events, start_error=JournalFailure("start unavailable")),
    )

    with pytest.raises(JournalFailure, match="start unavailable"):
        recorded.execute()

    assert events == [
        ("start", "publish_once", "automatic", "scheduler", STARTED)
    ]


def test_success_journal_failure_does_not_repeat_underlying_action() -> None:
    # Поломка: terminal write error повторно вызывает Telegram action.
    events: list[tuple[object, ...]] = []
    recorded = _recorded(
        FakeAction(events, result=object()),
        FakeJournal(events, succeed_error=JournalFailure("finish unavailable")),
    )

    with pytest.raises(JournalFailure, match="finish unavailable"):
        recorded.execute()

    assert events.count(("action",)) == 1
    assert events[-1] == ("succeed", 41, "empty", FINISHED)


def test_run_once_uses_its_own_operation_and_failure_codes() -> None:
    # Поломка: два action смешиваются в журнале или сохраняют небезопасную ошибку.
    events: list[tuple[object, ...]] = []
    original = SourceFailure("secret source payload")
    recorded = _recorded(
        FakeAction(events, error=original),
        FakeJournal(events),
        operation="run_once",
        success_outcome="completed",
        failure_code="run_once_failed",
    )

    with pytest.raises(SourceFailure):
        recorded.execute()

    assert events[0] == (
        "start",
        "run_once",
        "automatic",
        "scheduler",
        STARTED,
    )
    assert events[-1] == ("fail", 41, "run_once_failed", FINISHED)


def test_invalid_callable_success_outcome_does_not_reach_journal() -> None:
    # Поломка: callable сохраняет arbitrary outcome вместо fixed vocabulary.
    events: list[tuple[object, ...]] = []

    recorded = _recorded(
        FakeAction(events, result=object()),
        FakeJournal(events),
        success_outcome=lambda _: "private payload",
    )

    with pytest.raises(ValueError, match="outcome"):
        recorded.execute()

    assert events == [
        ("start", "publish_once", "automatic", "scheduler", STARTED),
        ("action",),
    ]


def test_run_once_records_codex_profile_and_counts_from_shared_result() -> None:
    from postify.application.content.process_content import ProcessContentResult
    from postify.application.ingestion.import_candidates import ImportResult
    from postify.application.jobs.run_once import RunOnceResult
    from postify.application.observability.record_operation import (
        run_once_operation_metadata,
    )
    from postify.application.selection.select_candidates import SelectionResult

    events: list[tuple[object, ...]] = []
    result = RunOnceResult(
        ImportResult(3, 2, 1),
        SelectionResult(2, 2, 0, 0),
        ProcessContentResult(
            claimed=2,
            packages_created=1,
            materials_taken=2,
            codex_model="gpt-5.6-luna",
            codex_reasoning_effort="high",
        ),
    )

    _recorded(
        FakeAction(events, result=result),
        FakeJournal(events),
        operation="run_once",
        success_outcome="completed",
        failure_code="run_once_failed",
        result_metadata=run_once_operation_metadata,
    ).execute()

    assert events[-1] == (
        "succeed",
        41,
        "completed",
        FINISHED,
        {
            "codex_model": "gpt-5.6-luna",
            "codex_reasoning_effort": "high",
            "materials_taken": 2,
            "packages_created": 1,
        },
    )


def test_invalid_failure_code_is_rejected_before_action_starts() -> None:
    # Поломка: wrong failure pairing writes arbitrary text after an action failure.
    events: list[tuple[object, ...]] = []

    with pytest.raises(ValueError, match="failure"):
        _recorded(
            FakeAction(events, error=SourceFailure("original")),
            FakeJournal(events),
            failure_code="private failure",
        )

    assert events == []

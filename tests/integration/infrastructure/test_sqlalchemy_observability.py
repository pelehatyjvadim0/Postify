from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from tests.integration.infrastructure.test_sqlalchemy_delivery import (
    PROJECT_ID,
    _seed_project,
)


pytestmark = pytest.mark.integration
NOW = datetime(2026, 8, 9, 9, tzinfo=UTC)
FINISHED = NOW + timedelta(seconds=3)


def _journal(engine):
    from postify.infrastructure.repositories.sqlalchemy_observability import (
        SqlAlchemyOperationRunRepository,
    )

    return SqlAlchemyOperationRunRepository(sessionmaker(engine), project_id=PROJECT_ID)


def test_succeeded_run_persists_its_result_payload_as_jsonb(
    migrated_database_url: str,
) -> None:
    # Поломка: UI опрашивает операцию и не получает id созданного поста.
    from postify.domain.observability.models import OperationKind

    engine = create_engine(migrated_database_url)
    _seed_project(engine)
    journal = _journal(engine)
    try:
        run_id = journal.start(OperationKind.GENERATE_POST, now=NOW, mode="manual", actor="user")
        journal.succeed(run_id, outcome="completed", now=FINISHED, result={"post_id": 77})

        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT status,outcome,failure_code,mode,actor,result,finished_at"
                    " FROM operation_runs WHERE id=:id"
                ),
                {"id": run_id},
            ).one()

        assert row.status == "succeeded"
        assert (row.outcome, row.failure_code) == ("completed", None)
        assert (row.mode, row.actor) == ("manual", "user")
        assert row.result == {"post_id": 77}
        assert row.finished_at == FINISHED
    finally:
        engine.dispose()


def test_failed_run_keeps_the_empty_default_result_and_its_fixed_code(
    migrated_database_url: str,
) -> None:
    # Поломка: failure_code расходится с CHECK базы или в result утекает текст ошибки.
    from postify.domain.observability.models import OperationKind

    engine = create_engine(migrated_database_url)
    _seed_project(engine)
    journal = _journal(engine)
    try:
        run_id = journal.start(OperationKind.PUBLISH_ONCE, now=NOW)
        journal.fail(run_id, failure_code="publish_once_failed", now=FINISHED)

        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "SELECT status,outcome,failure_code,result FROM operation_runs WHERE id=:id"
                ),
                {"id": run_id},
            ).one()

        assert (row.status, row.outcome, row.failure_code) == (
            "failed",
            None,
            "publish_once_failed",
        )
        assert row.result == {}
    finally:
        engine.dispose()


def test_second_run_of_the_same_operation_is_refused_until_the_first_finishes(
    migrated_database_url: str,
) -> None:
    # Поломка: параллельный запуск одной операции проекта создаёт две running-строки.
    from postify.domain.observability.models import OperationKind

    engine = create_engine(migrated_database_url)
    _seed_project(engine)
    journal = _journal(engine)
    try:
        run_id = journal.start(OperationKind.PUBLISH_ONCE, now=NOW)
        with pytest.raises(RuntimeError, match="operation_busy"):
            journal.start(OperationKind.PUBLISH_ONCE, now=NOW)
        # Другой вид операции не блокируется чужой running-строкой.
        other = journal.start(OperationKind.GENERATE_POST, now=NOW)
        assert other != run_id

        journal.succeed(run_id, outcome="empty", now=FINISHED)
        assert journal.start(OperationKind.PUBLISH_ONCE, now=FINISHED) != run_id
    finally:
        engine.dispose()


def test_finished_run_cannot_be_finished_twice(migrated_database_url: str) -> None:
    # Поломка: повторная запись итога переписывает уже опубликованный результат.
    from postify.domain.observability.models import OperationKind
    from postify.infrastructure.repositories.sqlalchemy_observability import (
        InvalidOperationRunTransition,
    )

    engine = create_engine(migrated_database_url)
    _seed_project(engine)
    journal = _journal(engine)
    try:
        run_id = journal.start(OperationKind.PUBLISH_ONCE, now=NOW)
        journal.succeed(run_id, outcome="published", now=FINISHED, result={"post_id": 5})

        with pytest.raises(InvalidOperationRunTransition):
            journal.fail(run_id, failure_code="publish_once_failed", now=FINISHED)

        with engine.connect() as connection:
            row = connection.execute(
                text("SELECT status,outcome,result FROM operation_runs WHERE id=:id"),
                {"id": run_id},
            ).one()
        assert (row.status, row.outcome, row.result) == (
            "succeeded",
            "published",
            {"post_id": 5},
        )
    finally:
        engine.dispose()

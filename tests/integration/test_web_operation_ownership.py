from __future__ import annotations

from contextlib import contextmanager
from threading import Event

import pytest
from sqlalchemy import create_engine, text

from postify.web.services import WebApplication
from tests.integration.test_import_component import configured_settings


pytestmark = pytest.mark.integration


def test_two_web_instances_share_durable_operation_ownership(
    migrated_database_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Поломка review: два process-local active set принимают одинаковую работу.
    from postify.web import services

    started = Event()
    release = Event()

    class BlockingRun:
        def execute(self):
            started.set()
            assert release.wait(timeout=2)
            return object()

    @contextmanager
    def opened(*args, **kwargs):
        assert kwargs["record_operation"] is False
        yield BlockingRun()

    monkeypatch.setattr(services, "open_project_run_once", opened)
    settings = configured_settings(migrated_database_url)
    first = WebApplication(settings, None)
    second = WebApplication(settings, None)
    try:
        assert first.run_once(1) == {"status": "accepted"}
        assert started.wait(timeout=1)
        with pytest.raises(RuntimeError, match="operation_busy"):
            second.run_once(1)
        release.set()
        first.close()
        second.close()

        engine = create_engine(migrated_database_url)
        try:
            with engine.connect() as connection:
                rows = connection.execute(
                    text(
                        "SELECT status,outcome FROM operation_runs "
                        "WHERE project_id=1 AND operation='run_once' ORDER BY id"
                    )
                ).all()
            assert rows == [("succeeded", "completed")]
        finally:
            engine.dispose()
    finally:
        release.set()
        # close идемпотентен для cleanup после раннего assertion.
        first.close()
        second.close()

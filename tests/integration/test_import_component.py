from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from postify.config import Settings
from postify.infrastructure.database.models import CandidateModel


pytestmark = pytest.mark.integration


def configured_settings(database_url: str) -> Settings:
    return Settings(
        database_url=database_url,
        hn_algolia_url="https://hn.example.test/api/v1/search_by_date",
        hn_query="python",
        hn_tags="story",
        hn_hits_per_page=1,
        postgresql_systemd_unit="postgresql.service",
        postgresql_ownership="dedicated",
        postify_on_calendar="0 9 * * 1-5",
        postify_timezone="Europe/Moscow",
    )


def tcp_database_url(database_url: str) -> str:
    parts = urlsplit(database_url)
    query = parse_qs(parts.query)
    if "host" not in query:
        return database_url

    return urlunsplit(
        (
            parts.scheme,
            f"{parts.username}@localhost:{query['port'][0]}",
            parts.path,
            urlencode({"options": query["options"][0]}),
            "",
        )
    )


def full_hn_hit() -> dict[str, object]:
    return {
        "objectID": "123",
        "title": "Практический Python",
        "url": "https://example.test/practical-python",
        "created_at_i": int(datetime(2026, 8, 1, 10, 0, tzinfo=UTC).timestamp()),
        "author": "alice",
    }


def test_open_importer_persists_one_hn_hit_and_keeps_duplicate_out_of_second_session(
    migrated_database_url: str,
) -> None:
    # Break caught: wiring a fake source/repository or losing duplicate protection across sessions.
    from postify.bootstrap import open_importer

    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"hits": [full_hn_hit()]}))
    settings = configured_settings(tcp_database_url(migrated_database_url))

    with open_importer(settings, transport=transport) as importer:
        assert importer.execute().created == 1
        assert importer.execute().created == 0

    engine = create_engine(migrated_database_url)
    try:
        with sessionmaker(engine)() as second_session:
            stored = second_session.scalars(select(CandidateModel)).all()
        assert [(item.source_id, item.title, item.url) for item in stored] == [
            ("123", "Практический Python", "https://example.test/practical-python")
        ]
    finally:
        engine.dispose()


def test_open_importer_closes_client_and_disposes_engine_on_success_and_source_error(monkeypatch) -> None:
    # Break caught: leaking either HTTP or database resources on normal or failing importer lifecycles.
    from postify import bootstrap
    from postify.application.ports.candidate_source import SourceFetchError

    events: list[str] = []

    class TrackingClient(httpx.Client):
        def close(self) -> None:
            events.append("client:close")
            super().close()

    class TrackingEngine:
        def dispose(self) -> None:
            events.append("engine:dispose")

    monkeypatch.setattr(bootstrap.httpx, "Client", TrackingClient)
    monkeypatch.setattr(bootstrap, "create_engine_from_settings", lambda settings: TrackingEngine())
    monkeypatch.setattr(bootstrap, "sessionmaker", lambda engine: object())

    with bootstrap.open_importer(configured_settings("postgresql+psycopg://unused")):
        pass

    assert events == ["client:close", "engine:dispose"]
    events.clear()

    class FailingSource:
        def __init__(self, **kwargs: object) -> None:
            pass

        def fetch(self) -> list[object]:
            raise SourceFetchError("источник недоступен")

    monkeypatch.setattr(bootstrap, "HnAlgoliaCandidateSource", FailingSource)
    monkeypatch.setattr(bootstrap, "SqlAlchemyCandidateRepository", lambda session_factory: object())

    with pytest.raises(SourceFetchError, match="источник недоступен"):
        with bootstrap.open_importer(configured_settings("postgresql+psycopg://unused")) as importer:
            importer.execute()

    assert events == ["client:close", "engine:dispose"]

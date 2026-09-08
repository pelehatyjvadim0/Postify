from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from postify.domain.projects.models import ProjectConfiguration
from postify.infrastructure.database.models import ContentFormatModel
from postify.infrastructure.repositories.sqlalchemy_projects import SqlAlchemyProjectRepository


pytestmark = pytest.mark.integration


def test_persisted_runtime_brief_has_no_cta_and_preserves_editorial_fields(migrated_database_url: str) -> None:
    engine = create_engine(migrated_database_url)
    repository = SqlAlchemyProjectRepository(sessionmaker(engine, expire_on_commit=False))
    now = datetime(2026, 9, 5, tzinfo=UTC)
    configuration = ProjectConfiguration(
        media_max_bytes=10_000_000,
        analysis_timeout_seconds=60,
        analysis_batch_size=12,
        analysis_model="gpt-5.6-terra",
        analysis_reasoning_effort="medium",
        source_language="ar",
        tone="Кратко, спокойно",
    )
    try:
        project = repository.replace_default(
            name="Тестовый проект",
            topic="Тема",
            language="ru",
            audience="Аудитория",
            timezone="Europe/Moscow",
            configuration=configuration,
            now=now,
        )
        with repository._session_factory() as session:
            session.add(ContentFormatModel(project_id=1, name="Короткий пост", kind="text", instructions="До 500 знаков", enabled=True, created_at=now, updated_at=now))
            session.commit()
        effective = repository.runtime_graph(1).effective_generation()
    finally:
        engine.dispose()

    assert effective.brief.source_language == "ar"
    assert effective.brief.tone == "Кратко, спокойно"
    assert "cta" not in effective.snapshot

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from postify.domain.candidates.models import Candidate
from postify.domain.content.models import AnalyzedTopic, BatchAnalysis, ExtractedArticle
from postify.infrastructure.repositories.sqlalchemy_candidates import SqlAlchemyCandidateRepository
from postify.infrastructure.repositories.sqlalchemy_content import SqlAlchemyContentRepository

pytestmark = pytest.mark.integration
NOW = datetime(2026, 9, 5, tzinfo=UTC)


def test_text_material_is_deduplicated_claimed_once_and_requires_editor_review(migrated_database_url):
    engine = create_engine(migrated_database_url)
    sf = sessionmaker(engine)
    candidate = Candidate("telegram_group", "group:17", "خبر", "", NOW, {}, source_text="هذا نص عربي كامل", published_at=NOW)
    try:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO channel_connections(id,project_id,provider,name,enabled,configuration,connection_status,created_at,updated_at) VALUES (401,1,'telegram','Канал',true,'{}'::jsonb,'configured',:now,:now)"), {"now": NOW})
            connection.execute(text("INSERT INTO content_formats(id,project_id,name,kind,instructions,enabled,created_at,updated_at) VALUES (401,1,'Тестовый пост','text','Текст',true,:now,:now)"), {"now": NOW})
            connection.execute(text("INSERT INTO publication_routes(id,project_id,channel_id,format_id,enabled,created_at,updated_at) VALUES (401,1,401,401,true,:now,:now)"), {"now": NOW})
        importer = SqlAlchemyCandidateRepository(sf)
        assert importer.save_new([candidate]) == 1
        assert importer.save_new([candidate]) == 0
        repository = SqlAlchemyContentRepository(sf)
        claimed = repository.claim(now=NOW, batch_size=10)
        assert [(item.source_url, item.source_text) for item in claimed] == [("", candidate.source_text)]
        assert repository.claim(now=NOW, batch_size=10) == ()
        article = ExtractedArticle("", candidate.title, candidate.source_text, ())
        topic = AnalyzedTopic(claimed[0].id, "Русский перевод", 100, "Русский текст новости", None)
        drafts = repository.save_analysis_and_create_packages(BatchAnalysis((topic,), (claimed[0].id,), 1), articles={claimed[0].id: article}, now=NOW)
        repository.complete_package(drafts[0].package_id, media=None, status="awaiting_review", now=NOW)
        package = repository.get_package(drafts[0].package_id)
        assert package.status == "awaiting_review"
        repository.save_plan(package.id, scheduled_at=NOW + timedelta(hours=1), route_id=401, now=NOW)
        assert repository.approve(package.id, now=NOW).status == "approved"
    finally:
        engine.dispose()

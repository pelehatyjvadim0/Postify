from datetime import timedelta

import pytest
from sqlalchemy import text

from postify.application.content.manual_operations import ManualContentOperations
from postify.domain.content.models import AnalyzedTopic, BatchAnalysis, ExtractedArticle, InvalidContentTransition
from tests.integration.infrastructure.test_mvp_plan_delivery import graph, review, delivery
from tests.integration.infrastructure.test_sqlalchemy_delivery import NOW, _seed_package

pytestmark = pytest.mark.integration


def original_and_context(engine):
    repository = review(engine)
    original = _seed_package(engine, status="awaiting_review")
    repository.save_plan(original, scheduled_at=NOW + timedelta(hours=1), route_id=401, now=NOW)
    context = ManualContentOperations(repository).regenerate_post(original)
    return repository, original, context


def generate(repository, context):
    attempt = repository.claim(now=NOW, batch_size=1, context=context)[0]
    article = ExtractedArticle(attempt.source_url, "Материал", "Исходный текст", ())
    batch = BatchAnalysis((AnalyzedTopic(attempt.id, "Анализ", 100, "Новая версия", None),), (attempt.id,), 1)
    draft = repository.save_analysis_and_create_packages(batch, articles={attempt.id: article}, now=NOW, context=context)[0]
    repository.complete_package(draft.package_id, media=None, status="awaiting_review", now=NOW)
    return draft.package_id


def test_stale_tab_cannot_approve_previous_version(graph):
    repository, original, context = original_and_context(graph)
    replacement = generate(repository, context)
    with pytest.raises(InvalidContentTransition):
        repository.approve(original, now=NOW)
    assert repository.get_package(original).status == "awaiting_review"
    assert repository.approve(replacement, now=NOW).status == "approved"
    reserved = delivery(graph).reserve_next(now=NOW + timedelta(hours=1))
    assert reserved.package_id == replacement


def test_approval_cannot_overtake_in_flight_regeneration(graph):
    repository, original, context = original_and_context(graph)
    attempt = repository.claim(now=NOW, batch_size=1, context=context)[0]
    with pytest.raises(InvalidContentTransition):
        repository.approve(original, now=NOW)
    assert repository.attempt_status(attempt.id) == "processing"
    assert repository.get_package(original).status == "awaiting_review"


def test_stale_regeneration_command_cannot_create_a_sibling_version(graph):
    repository, original, context = original_and_context(graph)
    replacement = generate(repository, context)
    repository.claim(now=NOW, batch_size=1, context=context)
    with graph.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM content_attempts")).scalar_one() == 2
    assert repository.get_package(replacement).previous_package_id == original


def test_preexisting_approved_previous_version_is_not_reserved(graph):
    repository, original, context = original_and_context(graph)
    replacement = generate(repository, context)
    # Represents an old approval created through the former stale-tab bug.
    with graph.begin() as connection:
        connection.execute(text("UPDATE content_packages SET status='approved' WHERE id=:id"), {"id": original})
    repository.approve(replacement, now=NOW)
    reserved = delivery(graph).reserve_next(now=NOW + timedelta(hours=1))
    assert reserved.package_id == replacement

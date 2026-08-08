from __future__ import annotations

from datetime import UTC, datetime

import pytest


NOW = datetime(2026, 8, 8, 9, tzinfo=UTC)


def _models_api():
    from postify.domain.content.models import (
        AnalysisInput,
        AnalyzedTopic,
        BatchAnalysis,
        ContentAttempt,
        ContentPackage,
        ContentValidationError,
        ExtractedArticle,
        PackageStatus,
        validate_transition,
    )

    return {
        "AnalysisInput": AnalysisInput,
        "AnalyzedTopic": AnalyzedTopic,
        "BatchAnalysis": BatchAnalysis,
        "ContentAttempt": ContentAttempt,
        "ContentPackage": ContentPackage,
        "ContentValidationError": ContentValidationError,
        "ExtractedArticle": ExtractedArticle,
        "PackageStatus": PackageStatus,
        "validate_transition": validate_transition,
    }


def test_extracted_article_requires_body_beyond_title_and_snippet() -> None:
    # Поломка (gate 4): article body пуст, а AI получает лишь HN-поля.
    api = _models_api()

    with pytest.raises(api["ContentValidationError"]):
        api["ExtractedArticle"](
            source_url="https://source.test/post",
            title="HN title",
            text="   ",
            image_candidates=(),
        )


@pytest.mark.parametrize("attempt_no", [0, 3])
def test_attempt_allows_only_first_or_single_retry_attempt(attempt_no: int) -> None:
    # Поломка (gate 5): появляется нулевая или бесконечная попытка.
    api = _models_api()

    with pytest.raises(api["ContentValidationError"]):
        api["ContentAttempt"](
            id=1,
            candidate_id=7,
            attempt_no=attempt_no,
            tier="fresh",
            status="processing",
            source_url="https://source.test/post",
            started_at=NOW,
        )


def test_batch_rejects_duplicate_or_unknown_attempt_ids() -> None:
    # Поломка (gate 3/10): AI может создать два пакета или пакет для чужой темы.
    api = _models_api()
    topic = api["AnalyzedTopic"](
        attempt_id=1,
        analysis="Полезный анализ",
        usefulness=90,
        post_text="Текст поста",
        media_query="PostgreSQL",
    )

    with pytest.raises(api["ContentValidationError"]):
        api["BatchAnalysis"](topics=(topic, topic), requested_attempt_ids=(1, 2), package_limit=2)

    foreign = api["AnalyzedTopic"](
        attempt_id=99,
        analysis="Анализ",
        usefulness=80,
        post_text="Пост",
        media_query="database",
    )
    with pytest.raises(api["ContentValidationError"]):
        api["BatchAnalysis"](topics=(foreign,), requested_attempt_ids=(1, 2), package_limit=2)


def test_batch_enforces_package_limit_and_usefulness_range() -> None:
    # Поломка (gate 1): AI-ответ обходит лимит или шкалу оценки.
    api = _models_api()
    with pytest.raises(api["ContentValidationError"]):
        api["AnalyzedTopic"](
            attempt_id=1,
            analysis="Анализ",
            usefulness=101,
            post_text="Пост",
            media_query="database",
        )

    valid_topics = tuple(
        api["AnalyzedTopic"](
            attempt_id=index,
            analysis=f"Анализ {index}",
            usefulness=80,
            post_text=f"Пост {index}",
            media_query="database",
        )
        for index in (1, 2)
    )
    with pytest.raises(api["ContentValidationError"]):
        api["BatchAnalysis"](
            topics=valid_topics,
            requested_attempt_ids=(1, 2),
            package_limit=1,
        )


def test_analyzed_topic_requires_russian_analysis_and_post() -> None:
    # Поломка: Codex batch принимает англоязычный результат для русскоязычной аудитории.
    api = _models_api()

    with pytest.raises(api["ContentValidationError"]):
        api["AnalyzedTopic"](
            attempt_id=1,
            analysis="Only English analysis",
            usefulness=80,
            post_text="Only English post",
            media_query="database",
        )


def test_post_text_must_not_contain_source_url() -> None:
    # Поломка (gate 7): source URL попадает в будущий Telegram-пост.
    api = _models_api()
    source_url = "https://source.test/private-article"

    with pytest.raises(api["ContentValidationError"]):
        api["ContentPackage"](
            id=1,
            attempt_id=1,
            source_url=source_url,
            context="Полный контекст",
            analysis="Анализ",
            post_text=f"Читайте {source_url}",
            media_path="/var/lib/postify/media/one.jpg",
            media_source_type="og",
            media_source_url="https://cdn.test/one.jpg",
            review_required=True,
            status=api["PackageStatus"].AWAITING_REVIEW,
        )


@pytest.mark.parametrize(
    ("current", "target", "allowed"),
    [
        ("not_started", "processing", True),
        ("processing", "awaiting_review", True),
        ("processing", "approved", True),
        ("awaiting_review", "approved", True),
        ("awaiting_review", "rejected", True),
        ("approved", "rejected", False),
        ("rejected", "approved", False),
        ("failed", "processing", False),
    ],
)
def test_package_transition_matrix_is_closed(current: str, target: str, allowed: bool) -> None:
    # Поломка (gate 6): terminal/review статус обходится прямым переходом.
    api = _models_api()

    if allowed:
        assert api["validate_transition"](current, target) is None
    else:
        with pytest.raises(api["ContentValidationError"]):
            api["validate_transition"](current, target)

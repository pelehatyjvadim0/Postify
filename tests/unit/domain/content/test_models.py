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
        ExecutionActor,
        ExecutionContext,
        ExecutionMode,
        ExecutionPurpose,
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
        "ExecutionActor": ExecutionActor,
        "ExecutionContext": ExecutionContext,
        "ExecutionMode": ExecutionMode,
        "ExecutionPurpose": ExecutionPurpose,
        "ContentValidationError": ContentValidationError,
        "ExtractedArticle": ExtractedArticle,
        "PackageStatus": PackageStatus,
        "validate_transition": validate_transition,
    }


def test_manual_execution_context_has_server_owned_target_and_rejects_mixed_targets() -> None:
    api = _models_api()
    context = api["ExecutionContext"](
        mode="manual",
        actor="ui",
        purpose="retry_analysis",
        batch_size=1,
        target_attempt_id=17,
    )

    assert context.is_manual
    assert context.mode is api["ExecutionMode"].MANUAL
    assert context.actor is api["ExecutionActor"].UI
    assert context.purpose is api["ExecutionPurpose"].RETRY_ANALYSIS
    assert context.target_attempt_id == 17
    with pytest.raises(api["ContentValidationError"]):
        api["ExecutionContext"](
            mode="manual",
            actor="ui",
            purpose="retry_analysis",
            target_attempt_id=17,
            target_package_id=9,
        )


def test_execution_context_enforces_operation_specific_server_policy() -> None:
    api = _models_api()

    with pytest.raises(api["ContentValidationError"]):
        api["ExecutionContext"](
            mode="manual", actor="ui", purpose="retry_analysis", batch_size=2,
            target_attempt_id=7,
        )
    with pytest.raises(api["ContentValidationError"]):
        api["ExecutionContext"](
            mode="automatic", actor="scheduler", purpose="retry_analysis",
            batch_size=1, target_attempt_id=7,
        )


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


@pytest.mark.parametrize("attempt_no", [0, -1])
def test_attempt_requires_positive_append_only_number(attempt_no: int) -> None:
    # Break caught: an invalid zero/negative attempt number enters append-only history.
    api = _models_api()

    with pytest.raises(api["ContentValidationError"]):
        api["ContentAttempt"](
            id=1,
            candidate_id=7,
            attempt_no=attempt_no,
            status="processing",
            source_url="https://source.test/post",
            started_at=NOW,
        )


def test_attempt_allows_manual_history_beyond_automatic_retry_limit() -> None:
    api = _models_api()

    attempt = api["ContentAttempt"](
        id=1, candidate_id=7, attempt_no=3, status="processing",
        source_url="https://source.test/post", started_at=NOW,
    )

    assert attempt.attempt_no == 3


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
            status=api["PackageStatus"].AWAITING_REVIEW,
        )


def test_stored_post_can_preserve_an_allowed_source_link() -> None:
    api = _models_api()
    source_url = "https://source.test/article"

    package = api["ContentPackage"](
        id=1,
        attempt_id=1,
        source_url=source_url,
        context="Полный контекст",
        analysis="Анализ",
        post_text=f"Читайте {source_url}",
        media_path="/var/lib/postify/media/one.jpg",
        media_source_type="og",
        media_source_url="https://cdn.test/one.jpg",
        status=api["PackageStatus"].AWAITING_REVIEW,
        source_url_allowed=True,
    )

    assert package.source_url_allowed is True


@pytest.mark.parametrize(
    ("current", "target", "allowed"),
    [
        ("not_started", "processing", True),
        ("processing", "awaiting_review", True),
        ("processing", "approved", False),
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


def test_batch_requires_one_analysis_result_for_every_requested_attempt() -> None:
    # Поломка re-review 8: успешно извлечённая статья исчезает из AI outcome.
    api = _models_api()
    only_one = api["AnalyzedTopic"](
        attempt_id=1,
        analysis="Полный анализ первой статьи",
        usefulness=80,
        post_text="Пост первой статьи",
        media_query="database",
        selected=True,
    )

    with pytest.raises(api["ContentValidationError"]):
        api["BatchAnalysis"](
            topics=(only_one,),
            requested_attempt_ids=(1, 2),
            package_limit=1,
        )


@pytest.mark.parametrize(
    ("post_text", "media_query"),
    [(None, "database"), ("", None), ("Русский пост", "")],
)
def test_selected_analysis_requires_post_and_valid_optional_media_query(
    post_text: str | None, media_query: str | None
) -> None:
    # Выбранный материал обязан содержать текст; заданный запрос медиа не бывает пустым.
    api = _models_api()

    with pytest.raises(api["ContentValidationError"]):
        api["AnalyzedTopic"](
            attempt_id=1,
            analysis="Полный анализ",
            usefulness=80,
            selected=True,
            post_text=post_text,
            media_query=media_query,
        )


@pytest.mark.parametrize("selected", [0, 1])
def test_analyzed_topic_rejects_integer_selected(selected: int) -> None:
    # Поломка fix-round 2: int принимается как bool.
    api = _models_api()

    with pytest.raises(api["ContentValidationError"]):
        api["AnalyzedTopic"](
            attempt_id=1,
            analysis="Полный русский анализ",
            usefulness=80,
            selected=selected,
            post_text="Русский пост" if selected else None,
            media_query="database" if selected else None,
        )


def test_nonselected_analysis_keeps_analysis_without_package_fields() -> None:
    # Поломка re-review 8: nonselected article теряет анализ или требует фиктивный пост/media.
    api = _models_api()
    selected = api["AnalyzedTopic"](
        attempt_id=1,
        analysis="Выбранный анализ",
        usefulness=90,
        selected=True,
        post_text="Русский пост",
        media_query="database",
    )
    nonselected = api["AnalyzedTopic"](
        attempt_id=2,
        analysis="Сохранённый анализ невыбранной статьи",
        usefulness=40,
        selected=False,
        post_text=None,
        media_query=None,
    )

    batch = api["BatchAnalysis"](
        topics=(selected, nonselected),
        requested_attempt_ids=(1, 2),
        package_limit=1,
    )

    assert batch.topics == (selected, nonselected)
    assert batch.requested_attempt_ids == (1, 2)
    assert batch.selected_topics == (selected,)
    assert batch.topics[1].analysis == "Сохранённый анализ невыбранной статьи"

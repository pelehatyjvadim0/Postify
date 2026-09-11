from datetime import UTC, datetime

import pytest

from postify.domain.posts.models import (
    ALLOWED_TRANSITIONS,
    InvalidPostTransition,
    Post,
    PostStatus,
    StoredMedia,
    TEXT_LIMIT,
    TEXT_LIMIT_WITH_MEDIA,
    text_length,
    validate_text,
    validate_transition,
)


def test_generation_leads_either_to_review_or_failure():
    validate_transition("generating", "needs_review")
    validate_transition("generating", "failed")
    with pytest.raises(InvalidPostTransition):
        validate_transition("generating", "approved")


def test_editor_decisions_follow_review():
    validate_transition("needs_review", "approved")
    validate_transition("needs_review", "rejected")
    with pytest.raises(InvalidPostTransition):
        validate_transition("needs_review", "published")


def test_approved_post_returns_to_review_after_edit():
    validate_transition("approved", "needs_review")


def test_publication_is_reachable_only_from_approved():
    validate_transition("approved", "published")
    for status in ("needs_review", "rejected", "failed", "generating"):
        with pytest.raises(InvalidPostTransition):
            validate_transition(status, "published")


def test_terminal_statuses_have_no_outgoing_transitions():
    outgoing = {str(current) for current, _ in ALLOWED_TRANSITIONS}
    assert PostStatus.PUBLISHED not in outgoing
    assert PostStatus.REJECTED not in outgoing
    assert PostStatus.FAILED not in outgoing


def test_unknown_status_is_rejected():
    with pytest.raises(InvalidPostTransition):
        validate_transition("processing", "needs_review")


def test_length_counts_utf16_units_like_telegram():
    # Эмодзи вне BMP занимает две единицы UTF-16 — Telegram считает так же.
    assert text_length("🌾") == 2
    assert text_length("зерно") == 5


def test_media_shrinks_the_text_limit_to_the_caption_size():
    validate_text("а" * TEXT_LIMIT_WITH_MEDIA, with_media=True)
    with pytest.raises(InvalidPostTransition):
        validate_text("а" * (TEXT_LIMIT_WITH_MEDIA + 1), with_media=True)
    validate_text("а" * TEXT_LIMIT, with_media=False)
    with pytest.raises(InvalidPostTransition):
        validate_text("а" * (TEXT_LIMIT + 1), with_media=False)


def test_blank_text_is_not_publishable():
    with pytest.raises(InvalidPostTransition):
        validate_text("   \n\t ", with_media=False)


def test_post_reports_its_length_for_the_editor():
    post = Post(
        id=1,
        project_id=3,
        post_text="Хранение зерна 🌾",
        media_path=None,
        media_mime=None,
        status=PostStatus.NEEDS_REVIEW,
        created_at=datetime(2026, 10, 9, tzinfo=UTC),
        updated_at=datetime(2026, 10, 9, tzinfo=UTC),
    )
    assert post.char_count == text_length(post.post_text)


def test_stored_media_keeps_path_and_mime_together():
    media = StoredMedia("/data/media/42.jpg", "image/jpeg")
    assert (media.local_path, media.mime) == ("/data/media/42.jpg", "image/jpeg")

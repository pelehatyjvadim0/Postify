from __future__ import annotations

import pytest


def _delivery_api():
    from postify.domain.delivery.models import (
        DeliveryClaim,
        DeliveryStatus,
        PublishContentResult,
        PublishFailureKind,
        TelegramMessage,
        TelegramPublishError,
    )

    return {
        "DeliveryClaim": DeliveryClaim,
        "DeliveryStatus": DeliveryStatus,
        "PublishContentResult": PublishContentResult,
        "PublishFailureKind": PublishFailureKind,
        "TelegramMessage": TelegramMessage,
        "TelegramPublishError": TelegramPublishError,
    }


def test_delivery_types_preserve_the_complete_public_contract() -> None:
    # Поломка: action/adapter расходятся в статусах или полях claim/result.
    api = _delivery_api()
    claim = api["DeliveryClaim"](
        delivery_id=11,
        post_id=41,
        attempt_no=2,
        post_text="Текст поста",
        media_path="/media/41.png",
        media_mime="image/png",
    )

    assert tuple(item.value for item in api["DeliveryStatus"]) == (
        "sending",
        "retryable",
        "published",
        "failed",
        "uncertain",
    )
    assert tuple(item.value for item in api["PublishFailureKind"]) == (
        "retryable",
        "failed",
        "uncertain",
    )
    assert claim.delivery_id == 11
    assert claim.post_id == 41
    assert claim.attempt_no == 2
    assert api["TelegramMessage"](message_id=731).message_id == 731
    assert api["PublishContentResult"](
        "published", post_id=41, message_id=731
    ) == api["PublishContentResult"](
        outcome="published", post_id=41, message_id=731
    )


@pytest.mark.parametrize(("code", "reason"), [("", "safe"), ("safe", "   ")])
def test_publish_error_rejects_empty_operator_safe_fields(code: str, reason: str) -> None:
    # Поломка: в журнал попадает пустая необъяснимая причина.
    api = _delivery_api()

    with pytest.raises(ValueError):
        api["TelegramPublishError"](
            code=code,
            reason=reason,
            kind=api["PublishFailureKind"].FAILED,
        )


def test_approved_post_has_only_the_published_terminal_transition() -> None:
    # Поломка: approved можно вернуть в rejected/generating или нельзя подтвердить.
    from postify.domain.posts.models import (
        InvalidPostTransition,
        PostStatus,
        validate_transition,
    )

    assert PostStatus.PUBLISHED.value == "published"
    assert validate_transition("approved", "published") is None
    for forbidden in ("generating", "rejected", "approved"):
        with pytest.raises(InvalidPostTransition):
            validate_transition("approved", forbidden)

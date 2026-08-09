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
        package_id=41,
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
    assert claim.package_id == 41
    assert claim.attempt_no == 2
    assert api["TelegramMessage"](message_id=731).message_id == 731
    assert api["PublishContentResult"](
        "published", package_id=41, message_id=731
    ) == api["PublishContentResult"](
        outcome="published", package_id=41, message_id=731
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


def test_approved_package_has_only_the_published_terminal_transition() -> None:
    # Поломка: approved можно вернуть в review/rejected или нельзя подтвердить.
    from postify.domain.content.models import (
        ContentValidationError,
        PackageStatus,
        validate_transition,
    )

    assert PackageStatus.PUBLISHED.value == "published"
    assert validate_transition("approved", "published") is None
    for forbidden in ("processing", "awaiting_review", "rejected", "failed"):
        with pytest.raises(ContentValidationError):
            validate_transition("approved", forbidden)

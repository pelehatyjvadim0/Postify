from __future__ import annotations

import pytest

from postify.application.delivery.publication_mode import generated_post_status


@pytest.mark.parametrize(
    ("mode", "validation_passed", "expected"),
    [
        ("review", True, "needs_review"),
        ("review", False, "needs_review"),
        ("auto", True, "approved"),
        ("auto", False, "needs_review"),
    ],
)
def test_generated_post_status_fixes_mode_decision_at_generation(
    mode: str, validation_passed: bool, expected: str
) -> None:
    assert (
        generated_post_status(mode, validation_passed=validation_passed) == expected
    )


def test_unknown_publication_mode_is_rejected() -> None:
    with pytest.raises(ValueError, match="режим"):
        generated_post_status("unknown", validation_passed=True)


def test_non_boolean_validation_result_is_rejected() -> None:
    with pytest.raises(ValueError, match="boolean"):
        generated_post_status("auto", validation_passed=1)  # type: ignore[arg-type]

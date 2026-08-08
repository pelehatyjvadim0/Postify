from __future__ import annotations

from inspect import Signature, signature
from typing import get_type_hints
from types import SimpleNamespace

import httpx

import pytest


@pytest.mark.parametrize(
    ("module_name", "protocol_name", "required_methods"),
    [
        (
            "postify.application.ports.article_extractor",
            "ArticleExtractor",
            {"extract"},
        ),
        (
            "postify.application.ports.content_analyzer",
            "ContentAnalyzer",
            {"analyze"},
        ),
        (
            "postify.application.ports.content_repository",
            "ContentRepository",
            {
                "claim",
                "schedule_article_retry",
                "fail_attempt",
                "save_extracted",
                "save_analysis_and_create_packages",
                "complete_package",
                "fail_package",
                "active_media_paths",
                "list_packages",
                "get_package",
                "approve",
                "reject",
            },
        ),
        (
            "postify.application.ports.media_provider",
            "MediaProvider",
            {"acquire", "delete", "cleanup"},
        ),
    ],
)
def test_content_application_port_is_public_protocol_with_planned_capabilities(
    module_name: str, protocol_name: str, required_methods: set[str]
) -> None:
    # Поломка re-review 5: action зависит от concrete adapter/repository без public port.
    module = __import__(module_name, fromlist=[protocol_name])
    protocol = getattr(module, protocol_name)

    assert protocol.__module__ == module_name
    assert protocol.__dict__.get("_is_protocol") is True
    assert required_methods <= set(protocol.__dict__)
    for method_name in required_methods:
        method_signature = signature(getattr(protocol, method_name))
        assert method_signature.return_annotation is not Signature.empty
        assert all(
            parameter.annotation is not Signature.empty
            for name, parameter in method_signature.parameters.items()
            if name != "self"
        )


def test_process_content_constructor_is_annotated_only_with_content_ports() -> None:
    # Поломка re-review 5: ProcessContent dependencies не выражают architecture boundary.
    from postify.application.content.process_content import ProcessContent
    from postify.application.ports.article_extractor import ArticleExtractor
    from postify.application.ports.content_analyzer import ContentAnalyzer
    from postify.application.ports.content_repository import ContentRepository
    from postify.application.ports.media_provider import MediaProvider

    hints = get_type_hints(ProcessContent.__init__)

    assert hints["repository"] is ContentRepository
    assert hints["extractor"] is ArticleExtractor
    assert hints["analyzer"] is ContentAnalyzer
    assert hints["media"] is MediaProvider


def test_review_content_constructor_is_annotated_only_with_content_ports() -> None:
    # Поломка re-review 5: ReviewContent скрывает repository/filesystem contracts.
    from postify.application.content.review_content import ReviewContent
    from postify.application.ports.content_repository import ContentRepository
    from postify.application.ports.media_provider import MediaProvider

    hints = get_type_hints(ReviewContent.__init__)

    assert hints["repository"] is ContentRepository
    assert hints["media"] is MediaProvider


def test_bootstrap_injects_same_public_url_policy_into_article_and_media(
    tmp_path,
) -> None:
    # Поломка re-review 1/5: один adapter обходит общую подменяемую SSRF policy.
    from postify.adapters.http.public_url_policy import PublicHttpUrlPolicy
    from postify.bootstrap import _content_processor

    settings = SimpleNamespace(
        content_article_max_bytes=1000,
        content_codex_timeout_seconds=60,
        content_media_dir=tmp_path / "media",
        content_media_max_bytes=1000,
        content_daily_analysis_limit=12,
        content_daily_package_limit=3,
        content_priority_freshness_days=14,
        content_fresh_share_percent=90,
        content_reserve_share_percent=10,
        content_review_required=True,
        postify_timezone="UTC",
    )
    resources = SimpleNamespace(session_factory=lambda: None)
    with httpx.Client(transport=httpx.MockTransport(lambda request: None)) as client:
        resources.client = client
        processor = _content_processor(settings, resources)

    assert isinstance(processor.e.url_policy, PublicHttpUrlPolicy)
    assert processor.e.url_policy is processor.m.url_policy
    assert not processor.a.work.resolve().is_relative_to(
        settings.content_media_dir.resolve()
    )

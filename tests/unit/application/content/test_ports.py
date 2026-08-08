from __future__ import annotations

from collections.abc import Sequence
from inspect import Signature, signature
from types import SimpleNamespace
from typing import get_type_hints

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


def test_content_repository_returns_fully_typed_package_drafts() -> None:
    # Поломка fix-round 1: public port возвращает Sequence[object].
    from postify.application.ports.content_repository import (
        ContentRepository,
        PackageDraft,
    )
    from postify.domain.content.models import ExtractedArticle

    method_hints = get_type_hints(
        ContentRepository.save_analysis_and_create_packages
    )
    draft_hints = get_type_hints(PackageDraft)

    assert method_hints["return"] == Sequence[PackageDraft]
    assert draft_hints == {
        "attempt_id": int,
        "package_id": int,
        "article": ExtractedArticle,
        "media_query": str,
    }
    assert object not in draft_hints.values()


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


def test_bootstrap_public_transport_and_adapters_share_one_dns_policy(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Поломка fix-round 1: pinned backend существует, но production client его не использует.
    from postify.adapters.http.public_url_policy import (
        PublicHttpTransport,
        PublicNetworkBackend,
    )
    import postify.bootstrap as bootstrap

    class DisposableEngine:
        def __init__(self) -> None:
            self.disposed = False

        def dispose(self) -> None:
            self.disposed = True

    engine = DisposableEngine()
    monkeypatch.setattr(bootstrap, "create_engine_from_settings", lambda settings: engine)
    settings = SimpleNamespace(
        hn_algolia_url="https://hn.algolia.com/api/v1/search",
        hn_query="database",
        hn_tags="story",
        hn_hits_per_page=10,
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

    with bootstrap._open_import_resources(settings) as resources:
        processor = bootstrap._content_processor(settings, resources)
        transport = resources.client._transport

        assert isinstance(transport, PublicHttpTransport)
        assert isinstance(transport.network_backend, PublicNetworkBackend)
        assert transport.network_backend.policy is processor.e.url_policy
        assert processor.e.url_policy is processor.m.url_policy

    assert engine.disposed is True


@pytest.mark.parametrize(
    "collision",
    ["repository", "media"],
)
def test_bootstrap_keeps_codex_work_outside_repository_and_media_on_temp_collision(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    collision: str,
) -> None:
    # Поломка fix-round 1: temp-root вкладывает Codex work в repository/media.
    import postify.bootstrap as bootstrap

    repository = tmp_path / "operator-secret-repository"
    media = tmp_path / "operator-secret-media"
    repository.mkdir()
    media.mkdir()
    monkeypatch.chdir(repository)
    temp_root = repository if collision == "repository" else media
    monkeypatch.setattr(bootstrap.tempfile, "gettempdir", lambda: str(temp_root))
    runner_calls: list[object] = []

    def forbidden_runner(*args: object, **kwargs: object) -> None:
        runner_calls.append((args, kwargs))
        raise AssertionError("runner нельзя вызывать до проверки work root")

    monkeypatch.setattr(bootstrap.subprocess, "run", forbidden_runner)
    settings = SimpleNamespace(
        content_article_max_bytes=1000,
        content_codex_timeout_seconds=60,
        content_media_dir=media,
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

    try:
        with httpx.Client(
            transport=httpx.MockTransport(lambda request: None)
        ) as client:
            resources.client = client
            processor = bootstrap._content_processor(settings, resources)
    except (RuntimeError, ValueError) as error:
        assert runner_calls == []
        assert str(repository) not in str(error)
        assert str(media) not in str(error)
        return

    work = processor.a.work.resolve()
    assert runner_calls == []
    assert not work.is_relative_to(repository.resolve())
    assert not work.is_relative_to(media.resolve())
    assert not repository.resolve().is_relative_to(work)
    assert not media.resolve().is_relative_to(work)


@pytest.mark.parametrize("protected", ["repository", "media"])
def test_bootstrap_rejects_codex_work_candidate_that_contains_protected_path(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    protected: str,
) -> None:
    # Поломка fix-round 2: candidate-ancestor проходит one-way check.
    import postify.bootstrap as bootstrap

    temp_root = tmp_path / "temp-root"
    unsafe_candidate = temp_root / "postify-codex"
    repository = (
        unsafe_candidate / "repository"
        if protected == "repository"
        else tmp_path / "repository"
    )
    media = (
        unsafe_candidate / "media" if protected == "media" else tmp_path / "media"
    )
    repository.mkdir(parents=True)
    media.mkdir(parents=True)
    monkeypatch.setattr(bootstrap.tempfile, "gettempdir", lambda: str(temp_root))

    try:
        work = bootstrap._codex_work_dir(repository, media).resolve()
    except (RuntimeError, ValueError) as error:
        assert str(repository) not in str(error)
        assert str(media) not in str(error)
        return

    repository = repository.resolve()
    media = media.resolve()
    assert not work.is_relative_to(repository)
    assert not work.is_relative_to(media)
    assert not repository.is_relative_to(work)
    assert not media.is_relative_to(work)

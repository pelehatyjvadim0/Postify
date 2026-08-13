from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest


NOW = datetime(2026, 8, 8, 9, tzinfo=UTC)


def _api():
    from postify.application.content.process_content import ProcessContent
    from postify.adapters.articles.http_article_extractor import ArticleExtractionError
    from postify.adapters.ai.codex_content_analyzer import CodexAnalysisError
    from postify.adapters.media.local_media_provider import MediaAcquireError
    from postify.domain.content.models import (
        AnalyzedTopic,
        BatchAnalysis,
        ContentLimits,
        ExtractedArticle,
        StoredMedia,
    )

    return SimpleNamespace(
        ProcessContent=ProcessContent,
        ArticleExtractionError=ArticleExtractionError,
        CodexAnalysisError=CodexAnalysisError,
        MediaAcquireError=MediaAcquireError,
        AnalyzedTopic=AnalyzedTopic,
        BatchAnalysis=BatchAnalysis,
        ContentLimits=ContentLimits,
        ExtractedArticle=ExtractedArticle,
        StoredMedia=StoredMedia,
    )


class FakeRepository:
    def __init__(self, attempts: list[object]) -> None:
        self.attempts = attempts
        self.events: list[tuple[object, ...]] = []
        self.package_usage = 0
        self.protected = {"/media/active.jpg"}

    def active_media_paths(self) -> set[str]:
        self.events.append(("active_media_paths",))
        return set(self.protected)

    def claim(self, *, now: datetime, day: date, limits: object):
        self.events.append(("claim", now, day, limits))
        return tuple(self.attempts)

    def package_slots_remaining(self, *, day: date, limit: int) -> int:
        self.events.append(("package_slots", day, limit))
        return limit - self.package_usage

    def save_extracted(self, attempt_id: int, article: object) -> None:
        self.events.append(("save_extracted", attempt_id, article))

    def schedule_article_retry(
        self, attempt_id: int, *, retry_at: datetime, now: datetime
    ) -> None:
        self.events.append(("retry", attempt_id, retry_at, now))

    def fail_attempt(self, attempt_id: int, *, code: object, now: datetime) -> None:
        self.events.append(("fail_attempt", attempt_id, str(code), now))

    def save_analysis_and_create_packages(
        self,
        batch: object,
        *,
        articles: dict[int, object],
        review_required: bool,
        generation_snapshot: dict[str, object] | None = None,
        now: datetime,
        day: date,
        package_limit: int,
    ):
        self.events.append(
            (
                "drafts",
                batch,
                dict(articles),
                review_required,
                generation_snapshot,
                now,
                day,
                package_limit,
            )
        )
        return tuple(
            SimpleNamespace(attempt_id=topic.attempt_id, package_id=100 + topic.attempt_id,
                            article=articles[topic.attempt_id], media_query=topic.media_query)
            for topic in batch.topics
            if getattr(topic, "selected", True)
        )

    def complete_package(self, package_id: int, *, media: object, status: str, now: datetime):
        self.events.append(("complete", package_id, media, status, now))

    def fail_package(self, package_id: int, *, code: object, now: datetime) -> None:
        self.events.append(("fail_package", package_id, str(code), now))


class FakeExtractor:
    def __init__(self, outcomes: dict[str, object]) -> None:
        self.outcomes = outcomes
        self.urls: list[str] = []

    def extract(self, url: str):
        self.urls.append(url)
        outcome = self.outcomes[url]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeAnalyzer:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.calls: list[tuple[object, int]] = []
        self.briefs: list[object | None] = []

    def analyze(self, articles: object, package_limit: int, brief=None):
        materialized = tuple(articles)
        self.calls.append((materialized, package_limit))
        self.briefs.append(brief)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class FakeMedia:
    def __init__(self, outcome: object) -> None:
        self.outcome = outcome
        self.events: list[tuple[object, ...]] = []

    def cleanup(self, *, older_than: datetime, protected_paths: set[str]) -> int:
        self.events.append(("cleanup", older_than, protected_paths))
        return 0

    def acquire(self, article: object, query: str):
        self.events.append(("acquire", article, query))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _attempt(identifier: int, attempt_no: int = 1):
    return SimpleNamespace(
        id=identifier,
        candidate_id=identifier,
        attempt_no=attempt_no,
        source_url=f"https://source.test/{identifier}",
        title=f"HN title {identifier}",
        snippet=f"HN snippet {identifier}",
    )


def _article(api, identifier: int):
    return api.ExtractedArticle(
        source_url=f"https://source.test/{identifier}",
        title=f"Article {identifier}",
        text=f"ARTICLE-BODY-{identifier} complete practical context that came from the source.",
        image_candidates=(("og", f"https://cdn.test/{identifier}.jpg"),),
    )


def _batch(api, identifiers: tuple[int, ...]):
    topics = tuple(
        api.AnalyzedTopic(
            attempt_id=identifier,
            analysis=f"Анализ {identifier}",
            usefulness=90,
            post_text=f"Пост {identifier}",
            media_query=f"query {identifier}",
        )
        for identifier in identifiers
    )
    return api.BatchAnalysis(
        topics=topics,
        requested_attempt_ids=identifiers,
        package_limit=3,
    )


def _limits(api):
    return api.ContentLimits(
        analysis_limit=12,
        package_limit=3,
        freshness_days=14,
        fresh_share=90,
        reserve_share=10,
    )


def test_process_cleans_before_claim_and_passes_daily_limits() -> None:
    # Поломка (gate 1/9): cleanup после claim или claim не получает 12/3/локальный день.
    api = _api()
    repository = FakeRepository([])
    media = FakeMedia(None)
    processor = api.ProcessContent(
        repository,
        FakeExtractor({}),
        FakeAnalyzer(_batch(api, ())),
        media,
        limits=_limits(api),
        review_required=True,
        timezone="Europe/Moscow",
        clock=lambda: NOW,
    )

    result = processor.execute()

    assert media.events == [("cleanup", NOW - timedelta(hours=48), {"/media/active.jpg"})]
    assert repository.events[0] == ("active_media_paths",)
    assert repository.events[1][0:3] == ("claim", NOW, date(2026, 8, 8))
    assert repository.events[1][3] == _limits(api)
    assert result.claimed == 0


def test_partial_article_failure_schedules_one_retry_and_analyzes_real_body() -> None:
    # Поломка (gate 4/5/10): один fetch-сбой роняет batch или AI получает title/snippet.
    api = _api()
    attempts = [_attempt(1), _attempt(2)]
    first_error = api.ArticleExtractionError("SECRET transport details")
    article = _article(api, 2)
    repository = FakeRepository(attempts)
    analyzer = FakeAnalyzer(_batch(api, (2,)))
    media = FakeMedia(api.StoredMedia("/media/two.jpg", "image/jpeg", "og", "https://cdn.test/2.jpg"))
    processor = api.ProcessContent(
        repository,
        FakeExtractor({attempts[0].source_url: first_error, attempts[1].source_url: article}),
        analyzer,
        media,
        limits=_limits(api),
        review_required=True,
        timezone="UTC",
        clock=lambda: NOW,
    )

    result = processor.execute()

    assert ("retry", 1, NOW + timedelta(hours=6), NOW) in repository.events
    analyzed_inputs, package_limit = analyzer.calls[0]
    assert package_limit == 3
    assert [item.attempt_id for item in analyzed_inputs] == [2]
    assert analyzed_inputs[0].text == article.text
    assert "HN snippet" not in analyzed_inputs[0].text
    assert result.retry_scheduled == 1
    assert result.packages_created == 1


def test_second_article_failure_is_terminal_and_never_schedules_third_attempt() -> None:
    # Поломка (gate 5): второй fetch-сбой планирует бесконечный retry.
    api = _api()
    attempt = _attempt(1, attempt_no=2)
    repository = FakeRepository([attempt])
    processor = api.ProcessContent(
        repository,
        FakeExtractor({attempt.source_url: api.ArticleExtractionError("raw secret")}),
        FakeAnalyzer(_batch(api, ())),
        FakeMedia(None),
        limits=_limits(api),
        review_required=True,
        timezone="UTC",
        clock=lambda: NOW,
    )

    result = processor.execute()

    assert not [event for event in repository.events if event[0] == "retry"]
    failures = [event for event in repository.events if event[0] == "fail_attempt"]
    assert len(failures) == 1
    assert failures[0][2] == "article_unavailable"
    assert result.failed == 1


def test_codex_failure_finishes_all_extracted_attempts_with_safe_code() -> None:
    # Поломка (gate 10): Codex-сбой оставляет processing или сохраняет stderr.
    api = _api()
    attempts = [_attempt(1), _attempt(2)]
    repository = FakeRepository(attempts)
    secret = "TOKEN-IN-STDERR"
    processor = api.ProcessContent(
        repository,
        FakeExtractor({attempt.source_url: _article(api, attempt.id) for attempt in attempts}),
        FakeAnalyzer(api.CodexAnalysisError("codex_failed", secret)),
        FakeMedia(None),
        limits=_limits(api),
        review_required=True,
        timezone="UTC",
        clock=lambda: NOW,
    )

    result = processor.execute()

    failures = [event for event in repository.events if event[0] == "fail_attempt"]
    assert [(event[1], event[2]) for event in failures] == [
        (1, "codex_failed"),
        (2, "codex_failed"),
    ]
    assert secret not in repr(repository.events)
    assert result.failed == 2


@pytest.mark.parametrize(
    ("review_required", "expected_status"),
    [(True, "awaiting_review"), (False, "approved")],
)
def test_review_policy_controls_initial_completed_status(
    review_required: bool, expected_status: str
) -> None:
    # Поломка (gate 6): review-required обходится или auto-review зависает в awaiting_review.
    api = _api()
    attempt = _attempt(1)
    article = _article(api, 1)
    repository = FakeRepository([attempt])
    processor = api.ProcessContent(
        repository,
        FakeExtractor({attempt.source_url: article}),
        FakeAnalyzer(_batch(api, (1,))),
        FakeMedia(api.StoredMedia("/media/one.jpg", "image/jpeg", "og", "https://cdn.test/1.jpg")),
        limits=_limits(api),
        review_required=review_required,
        timezone="UTC",
        clock=lambda: NOW,
    )

    processor.execute()

    completes = [event for event in repository.events if event[0] == "complete"]
    assert len(completes) == 1
    assert completes[0][3] == expected_status


def test_media_failure_marks_package_failed_without_deleting_other_media() -> None:
    # Поломка (gate 9/10): filesystem-сбой оставляет processing или удаляет чужой файл.
    api = _api()
    attempt = _attempt(1)
    repository = FakeRepository([attempt])
    media = FakeMedia(api.MediaAcquireError("filesystem secret path"))
    processor = api.ProcessContent(
        repository,
        FakeExtractor({attempt.source_url: _article(api, 1)}),
        FakeAnalyzer(_batch(api, (1,))),
        media,
        limits=_limits(api),
        review_required=True,
        timezone="UTC",
        clock=lambda: NOW,
    )

    result = processor.execute()

    failures = [event for event in repository.events if event[0] == "fail_package"]
    assert len(failures) == 1
    assert failures[0][2] == "media_failed"
    assert not [event for event in media.events if event[0] == "delete"]
    assert "filesystem secret path" not in repr(repository.events)
    assert result.failed == 1


def test_process_persists_full_analysis_batch_but_acquires_media_only_for_selected() -> None:
    # Поломка re-review 8: action теряет nonselected outcome или создаёт для него пакет/media.
    api = _api()
    attempts = [_attempt(1), _attempt(2)]
    articles = {attempt.id: _article(api, attempt.id) for attempt in attempts}
    selected = api.AnalyzedTopic(
        attempt_id=1,
        analysis="Выбранный подробный анализ",
        usefulness=90,
        selected=True,
        post_text="Русский пост",
        media_query="database",
    )
    nonselected = api.AnalyzedTopic(
        attempt_id=2,
        analysis="Сохранённый анализ без пакета",
        usefulness=40,
        selected=False,
        post_text=None,
        media_query=None,
    )
    batch = api.BatchAnalysis(
        topics=(selected, nonselected),
        requested_attempt_ids=(1, 2),
        package_limit=1,
    )
    repository = FakeRepository(attempts)
    media = FakeMedia(
        api.StoredMedia(
            "/media/one.jpg", "image/jpeg", "og", "https://cdn.test/1.jpg"
        )
    )
    processor = api.ProcessContent(
        repository,
        FakeExtractor({attempt.source_url: articles[attempt.id] for attempt in attempts}),
        FakeAnalyzer(batch),
        media,
        limits=_limits(api),
        review_required=True,
        timezone="UTC",
        clock=lambda: NOW,
    )

    result = processor.execute()

    draft_event = next(event for event in repository.events if event[0] == "drafts")
    assert draft_event[1].topics == (selected, nonselected)
    assert [event[2] for event in media.events if event[0] == "acquire"] == [
        "database"
    ]
    assert result.packages_created == 1
    assert result.failed == 0


def test_process_passes_effective_generation_brief_and_persists_its_snapshot() -> None:
    # Поломка: runtime загрузил настройки, но анализатор и история пакета их потеряли.
    from postify.application.ports.content_analyzer import GenerationBrief

    api = _api()
    attempt = _attempt(1)
    article = _article(api, 1)
    brief = GenerationBrief(
        topic="Автоматизация отчётов",
        language="ru",
        audience="Редакторы",
        format_instructions="Хук, три шага и ограничение",
        cta="Открыть источник",
    )
    snapshot = {
        "topic": brief.topic,
        "language": brief.language,
        "audience": brief.audience,
        "format": {"id": 7, "instructions": brief.format_instructions},
        "cta": {"id": 9, "text": brief.cta, "link_mode": "source"},
    }
    repository = FakeRepository([attempt])
    analyzer = FakeAnalyzer(_batch(api, (1,)))
    processor = api.ProcessContent(
        repository,
        FakeExtractor({attempt.source_url: article}),
        analyzer,
        FakeMedia(
            api.StoredMedia(
                "/media/one.jpg",
                "image/jpeg",
                "og",
                "https://cdn.test/1.jpg",
            )
        ),
        limits=_limits(api),
        review_required=True,
        timezone="UTC",
        generation_brief=brief,
        generation_snapshot=snapshot,
        clock=lambda: NOW,
    )

    processor.execute()

    assert analyzer.briefs == [brief]
    draft = next(event for event in repository.events if event[0] == "drafts")
    assert draft[4] == snapshot

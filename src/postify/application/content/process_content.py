from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timedelta
from collections.abc import Callable
from zoneinfo import ZoneInfo
from postify.domain.content.models import AUTOMATIC_CONTEXT, AnalysisInput, ContentLimits, ExecutionContext
from postify.application.ports.article_extractor import ArticleExtractor
from postify.application.ports.content_analyzer import ContentAnalyzer
from postify.application.ports.content_repository import ContentRepository
from postify.application.ports.media_provider import MediaProvider
from postify.application.ports.content_analyzer import GenerationBrief


@dataclass(frozen=True, slots=True)
class ProcessContentResult:
    claimed: int = 0
    retry_scheduled: int = 0
    failed: int = 0
    packages_created: int = 0
    materials_taken: int = 0
    codex_model: str | None = None
    codex_reasoning_effort: str | None = None


ContentProcessResult = ProcessContentResult


class ProcessContent:
    def __init__(
        self,
        repository: ContentRepository,
        extractor: ArticleExtractor,
        analyzer: ContentAnalyzer,
        media: MediaProvider,
        *,
        limits: ContentLimits,
        review_required: bool,
        timezone: str,
        generation_brief: GenerationBrief | None = None,
        generation_snapshot: dict[str, object] | None = None,
        codex_model: str | None = None,
        codex_reasoning_effort: str | None = None,
        context: ExecutionContext = AUTOMATIC_CONTEXT,
        clock: Callable[[], datetime],
    ):
        self.r = repository
        self.e = extractor
        self.a = analyzer
        self.m = media
        self.limits = limits
        self.review = review_required
        self.tz = ZoneInfo(timezone)
        self.brief = generation_brief
        self.generation_snapshot = dict(generation_snapshot or {})
        self.codex_model = codex_model
        self.codex_reasoning_effort = codex_reasoning_effort
        self.context = context
        self.clock = clock

    def execute(self):
        now = self.clock()
        self.m.cleanup(
            older_than=now - timedelta(hours=48),
            protected_paths=self.r.active_media_paths(),
        )
        day = now.astimezone(self.tz).date()
        attempts = self.r.claim(
            now=now, day=day, limits=self.limits, context=self.context
        )
        articles = {}
        retry = failed = 0
        for x in attempts:
            try:
                article = self.e.extract(x.source_url)
                self.r.save_extracted(x.id, article)
                articles[x.id] = article
            except Exception:
                if not self.context.is_manual and x.attempt_no == 1:
                    self.r.schedule_article_retry(
                        x.id, retry_at=now + timedelta(hours=6), now=now
                    )
                    retry += 1
                else:
                    self.r.fail_attempt(x.id, code="article_unavailable", now=now)
                    failed += 1
        if not articles:
            return ProcessContentResult(
                len(attempts), retry, failed, 0, materials_taken=len(attempts)
            )
        inputs = tuple(
            AnalysisInput(i, a.source_url, a.title, a.text) for i, a in articles.items()
        )
        try:
            package_slots = self.r.package_slots_remaining(
                day=day, limit=self.limits.package_limit, context=self.context
            )
            batch = (
                self.a.analyze(inputs, package_slots, self.brief)
                if self.brief is not None
                else self.a.analyze(inputs, package_slots)
            )
        except Exception as error:
            code = getattr(error, "code", "codex_failed")
            for i in articles:
                self.r.fail_attempt(i, code=code, now=now)
            return ProcessContentResult(
                len(attempts),
                retry,
                failed + len(articles),
                0,
                materials_taken=len(attempts),
                codex_model=self.codex_model,
                codex_reasoning_effort=self.codex_reasoning_effort,
            )
        save_kwargs = dict(
            batch=batch,
            articles=articles,
            review_required=self.review,
            generation_snapshot=self.generation_snapshot,
            now=now,
            day=day,
            package_limit=self.limits.package_limit,
            context=self.context,
        )
        drafts = self.r.save_analysis_and_create_packages(
            **save_kwargs,
        )
        made = 0
        for d in drafts:
            try:
                self.r.complete_package(
                    d.package_id,
                    media=self.m.acquire(d.article, d.media_query),
                    status="awaiting_review" if self.review else "approved",
                    now=now,
                )
                made += 1
            except Exception:
                self.r.fail_package(d.package_id, code="media_failed", now=now)
                failed += 1
        return ProcessContentResult(
            len(attempts),
            retry,
            failed,
            made,
            materials_taken=len(attempts),
            codex_model=self.codex_model,
            codex_reasoning_effort=self.codex_reasoning_effort,
        )

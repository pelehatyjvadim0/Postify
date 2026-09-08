from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from collections.abc import Callable
from postify.domain.content.models import AUTOMATIC_CONTEXT, AnalysisInput, ExecutionContext, ExtractedArticle
from postify.application.ports.content_analyzer import ContentAnalyzer
from postify.application.ports.content_repository import ContentRepository
from postify.application.ports.content_analyzer import GenerationBrief


@dataclass(frozen=True, slots=True)
class ProcessContentResult:
    claimed: int = 0
    retry_scheduled: int = 0
    failed: int = 0
    packages_created: int = 0
    materials_taken: int = 0
    model: str | None = None
    codex_model: str | None = None
    codex_reasoning_effort: str | None = None


ContentProcessResult = ProcessContentResult


class ProcessContent:
    def __init__(
        self,
        repository: ContentRepository,
        analyzer: ContentAnalyzer,
        *,
        batch_size: int,
        generation_brief: GenerationBrief | None = None,
        generation_snapshot: dict[str, object] | None = None,
        model: str | None = None,
        codex_model: str | None = None,
        codex_reasoning_effort: str | None = None,
        context: ExecutionContext = AUTOMATIC_CONTEXT,
        clock: Callable[[], datetime],
    ):
        self.r = repository
        self.a = analyzer
        self.batch_size = batch_size
        self.model = model
        self.brief = generation_brief
        self.generation_snapshot = dict(generation_snapshot or {})
        self.codex_model = codex_model
        self.codex_reasoning_effort = codex_reasoning_effort
        self.context = context
        self.clock = clock

    def execute(self):
        now = self.clock()
        attempts = self.r.claim(now=now, batch_size=self.batch_size, context=self.context)
        articles = {}
        retry = failed = 0
        for x in attempts:
            try:
                source_text = getattr(x, "source_text", None)
                if source_text is None:
                    raise ValueError("Source has no text")
                article = ExtractedArticle(x.source_url, x.title, source_text, ())
                self.r.save_extracted(x.id, article)
                articles[x.id] = article
            except Exception:
                self.r.fail_attempt(x.id, code="source_text_unavailable", now=now)
                failed += 1
        if not articles:
            return ProcessContentResult(
                len(attempts), retry, failed, 0, materials_taken=len(attempts)
            )
        inputs = tuple(
            AnalysisInput(i, a.source_url, a.title, a.text) for i, a in articles.items()
        )
        try:
            self.model = self.model or getattr(self.a, "model", None)
            provider = getattr(self.a, "provider", None)
            if provider in {"gemini", "codex"}:
                self.generation_snapshot.update(
                    provider=provider, model=self.model, prompt_version=self.a.prompt_version
                )
            package_slots = len(inputs)
            batch = (
                self.a.analyze(inputs, package_slots, self.brief)
                if self.brief is not None
                else self.a.analyze(inputs, package_slots)
            )
        except Exception as error:
            code = getattr(error, "code", "generation_failed")
            for i in articles:
                self.r.fail_attempt(i, code=code, now=now)
            return ProcessContentResult(
                len(attempts),
                retry,
                failed + len(articles),
                0,
                materials_taken=len(attempts),
                model=self.model,
                codex_model=self.codex_model,
                codex_reasoning_effort=self.codex_reasoning_effort,
            )
        save_kwargs = dict(
            batch=batch,
            articles=articles,
            generation_snapshot=self.generation_snapshot,
            now=now,
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
                    media=None,
                    status="awaiting_review",
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
            model=self.model,
            codex_model=self.codex_model,
            codex_reasoning_effort=self.codex_reasoning_effort,
        )

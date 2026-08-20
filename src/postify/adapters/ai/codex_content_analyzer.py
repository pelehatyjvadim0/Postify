from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from subprocess import CompletedProcess
from typing import Literal

from pydantic import BaseModel, ValidationError

from postify.adapters.ai.codex_output import batch_output_model, batch_output_schema

from postify.domain.content.models import (
    AnalysisInput,
    AnalyzedTopic,
    BatchAnalysis,
    ContentValidationError,
)
from postify.application.ports.content_analyzer import GenerationBrief


class CodexAnalysisError(RuntimeError):
    def __init__(self, code: str = "codex_failed", message: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.reason = message


class CodexContentAnalyzer:
    def __init__(
        self,
        runner: Callable[..., CompletedProcess[str]],
        repository_cwd: Path,
        timeout_seconds: float,
        work_dir: Path,
        model: str = "gpt-5.6-luna",
        reasoning_effort: Literal["low", "medium", "high", "xhigh", "max"] = "high",
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model не может быть пустой")
        if reasoning_effort not in {"low", "medium", "high", "xhigh", "max"}:
            raise ValueError("Неизвестный reasoning effort")
        self.runner = runner
        self.cwd = Path(repository_cwd)
        self.timeout = timeout_seconds
        self.work = Path(work_dir)
        self.model = model.strip()
        self.reasoning_effort = reasoning_effort

    def analyze(
        self,
        articles: Sequence[AnalysisInput],
        package_limit: int,
        brief: GenerationBrief | None = None,
    ) -> BatchAnalysis:
        materialized = tuple(articles)
        invocation = self._create_invocation_dir()
        result: BatchAnalysis | None = None
        failure: CodexAnalysisError | None = None
        try:
            schema = invocation / "schema.json"
            output = invocation / "output.json"
            output_model = batch_output_model(len(materialized))
            schema.write_text(
                json.dumps(self._schema(len(materialized)), ensure_ascii=False),
                encoding="utf-8",
            )
            done = self._run(
                invocation, schema, output, materialized, package_limit, brief
            )
            if done.returncode:
                raise CodexAnalysisError()
            result = self._parse_output(
                output,
                materialized,
                package_limit,
                output_model,
                allow_source_url=brief is not None
                and brief.cta_link_mode == "source",
            )
        except CodexAnalysisError as error:
            failure = error
        except Exception:
            failure = CodexAnalysisError()
        try:
            shutil.rmtree(invocation)
        except OSError:
            if failure is None:
                failure = CodexAnalysisError()
        if failure is not None:
            raise failure
        if result is None:
            raise CodexAnalysisError()
        return result

    def _create_invocation_dir(self) -> Path:
        try:
            if _paths_overlap(self.cwd.resolve(), self.work.resolve()):
                raise OSError
            self.work.mkdir(parents=True, exist_ok=True)
            return Path(tempfile.mkdtemp(prefix="codex-", dir=self.work))
        except OSError:
            raise CodexAnalysisError() from None

    def _run(
        self,
        invocation: Path,
        schema: Path,
        output: Path,
        articles: tuple[AnalysisInput, ...],
        package_limit: int,
        brief: GenerationBrief | None,
    ) -> CompletedProcess[str]:
        prompt = self._prompt(articles, package_limit, brief)
        argv = [
            "codex",
            "exec",
            "--model",
            self.model,
            "--config",
            f'model_reasoning_effort="{self.reasoning_effort}"',
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            "--cd",
            str(invocation),
            "--output-schema",
            str(schema),
            "--output-last-message",
            str(output),
            "-",
        ]
        try:
            return self.runner(
                argv,
                input=prompt,
                text=True,
                capture_output=True,
                shell=False,
                timeout=self.timeout,
            )
        except Exception:
            raise CodexAnalysisError() from None

    @staticmethod
    def _schema(article_count: int) -> dict[str, object]:
        return batch_output_schema(article_count)

    @staticmethod
    def _prompt(
        articles: tuple[AnalysisInput, ...],
        package_limit: int,
        brief: GenerationBrief | None = None,
    ) -> str:
        include_source = brief is not None and brief.cta_link_mode == "source"
        material = "\n\n".join(
            f"Попытка {article.attempt_id}. Заголовок: {article.title}"
            + (f"\nURL источника: {article.source_url}" if include_source else "")
            + f"\nПолный текст статьи:\n{article.text}"
            for article in articles
        )
        product_context = ""
        language_instruction = "Пиши анализ и выбранные посты на русском. "
        if brief is not None:
            cta = brief.cta
            if brief.cta_link_mode == "custom" and brief.cta_url:
                cta = f"{cta}: {brief.cta_url}"
            product_context = (
                f"Тема проекта: {brief.topic}. Язык: {brief.language}. "
                f"Аудитория: {brief.audience}. Формат: {brief.format_instructions}. "
                f"CTA: {cta}.\n"
            )
            language_instruction = (
                f"Пиши анализ и выбранные посты на языке {brief.language}. "
            )
        return (
            product_context
            + "Проанализируй каждую статью и верни ровно один outcome на каждую попытку. "
            f"Выбери не более {package_limit}. {language_instruction}"
            + (
                "Добавь URL источника только в CTA выбранных постов.\n\n"
                if include_source
                else "Не добавляй source URL или URL источника в посты.\n\n"
            )
            + material
        )

    @staticmethod
    def _parse_output(
        output: Path,
        articles: tuple[AnalysisInput, ...],
        package_limit: int,
        output_model: type[BaseModel] | None = None,
        *,
        allow_source_url: bool = False,
    ) -> BatchAnalysis:
        try:
            raw_output = output.read_text(encoding="utf-8")
        except OSError:
            raise CodexAnalysisError("codex_output_unavailable") from None
        model = output_model or batch_output_model(len(articles))
        try:
            payload = model.model_validate_json(raw_output)
        except ValidationError as error:
            first = error.errors(include_url=False)[0]
            code = (
                "codex_output_not_json"
                if first.get("type") == "json_invalid"
                else "codex_output_schema_mismatch"
            )
            location = ".".join(str(item) for item in first.get("loc", ()))
            raise CodexAnalysisError(code, location) from None
        try:
            topics = tuple(
                AnalyzedTopic(
                    **item.model_dump()
                )
                for item in payload.topics
            )
            batch = BatchAnalysis(
                topics, tuple(item.attempt_id for item in articles), package_limit
            )
            if not allow_source_url and any(
                topic.post_text is not None and article.source_url in topic.post_text
                for article in articles
                for topic in topics
            ):
                raise CodexAnalysisError("codex_output_source_url_forbidden")
            return batch
        except CodexAnalysisError:
            raise
        except (ValueError, TypeError, ContentValidationError):
            raise CodexAnalysisError("codex_output_domain_invalid") from None


def _paths_overlap(first: Path, second: Path) -> bool:
    return first.is_relative_to(second) or second.is_relative_to(first)

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from subprocess import CompletedProcess
from typing import Any

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


class CodexContentAnalyzer:
    def __init__(
        self,
        runner: Callable[..., CompletedProcess[str]],
        repository_cwd: Path,
        timeout_seconds: float,
        work_dir: Path,
    ) -> None:
        self.runner = runner
        self.cwd = Path(repository_cwd)
        self.timeout = timeout_seconds
        self.work = Path(work_dir)

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
            schema.write_text(
                json.dumps(self._schema(len(materialized)), ensure_ascii=False),
                encoding="utf-8",
            )
            done = self._run(
                invocation, schema, output, materialized, package_limit, brief
            )
            if done.returncode:
                raise CodexAnalysisError()
            result = self._parse_output(output, materialized, package_limit)
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
        common_properties = {
            "attempt_id": {"type": "integer", "minimum": 1},
            "analysis": {"type": "string", "minLength": 1},
            "usefulness": {"type": "integer", "minimum": 0, "maximum": 100},
        }
        required = [
            "attempt_id",
            "analysis",
            "usefulness",
            "selected",
            "post_text",
            "media_query",
        ]
        selected_topic = {
            "type": "object",
            "additionalProperties": False,
            "required": required,
            "properties": {
                **common_properties,
                "selected": {"type": "boolean", "const": True},
                "post_text": {"type": "string", "minLength": 1},
                "media_query": {"type": "string", "minLength": 1},
            },
        }
        unselected_topic = {
            "type": "object",
            "additionalProperties": False,
            "required": required,
            "properties": {
                **common_properties,
                "selected": {"type": "boolean", "const": False},
                "post_text": {"type": "null"},
                "media_query": {"type": "null"},
            },
        }
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["topics"],
            "properties": {
                "topics": {
                    "type": "array",
                    "minItems": article_count,
                    "maxItems": article_count,
                    "items": {"anyOf": [selected_topic, unselected_topic]},
                }
            },
        }

    @staticmethod
    def _prompt(
        articles: tuple[AnalysisInput, ...],
        package_limit: int,
        brief: GenerationBrief | None = None,
    ) -> str:
        material = "\n\n".join(
            f"Попытка {article.attempt_id}. Заголовок: {article.title}\nПолный текст статьи:\n{article.text}"
            for article in articles
        )
        product_context = ""
        language_instruction = "Пиши анализ и выбранные посты на русском. "
        if brief is not None:
            product_context = (
                f"Тема проекта: {brief.topic}. Язык: {brief.language}. "
                f"Аудитория: {brief.audience}. Формат: {brief.format_instructions}. "
                f"CTA: {brief.cta}.\n"
            )
            language_instruction = (
                f"Пиши анализ и выбранные посты на языке {brief.language}. "
            )
        return (
            product_context
            + "Проанализируй каждую статью и верни ровно один outcome на каждую попытку. "
            f"Выбери не более {package_limit}. {language_instruction}"
            "Не добавляй source URL или URL источника в посты.\n\n" + material
        )

    @staticmethod
    def _parse_output(
        output: Path, articles: tuple[AnalysisInput, ...], package_limit: int
    ) -> BatchAnalysis:
        try:
            payload: Any = json.loads(output.read_text(encoding="utf-8"))
            raw_topics = payload["topics"]
            if not isinstance(raw_topics, list):
                raise ValueError
            topics = tuple(
                AnalyzedTopic(
                    attempt_id=item["attempt_id"],
                    analysis=item["analysis"],
                    usefulness=item["usefulness"],
                    selected=item["selected"],
                    post_text=item["post_text"],
                    media_query=item["media_query"],
                )
                for item in raw_topics
            )
            batch = BatchAnalysis(
                topics, tuple(item.attempt_id for item in articles), package_limit
            )
            if any(
                topic.post_text is not None and article.source_url in topic.post_text
                for article in articles
                for topic in topics
            ):
                raise ContentValidationError
            return batch
        except (OSError, ValueError, KeyError, TypeError, ContentValidationError):
            raise CodexAnalysisError("codex_invalid_output") from None


def _paths_overlap(first: Path, second: Path) -> bool:
    return first.is_relative_to(second) or second.is_relative_to(first)

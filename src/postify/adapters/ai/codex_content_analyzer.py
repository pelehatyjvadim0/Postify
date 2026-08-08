from __future__ import annotations
import json
import tempfile
from pathlib import Path
from postify.domain.content.models import (
    AnalyzedTopic,
    BatchAnalysis,
    ContentValidationError,
)


class CodexAnalysisError(RuntimeError):
    def __init__(self, code="codex_failed", message=""):
        super().__init__(code)
        self.code = code


class CodexContentAnalyzer:
    def __init__(self, runner, repository_cwd, timeout_seconds, work_dir):
        self.runner = runner
        self.cwd = Path(repository_cwd)
        self.timeout = timeout_seconds
        self.work = Path(work_dir)

    def analyze(self, articles, package_limit):
        articles = tuple(articles)
        self.work.mkdir(parents=True, exist_ok=True)
        output = self.work / f"codex-{next(tempfile._get_candidate_names())}.json"
        schema = self.work / "codex-schema.json"
        schema.write_text('{"type":"object"}')
        prompt = json.dumps(
            {
                "articles": [
                    a.__dict__
                    if hasattr(a, "__dict__")
                    else {
                        "attempt_id": a.attempt_id,
                        "source_url": a.source_url,
                        "title": a.title,
                        "text": a.text,
                    }
                    for a in articles
                ]
            },
            ensure_ascii=False,
        )
        argv = [
            "codex",
            "exec",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--ignore-user-config",
            "--ignore-rules",
            "--cd",
            str(self.cwd),
            "--output-schema",
            str(schema),
            "--output-last-message",
            str(output),
        ]
        try:
            done = self.runner(
                argv,
                input=prompt,
                text=True,
                capture_output=True,
                shell=False,
                timeout=self.timeout,
            )
        except Exception as e:
            raise CodexAnalysisError() from e
        if done.returncode:
            raise CodexAnalysisError()
        try:
            payload = json.loads(output.read_text())
            topics = tuple(AnalyzedTopic(**x) for x in payload["topics"])
            batch = BatchAnalysis(
                topics, tuple(a.attempt_id for a in articles), package_limit
            )
            if any(a.source_url in t.post_text for a in articles for t in topics):
                raise ContentValidationError()
            return batch
        except (OSError, ValueError, KeyError, TypeError, ContentValidationError) as e:
            raise CodexAnalysisError("codex_invalid_output") from e

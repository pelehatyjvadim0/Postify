from __future__ import annotations

import json
from pathlib import Path
import subprocess

import pytest


MARKER = "ARTICLE-BODY-MARKER-3d621"


def _api():
    from postify.adapters.ai.codex_content_analyzer import (
        CodexAnalysisError,
        CodexContentAnalyzer,
    )
    from postify.domain.content.models import AnalysisInput

    return AnalysisInput, CodexAnalysisError, CodexContentAnalyzer


def _input(AnalysisInput):
    return AnalysisInput(
        attempt_id=17,
        source_url="https://source.test/post",
        title="HN title without marker",
        text=f"Полный текст {MARKER} с практическими деталями.",
    )


def _valid_output() -> dict[str, object]:
    return {
        "topics": [
            {
                "attempt_id": 17,
                "analysis": "Практический анализ",
                "usefulness": 91,
                "post_text": "Русский текст без ссылки",
                "media_query": "PostgreSQL architecture",
            }
        ]
    }


def test_codex_exec_receives_article_body_and_hardened_invocation(tmp_path: Path) -> None:
    # Поломка (gate 4): marker article body не передаётся в stdin Codex.
    AnalysisInput, _, CodexContentAnalyzer = _api()
    calls: list[tuple[list[str], dict[str, object]]] = []

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        output_path = Path(argv[argv.index("--output-last-message") + 1])
        output_path.write_text(json.dumps(_valid_output()), encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, stdout="ignored", stderr="ignored")

    analyzer = CodexContentAnalyzer(
        runner=runner,
        repository_cwd=tmp_path,
        timeout_seconds=600,
        work_dir=tmp_path,
    )
    result = analyzer.analyze([_input(AnalysisInput)], package_limit=3)

    argv, kwargs = calls[0]
    assert argv[:2] == ["codex", "exec"]
    assert "--ephemeral" in argv
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert "--ignore-user-config" in argv
    assert "--ignore-rules" in argv
    assert argv[argv.index("--cd") + 1] == str(tmp_path)
    assert "--output-schema" in argv
    assert "--output-last-message" in argv
    assert "--model" not in argv
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == 600
    assert MARKER in str(kwargs["input"])
    assert result.topics[0].attempt_id == 17


@pytest.mark.parametrize(
    "payload",
    [
        "not-json",
        json.dumps({"topics": [{"attempt_id": 999, "analysis": "x", "usefulness": 1,
                                 "post_text": "x", "media_query": "x"}]}),
        json.dumps({"topics": [{"attempt_id": 17, "analysis": "x", "usefulness": 1,
                                 "post_text": "https://source.test/post", "media_query": "x"}]}),
    ],
)
def test_codex_rejects_invalid_json_unknown_id_and_source_url(
    tmp_path: Path, payload: str
) -> None:
    # Поломка (gate 7/10): malformed/untrusted batch создаёт пакет.
    AnalysisInput, CodexAnalysisError, CodexContentAnalyzer = _api()

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        Path(argv[argv.index("--output-last-message") + 1]).write_text(payload, encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, stdout="raw", stderr="secret")

    analyzer = CodexContentAnalyzer(runner, tmp_path, 600, tmp_path)
    with pytest.raises(CodexAnalysisError):
        analyzer.analyze([_input(AnalysisInput)], package_limit=3)


def test_codex_failure_exposes_stable_code_without_stdout_stderr_or_prompt(
    tmp_path: Path,
) -> None:
    # Поломка (gate 10): subprocess-ошибка раскрывает stderr/секрет/article.
    AnalysisInput, CodexAnalysisError, CodexContentAnalyzer = _api()
    secret = "TOKEN-DO-NOT-LEAK"

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(argv, 9, stdout=f"stdout {MARKER}", stderr=secret)

    analyzer = CodexContentAnalyzer(runner, tmp_path, 600, tmp_path)
    with pytest.raises(CodexAnalysisError) as caught:
        analyzer.analyze([_input(AnalysisInput)], package_limit=3)

    assert caught.value.code == "codex_failed"
    assert secret not in str(caught.value)
    assert MARKER not in str(caught.value)

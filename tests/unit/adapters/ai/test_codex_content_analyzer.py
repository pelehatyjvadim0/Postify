from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
from threading import Barrier

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


def _valid_output(attempt_ids: tuple[int, ...] = (17,)) -> dict[str, object]:
    return {
        "topics": [
            {
                "attempt_id": attempt_id,
                "analysis": f"Практический анализ {attempt_id}",
                "usefulness": 91,
                "selected": True,
                "post_text": f"Русский текст без ссылки {attempt_id}",
                "media_query": "PostgreSQL architecture",
            }
            for attempt_id in attempt_ids
        ]
    }


def _schema_accepts(schema: dict[str, object], value: object) -> bool:
    if "const" in schema and value != schema["const"]:
        return False
    expected_type = schema.get("type")
    type_checks = {
        "object": lambda item: isinstance(item, dict),
        "array": lambda item: isinstance(item, list),
        "string": lambda item: isinstance(item, str),
        "integer": lambda item: isinstance(item, int) and not isinstance(item, bool),
        "boolean": lambda item: isinstance(item, bool),
        "null": lambda item: item is None,
    }
    if isinstance(expected_type, str) and not type_checks[expected_type](value):
        return False
    if isinstance(value, str) and len(value) < int(schema.get("minLength", 0)):
        return False
    if "required" in schema and isinstance(value, dict):
        if not set(schema["required"]).issubset(value):
            return False
    if "properties" in schema and isinstance(value, dict):
        for name, child_schema in schema["properties"].items():
            if name in value and not _schema_accepts(child_schema, value[name]):
                return False
    if "anyOf" in schema and not any(
        _schema_accepts(child, value) for child in schema["anyOf"]
    ):
        return False
    if "oneOf" in schema and sum(
        _schema_accepts(child, value) for child in schema["oneOf"]
    ) != 1:
        return False
    if "allOf" in schema and not all(
        _schema_accepts(child, value) for child in schema["allOf"]
    ):
        return False
    if "if" in schema:
        branch = "then" if _schema_accepts(schema["if"], value) else "else"
        if branch in schema and not _schema_accepts(schema[branch], value):
            return False
    return True


def _schema_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            keys.add(key)
            keys.update(_schema_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.update(_schema_keys(child))
    return keys


def test_codex_exec_receives_article_body_and_hardened_invocation(tmp_path: Path) -> None:
    # Поломка (gate 4): marker article body не передаётся в stdin Codex.
    AnalysisInput, _, CodexContentAnalyzer = _api()
    calls: list[tuple[list[str], dict[str, object]]] = []
    invocation_dirs: list[Path] = []

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append((argv, kwargs))
        output_path = Path(argv[argv.index("--output-last-message") + 1])
        invocation_dirs.append(output_path.parent)
        output_path.write_text(json.dumps(_valid_output()), encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, stdout="ignored", stderr="ignored")

    repository = tmp_path / "repository"
    work = tmp_path / "work"
    analyzer = CodexContentAnalyzer(
        runner=runner,
        repository_cwd=repository,
        timeout_seconds=600,
        work_dir=work,
    )
    result = analyzer.analyze([_input(AnalysisInput)], package_limit=3)

    argv, kwargs = calls[0]
    assert argv[:2] == ["codex", "exec"]
    assert "--ephemeral" in argv
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert "--ignore-user-config" in argv
    assert "--ignore-rules" in argv
    invocation = invocation_dirs[0]
    assert invocation.parent == work
    assert Path(argv[argv.index("--cd") + 1]) == invocation
    assert Path(argv[argv.index("--output-schema") + 1]).parent == invocation
    assert Path(argv[argv.index("--output-last-message") + 1]).parent == invocation
    assert "--output-schema" in argv
    assert "--output-last-message" in argv
    assert "--model" not in argv
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == 600
    assert MARKER in str(kwargs["input"])
    assert result.topics[0].attempt_id == 17
    assert not invocation.exists()


@pytest.mark.parametrize(
    "relationship",
    ["equal", "work-inside-repository", "repository-inside-work"],
)
def test_codex_rejects_overlapping_repository_and_work_before_artifacts_or_runner(
    tmp_path: Path,
    relationship: str,
) -> None:
    # Поломка fix-round 2: invocation создаётся внутри repository overlap.
    AnalysisInput, CodexAnalysisError, CodexContentAnalyzer = _api()
    root = tmp_path / "operator-secret-overlap"
    if relationship == "equal":
        repository = work = root
    elif relationship == "work-inside-repository":
        repository, work = root, root / "work"
    else:
        work, repository = root, root / "repository"
    repository.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    before = {path.relative_to(tmp_path) for path in tmp_path.rglob("*")}
    runner_calls: list[list[str]] = []

    def forbidden_runner(
        argv: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        runner_calls.append(argv)
        raise AssertionError("runner не должен вызываться при overlap")

    analyzer = CodexContentAnalyzer(forbidden_runner, repository, 600, work)

    with pytest.raises(CodexAnalysisError) as caught:
        analyzer.analyze([_input(AnalysisInput)], package_limit=1)

    assert caught.value.code == "codex_failed"
    assert "operator-secret" not in str(caught.value)
    assert runner_calls == []
    assert {path.relative_to(tmp_path) for path in tmp_path.rglob("*")} == before


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


@pytest.mark.parametrize("selected", [0, 1])
def test_codex_rejects_integer_selected_as_invalid_output(
    tmp_path: Path,
    selected: int,
) -> None:
    # Поломка fix-round 2: JSON integer проходит как bool.
    AnalysisInput, CodexAnalysisError, CodexContentAnalyzer = _api()
    payload = _valid_output()
    topic = payload["topics"][0]
    topic["selected"] = selected
    topic["post_text"] = "Русский пост" if selected else None
    topic["media_query"] = "database" if selected else None

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        Path(argv[argv.index("--output-last-message") + 1]).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    analyzer = CodexContentAnalyzer(
        runner,
        tmp_path / "repository",
        600,
        tmp_path / "work",
    )

    with pytest.raises(CodexAnalysisError) as caught:
        analyzer.analyze([_input(AnalysisInput)], package_limit=1)

    assert caught.value.code == "codex_invalid_output"


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


def test_codex_runner_exception_does_not_leak_secret_and_cleans_invocation_dir(
    tmp_path: Path,
) -> None:
    # Поломка re-review 6: exception из runner раскрывает секрет и оставляет prompt/schema.
    AnalysisInput, CodexAnalysisError, CodexContentAnalyzer = _api()
    secret = "RUNNER-TOKEN-DO-NOT-LEAK"
    invocation_dirs: list[Path] = []

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        invocation_dirs.append(Path(argv[argv.index("--output-schema") + 1]).parent)
        raise OSError(f"subprocess failed with {secret} and {MARKER}")

    analyzer = CodexContentAnalyzer(
        runner,
        tmp_path / "repository",
        600,
        tmp_path / "work",
    )
    with pytest.raises(CodexAnalysisError) as caught:
        analyzer.analyze([_input(AnalysisInput)], package_limit=3)

    assert caught.value.code == "codex_failed"
    assert secret not in str(caught.value)
    assert MARKER not in str(caught.value)
    assert len(invocation_dirs) == 1
    assert not invocation_dirs[0].exists()


def test_codex_cleanup_failure_is_sanitized_and_cannot_return_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Поломка fix-round 1: cleanup молча оставляет raw prompt/output.
    AnalysisInput, CodexAnalysisError, CodexContentAnalyzer = _api()
    import postify.adapters.ai.codex_content_analyzer as codex_module

    secret = "CLEANUP-TOKEN-DO-NOT-LEAK"

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        Path(argv[argv.index("--output-last-message") + 1]).write_text(
            json.dumps(_valid_output()), encoding="utf-8"
        )
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    def failing_cleanup(path: Path, *, ignore_errors: bool = False) -> None:
        raise OSError(f"cleanup failed at {path} with {secret}")

    monkeypatch.setattr(codex_module.shutil, "rmtree", failing_cleanup)
    analyzer = CodexContentAnalyzer(
        runner,
        tmp_path / "repository",
        600,
        tmp_path / "work",
    )

    with pytest.raises(CodexAnalysisError) as caught:
        analyzer.analyze([_input(AnalysisInput)], package_limit=1)

    assert caught.value.code == "codex_failed"
    assert secret not in str(caught.value)
    assert str(tmp_path) not in str(caught.value)


def test_codex_success_uses_isolated_nonrepository_directory_and_cleans_it(
    tmp_path: Path,
) -> None:
    # Поломка re-review 6: success пишет schema/raw output в repository/media и не удаляет.
    AnalysisInput, _, CodexContentAnalyzer = _api()
    repository = tmp_path / "repository"
    media = tmp_path / "media"
    work = tmp_path / "work"
    repository.mkdir()
    media.mkdir()
    invocation_dirs: list[Path] = []

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        invocation_dir = Path(argv[argv.index("--output-schema") + 1]).parent
        invocation_dirs.append(invocation_dir)
        assert Path(argv[argv.index("--output-last-message") + 1]).parent == invocation_dir
        assert Path(argv[argv.index("--cd") + 1]) == invocation_dir
        Path(argv[argv.index("--output-last-message") + 1]).write_text(
            json.dumps(_valid_output()), encoding="utf-8"
        )
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    analyzer = CodexContentAnalyzer(runner, repository, 600, work)
    result = analyzer.analyze([_input(AnalysisInput)], package_limit=1)

    assert result.topics[0].attempt_id == 17
    assert len(invocation_dirs) == 1
    assert invocation_dirs[0].parent == work
    assert not invocation_dirs[0].is_relative_to(repository)
    assert not invocation_dirs[0].is_relative_to(media)
    assert not invocation_dirs[0].exists()


def test_codex_writes_strict_schema_and_explicit_complete_batch_prompt(
    tmp_path: Path,
) -> None:
    # Поломка re-review 6/8/9: schema допускает partial/extra fields, prompt не задаёт продуктовые правила.
    AnalysisInput, _, CodexContentAnalyzer = _api()
    second = AnalysisInput(
        attempt_id=18,
        source_url="https://source.test/second",
        title="Second title",
        text="SECOND-ARTICLE-BODY-MARKER с полным текстом статьи.",
    )
    captured: dict[str, object] = {}

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        schema_path = Path(argv[argv.index("--output-schema") + 1])
        output_path = Path(argv[argv.index("--output-last-message") + 1])
        captured["schema"] = json.loads(schema_path.read_text(encoding="utf-8"))
        captured["prompt"] = kwargs["input"]
        captured["argv"] = tuple(argv)
        output_path.write_text(
            json.dumps(_valid_output((17, 18)), ensure_ascii=False),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    analyzer = CodexContentAnalyzer(
        runner,
        tmp_path / "repository",
        600,
        tmp_path / "work",
    )
    analyzer.analyze([_input(AnalysisInput), second], package_limit=2)

    schema = captured["schema"]
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["topics"]
    topics_schema = schema["properties"]["topics"]
    assert topics_schema["minItems"] == 2
    assert topics_schema["maxItems"] == 2
    topic_schema = topics_schema["items"]
    assert topic_schema["additionalProperties"] is False
    assert set(topic_schema["required"]) == {
        "attempt_id",
        "analysis",
        "usefulness",
        "selected",
        "post_text",
        "media_query",
    }
    properties = topic_schema["properties"]
    assert properties["attempt_id"] == {"type": "integer", "minimum": 1}
    assert properties["analysis"] == {"type": "string", "minLength": 1}
    assert properties["usefulness"] == {
        "type": "integer",
        "minimum": 0,
        "maximum": 100,
    }
    assert properties["selected"] == {"type": "boolean"}
    nullable_text = {
        "anyOf": [{"type": "string", "minLength": 1}, {"type": "null"}]
    }
    assert properties["post_text"] == nullable_text
    assert properties["media_query"] == nullable_text
    common = {
        "attempt_id": 17,
        "analysis": "Полный анализ",
        "usefulness": 90,
    }
    assert _schema_accepts(
        topic_schema,
        {**common, "selected": True, "post_text": "Пост", "media_query": "db"},
    )
    assert _schema_accepts(
        topic_schema,
        {**common, "selected": False, "post_text": None, "media_query": None},
    )
    assert not _schema_accepts(
        topic_schema,
        {**common, "selected": True, "post_text": None, "media_query": None},
    )
    assert not _schema_accepts(
        topic_schema,
        {**common, "selected": False, "post_text": "Пост", "media_query": "db"},
    )
    unsupported_composition = {
        "allOf",
        "not",
        "dependentRequired",
        "dependentSchemas",
        "if",
        "then",
        "else",
    }
    assert _schema_keys(schema) & unsupported_composition == set()
    prompt = str(captured["prompt"])
    assert "на русском" in prompt.casefold()
    assert "кажд" in prompt.casefold() and "стать" in prompt.casefold()
    assert "не более 2" in prompt.casefold()
    assert "url" in prompt.casefold() and "не добав" in prompt.casefold()
    assert MARKER in prompt
    assert "SECOND-ARTICLE-BODY-MARKER" in prompt
    assert "--skip-git-repo-check" in captured["argv"]
    assert captured["argv"][-1] == "-"


def test_codex_preserves_selected_and_nonselected_outcomes_from_complete_batch(
    tmp_path: Path,
) -> None:
    # Поломка fix-round 1: parser теряет selected или nonselected outcome.
    AnalysisInput, _, CodexContentAnalyzer = _api()
    second = AnalysisInput(
        attempt_id=18,
        source_url="https://source.test/second",
        title="Second title",
        text="Полный текст второй статьи.",
    )
    payload = {
        "topics": [
            {
                "attempt_id": 17,
                "analysis": "Выбранный подробный анализ",
                "usefulness": 91,
                "selected": True,
                "post_text": "Русский пост для публикации",
                "media_query": "PostgreSQL architecture",
            },
            {
                "attempt_id": 18,
                "analysis": "Сохранённый анализ невыбранной статьи",
                "usefulness": 42,
                "selected": False,
                "post_text": None,
                "media_query": None,
            },
        ]
    }

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        Path(argv[argv.index("--output-last-message") + 1]).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    result = CodexContentAnalyzer(
        runner,
        tmp_path / "repository",
        600,
        tmp_path / "work",
    ).analyze([_input(AnalysisInput), second], package_limit=1)

    assert result.requested_attempt_ids == (17, 18)
    assert tuple(topic.attempt_id for topic in result.topics) == (17, 18)
    assert result.topics[0].selected is True
    assert result.topics[1].selected is False
    assert result.topics[1].post_text is None
    assert result.topics[1].media_query is None
    assert result.selected_topics == (result.topics[0],)


def test_codex_concurrent_runs_use_distinct_directories_and_cleanup_both(
    tmp_path: Path,
) -> None:
    # Поломка re-review 6: concurrent runs разделяют schema/output и оставляют raw context.
    AnalysisInput, _, CodexContentAnalyzer = _api()
    barrier = Barrier(2)
    invocation_dirs: list[Path] = []

    def runner(argv: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        invocation_dir = Path(argv[argv.index("--output-schema") + 1]).parent
        invocation_dirs.append(invocation_dir)
        barrier.wait(timeout=5)
        Path(argv[argv.index("--output-last-message") + 1]).write_text(
            json.dumps(_valid_output()), encoding="utf-8"
        )
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    work = tmp_path / "work"
    analyzer = CodexContentAnalyzer(runner, tmp_path / "repository", 600, work)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda _: analyzer.analyze([_input(AnalysisInput)], package_limit=1),
                range(2),
            )
        )

    assert [result.topics[0].attempt_id for result in results] == [17, 17]
    assert len(set(invocation_dirs)) == 2
    assert all(path.parent == work for path in invocation_dirs)
    assert all(not path.exists() for path in invocation_dirs)

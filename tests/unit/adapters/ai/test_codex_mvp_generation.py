import json
import os
import subprocess
from pathlib import Path

from postify.adapters.ai.codex_content_analyzer import CodexContentAnalyzer
from postify.application.ports.content_analyzer import GenerationBrief
from postify.domain.content.models import AnalysisInput


def test_codex_mvp_prompt_contains_brief_and_isolates_untrusted_input(tmp_path: Path, monkeypatch) -> None:
    captured = {}
    monkeypatch.setenv("POSTIFY_SYNTHETIC_SECRET", "canary-must-not-reach-codex")
    monkeypatch.setenv("HTTPS_PROXY", "http://must-not-reach-codex.invalid")

    def runner(argv, **kwargs):
        captured["argv"] = argv
        captured["prompt"] = kwargs["input"]
        captured["env"] = kwargs["env"]
        Path(argv[argv.index("--output-last-message") + 1]).write_text(
            json.dumps({"topics": [{"attempt_id": 7, "analysis": "Пояснение", "usefulness": 100, "selected": True, "post_text": "Готовый русский пост", "media_query": None}]}),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(argv, 0)

    result = CodexContentAnalyzer(runner, tmp_path / "repo", 60, tmp_path / "work").analyze(
        [AnalysisInput(7, "https://source.test/post", "Заголовок", "Текст")],
        package_limit=1,
        brief=GenerationBrief("Культура", "ru", "Читатели", "Короткий пост", "ar", "Спокойный"),
    )

    assert result.selected_topics[0].post_text == "Готовый русский пост"
    prompt = captured["prompt"]
    assert '"topic": "Культура"' in prompt
    assert '"tone": "Спокойный"' in prompt
    assert "CTA" not in prompt and "cta" not in prompt
    argv = captured["argv"]
    assert "--strict-config" in argv
    assert "--ignore-user-config" not in argv
    assert "--ignore-rules" in argv
    assert "--ephemeral" in argv
    for feature in (
        "shell_tool", "unified_exec", "code_mode", "code_mode_host",
        "plugins", "apps", "enable_mcp_apps", "multi_agent", "browser_use",
        "browser_use_external", "browser_use_full_cdp_access", "computer_use",
        "image_generation", "in_app_browser", "standalone_web_search", "view_image",
        "skill_search", "skill_mcp_dependency_install", "hooks", "sleep_tool",
        "tool_suggest", "artifact",
    ):
        assert ("--disable", feature) in zip(argv, argv[1:])
    assert captured["env"] == {
        "CODEX_HOME": os.environ.get("CODEX_HOME", str(Path.home() / ".codex")),
        "HOME": "/nonexistent",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", os.environ.get("LANG", "C.UTF-8")),
        "PATH": os.environ["PATH"],
    }

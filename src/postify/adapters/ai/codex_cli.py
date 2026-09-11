"""Транспорт Codex CLI: текст на входе, текст модели на выходе.

Адаптер ничего не знает о назначении вызова. Контекст запроса, разбор ответа
и учёт расхода живут в шлюзе вызовов модели, который вызывает этот транспорт.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path
from subprocess import CompletedProcess
from typing import Literal


REASONING_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})

DISABLED_TOOLS = (
    "shell_tool",
    "unified_exec",
    "code_mode",
    "code_mode_host",
    "plugins",
    "apps",
    "enable_mcp_apps",
    "multi_agent",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "computer_use",
    "image_generation",
    "in_app_browser",
    "standalone_web_search",
    "view_image",
    "skill_search",
    "skill_mcp_dependency_install",
    "hooks",
    "sleep_tool",
    "tool_suggest",
    "artifact",
)


class CodexCallError(RuntimeError):
    """Вызов Codex не дал пригодного ответа."""

    def __init__(self, code: str = "codex_failed", reason: str = "") -> None:
        super().__init__(code)
        self.code = code
        self.reason = reason


class CodexCli:
    """Запускает `codex exec` в одноразовом каталоге и отдаёт последнее сообщение."""

    provider = "codex"

    def __init__(
        self,
        runner: Callable[..., CompletedProcess[str]],
        *,
        work_dir: Path,
        repository_cwd: Path,
        timeout_seconds: float,
        model: str = "gpt-5.6-terra",
        reasoning_effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium",
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("model не может быть пустой")
        if reasoning_effort not in REASONING_EFFORTS:
            raise ValueError("Неизвестный reasoning effort")
        self.runner = runner
        self.work = Path(work_dir)
        self.cwd = Path(repository_cwd)
        self.timeout = timeout_seconds
        self.model = model.strip()
        self.reasoning_effort = reasoning_effort

    def complete(
        self,
        prompt: str,
        *,
        output_schema: dict[str, object] | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> str:
        """Возвращает последнее сообщение модели; при схеме это JSON-документ."""
        effort = reasoning_effort or self.reasoning_effort
        if effort not in REASONING_EFFORTS:
            raise ValueError("Неизвестный reasoning effort")
        invocation = self._invocation_dir()
        try:
            output = invocation / "output.txt"
            schema_path: Path | None = None
            if output_schema is not None:
                schema_path = invocation / "schema.json"
                schema_path.write_text(
                    json.dumps(output_schema, ensure_ascii=False), encoding="utf-8"
                )
            done = self._run(
                invocation,
                prompt,
                output,
                schema_path,
                model=(model or self.model),
                reasoning_effort=effort,
            )
            if done.returncode:
                raise CodexCallError("codex_failed", (done.stderr or "")[:500])
            try:
                return output.read_text(encoding="utf-8")
            except OSError:
                raise CodexCallError("codex_output_unavailable") from None
        finally:
            shutil.rmtree(invocation, ignore_errors=True)

    def _invocation_dir(self) -> Path:
        try:
            if _paths_overlap(self.cwd.resolve(), self.work.resolve()):
                raise OSError
            self.work.mkdir(parents=True, exist_ok=True)
            return Path(tempfile.mkdtemp(prefix="codex-", dir=self.work))
        except OSError:
            raise CodexCallError("codex_work_unavailable") from None

    def _run(
        self,
        invocation: Path,
        prompt: str,
        output: Path,
        schema: Path | None,
        *,
        model: str,
        reasoning_effort: str,
    ) -> CompletedProcess[str]:
        argv = [
            "codex",
            "exec",
            "--strict-config",
            "--model",
            model,
            "--config",
            f'model_reasoning_effort="{reasoning_effort}"',
        ]
        for tool in DISABLED_TOOLS:
            argv.extend(["--disable", tool])
        argv.extend(
            [
                "--ephemeral",
                "--sandbox",
                "read-only",
                "--ignore-rules",
                "--skip-git-repo-check",
                "--cd",
                str(invocation),
            ]
        )
        if schema is not None:
            argv.extend(["--output-schema", str(schema)])
        argv.extend(["--output-last-message", str(output), "-"])
        try:
            return self.runner(
                argv,
                input=prompt,
                text=True,
                capture_output=True,
                shell=False,
                timeout=self.timeout,
                env=codex_environment(),
            )
        except Exception:
            raise CodexCallError("codex_unavailable") from None


def codex_work_dir(repository: Path, media_dir: Path) -> Path:
    """Каталог вызовов вне репозитория и вне каталога медиа."""
    repository = repository.resolve()
    media_dir = media_dir.resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    for candidate in (temp_root / "postify-codex", temp_root.parent / "postify-codex"):
        resolved = candidate.resolve()
        if not _paths_overlap(resolved, repository) and not _paths_overlap(
            resolved, media_dir
        ):
            return resolved
    raise CodexCallError("codex_work_unavailable")


def codex_environment() -> dict[str, str]:
    language = os.environ.get("LANG", "C.UTF-8")
    return {
        "CODEX_HOME": os.environ.get("CODEX_HOME", str(Path.home() / ".codex")),
        "HOME": "/nonexistent",
        "LANG": language,
        "LC_ALL": os.environ.get("LC_ALL", language),
        "PATH": os.environ["PATH"],
    }


def _paths_overlap(first: Path, second: Path) -> bool:
    return first.is_relative_to(second) or second.is_relative_to(first)

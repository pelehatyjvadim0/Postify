from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


sys.path.insert(0, str(Path(__file__).parents[3] / "adws"))

from adw_modules import postify_quality, quality  # noqa: E402
from adw_modules.data_types import QualityCheckSpec  # noqa: E402


class _Sink:
    def __init__(self) -> None:
        self.values: list[object] = []

    def note(self, value: object) -> None:
        self.values.append(value)

    def event(self, value: object) -> None:
        self.values.append(value)


def _run(tmp_path):
    return SimpleNamespace(
        phases=[SimpleNamespace(seq=1, phase_id="quality-phase")],
        context_handoff_dir=tmp_path,
        repo_root=tmp_path,
        console=_Sink(),
        tracer=_Sink(),
        adw_id="quality-smoke",
    )


def test_universal_profile_has_real_commands_and_no_wave_manifest(tmp_path) -> None:
    specs = postify_quality.quality_specs(_run(tmp_path))
    commands = [" ".join(spec.argv) for spec in specs]

    assert {spec.name for spec in specs} == {
        "postgresql16_full_suite",
        "ruff",
        "compileall",
        "lock",
        "build_wheel",
        "diff",
        "node_api",
        "node_screens",
        "node_settings",
        "node_app",
    }
    assert all(quality._configuration_error(spec.argv) is None for spec in specs)
    assert not any("placeholder" in command.casefold() for command in commands)
    assert not any("wave-6" in command.casefold() for command in commands)
    assert not any("manifest" in command.casefold() for command in commands)


def test_full_suite_command_explicitly_selects_all_tests_without_exclusions(tmp_path) -> None:
    spec = postify_quality.test_spec()

    assert spec.argv == ["uv", "run", "pytest", "-p", "no:cacheprovider", "-q", "tests"]
    assert not any(option in spec.argv for option in ("-m", "-k", "--ignore"))
    specs = postify_quality.quality_specs(_run(tmp_path))
    assert [item.name for item in specs].count(spec.name) == 1
    for name in ("node_api", "node_screens", "node_settings", "node_app"):
        assert [item.name for item in specs].count(name) == 1


def test_placeholder_command_fails_closed_without_execution(
    tmp_path, monkeypatch
) -> None:
    def must_not_run(*args, **kwargs):
        raise AssertionError("placeholder command was executed")

    monkeypatch.setattr(quality.subprocess, "run", must_not_run)
    spec = QualityCheckSpec(
        name="placeholder",
        area="backend",
        operation="test",
        argv=["echo", "PLACEHOLDER test"],
    )

    result = quality._run(spec, _run(tmp_path))

    assert result.passed is False
    assert result.returncode == quality.NOT_CONFIGURED_EXIT
    assert "quality_check_not_configured" in result.output_tail

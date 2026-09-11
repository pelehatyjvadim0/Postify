from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from zipfile import ZipFile


def test_built_wheel_contains_baseline_alembic_head(tmp_path: Path) -> None:
    # Поломка (gate 12/re-review 7): stale build/egg-info скрывает потерянный head.
    project_root = Path(__file__).parents[3]
    isolated_source = tmp_path / "source"
    wheelhouse = tmp_path / "wheelhouse"
    shutil.copytree(
        project_root,
        isolated_source,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv",
            ".pytest_cache",
            "__pycache__",
            "build",
            "dist",
            "*.egg-info",
        ),
    )
    assert not (isolated_source / "build").exists()
    assert not (isolated_source / "src/postify.egg-info").exists()

    completed = subprocess.run(
        [
            "uv",
            "build",
            "--offline",
            "--wheel",
            "--out-dir",
            str(wheelhouse),
        ],
        cwd=isolated_source,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    wheel = next(wheelhouse.glob("postify-*.whl"))

    with ZipFile(wheel) as archive:
        names = set(archive.namelist())

    assert (
        "postify/infrastructure/database/migrations/versions/"
        "20260911_01_baseline.py"
    ) in names

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from zipfile import ZipFile


def test_clean_wheel_contains_operation_journal_modules(
    tmp_path: Path,
) -> None:
    # Поломка: clean wheel теряет durable operation journal.
    project_root = Path(__file__).parents[3]
    isolated_source = tmp_path / "source"
    wheelhouse = tmp_path / "wheelhouse"
    shutil.copytree(
        project_root,
        isolated_source,
        ignore=shutil.ignore_patterns(
            ".git", ".venv", ".pytest_cache", "__pycache__", "build", "dist", "*.egg-info"
        ),
    )

    completed = subprocess.run(
        ["uv", "build", "--offline", "--wheel", "--out-dir", str(wheelhouse)],
        cwd=isolated_source,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    with ZipFile(next(wheelhouse.glob("postify-*.whl"))) as archive:
        names = set(archive.namelist())
    assert {
        "postify/domain/observability/models.py",
        "postify/application/observability/record_operation.py",
        "postify/application/ports/observability.py",
        "postify/infrastructure/repositories/sqlalchemy_observability.py",
        "postify/infrastructure/database/migrations/versions/20260911_01_baseline.py",
    } <= names

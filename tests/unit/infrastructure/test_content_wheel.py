from __future__ import annotations

from pathlib import Path
import subprocess
from zipfile import ZipFile


def test_built_wheel_contains_wave_three_alembic_head(tmp_path: Path) -> None:
    # Поломка (gate 12): Alembic head есть в checkout, но потерян в wheel.
    completed = subprocess.run(
        [
            "uv",
            "build",
            "--offline",
            "--wheel",
            "--out-dir",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    wheel = next(tmp_path.glob("postify-*.whl"))

    with ZipFile(wheel) as archive:
        names = set(archive.namelist())

    assert (
        "postify/infrastructure/database/migrations/versions/"
        "20260808_03_add_content_packages.py"
    ) in names

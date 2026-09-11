from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
from zipfile import ZipFile


def test_clean_wheel_contains_delivery_modules_and_new_alembic_head(tmp_path: Path) -> None:
    # Поломка: wheel теряет migration/repository/action/adapter и hermetic install не запустится.
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
        "postify/domain/delivery/models.py",
        "postify/application/delivery/publish_content.py",
        "postify/application/ports/delivery_repository.py",
        "postify/application/ports/telegram_publisher.py",
        "postify/adapters/telegram/bot_api.py",
        "postify/infrastructure/repositories/sqlalchemy_delivery.py",
        "postify/infrastructure/database/migrations/versions/20260911_01_baseline.py",
    } <= names

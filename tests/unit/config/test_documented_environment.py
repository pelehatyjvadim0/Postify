from __future__ import annotations

import os
from pathlib import Path
import subprocess


ROOT = Path(__file__).parents[3]


def test_documented_environment_loading_preserves_spaced_values(tmp_path: Path) -> None:
    environment_file = tmp_path / ".env"
    environment_file.write_text((ROOT / ".env.example").read_text())

    result = subprocess.run(
        [
            "sh",
            "-c",
            'set -a; . "$1"; set +a; printf "%s\\n%s\\n" "$POSTIFY_ON_CALENDAR" "$SELECTION_AUDIENCE"',
            "sh",
            str(environment_file),
        ],
        check=True,
        capture_output=True,
        text=True,
        env={"PATH": os.environ["PATH"]},
    )

    assert result.stdout.splitlines() == [
        "0 9 * * 1-5",
        "Читатели практических материалов",
    ]


def test_documented_pg_dump_target_strips_sqlalchemy_driver_safely() -> None:
    result = subprocess.run(
        [
            "sh",
            "-c",
            'DATABASE_URL="postgresql+psycopg://postify:secret@db:5432/postify"; '
            'PG_DUMP_DATABASE_URL="postgresql:${DATABASE_URL#postgresql+psycopg:}"; '
            'printf "%s" "$PG_DUMP_DATABASE_URL"',
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout == "postgresql://postify:secret@db:5432/postify"

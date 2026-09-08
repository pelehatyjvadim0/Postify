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
            'set -a; . "$1"; set +a; printf "%s\\n%s\\n" "$CONTENT_ANALYZER" "$CONTENT_MODEL"',
            "sh",
            str(environment_file),
        ],
        check=True,
        capture_output=True,
        text=True,
        env={"PATH": os.environ["PATH"]},
    )

    assert result.stdout.splitlines() == [
        "codex",
        "gpt-5.6-terra",
    ]

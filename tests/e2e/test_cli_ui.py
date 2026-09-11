from __future__ import annotations

import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from zipfile import ZipFile

import httpx
import pytest
from sqlalchemy import create_engine, text


ROOT = Path(__file__).parents[2]

pytestmark = pytest.mark.integration


def _subprocess_environment(temporary_directory: Path) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", os.defpath),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TMPDIR": str(temporary_directory),
        # Build tooling may reuse downloaded distributions, while application
        # configuration below remains an explicit allowlist.
        "UV_CACHE_DIR": os.environ.get("UV_CACHE_DIR", str(Path.home() / ".cache/uv")),
    }


def _schema_url(database_url: str, schema_name: str) -> str:
    parts = urlsplit(database_url)
    query = parse_qs(parts.query)
    options = query.get("options", []) + [f"-csearch_path={schema_name}"]
    query["options"] = options
    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), "")
    )


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _runtime_environment(database_url: str, media_dir: Path) -> dict[str, str]:
    environment = _subprocess_environment(media_dir.parent)
    environment.update(
        {
            "DATABASE_URL": database_url,
            "DATABASE_READINESS_TIMEOUT_SECONDS": "5",
            "RUN_ONCE_WAIT_TIMEOUT_SECONDS": "5",
            "POSTIFY_ON_CALENDAR": "0 7 * * 1-5",
            "POSTIFY_TIMEZONE": "Europe/Moscow",
            "PROJECT_TOPIC": "python",
            "PROJECT_LANGUAGE": "ru",
            "PROJECT_AUDIENCE": "Тестовая аудитория",
            "CONTENT_BATCH_SIZE": "12",
            "CONTENT_MEDIA_DIR": str(media_dir),
            "CONTENT_MEDIA_MAX_BYTES": "10000000",
            "CONTENT_ANALYSIS_TIMEOUT_SECONDS": "600",
        }
    )
    return environment


def _migrate_installed_wheel(python: Path, environment: dict[str, str]) -> None:
    migration = """
import os
from importlib.resources import as_file, files
from pathlib import Path
from alembic import command
from alembic.config import Config
import postify

assert Path(postify.__file__).is_relative_to(Path(os.environ['POSTIFY_INSTALLED_WHEEL_DIR']))
with as_file(files('postify.infrastructure.database.migrations')) as path:
    config = Config()
    config.set_main_option('script_location', str(path))
    command.upgrade(config, 'head')
"""
    result = subprocess.run(
        [str(python), "-c", migration],
        cwd=python.parents[2],
        env={**environment, "POSTIFY_ALEMBIC_DATABASE_URL": environment["DATABASE_URL"]},
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def _wait_for_response(url: str, process: subprocess.Popen[str]) -> httpx.Response:
    deadline = time.monotonic() + 15
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise AssertionError(f"postify ui завершился с кодом {process.returncode}")
        try:
            return httpx.get(url, timeout=0.5)
        except httpx.HTTPError as error:
            last_error = error
            time.sleep(0.05)
    raise AssertionError(f"postify ui не ответил: {type(last_error).__name__}")


def test_installed_wheel_migrates_and_serves_complete_ui_outside_checkout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Break caught: wheel UI works only from the checkout, misses an asset/migration,
    # starts without creating the configured project, or consumes caller secrets.
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        raise RuntimeError("Для wheel e2e требуется TEST_DATABASE_URL")

    ambient_token = "ambient-token-must-not-be-persisted"
    ambient_query = "ambient-query-must-not-bootstrap"
    monkeypatch.setenv(
        "POSTIFY_SECRET_KEY", "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
    )
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", ambient_token)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "ambient-chat-must-not-bootstrap")
    monkeypatch.setenv("TELEGRAM_TIMEOUT_SECONDS", "99")
    monkeypatch.setenv("HN_QUERY", ambient_query)
    monkeypatch.setenv("HN_ALGOLIA_URL", "https://ambient.example.invalid/search")
    monkeypatch.setenv("POSTIFY_TIMEZONE", "UTC")

    schema_name = f"postify_wheel_{os.urandom(8).hex()}"
    admin_engine = create_engine(database_url)
    with admin_engine.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema_name}"'))

    try:
        wheelhouse = tmp_path / "wheelhouse"
        tool_environment = {
            **_subprocess_environment(tmp_path),
            "UV_NO_CONFIG": "1",
        }
        subprocess.run(
            ["uv", "build", "--offline", "--wheel", "--out-dir", str(wheelhouse)],
            cwd=ROOT,
            env=tool_environment,
            check=True,
            capture_output=True,
            text=True,
        )
        wheel = next(wheelhouse.glob("postify-*.whl"))
        with ZipFile(wheel) as archive:
            names = set(archive.namelist())
        assert {
            "postify/web/static/index.html",
            "postify/infrastructure/database/migrations/env.py",
            (
                "postify/infrastructure/database/migrations/versions/"
                "20260812_07_add_schedule_slot_claims.py"
            ),
        } <= names
        # Имена файлов сборки фронтенда содержат хеш и меняются при каждой
        # пересборке, поэтому проверяется наличие, а не конкретное имя.
        assert any(
            name.startswith("postify/web/static/assets/") and name.endswith(".js")
            for name in names
        )
        assert any(
            name.startswith("postify/web/static/assets/") and name.endswith(".css")
            for name in names
        )

        installed = tmp_path / "installed-wheel"
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--offline",
                "--no-deps",
                "--target",
                str(installed),
                str(wheel),
            ],
            env=tool_environment,
            check=True,
            capture_output=True,
            text=True,
        )

        outside_checkout = tmp_path / "runtime"
        outside_checkout.mkdir()
        assert not outside_checkout.resolve().is_relative_to(ROOT.resolve())
        isolated_url = _schema_url(database_url, schema_name)
        environment = _runtime_environment(isolated_url, tmp_path / "media")
        environment["PYTHONPATH"] = str(installed)
        environment["POSTIFY_INSTALLED_WHEEL_DIR"] = str(installed)
        python = Path(sys.executable)
        _migrate_installed_wheel(python, environment)

        port = _free_port()
        log_path = tmp_path / "postify-ui.log"
        with log_path.open("w") as log:
            process = subprocess.Popen(
                [
                    str(Path(sys.prefix) / "bin" / "postify"),
                    "ui",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=outside_checkout,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )
            try:
                root = _wait_for_response(f"http://127.0.0.1:{port}/", process)
                stylesheet = re.search(
                    r'href="\./(assets/[^"]+\.css)"', root.text
                )
                assert stylesheet is not None
                styles = httpx.get(
                    f"http://127.0.0.1:{port}/static/{stylesheet.group(1)}",
                    timeout=2,
                )
                bootstrap = httpx.get(
                    f"http://127.0.0.1:{port}/api/v1/bootstrap", timeout=2
                )
                settings = httpx.get(
                    f"http://127.0.0.1:{port}/api/v1/projects/1/settings",
                    timeout=2,
                )

                assert root.status_code == 200
                assert "AutoPostTG" in root.text
                assert styles.status_code == 200
                assert "--background" in styles.text
                assert bootstrap.status_code == 200
                active_project = bootstrap.json()["activeProject"]
                assert active_project["id"] == 1
                assert active_project["topic"] == "python"
                assert active_project["timezone"] == "Europe/Moscow"
                assert ambient_query not in bootstrap.text
                assert ambient_token not in bootstrap.text
                assert settings.status_code == 200
                stored_settings = settings.json()
                assert stored_settings["channels"] == []
                assert stored_settings["routes"] == []
                assert stored_settings["sources"] == []
                assert ambient_query not in settings.text
                assert ambient_token not in settings.text
                assert "secretConfigured" not in settings.text
            finally:
                process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)

        assert process.returncode == 0, log_path.read_text()
        with admin_engine.connect() as connection:
            assert connection.execute(
                text(f'SELECT count(*) FROM "{schema_name}".channel_connections')
            ).scalar_one() == 0
            assert connection.execute(
                text(f'SELECT count(*) FROM "{schema_name}".publication_routes')
            ).scalar_one() == 0
            assert connection.execute(
                text(
                    f'SELECT count(*) FROM "{schema_name}".channel_connections '
                    "WHERE encrypted_secret IS NOT NULL"
                )
            ).scalar_one() == 0
    finally:
        with admin_engine.begin() as connection:
            connection.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        admin_engine.dispose()

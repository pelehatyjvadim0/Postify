"""Запуск единственного UI/scheduler процесса внутри контейнера."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

from cryptography.fernet import Fernet


def main() -> None:
    # Единственный способ войти — Telegram-бот авторизации. Без его токена
    # приложение поднимать бессмысленно: попасть внутрь будет нечем.
    if not os.environ.get("AUTH_BOT_TOKEN"):
        raise RuntimeError(
            "Не задан AUTH_BOT_TOKEN: без бота авторизации вход в приложение невозможен"
        )
    # Ключ принадлежит этому контуру и переживает перезапуск вместе с volume.
    if not os.environ.get("POSTIFY_SECRET_KEY"):
        key_path = Path("/data/secret.key")
        try:
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "wb") as stream:
                stream.write(Fernet.generate_key())
        os.environ["POSTIFY_SECRET_KEY"] = key_path.read_text().strip()
    os.environ["POSTIFY_ALEMBIC_DATABASE_URL"] = os.environ["DATABASE_URL"]
    subprocess.run(["alembic", "upgrade", "head"], check=True)
    argv = [
        "uvicorn", "postify.web.app:create_app", "--factory",
        "--host", os.environ.get("AUTOPOST_LISTEN_HOST", "0.0.0.0"),
        "--port", os.environ.get("AUTOPOST_LISTEN_PORT", "8000"), "--workers", "1",
    ]
    if os.environ.get("AUTOPOST_RELOAD") == "1":
        argv.extend(["--reload", "--reload-dir", "/app/src"])
    os.execvp(argv[0], argv)


if __name__ == "__main__":
    main()

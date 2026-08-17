"""Небольшие общие вспомогательные функции. Всё более крупное должно быть в отдельном модуле."""

from __future__ import annotations

import os
import secrets
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def operator_env() -> dict[str, str]:
    """Собственное окружение инженера в том виде, в каком его передал бы shell.

    Агенты и блоки качества должны видеть в точности то, что видит оператор:
    его PATH, toolchain и глобально установленные пакеты. Копирование os.environ
    почти даёт это, однако ADW запускаются через `uv run`, который добавляет bin
    своего временного venv в начало PATH и устанавливает VIRTUAL_ENV. Этот venv
    содержит СОБСТВЕННЫЕ зависимости ADW (pydantic, pyyaml), а не зависимости
    оператора, поэтому всё, что subprocess разрешает через него — `python3`,
    `pip`, любой глобально установленный через pip CLI — незаметно становится
    неправильным.

    Удаление venv восстанавливает эквивалентность: `python3` в bash агента —
    тот же `python3`, который инженер получает в терминале. На собственные
    импорты ADW это не влияет: это окружение передаётся только дочерним процессам.
    """
    env = os.environ.copy()
    venv = env.pop("VIRTUAL_ENV", "")
    if not venv:
        return env
    venv_bin = str(Path(venv) / "bin")
    parts = [p for p in env.get("PATH", "").split(os.pathsep) if p and p != venv_bin]
    env["PATH"] = os.pathsep.join(parts)
    return env


def new_id(length: int = 8) -> str:
    return secrets.token_hex(length // 2)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def ensure_dir(path: str | Path) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def resolve_prompt(arg: str) -> str:
    """Аргумент prompt CLI: путь к файлу разрешается в его содержимое, иначе это встроенный текст."""
    try:
        p = Path(arg)
        if p.is_file():
            return p.read_text()
    except OSError:
        pass
    return arg


def engineer_name() -> str:
    name = os.environ.get("ENGINEER_NAME", "").strip()
    if name:
        return name
    try:
        out = subprocess.run(["git", "config", "user.name"],
                             capture_output=True, text=True, timeout=5)
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except OSError:
        pass
    return os.environ.get("USER", "engineer")

"""Низкоуровневые операции git для фаз кода. Вся низкоуровневая логика находится в adw_modules."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _git(*args: str) -> str:
    result = subprocess.run(["git", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout.strip()


def current_branch() -> str:
    return _git("rev-parse", "--abbrev-ref", "HEAD")


def create_branch(name: str) -> str:
    _git("checkout", "-b", name)
    return name


def is_repo() -> bool:
    result = subprocess.run(["git", "rev-parse", "--git-dir"],
                            capture_output=True, text=True)
    return result.returncode == 0


def repo_root() -> Path:
    """Абсолютный корень кодовой базы — место, где запускаются агенты.

    Верхний уровень git, если он существует, иначе cwd процесса (ADW нормально
    работают вне git-каталога; репозиторий нужен лишь фазе коммита). Путь всегда
    абсолютный, поэтому его безопасно передавать subprocess независимо от места
    запуска ADW.
    """
    if is_repo():
        return Path(_git("rev-parse", "--show-toplevel")).resolve()
    return Path.cwd().resolve()


def commit_all(message: str) -> str:
    """Добавить рабочее дерево в индекс и закоммитить его. Вернуть новый короткий sha."""
    if not is_repo():
        raise RuntimeError(
            "not a git repository — a commit phase needs one. Run `git init` in the "
            "repo root (and make a first commit) before running an ADW that commits.")
    _git("add", "-A")
    if not _git("status", "--porcelain"):
        raise RuntimeError("nothing to commit — the preceding phases changed no files")
    _git("commit", "-m", message)
    return _git("rev-parse", "--short", "HEAD")


def changed_files() -> list[str]:
    out = _git("status", "--porcelain")
    return [line[3:] for line in out.splitlines() if line]


# ── служебные функции diff (собираются в ChangeSet через documentation.py) ───

def ref_exists(ref: str) -> bool:
    """True, если `ref` разрешается в коммит. Исключений не вызывает: это проверка."""
    result = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
                            capture_output=True, text=True)
    return result.returncode == 0


def rev(ref: str = "HEAD") -> str:
    return _git("rev-parse", ref)


def short_sha(ref: str = "HEAD") -> str:
    return _git("rev-parse", "--short", ref)


def merge_base(ref: str, other: str = "HEAD") -> str:
    """Коммит расхождения `ref` и `other` — честная база ветки.

    На самой базовой ветке возвращается HEAD, то есть diff точно описывает
    «что ещё не закоммичено». Вне неё diff включает всю ветку и рабочее дерево.
    Одна команда покрывает оба случая, поэтому ADW не требуется ветвиться по ним.
    """
    return _git("merge-base", ref, other)


def is_dirty() -> bool:
    return bool(_git("status", "--porcelain"))


def untracked_files() -> list[str]:
    out = _git("ls-files", "--others", "--exclude-standard")
    return [line for line in out.splitlines() if line]


def diff_files(base: str) -> list[str]:
    """Отслеживаемые файлы, отличающиеся между `base` и рабочим деревом."""
    out = _git("diff", "--name-only", base)
    return [line for line in out.splitlines() if line]


def diff_stat(base: str) -> str:
    return _git("diff", "--stat", base)


def diff_counts(base: str) -> tuple[int, int]:
    """(вставки, удаления) во всём diff. Бинарные файлы не считаются ни тем, ни другим."""
    insertions = deletions = 0
    for line in _git("diff", "--numstat", base).splitlines():
        added, removed, *_ = line.split("\t")
        if added.isdigit():
            insertions += int(added)
        if removed.isdigit():
            deletions += int(removed)
    return insertions, deletions


def diff_text(base: str) -> str:
    return _git("diff", base)

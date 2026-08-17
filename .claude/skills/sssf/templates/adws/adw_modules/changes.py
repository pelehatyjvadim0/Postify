"""Детерминированная фиксация изменений: что было создано, напрямую из git.

«Что изменилось после main» не требует суждения: это две команды git и
вычитание. Поэтому это код, а агент получает лишь результат. Фиксация записывает
полный diff в `context_handoff/` и возвращает ChangeSet; `as_envelope` адаптирует
его к единому формату передачи между агентами.

База разрешается, а не предполагается. Вне базовой ветки diff охватывает всю
ветку и рабочее дерево; на ней — незафиксированное дерево; а для чистого дерева —
последний коммит, поскольку «документировать только что выполненную работу»
имеет ответ даже сразу после коммита цепочки. Выбранная причина сохраняется в
`BaseRef.reason`, поэтому трассировка всегда показывает, относительно чего измерен diff.
"""

from __future__ import annotations

from . import git_helper
from .data_types import BaseRef, ChangeCapture, ChangeSet, ChangesOutput

DIFF_FILENAME = "changes.diff"


def resolve_base(ref: str) -> BaseRef:
    """Выбрать коммит, от которого измеряется работа, и записать причину выбора."""
    if not git_helper.is_repo():
        raise RuntimeError(
            "not a git repository — change capture needs one. Run `git init` in "
            "the repo root before running an ADW that documents a change.")
    if not git_helper.ref_exists(ref):
        raise RuntimeError(
            f"base ref {ref!r} does not exist in this repository — pass --base "
            f"with a ref that does (e.g. --base master, --base HEAD~1).")

    # Сначала создаётся, затем получает причину: BaseRef.label умеет вывести
    # закреплённый sha, а причина — строка, которую человек читает в трассировке.
    base = BaseRef(ref=ref, commit=git_helper.merge_base(ref, "HEAD"))
    if git_helper.short_sha(base.commit) != git_helper.short_sha("HEAD"):
        base.reason = (f"HEAD is ahead of {base.label} — diffing every commit since, "
                       f"plus the working tree")
    elif git_helper.is_dirty():
        base.reason = f"HEAD is on {base.label} — diffing the uncommitted working tree"
    elif git_helper.ref_exists("HEAD~1"):
        base.commit = git_helper.rev("HEAD~1")
        base.reason = (f"HEAD is on {base.label} with a clean tree — falling back to "
                       f"the last commit")
    else:
        base.reason = f"HEAD is on {base.label} with a clean tree and no parent commit"
    return base


def capture(run, params: ChangeCapture) -> ChangeSet:
    """Сравнить рабочее дерево с разрешённой базой и сохранить доказательства."""
    base = resolve_base(params.base)
    files = git_helper.diff_files(base.commit)
    untracked = git_helper.untracked_files() if params.include_untracked else []
    insertions, deletions = git_helper.diff_counts(base.commit)
    stat = git_helper.diff_stat(base.commit)

    text = git_helper.diff_text(base.commit)
    lines = text.splitlines()
    truncated = len(lines) > params.max_diff_lines
    if truncated:
        text = "\n".join(lines[:params.max_diff_lines])
        text += (f"\n\n[truncated at {params.max_diff_lines} lines of "
                 f"{len(lines)} — run `git diff {base.commit}` for the rest]")

    # Неотслеживаемые файлы по определению отсутствуют в `git diff`, поэтому
    # здесь они перечисляются, а не молча пропадают из записи. Читатель имеет
    # `read` и может открыть любой из них.
    untracked_block = ("\n".join(f"  {f}" for f in untracked) if untracked
                       else "  (none)")
    diff_path = run.context_handoff_dir / DIFF_FILENAME
    diff_path.write_text(
        f"# changes since {base.label} @ {git_helper.short_sha(base.commit)}\n"
        f"# {base.reason}\n"
        f"# +{insertions} -{deletions} across {len(files)} tracked file(s)\n\n"
        f"## stat\n{stat or '  (no tracked changes)'}\n\n"
        f"## untracked files\n{untracked_block}\n\n"
        f"## diff\n{text}\n")

    return ChangeSet(base=base, files=files, untracked=untracked,
                     insertions=insertions, deletions=deletions, stat=stat,
                     diff_path=str(diff_path), truncated=truncated)


def as_envelope(changes: ChangeSet, notes: str = "") -> ChangesOutput:
    """Обернуть зафиксированное изменение, чтобы его можно было передать агенту напрямую."""
    total = len(changes.files) + len(changes.untracked)
    return ChangesOutput(
        status="success",
        summary=(f"{total} file(s) changed since {changes.base.label} "
                 f"(+{changes.insertions} -{changes.deletions})"),
        artifacts=[changes.diff_path],
        notes_for_next_agent=notes,
        base=f"{changes.base.label} @ {git_helper.short_sha(changes.base.commit)} "
             f"— {changes.base.reason}",
        changed_files=changes.files + changes.untracked,
        insertions=changes.insertions,
        deletions=changes.deletions,
        stat=changes.stat,
        diff_path=changes.diff_path,
    )

"""Что агент может ИЗМЕНЯТЬ; проверяется кодом после совершения действия.

`tools:` — список возможностей, а не песочница. Сам по себе он не обеспечивает
контроль из-за двух уязвимостей:

  * `bash` запускает что угодно. Разработчик, получивший bash для запуска тестов,
    может выполнить и `git checkout adws/`. Это не гипотетический случай: так уже
    отбрасывались незакоммиченные изменения именно той проверки качества, по
    которой агенту предстояло оцениваться.
  * `write` работает с любым путём, а не только с файлом отчёта, для которого он
    был выдан. Ревьюер, настроенный как «без редактирования, чтобы не исправлять
    код молча», всё равно мог бы переписать проверяемый код.

Поэтому права проверяются так же, как любое другое утверждение системы: по факту
и относительно самого репозитория. `snapshot()` фиксирует набор изменений дерева
до запуска агента; `enforce()` сравнивает его после и завершает фазу ошибкой, если
агент затронул что-либо за пределами allowlist.

Сравнение наборов изменений, а не наблюдение за записями, ловит `git checkout`:
путь, изменённый до запуска агента и чистый после него, был возвращён в исходное
состояние, а откат — это тоже изменение. Появление, исчезновение и правка равно
учитываются.

Нарушение прав — НЕ нарушение gate. Gate предназначены для работы, которую можно
попросить агента переделать; нарушение нельзя исправить повторным prompt, потому
что запись уже произошла. Оно прерывает фазу и называет все недопустимые пути.

Его определяют два ключа в sssf.config.yaml:
    defaults.protected_files   пути, которые агент не может трогать, пока не укажет их сам
    agents[].writes      None = без ограничений · [] = только чтение · [...] = только эти пути
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from .data_types import AgentConfig, SSSFConfig


class PermissionBreach(RuntimeError):
    """Агент изменил путь, который не имел права изменять."""


def _git(args: list[str], cwd) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    return result.stdout if result.returncode == 0 else ""


def snapshot(run) -> dict[str, str]:
    """Сформировать отпечаток каждого пути, по которому рабочее дерево отличается.

    Отслеживаемые файлы несут значения numstat, поэтому правка уже изменённого
    файла всё равно регистрируется. Неотслеживаемые файлы перечисляются по имени.
    Игнорируемые Git пути никогда не появляются; поэтому runtime сессии в
    `data_dir`, куда законно попадают файлы передачи, не требует особого случая.
    """
    fingerprints: dict[str, str] = {}
    for line in _git(["diff", "HEAD", "--numstat"], run.repo_root).splitlines():
        fields = line.split("\t")
        if len(fields) >= 3:
            path = fields[-1].strip()
            fingerprints[path] = f"{fields[0]},{fields[1]}"
    for path in _git(["ls-files", "--others", "--exclude-standard"],
                     run.repo_root).splitlines():
        if path.strip():
            fingerprints[path.strip()] = "untracked"
    return fingerprints


def changed_paths(before: dict[str, str], after: dict[str, str]) -> list[str]:
    """Каждый путь с другим состоянием: появившийся, исчезнувший или переписанный."""
    return sorted({p for p in set(before) | set(after)
                   if before.get(p) != after.get(p)})


def _glob(pattern: str) -> re.Pattern:
    """Преобразовать шаблон, где `*` останавливается на разделителе пути.

    fnmatch позволил бы `*` пересекать `/`, незаметно расширяя каждый шаблон:
    `adws/adw_*.py` совпал бы с `adws/adw_data/sessions/x/y.py`, а не только
    со скриптами ADW, которые имеются в виду. `**` означает «пересекать каталоги».
    """
    out, i = [], 0
    while i < len(pattern):
        char = pattern[i]
        if pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif char == "*":
            out.append("[^/]*")
            i += 1
        elif char == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(char))
            i += 1
    return re.compile("".join(out))


def _matches(path: str, pattern: str) -> bool:
    if pattern.endswith("/"):                      # префикс каталога
        return path.startswith(pattern)
    if "*" in pattern or "?" in pattern:
        return _glob(pattern).fullmatch(path) is not None
    return path == pattern


def always_writable(cfg: SSSFConfig) -> list[str]:
    """Runtime сессии, в который должен иметь возможность писать КАЖДЫЙ агент.

    `context_handoff/` — единое место передачи работы между агентами; рядом
    лежат собственные prompt агента, raw_output.jsonl и envelope.json. Scout
    пишет туда выводы, ревьюер — ревью, планировщик — план. Агент только для
    чтения ограничен относительно РЕПОЗИТОРИЯ, но не относительно своего отчёта.

    Право выдаётся через `data_dir`, а не оставляется на усмотрение .gitignore.
    Обычно runtime игнорируется и не появляется в snapshot, но способность агента
    записать результат не должна зависеть от записи gitignore, которую можно
    удалить или которая не охватит изменённый `data_dir`.
    """
    return [cfg.defaults.data_dir.rstrip("/") + "/"]


def permitted(path: str, agent: AgentConfig, cfg: SSSFConfig) -> bool:
    """Сначала runtime сессии, затем собственный список агента, затем защищённые пути."""
    if any(_matches(path, p) for p in always_writable(cfg)):
        return True
    if any(_matches(path, p) for p in (agent.writes or [])):
        return True                      # указание пути открывает доступ к защищённому пути
    if any(_matches(path, p) for p in cfg.defaults.protected_files):
        return False
    return agent.writes is None          # None = без ограничений, [] = без записей в репозиторий


def _roll_back(run, path: str, before: dict[str, str], after: dict[str, str]) -> str:
    """Отменить одно неразрешённое изменение. Возвращает описание результата.

    Отменяются только изменения, ВНЕСЁННЫЕ агентом. Путь, уже изменённый до
    запуска агента, остаётся как есть: у оператора там была незакоммиченная
    работа, и её удаление ради уборки нанесло бы тот же ущерб, который модуль
    призван предотвращать, только виноват был бы cleanup, а не агент.
    """
    if path in before:
        # Уже был изменён. Если теперь его нет в diff, агент откатил
        # незакоммиченную работу инженера, и содержимое не в нашей власти
        # восстановить — сообщаем об этом явно, а не притворяемся, что исправили.
        return "REVERTED-BY-AGENT (uncommitted work lost, cannot restore)" \
            if path not in after else "left as-is (was already modified)"
    if after.get(path) == "untracked":
        try:
            (Path(run.repo_root) / path).unlink()
            return "deleted"
        except OSError as error:
            return f"could not delete ({error})"
    result = subprocess.run(["git", "checkout", "--", path],
                            cwd=run.repo_root, capture_output=True, text=True)
    return "rolled back" if result.returncode == 0 else "could not roll back"


def enforce(run, phase, agent: AgentConfig, before: dict[str, str]) -> list[str]:
    """Сравнить дерево с `before`; отменить изменение и выбросить ошибку при нарушении.

    Возвращает пути, законно изменённые агентом, чтобы трасса записывала то, что
    агент действительно затронул, а не только заявленное в его конверте.

    Простое обнаружение оставило бы в репозитории неразрешённое изменение при
    сообщении о сбое, поэтому всё добавленное агентом вне allowlist откатывается
    до завершения фазы. То, что отменить нельзя, указывается в отчёте.
    """
    after = snapshot(run)
    touched = changed_paths(before, after)
    breaches = [p for p in touched if not permitted(p, agent, run.cfg)]
    if not breaches:
        return touched

    outcomes = {p: _roll_back(run, p, before, after) for p in breaches}
    scope = ("read-only" if agent.writes == []
             else f"limited to {agent.writes}" if agent.writes
             else f"barred from {run.cfg.defaults.protected_files}")
    detail = "\n".join(f"  - {p} — {outcome}" for p, outcome in outcomes.items())
    raise PermissionBreach(
        f"{agent.name} is {scope} but modified {len(breaches)} path(s):\n{detail}")

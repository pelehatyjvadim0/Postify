"""Детерминированные блоки lint, typecheck, build и test.

Известная команда не требует суждения. Всё, чей вызов можно записать, должно
быть кодом здесь: это выполняется за миллисекунды, ничего не стоит и всегда
даёт один и тот же ответ. Агенты нужны для частей, где требуется читать и решать.

╔══════════════════════════════════════════════════════════════════════════════╗
║  ЗАМЕНИТЕ НИЖЕ КОМАНДЫ-ЗАПОЛНИТЕЛИ.                                          ║
║                                                                              ║
║  Каждый блок поставляется с `echo`, который завершается с 0 и сообщает, что   ║
║  он ненастоящий. Это намеренные заполнители: шаблонный репозиторий не может   ║
║  угадать ваш тестовый раннер, а ошибочная, но правдоподобная команда,         ║
║  молча завершающаяся успешно, хуже команды, которая прямо говорит об этом.   ║
║                                                                              ║
║  Для нужного блока замените `_placeholder(...)` на настоящий argv, например:  ║
║      argv=["bun", "test", "apps/web/server.test.ts"]                         ║
║      argv=["uv", "run", "pytest", "-q"]                                      ║
║      argv=["npm", "run", "lint"]                                             ║
║  Удалите ненужные блоки и уберите их из списка run_quality().                 ║
║                                                                              ║
║  Два правила для настоящей команды:                                          ║
║    1. Используйте СПИСОК argv, а не строку shell: без ошибок кавычек и       ║
║       shell-инъекций.                                                         ║
║    2. Вызывайте бинарники по ПРОСТОМУ ИМЕНИ. Блоки наследуют окружение        ║
║       оператора (см. utils.operator_env), поэтому `bun`, `uv`, `pytest`      ║
║       разрешаются так же, как в его терминале. Никогда не указывайте         ║
║       абсолютный путь, например /Users/you/.bun/bin/bun: это привязывает     ║
║       трассировку к вашей машине.                                             ║
╚══════════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import shlex
import subprocess
import time
from pathlib import Path
from typing import Callable

from .data_types import (EventRecord, QualityCheckResult, QualityCheckSpec, QualityResult,
                         VerifyOutput)
from .utils import now_iso, operator_env

# Какая часть вывода упавшей команды возвращается в конверте. Её достаточно,
# чтобы builder действовал без открытия артефакта; ограничение не даёт длинному
# стек-трейсу переполнить контекст следующего агента.
TAIL_CHARS = 4_000


def _placeholder(name: str) -> list[str]:
    """Команда, которая ничего не делает и прямо об этом сообщает. Замените каждый её вызов."""
    return ["echo", f"PLACEHOLDER {name}: edit adws/adw_modules/quality.py and "
                    f"replace this echo with the real {name} command"]


def _check_dir(run, name: str) -> Path:
    seq = run.phases[-1].seq if run.phases else 0
    path = run.context_handoff_dir / "quality" / f"{seq:02d}_{name}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run(spec: QualityCheckSpec, run) -> QualityCheckResult:
    phase = run.phases[-1]
    output_dir = _check_dir(run, spec.name)
    output_artifact = output_dir / "command.log"
    command = shlex.join(spec.argv)
    env = operator_env()             # собственное окружение shell инженера

    run.console.note(f"quality {spec.name}: {command}")
    started_at = now_iso()
    clock = time.monotonic()
    stdout = ""
    stderr = ""
    try:
        completed = subprocess.run(
            spec.argv,
            cwd=run.repo_root,
            env=env,
            capture_output=True,
            text=True,
            timeout=spec.timeout_seconds,
        )
        returncode = completed.returncode
        stdout = completed.stdout
        stderr = completed.stderr
    except subprocess.TimeoutExpired as error:
        returncode = 124
        stdout = error.stdout or ""
        stderr = (error.stderr or "") + f"\nTimed out after {spec.timeout_seconds}s."
    except OSError as error:
        # Отсутствующий бинарник попадает сюда с кодом 127 и настоящим сообщением:
        # предварительная проверка не нужна и не желательна.
        returncode = 127
        stderr = str(error)

    duration = time.monotonic() - clock
    output_artifact.write_text(
        f"$ {command}\nexit: {returncode}\nduration_seconds: {duration:.3f}\n"
        f"\n--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}\n"
    )
    passed = returncode == 0
    run.tracer.event(EventRecord(
        adw_id=run.adw_id,
        phase_id=phase.phase_id,
        type="tool_call",
        name=f"quality:{spec.name}",
        payload={
            "area": spec.area,
            "operation": spec.operation,
            "command": command,
            "returncode": returncode,
            "passed": passed,
            "output_artifact": str(output_artifact),
        },
        started_at=started_at,
        ended_at=now_iso(),
    ))
    run.console.note(
        f"quality {spec.name}: {'passed' if passed else 'failed'} "
        f"(exit {returncode}, {duration:.1f}s)"
    )
    return QualityCheckResult(
        name=spec.name,
        area=spec.area,
        operation=spec.operation,
        command=command,
        returncode=returncode,
        passed=passed,
        duration_seconds=duration,
        output_artifact=str(output_artifact),
        output_tail=(stdout + stderr)[-TAIL_CHARS:],
    )


# ── Блоки ────────────────────────────────────────────────────────────────────
# Замените каждый argv ниже. См. баннер в начале этого файла.

def test(run) -> QualityCheckResult:
    """Запустить тестовый набор проекта. Этот блок важнее всего подключить первым."""
    return _run(QualityCheckSpec(
        name="test",
        area="backend",
        operation="build",
        argv=_placeholder("test"),        # например, ["bun", "test"] или ["uv", "run", "pytest", "-q"]
        timeout_seconds=600,
    ), run)


def lint(run) -> QualityCheckResult:
    return _run(QualityCheckSpec(
        name="lint",
        area="backend",
        operation="lint",
        argv=_placeholder("lint"),        # например, ["bun", "x", "oxlint@1.36.0", "src"]
    ), run)


def typecheck(run) -> QualityCheckResult:
    return _run(QualityCheckSpec(
        name="typecheck",
        area="backend",
        operation="typecheck",
        argv=_placeholder("typecheck"),   # например, ["bun", "x", "tsc", "--noEmit"]
    ), run)


def build(run) -> QualityCheckResult:
    output_dir = _check_dir(run, "build") / "bundle"
    return _run(QualityCheckSpec(
        name="build",
        area="backend",
        operation="build",
        argv=_placeholder("build"),       # например, ["bun", "build", "src/index.ts", "--outdir", str(output_dir)]
    ), run)


def run_tests(run) -> QualityResult:
    """Только тестовый набор в виде QualityResult — детерминированная фаза тестов.

    Это заменяет агента `tester`, когда команда уже записана. Агент, заново
    определяющий раннер в каждом запуске, дорого выясняет то, что уже знает
    subprocess; цикл исправления не меняется, поскольку сбой всё ещё достигает
    builder через `as_envelope` ниже.
    """
    check = test(run)
    failures = ([] if check.passed else
                [f"{check.name}: `{check.command}` exited {check.returncode}\n"
                 f"{check.output_tail}".rstrip()])
    return QualityResult(passed=check.passed, checks=[check], failures=failures,
                         artifacts=[check.output_artifact])


def as_envelope(result: QualityResult, what: str) -> VerifyOutput:
    """Обернуть детерминированный результат, чтобы его можно было передать агенту напрямую.

    Агенты передают друг другу типизированные конверты, а блоки кода возвращают
    QualityResult. Это адаптер: упавший lint или тест возвращается в builder
    через ту же точку, что и отчёт агента; разницу знает только скрипт ADW.
    """
    return VerifyOutput(
        status="success" if result.passed else "fail",
        summary=(f"{what}: all {len(result.checks)} check(s) passed" if result.passed
                 else f"{what}: {len(result.failures)} of {len(result.checks)} check(s) failed"),
        artifacts=result.artifacts,
        notes_for_next_agent=("" if result.passed else
                              "Fix every failure below. The output is verbatim from the "
                              "command — trust it over any summary."),
        passed=result.passed,
        failures=result.failures,
    )


def run_quality(run) -> QualityResult:
    """Запустить все блоки и собрать ВСЕ ошибки: один проход сообщает всё.

    Контракт порядка для вызывающего кода: падение блока НЕ проваливает фазу.
    Раннер выполнил свою работу; упал КОД. Передайте этот результат builder и
    позвольте ограниченному циклу исправления определить судьбу запуска.
    """
    blocks: list[Callable] = [
        test,
        lint,
        typecheck,
        build,
    ]
    checks = [block(run) for block in blocks]
    # Ошибка — это команда, её код завершения и фактический вывод: всё, что
    # нужно builder для исправления без открытия лога или догадок парсера о
    # том, что ошибка «значит».
    failures = [
        f"{check.name}: `{check.command}` exited {check.returncode}\n{check.output_tail}".rstrip()
        for check in checks if not check.passed
    ]
    return QualityResult(
        passed=not failures,
        checks=checks,
        failures=failures,
        artifacts=[check.output_artifact for check in checks],
    )

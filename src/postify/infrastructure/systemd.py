from __future__ import annotations

from collections.abc import Callable
from typing import Protocol


class CommandResult(Protocol):
    stdout: str
    stderr: str
    returncode: int


class RunOnceTimeoutError(TimeoutError):
    """Однократный запуск не завершился за отведённое время."""


class SystemdCommandError(RuntimeError):
    """Команда systemctl завершилась с неожиданной ошибкой."""


class SystemdController:
    _timer_unit = "postify-run-once.timer"
    _publish_timer_unit = "postify-publish-once.timer"
    _run_once_service = "postify-run-once.service"

    def __init__(
        self,
        *,
        command_name: str,
        postgresql_unit: str,
        clock: Callable[[], float],
        sleeper: Callable[[float], None],
        runner: Callable[[list[str]], CommandResult],
    ) -> None:
        self._command_name = command_name
        self._postgresql_unit = postgresql_unit
        self._clock = clock
        self._sleeper = sleeper
        self._runner = runner

    def start_postgresql(self) -> None:
        self._run([self._command_name, "start", self._postgresql_unit])

    def stop_postgresql(self) -> None:
        self._run([self._command_name, "stop", self._postgresql_unit])

    def enable_timer(self) -> None:
        self._run([self._command_name, "enable", self._timer_unit])
        self._run([self._command_name, "start", self._timer_unit])

    def enable_and_start_timer(self) -> None:
        self.enable_timer()

    def enable_and_start_publish_timer(self) -> None:
        self._run([self._command_name, "enable", self._publish_timer_unit])
        self._run([self._command_name, "start", self._publish_timer_unit])

    def disable_timer(self) -> None:
        self._run([self._command_name, "disable", self._timer_unit])
        self._run([self._command_name, "stop", self._timer_unit])

    def disable_and_stop_timer(self) -> None:
        self.disable_timer()

    def disable_and_stop_publish_timer(self) -> None:
        self._run([self._command_name, "disable", self._publish_timer_unit])
        self._run([self._command_name, "stop", self._publish_timer_unit])

    def publish_timer_properties(self) -> dict[str, str]:
        return self._timer_properties(self._publish_timer_unit)

    def active_state(self, unit: str) -> str:
        result = self._runner([self._command_name, "is-active", unit])
        state = result.stdout.strip()
        if result.returncode and state not in {"inactive", "failed"}:
            self._raise_command_error(result)
        return state

    def timer_properties(self) -> dict[str, str]:
        return self._timer_properties(self._timer_unit)

    def _timer_properties(self, timer_unit: str) -> dict[str, str]:
        output = self._run(
            [
                self._command_name,
                "show",
                timer_unit,
                "--property=NextElapseUSecRealtime",
                "--property=LastTriggerUSec",
            ]
        ).stdout
        return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)

    def wait_for_run_once(self, *, timeout: float, poll_interval: float) -> str:
        deadline = self._clock() + timeout
        while True:
            state = self.active_state(self._run_once_service)
            if state in {"inactive", "failed"}:
                return state
            if self._clock() >= deadline:
                raise RunOnceTimeoutError("Превышено время ожидания postify-run-once.service")
            self._sleeper(poll_interval)

    def _run(self, argv: list[str]) -> CommandResult:
        result = self._runner(argv)
        if result.returncode:
            self._raise_command_error(result)
        return result

    @staticmethod
    def _raise_command_error(result: CommandResult) -> None:
        message = result.stderr.strip() or result.stdout.strip() or "Неизвестная ошибка systemctl"
        raise SystemdCommandError(message)

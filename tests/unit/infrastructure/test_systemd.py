from __future__ import annotations

import importlib
from dataclasses import dataclass

import pytest


@dataclass
class CommandResult:
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0


class RecordingRunner:
    def __init__(self, responses: list[CommandResult] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.responses = responses or []

    def __call__(self, argv: list[str]) -> CommandResult:
        self.calls.append(argv)
        return self.responses.pop(0) if self.responses else CommandResult()


class AdvancingClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@dataclass
class FailedCommandResult:
    stdout: str
    stderr: str
    returncode: int


def test_start_postgresql_uses_configured_unit() -> None:
    # Break caught: changing the PostgreSQL unit or omitting the start command.
    systemd = importlib.import_module("postify.infrastructure.systemd")
    runner = RecordingRunner()
    controller = systemd.SystemdController(
        command_name="systemctl",
        postgresql_unit="postgresql-custom.service",
        clock=lambda: 0.0,
        sleeper=lambda _: None,
        runner=runner,
    )

    controller.start_postgresql()

    assert runner.calls == [["systemctl", "start", "postgresql-custom.service"]]


def test_stop_postgresql_uses_configured_unit() -> None:
    # Break caught: stopping the default unit instead of the configured one.
    systemd = importlib.import_module("postify.infrastructure.systemd")
    runner = RecordingRunner()
    controller = systemd.SystemdController(
        command_name="systemctl",
        postgresql_unit="postgresql-custom.service",
        clock=lambda: 0.0,
        sleeper=lambda _: None,
        runner=runner,
    )

    controller.stop_postgresql()

    assert runner.calls == [["systemctl", "stop", "postgresql-custom.service"]]


def test_enable_and_disable_timer_start_and_stop_the_timer() -> None:
    # Break caught: changing timer lifecycle into an enable/disable-only operation.
    systemd = importlib.import_module("postify.infrastructure.systemd")
    runner = RecordingRunner()
    controller = systemd.SystemdController(
        command_name="systemctl",
        postgresql_unit="postgresql.service",
        clock=lambda: 0.0,
        sleeper=lambda _: None,
        runner=runner,
    )

    controller.enable_timer()
    controller.disable_timer()

    assert runner.calls == [
        ["systemctl", "enable", "postify-run-once.timer"],
        ["systemctl", "start", "postify-run-once.timer"],
        ["systemctl", "disable", "postify-run-once.timer"],
        ["systemctl", "stop", "postify-run-once.timer"],
    ]


def test_publish_timer_has_its_own_complete_lifecycle() -> None:
    # Поломка: установленный Telegram timer не включается или не выключается оператором.
    systemd = importlib.import_module("postify.infrastructure.systemd")
    runner = RecordingRunner()
    controller = systemd.SystemdController(command_name="systemctl", postgresql_unit="postgresql.service", clock=lambda: 0.0, sleeper=lambda _: None, runner=runner)

    controller.enable_and_start_publish_timer()
    controller.disable_and_stop_publish_timer()

    assert runner.calls == [
        ["systemctl", "enable", "postify-publish-once.timer"],
        ["systemctl", "start", "postify-publish-once.timer"],
        ["systemctl", "disable", "postify-publish-once.timer"],
        ["systemctl", "stop", "postify-publish-once.timer"],
    ]


def test_cli_lifecycle_methods_keep_enable_start_and_disable_stop_atomic() -> None:
    # Break caught: CLI orchestration calling only half of either timer lifecycle operation.
    systemd = importlib.import_module("postify.infrastructure.systemd")
    runner = RecordingRunner()
    controller = systemd.SystemdController(
        command_name="systemctl",
        postgresql_unit="postgresql.service",
        clock=lambda: 0.0,
        sleeper=lambda _: None,
        runner=runner,
    )

    controller.enable_and_start_timer()
    controller.disable_and_stop_timer()

    assert runner.calls == [
        ["systemctl", "enable", "postify-run-once.timer"],
        ["systemctl", "start", "postify-run-once.timer"],
        ["systemctl", "disable", "postify-run-once.timer"],
        ["systemctl", "stop", "postify-run-once.timer"],
    ]


def test_reads_active_state_and_timer_properties() -> None:
    # Break caught: reading a timer state through a command other than systemctl show/is-active.
    systemd = importlib.import_module("postify.infrastructure.systemd")
    runner = RecordingRunner(
        [
            CommandResult("active\n"),
            CommandResult("NextElapseUSecRealtime=tomorrow\nLastTriggerUSec=yesterday\n"),
        ]
    )
    controller = systemd.SystemdController(
        command_name="systemctl",
        postgresql_unit="postgresql.service",
        clock=lambda: 0.0,
        sleeper=lambda _: None,
        runner=runner,
    )

    state = controller.active_state("postify-run-once.timer")
    properties = controller.timer_properties()

    assert state == "active"
    assert properties == {
        "NextElapseUSecRealtime": "tomorrow",
        "LastTriggerUSec": "yesterday",
    }
    assert runner.calls == [
        ["systemctl", "is-active", "postify-run-once.timer"],
        [
            "systemctl",
            "show",
            "postify-run-once.timer",
            "--property=NextElapseUSecRealtime",
            "--property=LastTriggerUSec",
        ],
    ]


def test_wait_for_run_once_polls_only_the_service_until_terminal_state() -> None:
    # Break caught: stopping a running service or polling a timer rather than this run's service.
    systemd = importlib.import_module("postify.infrastructure.systemd")
    clock = AdvancingClock()
    runner = RecordingRunner([CommandResult("activating\n"), CommandResult("inactive\n")])
    controller = systemd.SystemdController(
        command_name="systemctl",
        postgresql_unit="postgresql.service",
        clock=clock,
        sleeper=clock.sleep,
        runner=runner,
    )

    assert controller.wait_for_run_once(timeout=5.0, poll_interval=1.0) == "inactive"
    assert runner.calls == [
        ["systemctl", "is-active", "postify-run-once.service"],
        ["systemctl", "is-active", "postify-run-once.service"],
    ]


def test_wait_for_run_once_raises_its_own_timeout_error() -> None:
    # Break caught: waiting forever or replacing timeout with a systemctl stop call.
    systemd = importlib.import_module("postify.infrastructure.systemd")
    clock = AdvancingClock()
    runner = RecordingRunner([CommandResult("active\n")] * 3)
    controller = systemd.SystemdController(
        command_name="systemctl",
        postgresql_unit="postgresql.service",
        clock=clock,
        sleeper=clock.sleep,
        runner=runner,
    )

    with pytest.raises(systemd.RunOnceTimeoutError):
        controller.wait_for_run_once(timeout=2.0, poll_interval=1.0)

    assert runner.calls == [
        ["systemctl", "is-active", "postify-run-once.service"],
        ["systemctl", "is-active", "postify-run-once.service"],
        ["systemctl", "is-active", "postify-run-once.service"],
    ]


def test_active_state_raises_command_error_for_non_terminal_systemctl_failure() -> None:
    # Break caught: converting a D-Bus error into a misleading run-once timeout.
    systemd = importlib.import_module("postify.infrastructure.systemd")
    runner = RecordingRunner(
        [FailedCommandResult(stdout="unknown\n", stderr="Failed to connect", returncode=1)]
    )
    controller = systemd.SystemdController(
        command_name="systemctl",
        postgresql_unit="postgresql.service",
        clock=lambda: 0.0,
        sleeper=lambda _: None,
        runner=runner,
    )

    with pytest.raises(systemd.SystemdCommandError, match="Failed to connect"):
        controller.active_state("postify-run-once.service")


@pytest.mark.parametrize("state", ["inactive", "failed"])
def test_active_state_accepts_terminal_state_with_systemctl_nonzero_code(state: str) -> None:
    # Break caught: treating normal terminal systemd states as command failures.
    systemd = importlib.import_module("postify.infrastructure.systemd")
    runner = RecordingRunner([FailedCommandResult(stdout=f"{state}\n", stderr="", returncode=3)])
    controller = systemd.SystemdController(
        command_name="systemctl",
        postgresql_unit="postgresql.service",
        clock=lambda: 0.0,
        sleeper=lambda _: None,
        runner=runner,
    )

    assert controller.active_state("postify-run-once.service") == state

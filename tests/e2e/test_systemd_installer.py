from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


INSTALLER = Path(__file__).parents[2] / "scripts" / "install-systemd.sh"


def write_fake_binaries(tmp_path: Path) -> tuple[Path, Path]:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    log_file = tmp_path / "commands.log"
    for name, body in {
        "systemctl": (
            'printf "systemctl %s\\n" "$*" >> "$COMMAND_LOG"\n'
            'if [ "${FAIL_DAEMON_RELOAD:-}" = "1" ] && [ "$1" = "daemon-reload" ]; then\n'
            '  count=$(cat "$DAEMON_RELOAD_COUNT_FILE" 2>/dev/null || printf 0)\n'
            '  count=$((count + 1))\n'
            '  printf "%s" "$count" > "$DAEMON_RELOAD_COUNT_FILE"\n'
            '  [ "$count" -ne 1 ] || exit 23\n'
            'fi\n'
        ),
        "systemd-analyze": (
            'printf "systemd-analyze %s\\n" "$*" >> "$COMMAND_LOG"\n'
            'if [ "${FAIL_VERIFY:-}" = "1" ] && [ "$1" = "verify" ]; then exit 17; fi\n'
        ),
        "install": (
            'printf "install %s\\n" "$*" >> "$COMMAND_LOG"\n'
            'count=$(cat "$INSTALL_COUNT_FILE" 2>/dev/null || printf 0)\n'
            'count=$((count + 1))\n'
            'printf "%s" "$count" > "$INSTALL_COUNT_FILE"\n'
            'if [ "${FAIL_INSTALL_AT:-0}" = "$count" ]; then exit 19; fi\n'
            'src=$4\n'
            'destination=$5\n'
            'mkdir -p "$(dirname "$destination")"\n'
            'cp "$src" "$destination"\n'
            'if [ "${INTERRUPT_INSTALL_AT:-0}" = "$count" ]; then\n'
            '  kill -TERM "$PPID"\n'
            'fi\n'
        ),
    }.items():
        executable = binary_dir / name
        executable.write_text(f"#!/bin/sh\nset -eu\n{body}")
        executable.chmod(0o755)
    return binary_dir, log_file


def run_installer(
    tmp_path: Path,
    *,
    calendars: list[str] | None = None,
    project_dir: str | None = None,
    fail_verify: bool = False,
    fail_second_install: bool = False,
    fail_install_at: int | None = None,
    fail_daemon_reload: bool = False,
    interrupt_after_first_install: bool = False,
    interrupt_install_at: int | None = None,
    with_existing_units: bool = False,
    environment_text: str | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    binary_dir, log_file = write_fake_binaries(tmp_path)
    project = tmp_path / "project"
    project.mkdir()
    environment_file = project / ".env"
    environment_file.write_text(environment_text or (
        "POSTIFY_TEST_VALUE=$(touch must-not-run)\n"
        "TELEGRAM_ON_CALENDAR_MORNING=Mon..Fri 10:00\n"
        "TELEGRAM_ON_CALENDAR_DAY='Mon..Fri 14:00'\n"
        'TELEGRAM_ON_CALENDAR_EVENING="Mon..Fri 19:00"\n'
    ))
    destination = tmp_path / "systemd"
    if with_existing_units:
        destination.mkdir()
        for name in (
            "postify-run-once.service",
            "postify-run-once.timer",
            "postify-publish-once.service",
            "postify-publish-once.timer",
        ):
            (destination / name).write_text(f"old {name}\n")
    command = [
        "sh",
        str(INSTALLER),
        "--project-dir",
        project_dir if project_dir is not None else str(project),
        "--env-file",
        str(environment_file),
        "--python",
        "/usr/bin/python3",
        "--user",
        "postify",
        "--group",
        "postify",
        "--timezone",
        "Europe/Moscow",
        "--destination",
        str(destination),
    ]
    for calendar in calendars or ["Mon..Fri 09:00", "Mon..Fri 13:00", "Mon..Fri 18:00"]:
        command.extend(["--on-calendar", calendar])
    environment = os.environ | {
        "PATH": f"{binary_dir}:{os.environ['PATH']}",
        "COMMAND_LOG": str(log_file),
        "INSTALL_COUNT_FILE": str(tmp_path / "install-count"),
        "DAEMON_RELOAD_COUNT_FILE": str(tmp_path / "daemon-reload-count"),
    }
    if fail_verify:
        environment["FAIL_VERIFY"] = "1"
    if fail_second_install:
        environment["FAIL_INSTALL_AT"] = "2"
    if fail_install_at is not None:
        environment["FAIL_INSTALL_AT"] = str(fail_install_at)
    if fail_daemon_reload:
        environment["FAIL_DAEMON_RELOAD"] = "1"
    if interrupt_after_first_install:
        environment["INTERRUPT_INSTALL_AT"] = "1"
    if interrupt_install_at is not None:
        environment["INTERRUPT_INSTALL_AT"] = str(interrupt_install_at)
    result = subprocess.run(command, capture_output=True, text=True, env=environment, check=False)
    return result, destination, log_file


def test_installer_validates_units_before_copying_and_reloads_daemon(tmp_path: Path) -> None:
    # Break caught: copying invalid units or executing values from the environment file.
    result, destination, log_file = run_installer(tmp_path)

    assert result.returncode == 0, result.stderr
    assert (destination / "postify-run-once.service").read_text() == """[Unit]
Description=Postify one-shot import
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
User=postify
Group=postify
WorkingDirectory={project}
EnvironmentFile={environment_file}
ExecStart=/usr/bin/python3 -m postify.cli run-once
TimeoutStartSec=15min
SyslogIdentifier=postify
""".format(project=tmp_path / "project", environment_file=tmp_path / "project" / ".env")
    assert (destination / "postify-run-once.timer").read_text() == """[Unit]
Description=Postify scheduled one-shot import

[Timer]
OnCalendar=Mon..Fri 09:00
OnCalendar=Mon..Fri 13:00
OnCalendar=Mon..Fri 18:00
Timezone=Europe/Moscow
Persistent=true
Unit=postify-run-once.service

[Install]
WantedBy=timers.target
"""
    assert (tmp_path / "must-not-run").exists() is False
    command_lines = log_file.read_text().splitlines()
    assert command_lines[:3] == [
        "systemd-analyze calendar Mon..Fri 09:00",
        "systemd-analyze calendar Mon..Fri 13:00",
        "systemd-analyze calendar Mon..Fri 18:00",
    ]
    assert command_lines[3:6] == [
        "systemd-analyze calendar Mon..Fri 10:00",
        "systemd-analyze calendar Mon..Fri 14:00",
        "systemd-analyze calendar Mon..Fri 19:00",
    ]
    assert command_lines[6].startswith("systemd-analyze verify ")
    assert command_lines[7].endswith(f" {destination}/postify-run-once.service")
    assert command_lines[8].endswith(f" {destination}/postify-run-once.timer")
    assert command_lines[9].endswith(f" {destination}/postify-publish-once.service")
    assert command_lines[10].endswith(f" {destination}/postify-publish-once.timer")
    assert command_lines[11] == "systemctl daemon-reload"


@pytest.mark.parametrize(
    ("calendars", "project_dir"),
    [
        (["", "Mon..Fri 13:00", "Mon..Fri 18:00"], None),
        (["Mon..Fri 09:00\nOnBootSec=1", "Mon..Fri 13:00", "Mon..Fri 18:00"], None),
        (["@ON_CALENDAR_1@", "Mon..Fri 13:00", "Mon..Fri 18:00"], None),
        (None, "relative-project"),
    ],
)
def test_installer_rejects_invalid_values_without_changing_destination(
    tmp_path: Path, calendars: list[str] | None, project_dir: str | None
) -> None:
    # Break caught: accepting unsafe schedule/path input and writing any unit nevertheless.
    result, destination, log_file = run_installer(
        tmp_path, calendars=calendars, project_dir=project_dir
    )

    assert result.returncode != 0
    assert destination.exists() is False


def test_installer_does_not_copy_when_systemd_verify_fails(tmp_path: Path) -> None:
    # Break caught: installing units even though systemd-analyze verify rejected them.
    result, destination, log_file = run_installer(tmp_path, fail_verify=True)

    assert result.returncode != 0
    assert destination.exists() is False
    assert log_file.read_text().splitlines()[-1].startswith("systemd-analyze verify ")


@pytest.mark.parametrize(
    "environment_text",
    [
        "TELEGRAM_ON_CALENDAR_DAY=Mon 14:00\nTELEGRAM_ON_CALENDAR_EVENING=Mon 19:00\n",
        "TELEGRAM_ON_CALENDAR_MORNING=Mon 10:00\nTELEGRAM_ON_CALENDAR_MORNING=Mon 11:00\nTELEGRAM_ON_CALENDAR_DAY=Mon 14:00\nTELEGRAM_ON_CALENDAR_EVENING=Mon 19:00\n",
        "TELEGRAM_ON_CALENDAR_MORNING=\nTELEGRAM_ON_CALENDAR_DAY=Mon 14:00\nTELEGRAM_ON_CALENDAR_EVENING=Mon 19:00\n",
        "TELEGRAM_ON_CALENDAR_MORNING=''\nTELEGRAM_ON_CALENDAR_DAY=Mon 14:00\nTELEGRAM_ON_CALENDAR_EVENING=Mon 19:00\n",
        'TELEGRAM_ON_CALENDAR_MORNING=""\nTELEGRAM_ON_CALENDAR_DAY=Mon 14:00\nTELEGRAM_ON_CALENDAR_EVENING=Mon 19:00\n',
        "TELEGRAM_ON_CALENDAR_MORNING=Mon 10:00\tbad\nTELEGRAM_ON_CALENDAR_DAY=Mon 14:00\nTELEGRAM_ON_CALENDAR_EVENING=Mon 19:00\n",
        "TELEGRAM_ON_CALENDAR_MORNING='Mon 10:00\nTELEGRAM_ON_CALENDAR_DAY=Mon 14:00\nTELEGRAM_ON_CALENDAR_EVENING=Mon 19:00\n",
        "TELEGRAM_ON_CALENDAR_MORNING=Mon 10:00\"\nTELEGRAM_ON_CALENDAR_DAY=Mon 14:00\nTELEGRAM_ON_CALENDAR_EVENING=Mon 19:00\n",
        "TELEGRAM_ON_CALENDAR_MORNING=Mon'10:00\nTELEGRAM_ON_CALENDAR_DAY=Mon 14:00\nTELEGRAM_ON_CALENDAR_EVENING=Mon 19:00\n",
    ],
)
def test_installer_rejects_invalid_telegram_dotenv_schedules_without_execution(
    tmp_path: Path, environment_text: str
) -> None:
    # Поломка: unsafe/malformed dotenv schedule рендерится, исполняется или меняет destination.
    result, destination, _ = run_installer(tmp_path, environment_text=environment_text)

    assert result.returncode != 0
    assert destination.exists() is False
    assert "Mon 10:00" not in result.stderr
    assert (tmp_path / "must-not-run").exists() is False


def test_installer_reads_quoted_and_unquoted_telegram_dotenv_schedules(tmp_path: Path) -> None:
    # Поломка: parser меняет literal values или использует CLI calendars для publish timer.
    text = (
        "POSTIFY_TEST_VALUE=$(touch must-not-run)\n"
        "TELEGRAM_ON_CALENDAR_MORNING=Mon..Fri 10:00\n"
        "TELEGRAM_ON_CALENDAR_DAY='Mon..Fri 14:00'\n"
        'TELEGRAM_ON_CALENDAR_EVENING="Mon..Fri 19:00"\n'
    )
    result, destination, _ = run_installer(tmp_path, environment_text=text)

    assert result.returncode == 0
    timer = (destination / "postify-publish-once.timer").read_text()
    assert "OnCalendar=Mon..Fri 10:00" in timer
    assert "OnCalendar=Mon..Fri 14:00" in timer
    assert "OnCalendar=Mon..Fri 19:00" in timer
    assert (tmp_path / "must-not-run").exists() is False


def test_installer_restores_existing_units_when_second_copy_fails(tmp_path: Path) -> None:
    # Break caught: leaving service and timer from different installation versions after a copy error.
    result, destination, _ = run_installer(
        tmp_path, fail_second_install=True, with_existing_units=True
    )

    assert result.returncode != 0
    assert (destination / "postify-run-once.service").read_text() == "old postify-run-once.service\n"
    assert (destination / "postify-run-once.timer").read_text() == "old postify-run-once.timer\n"


@pytest.mark.parametrize("failure", ["signal", "daemon-reload"])
def test_installer_restores_existing_units_when_finalization_fails(
    tmp_path: Path, failure: str
) -> None:
    # Break caught: returning an error after changing only part of the installed unit pair.
    result, destination, log_file = run_installer(
        tmp_path,
        fail_daemon_reload=failure == "daemon-reload",
        interrupt_after_first_install=failure == "signal",
        with_existing_units=True,
    )

    assert result.returncode != 0
    assert (destination / "postify-run-once.service").read_text() == "old postify-run-once.service\n"
    assert (destination / "postify-run-once.timer").read_text() == "old postify-run-once.timer\n"
    if failure == "daemon-reload":
        assert log_file.read_text().splitlines().count("systemctl daemon-reload") == 2


def test_installer_creates_separate_publish_units_and_verifies_all_before_copy(
    tmp_path: Path,
) -> None:
    # Поломка: publish делит run-once unit, не имеет трёх slots или copy идёт до verify.
    result, destination, log_file = run_installer(tmp_path)

    assert result.returncode == 0, result.stderr
    service = (destination / "postify-publish-once.service").read_text()
    timer = (destination / "postify-publish-once.timer").read_text()
    assert "Type=oneshot" in service
    assert "ExecStart=/usr/bin/python3 -m postify.cli publish-once" in service
    assert "SyslogIdentifier=postify-publish" in service
    assert timer.count("OnCalendar=") == 3
    assert "OnCalendar=Mon..Fri 10:00" in timer
    assert "OnCalendar=Mon..Fri 14:00" in timer
    assert "OnCalendar=Mon..Fri 19:00" in timer
    assert "Unit=postify-publish-once.service" in timer
    lines = log_file.read_text().splitlines()
    verify_index = next(index for index, line in enumerate(lines) if line.startswith("systemd-analyze verify "))
    first_copy = next(index for index, line in enumerate(lines) if line.startswith("install "))
    assert verify_index < first_copy
    assert all(name in lines[verify_index] for name in (
        "postify-run-once.service", "postify-run-once.timer",
        "postify-publish-once.service", "postify-publish-once.timer",
    ))


@pytest.mark.parametrize("install_index", [1, 2, 3, 4])
@pytest.mark.parametrize("failure", ["copy", "signal"])
def test_installer_rolls_back_all_four_units_after_each_partial_failure(
    tmp_path: Path, install_index: int, failure: str
) -> None:
    # Поломка: любой copy/signal оставляет смешанную версию четырёх unit.
    result, destination, _ = run_installer(
        tmp_path,
        fail_install_at=install_index if failure == "copy" else None,
        interrupt_install_at=install_index if failure == "signal" else None,
        with_existing_units=True,
    )

    assert result.returncode != 0
    for name in (
        "postify-run-once.service",
        "postify-run-once.timer",
        "postify-publish-once.service",
        "postify-publish-once.timer",
    ):
        assert (destination / name).read_text() == f"old {name}\n"

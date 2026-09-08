import asyncio
import stat

import pytest

from postify import telegram_login


def test_session_lock_restricts_permissions_and_rejects_concurrent_login(tmp_path):
    directory = tmp_path / "telegram"
    directory.mkdir(mode=0o755)
    session_file = directory / "account.session"
    session_file.write_bytes(b"existing-session")
    session_file.chmod(0o644)
    with telegram_login.session_lock(directory) as path:
        assert path == session_file
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        with pytest.raises(telegram_login.LoginError, match="telegram_session_busy"):
            with telegram_login.session_lock(directory):
                pytest.fail("Concurrent login acquired the lock")
        journal = directory / "account.session-journal"
        journal.write_bytes(b"private-journal")
        assert stat.S_IMODE(journal.stat().st_mode) == 0o600
    assert session_file.read_bytes() == b"existing-session"
    with telegram_login.session_lock(directory):
        pass


def test_noninteractive_password_fails_without_reading_or_echoing(monkeypatch):
    monkeypatch.setattr(telegram_login.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr(telegram_login.getpass, "getpass", lambda *_: pytest.fail("Password read without TTY"))
    with pytest.raises(telegram_login.LoginError, match="telegram_password_requires_tty"):
        asyncio.run(telegram_login.read_password())


@pytest.mark.parametrize("failure", ["unexpected", "password_invalid"])
def test_cli_disconnects_on_auth_failure_and_does_not_print_secret(monkeypatch, tmp_path, capsys, failure):
    import telethon
    from postify.adapters.telegram import account_login

    events = []

    class Client:
        def __init__(self, session, api_id, api_hash):
            events.append((session, api_id, api_hash))

        async def connect(self):
            events.append("connect")

        async def disconnect(self):
            events.append("disconnect")

    async def fail_authorization(client, *, show_qr, read_password):
        if failure == "password_invalid":
            raise account_login.AccountLoginError("password_invalid")
        raise RuntimeError("private-auth-token")

    monkeypatch.setenv("TELEGRAM_API_ID", "123")
    monkeypatch.setenv("TELEGRAM_API_HASH", "private-api-hash")
    monkeypatch.setattr(telegram_login, "SESSION_DIRECTORY", tmp_path / "session")
    monkeypatch.setattr(telethon, "TelegramClient", Client)
    monkeypatch.setattr(account_login, "authorize", fail_authorization)
    assert telegram_login.main(["--find", "نظرها درباره کار با زینب"]) == 1
    captured = capsys.readouterr()
    assert events[-1] == "disconnect"
    assert "connect" not in events
    if failure == "password_invalid":
        assert "password_invalid" in captured.err
        assert "Пароль двухэтапной проверки не принят" in captured.err
    else:
        assert "RuntimeError" in captured.err
    assert "private-auth-token" not in captured.out + captured.err
    assert "private-api-hash" not in captured.out + captured.err


def test_cli_requires_query_without_tty_before_opening_session(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TELEGRAM_API_ID", "123")
    monkeypatch.setenv("TELEGRAM_API_HASH", "private-api-hash")
    monkeypatch.setattr(telegram_login.sys.stdin, "isatty", lambda: False)
    directory = tmp_path / "session"
    monkeypatch.setattr(telegram_login, "SESSION_DIRECTORY", directory)
    assert telegram_login.main([]) == 1
    assert "telegram_query_requires_tty_or_find" in capsys.readouterr().err
    assert not directory.exists()

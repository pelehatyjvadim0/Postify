"""Private persistent Telegram session shared by login and source reads."""
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path

SESSION_DIRECTORY = Path("/data/telegram")

class TelegramSessionError(RuntimeError):
    pass


@contextmanager
def session_lock(directory: Path | None = None):
    directory = directory or SESSION_DIRECTORY
    previous_umask = os.umask(0o077)
    descriptor = None
    try:
        if directory.is_symlink():
            raise TelegramSessionError("unsafe_session_directory")
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        descriptor = os.open(directory / "account.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.fchmod(descriptor, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise TelegramSessionError("telegram_session_busy") from None
        for path in directory.glob("account.session*"):
            if path.is_symlink():
                raise TelegramSessionError("unsafe_session_file")
            path.chmod(0o600)
        yield directory / "account.session"
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.umask(previous_umask)

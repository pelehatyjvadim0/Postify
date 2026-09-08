"""Interactive account authorization; the caller owns session storage/disconnect."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
import unicodedata

from telethon.errors import PasswordHashInvalidError, SessionPasswordNeededError


class AccountLoginError(RuntimeError):
    """A safe error code without Telegram responses, tokens, or passwords."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class AccountLoginTimeout(AccountLoginError):
    def __init__(self):
        super().__init__("qr_login_expired")


async def authorize(
    client,
    show_qr: Callable[[str], None],
    read_password: Callable[[], Awaitable[str]],
) -> None:
    """Connect and authorize with at most five QR codes and three 2FA attempts.

    QR URLs go only to the supplied display callback. The client stays connected
    for dialog discovery; its owner must disconnect in a finally block.
    """
    try:
        await client.connect()
        if await client.is_user_authorized():
            return
        qr = await client.qr_login()
        for attempt in range(5):
            show_qr(qr.url)
            try:
                await qr.wait()
                return
            except TimeoutError:
                if attempt == 4:
                    raise AccountLoginTimeout() from None
                await qr.recreate()
            except SessionPasswordNeededError:
                for _ in range(3):
                    password = await read_password()
                    if not isinstance(password, str):
                        raise AccountLoginError("password_invalid")
                    try:
                        await client.sign_in(password=password)
                        return
                    except PasswordHashInvalidError:
                        continue
                raise AccountLoginError("password_invalid") from None
    except AccountLoginError:
        raise
    except Exception:
        raise AccountLoginError("account_login_failed") from None


def _normalized(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


async def find_groups(client, query: str) -> list[dict[str, object]]:
    """Read joined group/channel titles; never include private user dialogs."""
    try:
        needle = _normalized(query)
        if not needle:
            raise AccountLoginError("group_query_required")
        matches = []
        async for dialog in client.iter_dialogs():
            if not (dialog.is_group or dialog.is_channel):
                continue
            title = dialog.title
            if needle in _normalized(title):
                matches.append({
                    "id": dialog.id,
                    "title": title,
                    "type": "group" if dialog.is_group else "channel",
                })
        return matches
    except AccountLoginError:
        raise
    except Exception:
        raise AccountLoginError("group_search_failed") from None

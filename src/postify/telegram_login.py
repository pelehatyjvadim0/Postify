"""Интерактивный вход Telegram внутри контейнера, без импорта и публикации."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
from pathlib import Path
import sys


SESSION_DIRECTORY = Path("/data/telegram")
ACCOUNT_ERROR_MESSAGES = {
    "qr_login_expired": "QR-код истёк. Запустите вход заново.",
    "password_invalid": "Пароль двухэтапной проверки не принят после трёх попыток.",
    "account_login_failed": "Не удалось завершить вход Telegram.",
    "group_search_failed": "Не удалось получить подходящие группы.",
    "group_query_required": "Укажите часть названия группы.",
}


from postify.infrastructure.security.telegram_session import (
    TelegramSessionError as LoginError, session_lock as _session_lock,
)


def session_lock(directory: Path | None = None):
    return _session_lock(directory or SESSION_DIRECTORY)


def show_qr(url: str) -> None:
    import qrcode

    print("Откройте Telegram на телефоне: Настройки → Устройства → Подключить устройство. Сканируйте QR-код:")
    qr = qrcode.QRCode(border=4)
    qr.add_data(url)
    qr.make(fit=True)
    qr.print_ascii(invert=True)


async def read_password() -> str:
    if not sys.stdin.isatty():
        raise LoginError("telegram_password_requires_tty")
    return await asyncio.to_thread(getpass.getpass, "Пароль двухэтапной проверки Telegram: ")


async def login_and_find(session: Path, api_id: int, api_hash: str, query: str) -> None:
    from telethon import TelegramClient
    from postify.adapters.telegram.account_login import authorize, find_groups

    client = TelegramClient(str(session), api_id, api_hash)
    try:
        await authorize(client, show_qr=show_qr, read_password=read_password)
        groups = await find_groups(client, query)
        print("Вход выполнен. Найденные группы:")
        for group in groups:
            print(f"{group['id']}\t{group['title']}\t{group['type']}")
        if not groups:
            print("Групп с таким названием не найдено.")
    finally:
        await client.disconnect()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Вход Telegram по QR и поиск группы без отправки сообщений.")
    parser.add_argument("--find", metavar="НАЗВАНИЕ", help="Часть названия группы для поиска")
    args = parser.parse_args(argv)
    try:
        raw_id = os.environ.get("TELEGRAM_API_ID", "")
        api_hash = os.environ.get("TELEGRAM_API_HASH", "").strip()
        if not raw_id.isdecimal() or int(raw_id) <= 0 or not api_hash:
            raise LoginError("telegram_api_credentials_missing")
        query = args.find
        if query is None:
            if not sys.stdin.isatty():
                raise LoginError("telegram_query_requires_tty_or_find")
            query = input("Часть названия группы: ")
        query = query.strip()
        if not query:
            raise LoginError("telegram_group_query_required")
        with session_lock() as session:
            asyncio.run(login_and_find(session, int(raw_id), api_hash, query))
        return 0
    except (KeyboardInterrupt, EOFError):
        print("Вход отменён.", file=sys.stderr)
        return 130
    except Exception as error:
        safe_code = getattr(error, "code", None)
        if isinstance(safe_code, str) and safe_code in ACCOUNT_ERROR_MESSAGES:
            code = f"{safe_code}: {ACCOUNT_ERROR_MESSAGES[safe_code]}"
        else:
            code = str(error) if isinstance(error, LoginError) else type(error).__name__
        print(f"Вход не завершён: {code}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

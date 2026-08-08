from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from urllib.parse import urlsplit


class UnsafePublicUrlError(RuntimeError):
    def __init__(self, message: str = "unsafe_url") -> None:
        super().__init__(message)
        self.code = "unsafe_url"


def _resolve(host: str) -> tuple[str, ...]:
    return tuple(item[4][0] for item in socket.getaddrinfo(host, None))


class PublicHttpUrlPolicy:
    def __init__(self, *, resolver: Callable[[str], tuple[str, ...]] = _resolve) -> None:
        self.resolver = resolver

    def validate(self, url: str) -> str:
        try:
            parsed = urlsplit(url)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
            ):
                raise ValueError
            host = parsed.hostname
        except (ValueError, AttributeError) as error:
            raise UnsafePublicUrlError() from error
        except Exception as error:
            raise UnsafePublicUrlError() from error

        try:
            try:
                literal = ipaddress.ip_address(host)
            except ValueError:
                literal = None
            addresses = (str(literal),) if literal is not None else self.resolver(host)
            if not addresses or any(
                not address.is_global or address.is_multicast
                for address in map(ipaddress.ip_address, addresses)
            ):
                raise ValueError
        except (ValueError, OSError, socket.gaierror) as error:
            raise UnsafePublicUrlError() from error
        return url

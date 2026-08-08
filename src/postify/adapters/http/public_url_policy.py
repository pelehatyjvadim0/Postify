from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

import httpcore
import httpx


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
            port = parsed.port
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or port == 0
            ):
                raise ValueError
            if _literal_address(parsed.hostname) is not None:
                _require_public((parsed.hostname,))
        except Exception:
            raise UnsafePublicUrlError() from None
        return url

    def resolve_public(self, host: str) -> str:
        try:
            literal = _literal_address(host)
            addresses = (host,) if literal is not None else self.resolver(host)
            return _require_public(addresses)
        except Exception:
            raise UnsafePublicUrlError() from None


def _literal_address(host: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _require_public(addresses: tuple[str, ...]) -> str:
    parsed = tuple(ipaddress.ip_address(address) for address in addresses)
    if not parsed or any(not address.is_global or address.is_multicast for address in parsed):
        raise ValueError
    return str(parsed[0])


class PublicNetworkBackend:
    def __init__(self, *, policy: PublicHttpUrlPolicy, backend: Any) -> None:
        self.policy = policy
        self.backend = backend

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: object = None,
    ) -> object:
        public_ip = self.policy.resolve_public(host)
        return self.backend.connect_tcp(
            public_ip,
            port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: object = None,
    ) -> object:
        return self.backend.connect_unix_socket(
            path, timeout=timeout, socket_options=socket_options
        )

    def sleep(self, seconds: float) -> None:
        self.backend.sleep(seconds)


class PublicHttpTransport(httpx.HTTPTransport):
    def __init__(
        self,
        *,
        policy: PublicHttpUrlPolicy,
        backend: Any | None = None,
        **options: Any,
    ) -> None:
        super().__init__(**options)
        self.network_backend = PublicNetworkBackend(
            policy=policy,
            backend=backend if backend is not None else httpcore.SyncBackend(),
        )
        self._pool._network_backend = self.network_backend

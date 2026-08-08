from __future__ import annotations

import pytest


def _api():
    from postify.adapters.http.public_url_policy import (
        PublicHttpUrlPolicy,
        UnsafePublicUrlError,
    )

    return PublicHttpUrlPolicy, UnsafePublicUrlError


class RecordingResolver:
    def __init__(self, addresses: tuple[str, ...]) -> None:
        self.addresses = addresses
        self.hosts: list[str] = []

    def __call__(self, host: str) -> tuple[str, ...]:
        self.hosts.append(host)
        return self.addresses


class SequenceResolver:
    def __init__(self, answers: tuple[tuple[str, ...], ...]) -> None:
        self.answers = iter(answers)
        self.hosts: list[str] = []

    def __call__(self, host: str) -> tuple[str, ...]:
        self.hosts.append(host)
        return next(self.answers)


class RecordingNetworkBackend:
    def __init__(self) -> None:
        self.stream = object()
        self.calls: list[dict[str, object]] = []

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: object = None,
    ) -> object:
        self.calls.append(
            {
                "host": host,
                "port": port,
                "timeout": timeout,
                "local_address": local_address,
                "socket_options": socket_options,
            }
        )
        return self.stream


@pytest.mark.parametrize(
    "url",
    [
        "ftp://93.184.216.34/article",
        "https://user:password@public.test/article",
        "http://127.0.0.1/admin",
        "http://[::1]/admin",
        "http://10.1.2.3/internal",
        "http://169.254.169.254/latest/meta-data",
        "http://224.0.0.1/multicast",
        "http://192.0.2.1/reserved",
    ],
)
def test_public_http_url_policy_rejects_unsafe_scheme_userinfo_and_literal_ip(
    url: str,
) -> None:
    # Поломка re-review 1: literal SSRF/userinfo/не-HTTP URL проходит к клиенту.
    PublicHttpUrlPolicy, UnsafePublicUrlError = _api()
    resolver = RecordingResolver(("93.184.216.34",))

    with pytest.raises(UnsafePublicUrlError) as caught:
        PublicHttpUrlPolicy(resolver=resolver).validate(url)

    assert caught.value.code == "unsafe_url"
    assert url not in str(caught.value)


@pytest.mark.parametrize(
    "resolved_ip",
    [
        "127.0.0.1",
        "10.20.30.40",
        "169.254.20.30",
        "239.1.2.3",
        "192.0.2.25",
        "::1",
        "fc00::10",
        "fe80::10",
        "ff02::1",
        "2001:db8::10",
    ],
)
def test_public_http_url_policy_rejects_forbidden_dns_answer(resolved_ip: str) -> None:
    # Поломка re-review 1: hostname разрешается в non-public IP перед TCP connect.
    PublicHttpUrlPolicy, UnsafePublicUrlError = _api()
    from postify.adapters.http.public_url_policy import PublicNetworkBackend

    resolver = RecordingResolver(("93.184.216.34", resolved_ip))
    underlying = RecordingNetworkBackend()
    policy = PublicHttpUrlPolicy(resolver=resolver)
    backend = PublicNetworkBackend(policy=policy, backend=underlying)

    with pytest.raises(UnsafePublicUrlError):
        backend.connect_tcp("public.test", 443)

    assert resolver.hosts == ["public.test"]
    assert underlying.calls == []


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_public_http_url_policy_accepts_only_fully_public_dns_answers(scheme: str) -> None:
    # Поломка: безопасный публичный URL ошибочно блокируется либо DNS вообще не проверяется.
    PublicHttpUrlPolicy, _ = _api()
    from postify.adapters.http.public_url_policy import PublicNetworkBackend

    resolver = RecordingResolver(("93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"))
    url = f"{scheme}://public.test/article"
    policy = PublicHttpUrlPolicy(resolver=resolver)
    underlying = RecordingNetworkBackend()

    assert policy.validate(url) == url
    assert PublicNetworkBackend(policy=policy, backend=underlying).connect_tcp(
        "public.test", 80 if scheme == "http" else 443
    ) is underlying.stream
    assert resolver.hosts == ["public.test"]
    assert [call["host"] for call in underlying.calls] == ["93.184.216.34"]


@pytest.mark.parametrize(
    "url",
    [
        "https://public.test:not-a-port/article",
        "https://public.test:0/article",
        "https://public.test:65536/article",
    ],
    ids=["malformed", "zero", "overflow"],
)
def test_public_http_url_policy_rejects_invalid_port_before_dns_or_http(
    url: str,
) -> None:
    # Поломка fix-round 1: lazy port parsing отдаёт malformed URL к transport.
    PublicHttpUrlPolicy, UnsafePublicUrlError = _api()
    resolver = RecordingResolver(("93.184.216.34",))

    with pytest.raises(UnsafePublicUrlError) as caught:
        PublicHttpUrlPolicy(resolver=resolver).validate(url)

    assert caught.value.code == "unsafe_url"
    assert url not in str(caught.value)
    assert "public.test" not in str(caught.value)
    assert resolver.hosts == []


def test_public_network_backend_connects_to_the_validated_ip_without_hostname_lookup(
) -> None:
    # Поломка fix-round 1: policy проверяет IP, но TCP повторно резолвит hostname.
    from postify.adapters.http.public_url_policy import PublicNetworkBackend

    PublicHttpUrlPolicy, _ = _api()
    resolver = SequenceResolver((("93.184.216.34",),))
    underlying = RecordingNetworkBackend()
    backend = PublicNetworkBackend(
        policy=PublicHttpUrlPolicy(resolver=resolver), backend=underlying
    )
    socket_options = [(6, 1, 1)]

    stream = backend.connect_tcp(
        "public.test",
        443,
        timeout=2.5,
        local_address="192.0.2.10",
        socket_options=socket_options,
    )

    assert stream is underlying.stream
    assert resolver.hosts == ["public.test"]
    assert underlying.calls == [
        {
            "host": "93.184.216.34",
            "port": 443,
            "timeout": 2.5,
            "local_address": "192.0.2.10",
            "socket_options": socket_options,
        }
    ]


def test_public_network_backend_never_connects_after_dns_changes_to_private_ip(
) -> None:
    # Поломка fix-round 1: rebinding public→private открывает второй socket.
    from postify.adapters.http.public_url_policy import (
        PublicNetworkBackend,
        UnsafePublicUrlError,
    )

    PublicHttpUrlPolicy, _ = _api()
    resolver = SequenceResolver((("93.184.216.34",), ("127.0.0.1",)))
    underlying = RecordingNetworkBackend()
    backend = PublicNetworkBackend(
        policy=PublicHttpUrlPolicy(resolver=resolver), backend=underlying
    )

    backend.connect_tcp("public.test", 80)
    with pytest.raises(UnsafePublicUrlError) as caught:
        backend.connect_tcp("public.test", 80)

    assert caught.value.code == "unsafe_url"
    assert "public.test" not in str(caught.value)
    assert resolver.hosts == ["public.test", "public.test"]
    assert [call["host"] for call in underlying.calls] == ["93.184.216.34"]

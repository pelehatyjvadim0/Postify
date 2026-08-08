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
    # Поломка re-review 1: hostname разрешается в non-public IP после строковой проверки URL.
    PublicHttpUrlPolicy, UnsafePublicUrlError = _api()
    resolver = RecordingResolver(("93.184.216.34", resolved_ip))

    with pytest.raises(UnsafePublicUrlError):
        PublicHttpUrlPolicy(resolver=resolver).validate("https://public.test/article")

    assert resolver.hosts == ["public.test"]


@pytest.mark.parametrize("scheme", ["http", "https"])
def test_public_http_url_policy_accepts_only_fully_public_dns_answers(scheme: str) -> None:
    # Поломка: безопасный публичный URL ошибочно блокируется либо DNS вообще не проверяется.
    PublicHttpUrlPolicy, _ = _api()
    resolver = RecordingResolver(("93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"))
    url = f"{scheme}://public.test/article"

    assert PublicHttpUrlPolicy(resolver=resolver).validate(url) == url
    assert resolver.hosts == ["public.test"]

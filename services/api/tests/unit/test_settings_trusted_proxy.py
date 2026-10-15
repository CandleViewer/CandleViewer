"""#2275: MeshOnly's trusted proxy (`CV_MESH_TRUSTED_PROXY_*`) is checked at startup.

The header is read only when the TCP peer equals the configured address. An address that is not
an IP literal, a misspelt header name, or only one of the pair set would silently never read the
header, so every client behind the proxy would be judged and recorded as the proxy. Each fails
startup instead.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from candleviewer.settings import Settings, get_settings


@pytest.mark.parametrize(
    ("address", "normalised"),
    [
        ("127.0.0.1", "127.0.0.1"),
        (" ::1 ", "::1"),
        ("0:0:0:0:0:0:0:1", "::1"),
        ("::ffff:127.0.0.1", "127.0.0.1"),  # unwrapped, as `CidrAllowList` matches it
        ("FD7A:115C:A1E0::1", "fd7a:115c:a1e0::1"),
    ],
)
def test_trusted_proxy_address_is_normalised(address: str, normalised: str) -> None:
    s = Settings(mesh_trusted_proxy_header=" X-Forwarded-For ", mesh_trusted_proxy_address=address)
    assert (s.mesh_trusted_proxy_header, s.mesh_trusted_proxy_address) == (
        "x-forwarded-for",
        normalised,
    )


@pytest.mark.parametrize(
    "address", ["localhost", "proxy.internal", "127.0.0.1:8080", "127.0.0.0/8", "[::1]"]
)
def test_trusted_proxy_address_that_is_not_an_ip_is_refused(address: str) -> None:
    with pytest.raises(ValidationError, match=r"CV_MESH_TRUSTED_PROXY_ADDRESS .* not an IP"):
        Settings(mesh_trusted_proxy_header="x-forwarded-for", mesh_trusted_proxy_address=address)


@pytest.mark.parametrize("header", ["X-Forwarded-For:", "x forwarded for", "x-forwarded-for,"])
def test_trusted_proxy_header_that_is_not_a_field_name_is_refused(header: str) -> None:
    with pytest.raises(ValidationError, match=r"CV_MESH_TRUSTED_PROXY_HEADER .* not an HTTP"):
        Settings(mesh_trusted_proxy_header=header, mesh_trusted_proxy_address="127.0.0.1")


@pytest.mark.parametrize(
    ("header", "address"),
    [("x-forwarded-for", None), (None, "127.0.0.1"), ("x-forwarded-for", " "), ("", "::1")],
)
def test_trusted_proxy_with_only_one_setting_is_refused(
    header: str | None, address: str | None
) -> None:
    with pytest.raises(ValidationError, match="must be set together"):
        Settings(mesh_trusted_proxy_header=header, mesh_trusted_proxy_address=address)


def test_blank_trusted_proxy_settings_mean_no_trusted_proxy() -> None:
    s = Settings(mesh_trusted_proxy_header=" ", mesh_trusted_proxy_address="")
    assert (s.mesh_trusted_proxy_header, s.mesh_trusted_proxy_address) == (None, None)


def test_a_hostname_in_cv_mesh_trusted_proxy_address_fails_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CV_MESH_TRUSTED_PROXY_HEADER", "x-forwarded-for")
    monkeypatch.setenv("CV_MESH_TRUSTED_PROXY_ADDRESS", "localhost")
    with pytest.raises(ValidationError, match="not an IP address"):
        get_settings()

"""Unit (#2303, C-5.9): `listOrders`' `idempotency_key` is the client's `Idempotency-Key`, class P1
in 21 Sec.12 ("never logged or returned by any API"), so no access line carries its value. The
access line goes through the real `configure_logging()`, in uvicorn's own format: the value of each
`idempotency_key`, a percent-encoded name included, is a marker, while the path and the other
parameters stay readable. A hyphenated key is no shape the redaction filter knows, so this filter
is what keeps it out. `order_link_id` is no P1 column, but the filter's key-shape rule already
takes a free-text `cvl-` id, and the target holding it, whole: an over-redaction this change
leaves as it is (`observability/redaction.py`, #4713)."""

from __future__ import annotations

import logging

from candleviewer.observability.logging import AccessLineFilter
from tests.unit.observability.test_uvicorn_log_routing import (
    _ACCESS,
    _fresh_uvicorn_loggers,  # noqa: F401
    _replay_boot,
)

#: Keys as a client sends them: hyphenated, upper case and the 32-digit form.
KEYS = (
    "6f1c2b7e-3a4d-4e5f-8a6b-7c8d9e0f1a2b",
    "6F1C2B7E-3A4D-4E5F-8A6B-7C8D9E0F1A2C",
    "6f1c2b7e3a4d4e5f8a6b7c8d9e0f1a2d",
)
LINK = "cvl-0MduI3fiqJ6h0wkltsuR4T-JelO-00en"


def test_access_log_line_never_carries_the_idempotency_key() -> None:
    targets = [
        f"/api/v1/orders?idempotency_key={KEYS[0]}&order_link_id={LINK}",
        f"/api/v1/orders?open_only=true&idempotency_key={KEYS[1]}&idempotency_key={KEYS[2]}",
        f"/api/v1/orders?idempotency%5Fkey={KEYS[0]}&limit=5",  # the name as the route decodes it
    ]

    def emit() -> None:
        access = logging.getLogger("uvicorn.access")
        for target in targets:
            access.info(_ACCESS, "127.0.0.1:50000", "GET", target, "1.1", 200)

    got = _replay_boot(emit)
    assert got.err == "" and len(got.lines()) == 3
    assert not any(key in got.out or key.lower() in got.out for key in KEYS)
    assert "open_only=true" in got.out and "limit=5" in got.out
    assert got.out.count("/api/v1/orders?") == 2  # the link id's target is the key-shape marker
    assert LINK not in got.out and "[redacted:key-shape]" in got.out


def test_the_filter_cuts_only_the_named_values_and_leaves_other_lines_alone() -> None:
    def line(msg: str, *args: object) -> logging.LogRecord:
        return logging.LogRecord("uvicorn.access", logging.INFO, "f", 1, msg, args, None)

    flt = AccessLineFilter()
    record = line(_ACCESS, "c", "GET", f"/orders?a=1&idempotency_key={KEYS[0]}&b", "1.1", 200)
    assert flt.filter(record)
    assert record.args == (
        "c", "GET", "/orders?a=1&idempotency_key=[redacted:key-name]&b", "1.1", 200,
    )  # fmt: skip
    for msg, args in [
        (_ACCESS, ("c", "GET", "/orders", "1.1", 200)),  # no query string
        ("other %s %s %s", ("c", "GET", f"/x?idempotency_key={KEYS[0]}")),  # another format
    ]:
        record = line(msg, *args)
        assert flt.filter(record) and record.args == args

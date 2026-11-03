"""The exchange adapter's TLS context (#3461; C-2.7, C-12.2, defence in depth).

`exchange_tls_context()` builds the context the adapter's clients dial with: the REST client
(signed and public instances), the private-WS connectors and the trade-archive client. It trusts
certifi's bundle only, the CA set `httpx` ships with, and reads no environment variable: never
`SSL_CERT_FILE`, `SSL_CERT_DIR`, the platform's store or `SSLKEYLOGFILE`, so it opens and writes no
TLS key log. Each setting is explicit; with none of those variables set they equal `httpx`'s
default context, which `tests/unit/exchange/bybit/test_tls.py` compares field by field. The route
is the callers' half: each takes no proxy from the environment (`trust_env=False` on an `httpx`
client, `proxy=None` on a `websockets` dial).
"""

from __future__ import annotations

import ssl

import certifi


def exchange_tls_context() -> ssl.SSLContext:
    """A new client context on each call, never cached (`httpcore` sets ALPN on the context it is
    given, so each `httpx` client holds its own): the certificate and the host name verified, TLS
    1.2 at least (a proposed floor: today's default, which no owner document fixes yet), and the
    roots of certifi's bundle file, loaded from nowhere else."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_verify_locations(cafile=certifi.where())
    return context

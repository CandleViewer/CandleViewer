"""The `evidence_url` rules of a feature-flag write (E42-T03, module M21): pure, no I/O.

`PUT /admin/feature-flags/{flagKey}` (`22-api-openapi.yaml` `setFeatureFlag`) records
`evidence_url` in the `flags.change` audit, so a URL that may carry a credential is refused as
`credential_in_url`: userinfo, or a query or fragment parameter (a query nested in the fragment,
as in `#/cb?code=...`, included) whose name the audit redactor treats as a secret or
`TOKEN_PARAMS` lists; a path token is the contract's accepted residual. Otherwise the URL must
be `https` with a host, printable and without a space (`https_required`), and at most
`EVIDENCE_URL_MAX` characters (`string_too_long`). It is never dereferenced.

Only the first `EVIDENCE_URL_MAX + 1` characters are parsed, so a huge URL costs no more than a
long one. A URL that cannot be parsed cannot be inspected: it is `credential_in_url` when it
holds an `@`, `?` or `#` and `https_required` otherwise. What the audit records is never a
credential or an unparseable string, and never longer than `EVIDENCE_URL_MAX` characters.
"""

from __future__ import annotations

from typing import Final, Literal
from urllib.parse import SplitResult, parse_qsl, urlsplit

from candleviewer.audit.redact import REDACTION_MARKER, redact

EVIDENCE_URL_MAX: Final = 2048
#: Credential parameter names the audit redactor's secret names miss: signatures, one-time
#: codes, basic-auth and password fields, Azure SAS tokens and AWS SigV4 credentials.
TOKEN_PARAMS: Final = frozenset(
    {"sig", "code", "auth", "pass", "pwd", "passwd", "pw", "pswd", "sas", "x_amz_credential"}
)
REDACTED_CREDENTIAL: Final = "<redacted:credential>"
REDACTED_UNPARSEABLE: Final = "<redacted:unparseable>"
EvidenceRule = Literal["credential_in_url", "https_required", "string_too_long"]


def check_evidence_url(url: str | None) -> tuple[EvidenceRule | None, str | None]:
    """`url`'s refusal (`None` when it is absent or valid) and the form the audit records: a
    falsy value as is, an unparseable URL as `REDACTED_UNPARSEABLE`, a `credential_in_url`
    refusal as `REDACTED_CREDENTIAL`, anything else capped at `EVIDENCE_URL_MAX` characters."""
    if not url:
        return None, url
    head = url[: EVIDENCE_URL_MAX + 1]  # the cost never grows with the input
    try:
        parts = urlsplit(head)
        host = parts.hostname
    except ValueError:  # e.g. an unbalanced IPv6 bracket, or a netloc that NFKC would change
        carrier = any(c in head for c in "@?#")  # it may hold userinfo, a query or a fragment
        return ("credential_in_url" if carrier else "https_required"), REDACTED_UNPARSEABLE
    rule: EvidenceRule | None = None
    if "@" in parts.netloc or _secret_param(parts):
        rule = "credential_in_url"
    elif parts.scheme.lower() != "https" or not host or not head.isprintable() or " " in head:
        rule = "https_required"
    elif len(url) > EVIDENCE_URL_MAX:
        rule = "string_too_long"
    return rule, REDACTED_CREDENTIAL if rule == "credential_in_url" else url[:EVIDENCE_URL_MAX]


def _secret_param(parts: SplitResult) -> bool:
    """A parameter of the query, of the fragment or of a query nested in the fragment whose
    name the audit redactor treats as a secret or `TOKEN_PARAMS` lists (any case); `;`
    separates parameters as `&` does."""
    queries = (parts.query, parts.fragment, parts.fragment.partition("?")[2])
    params = dict.fromkeys((n for q in queries for n, _ in parse_qsl(q.replace(";", "&"))), "")
    redacted = redact(params) or {}
    return REDACTION_MARKER in redacted.values() or not TOKEN_PARAMS.isdisjoint(
        name.lower() for name in params
    )

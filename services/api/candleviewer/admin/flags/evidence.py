"""The `evidence_url` rules of a feature-flag write (E42-T03, module M21): pure, no I/O.

`PUT /admin/feature-flags/{flagKey}` (`22-api-openapi.yaml` `setFeatureFlag`) records
`evidence_url` in the `flags.change` audit, so a URL that may carry a credential is refused as
`credential_in_url`: userinfo, or a parameter of any `?`- or `#`-separated part of the query or
the fragment (a single-page route's `#/cb?code=...` or `#/cb#code=...` included), or a `;` path
parameter (Java's `/app;jsessionid=...`), whose name the audit redactor treats as a secret or
`TOKEN_PARAMS` lists. A credential that is neither the userinfo nor such a parameter, or that is
percent-encoded (a path token, a bare value, a URL nested in a value, `https://u:p%40h/x`), is
the accepted residual. Otherwise the URL must be `https` with a host, printable and without a
space (`https_required`), and at most `EVIDENCE_URL_MAX` characters (`string_too_long`). It is
never dereferenced.

Only the first `EVIDENCE_URL_MAX + 1` characters are parsed, so a huge URL costs no more than a
long one (bar C-level scans for `@` and `%40`). A URL that cannot be parsed cannot be inspected:
it is `credential_in_url` when it holds an `@` anywhere or a `?` or `#` in its head, and
`https_required` otherwise. What the audit records is never a credential or an unparseable
string, and never longer than `EVIDENCE_URL_MAX` characters: a refused URL that holds an `@` or
its percent-encoding `%40` anywhere, past the parsed head included, is recorded redacted whatever
its rule, because userinfo that `urlsplit` does not see in the netloc (`https:u:p@h`, a
scheme-less `u:p@h`, a password too long to parse, `https%3A%2F%2Fu%3Ap%40h`) is still userinfo,
and an accepted URL is recorded as is (a path `@` included).
"""

from __future__ import annotations

import re
from typing import Final, Literal
from urllib.parse import SplitResult, parse_qsl, urlsplit

from candleviewer.audit.redact import REDACTION_MARKER, redact

EVIDENCE_URL_MAX: Final = 2048
#: Credential parameter names the audit redactor's secret names miss, in the form they are
#: compared in (lower case, letters and digits only, so `X-Amz-Credential` is `xamzcredential`):
#: signatures, one-time codes, basic-auth and password fields, Azure SAS tokens, AWS SigV4 and
#: Google Cloud signed-URL credentials, AWS SigV2 key ids, SharePoint `tempauth` and Dropbox
#: `rlkey` links, Java and PHP session ids, and SAML responses and assertions. `ticket` and
#: `state` stay out: `?ticket=12345` is a legitimate support link.
TOKEN_PARAMS: Final = frozenset(
    {"sig", "code", "auth", "pass", "pwd", "passwd", "pw", "pswd", "sas"}
    | {"xamzcredential", "xgoogcredential", "awsaccesskeyid", "tempauth", "rlkey"}
    | {"jsessionid", "phpsessid", "samlresponse", "assertion"}
)
REDACTED_CREDENTIAL: Final = "<redacted:credential>"
REDACTED_UNPARSEABLE: Final = "<redacted:unparseable>"
EvidenceRule = Literal["credential_in_url", "https_required", "string_too_long"]


def check_evidence_url(url: str | None) -> tuple[EvidenceRule | None, str | None]:
    """`url`'s refusal (`None` when it is absent or valid) and the form the audit records: a
    falsy value as is, an unparseable URL as `REDACTED_UNPARSEABLE`, a `credential_in_url`
    refusal or any refused URL holding an `@` or a `%40` as `REDACTED_CREDENTIAL`, anything else
    capped at `EVIDENCE_URL_MAX` characters."""
    if not url:
        return None, url
    head = url[: EVIDENCE_URL_MAX + 1]  # parsing never grows with the input
    try:
        parts = urlsplit(head)
        host = parts.hostname
    except ValueError:  # e.g. an unbalanced IPv6 bracket, or a netloc that NFKC would change
        carrier = "@" in url or any(c in head for c in "?#")  # userinfo, a query or a fragment
        return ("credential_in_url" if carrier else "https_required"), REDACTED_UNPARSEABLE
    rule: EvidenceRule | None = None
    if "@" in parts.netloc or _secret_param(parts):
        rule = "credential_in_url"
    elif parts.scheme.lower() != "https" or not host or not head.isprintable() or " " in head:
        rule = "https_required"
    elif len(url) > EVIDENCE_URL_MAX:
        rule = "string_too_long"
    credential = rule == "credential_in_url" or (rule is not None and ("@" in url or "%40" in url))
    return rule, REDACTED_CREDENTIAL if credential else url[:EVIDENCE_URL_MAX]


def _secret_param(parts: SplitResult) -> bool:
    """A parameter of any `?`- or `#`-separated part of the query or the fragment, or a `;`
    parameter of the path (`/app;jsessionid=...`), whose name the audit redactor treats as a
    secret or, normalised, `TOKEN_PARAMS` lists; `;` separates parameters as `&` does."""
    queries = [*parts.path.split(";")[1:], *re.split(r"[?#]", f"{parts.query}#{parts.fragment}")]
    params = dict.fromkeys((n for q in queries for n, _ in parse_qsl(q.replace(";", "&"))), "")
    redacted = redact(params) or {}
    return REDACTION_MARKER in redacted.values() or not TOKEN_PARAMS.isdisjoint(
        re.sub(r"[^a-z0-9]", "", name.lower()) for name in params
    )

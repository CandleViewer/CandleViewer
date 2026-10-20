"""`reason.py`: the `credential_in_reason` rule of a feature-flag write (#3438, E42 AD-I02).

A refused reason comes back as `REDACTED_CREDENTIAL`, the only form any record of the request may
hold, and an honest one comes back as sent. The cases follow the rule ids of the module docstring
(R1 pairs and options, R2 URLs, R3 userinfo, R4 schemes, R5 credentials in words, R6 known
formats). Credential-shaped vectors are built at run time from parts (#3482): no test file holds a
secret-looking literal for the secret scanners to flag. `fixtures/flag_reasons_honest.json` holds
138 honest reasons, an independent corpus of rollouts, incidents, links, times, tickets and prose
that names credentials without carrying one; none may be refused.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest

from candleviewer.admin.flags.evidence import (
    REDACTED_CREDENTIAL,
    check_evidence_url,
    is_credential_name,
)
from candleviewer.admin.flags.reason import CREDENTIAL_IN_REASON, check_reason, credential_in_reason

_HONEST = json.loads(
    (Path(__file__).parent / "fixtures" / "flag_reasons_honest.json").read_text(encoding="utf-8")
)
#: A machine-issued token: mixed case and digits, 32 characters.
_TOKEN = "".join(a + b for a, b in zip("AbCdEfGhIjKlMnOp", "1234567890123456", strict=True))
_HEX64 = hashlib.sha256(b"#3438").hexdigest()
_SEED = base64.b32encode(b"0123456789").decode()  # a TOTP seed's shape
_BASIC = base64.b64encode(b"user:" + b"hunter2").decode()  # RFC 7617 user:password
_UUID = "f47ac10b-58cc-4372-a567-0e02b2c3d479"
_MIXED = "A1b2" + "C3d4E5f6"  # a short mixed-case secret
_LICENSE = "-".join(["ABCDE", "12345", "FGHIJ"])


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


_JWT = ".".join([_b64url(b'{"alg":"none"}'), _b64url(b'{"sub":"example"}'), _b64url(b"example")])
_PEM = "-----BEGIN " + "PRIVATE " + "KEY-----"
_RSA_PEM = "-----BEGIN RSA " + "PRIVATE " + "KEY----- MIIEow"
_AWS_ID = "AK" + "IA" + "EXAMPLE" + "KEY" + "012345"
_GITHUB = "gh" + "p_" + "a1B2" * 9
_RECOVERY = "-".join(["ABCD", "EFGH", "JKMN", "PQRS", "TUVW", "XYZ2", "3456"])
_BACKUP = "/admin/backups/42/download/" + "a1B2c3D4" * 6
_GITHUB_PAT = "github" + "_pat_" + "a1B2" * 6
_AWS_TEMP = "AS" + "IA" + "EXAMPLE" + "KEY" + "012345"
_SLACK = "xo" + "xb-" + "1234567890" + "-abcdef"
_GOOGLE = "AI" + "za" + "a1B2c3D4" * 4 + "e5F"
_TAILSCALE = "tskey" + "-auth-" + "a1B2c3D4" * 2
_SK = "s" + "k-" + "a1B2c3D4" * 3
_SK_LOWER = "s" + "k-" + "abcdef1234567890abcd"  # no capital: not an issuer key
_SK_NO_DIGIT = "s" + "k-" + "AbcdefGhij" + "klmnopQrstu"  # no digit: not an issuer key
_BASIC_SHORT = base64.b64encode(b"u:" + b"p").decode()

REFUSED = [
    # R1: a credential name bound to a value, in every syntax
    ("password=hunter2", "pair"),
    ("password=hunter2...", "trailing-dots"),
    ("Reason: password=hunter2", "label-then-pair"),
    ("rotating, password=hunter2", "after-prose"),
    ("PASSWORD   =   hunter2", "spaced-upper"),
    ("password\u3000=\u3000hunter2", "ideographic-spaces"),
    ("password\u00a0=\u00a0Tr0ub4dor&3", "no-break-spaces"),
    ("password\uff1ahunter2", "full-width-colon"),
    ('{"password": "hunter2"}', "json"),
    ('{\\"password\\": \\"hunter2\\"}', "escaped-json"),
    ("**password:** Tr0ub4dor&3", "markdown-label"),
    ("`password`: Tr0ub4dor&3", "code-span-label"),
    ("--password hunter2", "option"),
    (f"--token {_TOKEN}", "token-option"),
    ("mysql -u root --password=hunter2 cv", "option-equals"),
    (f"-Dapi.secret={_MIXED}", "property"),
    ("api_key: hunter2", "api-key"),
    ("X-BAPI-API-KEY: EXAMPLEKEY", "bybit-header"),
    ("API key: EXAMPLEKEY", "qualified-key"),
    (f"License key: {_LICENSE}", "license-key"),
    ('token: "abc123"', "quoted-token"),
    ("key=EXAMPLEKEY", "key-long-caps"),
    ("code: 123456", "six-digit-code"),
    ("2FA code: 1234", "2fa-qualified-code"),
    ("otp: 123456", "otp"),
    (f"seed: {_SEED}", "base32-seed"),
    (f"session: {_UUID.upper()}", "uuid-session"),
    ("session: abc123def456", "session-token"),
    ("pass: letmein", "pass-word"),
    ("pass=hunter2", "pass-value"),
    ("password=dragon", "plain-word-password"),
    ("client_secret=topsecret", "client-secret"),
    ("password: none", "no-word-list"),
    ("Cookie: session=abc123", "cookie-pair"),
    ("Set-Cookie: sid=abc123; HttpOnly", "set-cookie"),
    ("Authorization: Bearer abc123", "authorization-bearer"),
    (f"Authorization: Basic {_BASIC}", "authorization-basic"),
    (f"X-BAPI-SIGN: {_HEX64}", "signature-hex"),
    (f"session={_TOKEN}", "session-machine-token"),
    ("Server=db.internal;User Id=app;" + "Pass" + "word=hunter2;", "connection-string"),
    ("DB_PASS=hunter2", "env-pass-suffix"),
    ("export SMTP_PASS=Tr0ub4dor&3", "export-pass-suffix"),
    ("MAIL_PW: hunter2", "pw-suffix"),
    ("db.pwd=hunter2", "pwd-suffix-property"),
    ("mfa=123456", "mfa-code"),
    ("2fa: 123456", "2fa-code"),
    # R2: URLs, including a password that urlsplit cuts at `#`, `?` or `/`
    ("https" + "://user:hunter2@example.com/path", "userinfo"),
    ("see https" + "://u:hunter2@h.example/x", "userinfo-in-prose"),
    ("postgres" + "://app:hunter2@db.internal:5432/cv", "dsn"),
    ("redis" + "://:hunter2@cache.internal:6379/0", "password-only-userinfo"),
    ("https://example.com/cb?token=abc123", "token-param"),
    ("https://idp.example/#/cb?code=abc123", "fragment-route-param"),
    ("https://example.com/app;jsessionid=ABC123?x=1", "path-param"),
    ("https://example.com/x?%74oken=abc123", "percent-encoded-name"),
    ("https" + "://cv:Q7!rT2#wE9@db.local/x", "password-with-hash"),
    ("https" + "://cv:ab/cd@db.local/x", "password-with-slash"),
    ("[runbook](https" + "://owner:hunter2@wiki.example/cv)", "markdown-link"),
    ("https://user:hunter2\uff20host.example/x", "full-width-at"),
    # R3: userinfo outside a URL
    ("admin:Passw0rd!@10.0.0.5:5432", "bare-userinfo"),
    ("https:u:p@h", "schemeless-netloc"),
    # R4: authentication schemes
    ("Bearer abc123def456", "bearer"),
    (f"Basic {_BASIC}", "basic"),
    (f"Basic {_BASIC_SHORT}", "basic-short"),
    # R5: a credential named in words
    ("the password is Tr0ub4dor&3", "password-in-words"),
    (f"token was {_TOKEN}", "token-in-words"),
    ("secret A1b2C3d4E5f6G7h8I9", "secret-in-words"),
    (f"the secret key is {_TOKEN}", "qualified-noun-secret-key"),
    (f"the api key was {_TOKEN}", "qualified-noun-api-key"),
    ("the client secret is Tr0ub4dor&3", "qualified-secret-password-shaped"),
    ("the password is ABCD-12345", "unbracketed-ticket-shaped-password"),
    # R6: known formats, wherever they stand
    (f"pasted {_PEM} by mistake", "pem"),
    (f"key file: {_RSA_PEM}", "rsa-pem"),
    (f"debug token {_JWT}", "jwt"),
    (f"rotated {_AWS_ID} today", "aws-key-id"),
    (f"ci uses {_GITHUB}", "github-token"),
    (f"recovery code: {_RECOVERY}", "recovery-code"),
    (f"download via {_BACKUP}", "backup-link"),
    (f"ci uses {_GITHUB_PAT}", "github-fine-grained-token"),
    (f"rotated {_AWS_TEMP} today", "aws-temporary-key-id"),
    (f"bot token {_SLACK}", "slack-token"),
    (f"maps key {_GOOGLE}", "google-key"),
    (f"joined with {_TAILSCALE}", "tailscale-key"),
    (f"llm key {_SK}", "sk-key"),
]

ACCEPTED = [
    ("session: Asia open", "everyday-session"),
    ("per-symbol key: BTCUSDT", "market-symbol-key"),
    ("Ticket key: E42-T03", "ticket-key"),
    ("flag key: engine.webgl_v2 re-enabled", "flag-key"),
    ("Error code: 10006 rate-limit rejects", "error-code"),
    ("code=500", "status-code"),
    ("seed=42", "seed-number"),
    ("sig=ok", "everyday-sig"),
    ("key=ts,symbol", "key-list"),
    ("Pass: 12/12 canary checks", "pass-ratio"),
    ("set tokens=80/s on the rate limiter", "token-rate"),
    ("token: none; cookie: none; auth: none for the public endpoints", "none-values"),
    ("Authorization: owner only until Monday", "authorization-prose"),
    ("Cookie: consent banner removed from the toolbar", "cookie-prose"),
    ("commit hash: 3f9a1c2d", "commit-hash"),
    ("signature: verified", "signature-prose"),
    ("api_key=<redacted>", "redacted-placeholder"),
    ("Authorization: Bearer <redacted> in the log line is fine", "redacted-bearer"),
    ("export API_KEY=$BYBIT_API_KEY before the drill", "env-reference"),
    ("secret=${{ secrets.X }}", "template-reference"),
    ("password={{secrets.DB_PASSWORD}}", "template-reference-tight"),
    ("secret: N/A", "not-applicable"),
    ("password=********", "mask"),
    ("password=", "empty"),
    ("token=''", "empty-quoted"),
    ("Bybit key: ****AB12 revoked", "masked-id"),
    ("hashing.py:40 fixed", "source-file"),
    (
        "rollout 10:30: token budget raised, see "
        "https://github.com/CandleViewer/CandleViewer/issues/412",
        "time-and-link",
    ),
    ("bearer token support removed from the old endpoint", "bearer-prose"),
    ("Basic auth removed from the old endpoint", "basic-prose"),
    ("Basic auth-free health checks stay on", "basic-hyphenated"),
    ("header Authorization: Bearer", "scheme-without-value"),
    ("ran the backfill with --dry-run first", "non-credential-option"),
    ("the demo API key is expired; poller disabled until it is rotated", "key-in-prose"),
    ("password policy change shipped in #412", "password-policy"),
    ("notify ops@example.com once the flag is on", "email"),
    ("mailto:ops@example.com", "mailto"),
    ("Meeting 10:30@London-open", "time-at"),
    ("BTC:USDT@62000 limit used in the drill", "price-at"),
    ("image python:3.12-slim@sha256:" + _HEX64 + " pinned", "image-digest"),
    ("Bumped https://www.npmjs.com/package/@scope/pkg to 2.1.0", "scoped-package"),
    ("Support link https://support.example/tickets?ticket=12345", "ticket-param"),
    ("admin UI at https://[::1:8000/ after the toggle", "unparseable-url"),
    ("renewed the -----BEGIN CERTIFICATE----- on the proxy", "certificate"),
    ("Pin user " + _UUID + " out of the rollout", "uuid-in-prose"),
    ("<redacted:credential>", "the-marker-itself"),
    ("Rollout erh\u00f6ht auf 25% nach sauberem Canary-Lauf", "german"),
    (f"sample id {_SK_LOWER} from the docs", "lowercase-sk-sample"),
    (f"the docs placeholder {_SK_NO_DIGIT}", "sk-without-digit"),
    ("error 110007 seen on the demo account", "error-code-reworded"),
    ("the secret santa list is done", "secret-in-prose"),
    ("it keeps api_key, never api_secret (SR-E27-20, AC-33)", "secret-then-ticket"),
    ("MFA: provider down, engaging the kill switch", "mfa-prose"),
    ("2FA: rolled out to all managers", "2fa-prose"),
    ("cache bypass: enabled for the replay", "bypass-word"),
]


#: The accepted false positives of the module docstring: refused although they carry no
#: credential. The Owner rewords such a reason (`error 110007`, an ACCEPTED case).
FALSE_POSITIVES = [
    ("max_tokens=4096", "pair-name-max-tokens"),
    ("password_policy=strict", "pair-name-policy"),
    ("Hashing: argon2id", "pair-name-hashing"),
    ("flag_key=engine.webgl_v2", "pair-name-flag-key"),
    ("first_pass: 12/12 green", "pair-name-pass-suffix"),
    ("Password: unchanged", "strong-name-then-word"),
    ("owner:alice@example.com", "address-after-label"),
    ("code: 110007", "six-digits-after-bare-code"),
]


@pytest.mark.parametrize(("reason", "case"), REFUSED, ids=[case for _, case in REFUSED])
def test_a_reason_carrying_a_credential_is_refused_and_recorded_redacted(
    reason: str, case: str
) -> None:
    assert check_reason(reason) == (CREDENTIAL_IN_REASON, REDACTED_CREDENTIAL), case


@pytest.mark.parametrize(
    ("reason", "case"), FALSE_POSITIVES, ids=[case for _, case in FALSE_POSITIVES]
)
def test_a_documented_false_positive_is_refused(reason: str, case: str) -> None:
    """Pinned so the module docstring's list stays true: a change that accepts one updates it."""
    assert credential_in_reason(reason), case


@pytest.mark.parametrize(("reason", "case"), ACCEPTED, ids=[case for _, case in ACCEPTED])
def test_an_honest_reason_is_kept_as_sent(reason: str, case: str) -> None:
    assert check_reason(reason) == (None, reason), case


def test_the_honest_corpus_is_never_refused() -> None:
    """False positives block a flag change mid-incident: an independent corpus pins none."""
    assert len(_HONEST) == 138
    assert [reason for reason in _HONEST if credential_in_reason(reason)] == []


@pytest.mark.parametrize("reason", [None, ""])
def test_an_absent_reason_is_left_to_required(reason: str | None) -> None:
    assert check_reason(reason) == (None, reason)


@pytest.mark.parametrize(
    "name",
    [
        *("password", "api_key", "X-Amz-Credential", "sig", "code", "pw", "client_secret"),
        *("DB_PASS", "mail_pw", "mfa", "2fa", "bypass"),
        *("jsessionid", "ticket", "state", "orgId", "page", "symbol", "reason", "flag", "email"),
    ],
)
def test_the_name_test_is_the_one_credential_in_url_uses(name: str) -> None:
    """One source of truth for a credential's name (C-16.5): a reason's label is a credential
    exactly when the same name as a query parameter makes `evidence_url` a `credential_in_url`."""
    as_param = check_evidence_url(f"https://h.example/x?{name}=v")[0] == "credential_in_url"
    assert is_credential_name(name) is as_param


@pytest.mark.parametrize(
    "reason",
    ["=" * 100, "a=" * 50, "https://" * 12, "password" + " " * 40 + "x", "@:" * 64, ":" * 300],
)
def test_hostile_input_is_judged_without_an_error(reason: str) -> None:
    assert isinstance(credential_in_reason(reason), bool)

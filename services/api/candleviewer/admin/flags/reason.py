"""The `reason` rule of a feature-flag write (#3438, E42 AD-I02; module M21): pure, no I/O.

`PUT /admin/feature-flags/{flagKey}` (`22-api-openapi.yaml` `setFeatureFlag`) records `reason` as
sent: in every `flags.change` record's `after_state`, in an accepted write's own `reason` column
and in `maintenance.*`. Write-time redaction (`audit/redact.py`, SR-069) reads field names, never
free text, and audit rows are append-only, so a reason that carries a credential is refused as
`credential_in_reason`, the way `evidence.py` refuses one in `evidence_url` as
`credential_in_url`, and with the same name test (`is_credential_name`). A reason carries a
credential when, as sent or in NFKC form (so the full-width colon, equals sign and commercial at,
U+FF1A, U+FF1D and U+FF20, read as `:`, `=` and `@`), it holds one of these (rule ids R1-R6, which
the tests use):

- R1, a pair: a credential name, up to three closing quotes, brackets, `*` or backslashes, then
  `=` or `:` (one or two of them and an optional `>`, so `:=`, `==` and `=>` count; spaces
  around it), then a value whose first letter or digit comes within its first nine characters;
  or a credential-named `--option` and such a value after a space. The name is the whole run of
  ASCII letters, digits, `_`, `.` and `-` before the separator. No value is: a placeholder
  (`***`, `<redacted>`, `[REDACTED]`, `****AB12`, `N/A`, `$VAR`, `${...}`, `{{...}}`, `%VAR%`),
  or an everyday value (a word, a number of up to five digits, a market symbol, a flag key, a
  ticket, an issue, a slug or a `v` version) after one of the everyday names
  `_EVERYDAY_NAMES` that no word before it qualifies (`session: Asia open`, `key: BTCUSDT`,
  `code=500`; `API key: ...` reads as `api_key: ...`, which takes any value). A source file's
  name (`hashing.py:40`, `secrets.py: ...`) labels no credential;
- R2, a URL, from its scheme to the next space, that `check_evidence_url` refuses as
  `credential_in_url` (userinfo whose password holds a `/`, `?` or `#` included);
- R3, userinfo `urlsplit` does not see: a part between spaces, `/` and `\\` whose last `@` comes
  after a `:` and at least one more character (`u:p@h`, `admin:pw@10.0.0.5:5432`), unless the
  `@` starts an OCI digest (`@sha256:`), the part is an address (`mailto:`, `cc:` ...) or a time
  or ratio (`10:30@open`, `BTC:USDT@62000`);
- R4, an authentication scheme and its credential: `Bearer` and a token-like value, `Basic` and
  one or the base64 of `user:password`;
- R5, a credential named in words and a token-like value after it (`token was ...`,
  `exchange key ...`), or a password-shaped one after a noun ending in `password`,
  `passphrase`, `passwd` or `secret` (`client secret ...`);
- R6, a known format, wherever it stands: a PEM private key's armour, a JOSE compact
  serialisation (a JWT), a GitHub, AWS access-key-id, Slack, Google, Tailscale or `sk-` key, a
  CandleViewer recovery code or a backup download link's token.

A credential that is none of these is the accepted residual, as a path token is for `evidence_url`:
a bare password or key with no label, a credential written out in words, a name the tables miss, an
encoded or split one, a foreign path token, a URL password that starts with digits and holds a `/`
(read as a port), an all-digit `Bearer` value, a value after a source file's name
(`password.txt: ...`), and a key named in prose after a word the qualifier table does not hold (an
exchange's own name: C-2.2 keeps exchange names out of this module). Accepted false positives,
refused although they carry none: a pair whose name the shared test marks without naming a
credential (`max_tokens=4096`, `password_policy=strict`, `Hashing: argon2id`, `flag_key=...`, and
`_pass` counters such as `first_pass: 12/12`), a strong name followed by a word
(`Password: unchanged`), an address right after a label's colon (`owner:alice@example.com`), and six
or more digits after a bare `code` (`code: 110007`), the shape of a one-time code. The Owner rewords
such a reason (`error 110007`). A refused reason is recorded whole as `REDACTED_CREDENTIAL`: never
as sent, in part, as a digest or as a length. The cost is linear in the reason's length: every
pattern is possessive or bounded, a value is read at most `_VALUE_MAX` characters and each URL is
parsed once, at most `EVIDENCE_URL_MAX + 1` characters.
"""

from __future__ import annotations

import base64
import binascii
import re
import unicodedata
from typing import Final, Literal

from candleviewer.admin.flags.evidence import (
    REDACTED_CREDENTIAL,
    check_evidence_url,
    is_credential_name,
    name_key,
)

ReasonRule = Literal["credential_in_reason"]
CREDENTIAL_IN_REASON: Final[ReasonRule] = "credential_in_reason"

#: The most of a value that is read after a label or a scheme: more than any credential.
_VALUE_MAX: Final = 256
_QUOTES: Final = "\"'`"
_TRAILING: Final = ".,;:!?"
_CLOSING: Final = frozenset(".,;:!?)]}>\"'`")
_RUN: Final = re.compile(r"\S*+")
_SPACE: Final = re.compile(r"\s++")
_DELIMITERS: Final = re.compile(r"[\s,;&]")

# ---- R1: pairs and options ----------------------------------------------------------------------

#: A pair: the whole name (possessive, after no name character), up to three closing characters,
#: the separator, Markdown emphasis closing a label (`**Password:** ...`), spaces, and a lookahead
#: for the value, so a value is never consumed and the next name is read whole.
_PAIR: Final = re.compile(
    r"(?<![A-Za-z0-9_.-])(?P<name>[A-Za-z0-9_.-]++)"  # the name
    r"[\\\"'`\])*]{0,3}+(?P<pre>\s*+)(?P<sep>[:=]{1,2}+>?+)"  # closing characters, the separator
    r"(?:[*_]{1,3}+(?=\s))?+(?P<post>\s*+)"  # emphasis, then the spaces before the value
    r"(?=(?:[^\s\w]|_){0,8}[^\W_])"  # a letter or digit within the value's first nine
)
#: A `--name value` command-line option; a value starting with `-` is the next option.
_OPTION: Final = re.compile(
    r"(?<![A-Za-z0-9_.-])--(?P<name>[A-Za-z0-9][A-Za-z0-9_.-]*+)[ \t]++"
    r"(?=(?:[^\s\w-]|_){0,8}[^\W_])"
)
#: The scheme words a label's value may start with (`Authorization: Bearer ...`).
_SCHEME_WORDS: Final = frozenset({"bearer", "basic", "token", "digest", "bot", "apikey"})
#: No value: a mask, a masked id, a named placeholder or a reference to where the value lives.
_PLACEHOLDER: Final = re.compile(
    r"[*xX\N{BULLET}.\N{HORIZONTAL ELLIPSIS}#_-]++"  # ***, xxxx, ...
    r"|\*{3,}+[A-Za-z0-9]{1,6}+"  # a masked id: ****AB12
    r"|<[A-Za-z][A-Za-z _.:/-]*+>|\[[A-Za-z][A-Za-z _.:/-]*+\]"  # <redacted>, [REDACTED]
    r"|\$\{[^{}]*+\}|\$\(?[A-Z_][A-Z0-9_]*+\)?|%[A-Za-z_][A-Za-z0-9_]*+%"  # ${X}, $X, %X%
    r"|(?i:n/a)"  # not applicable
)
_TEMPLATE_START: Final = ("${", "{{", "{%")
#: A source file's name (`hashing.py:40`, `admin_kek.py: ...`): a reference, not a label.
_SOURCE: Final = re.compile(
    r"[A-Za-z0-9_.-]*\.(?:py|pyi|ts|tsx|js|jsx|mjs|cjs|md|json|ya?ml|toml|sql|sh|css|html|txt"
    r"|ini|cfg|lock|go|rs)",
    re.IGNORECASE,
)
#: Credential names that are also everyday words, whose machine-issued credentials are never
#: an everyday value (`session: Asia open`, `key: BTCUSDT`, `code=500`, `token: none`). After
#: `pass` only a number is everyday, after `hash` a hex digest is too. Every other credential
#: name (`password`, `secret`, `api_key`, `access_token` ...) takes any value.
_EVERYDAY_NAMES: Final = frozenset(
    {"session", "key", "code", "auth", "authorization", "sign", "signature", "sig", "seed"}
    | {"hash", "token", "tokens", "cookie", "jwt", "bearer", "kek", "dek", "pass", "mfa", "2fa"}
)
#: A word before an everyday name that says whose secret it is: `API key: ...` reads as
#: `api_key: ...`. No exchange names here: cv-adapter-isolation keeps them in the adapter (C-2.2).
_QUALIFIERS: Final = frozenset(
    {"api", "secret", "private", "access", "signing", "master", "client", "exchange"}
    | {"demo", "testnet", "live", "recovery", "auth", "session", "refresh", "bearer", "backup"}
    | {"invite", "reset", "otp", "totp", "mfa", "2fa", "login", "ssh", "pgp", "gpg", "encryption"}
    | {"license", "licence", "product", "activation", "serial", "registration", "webhook"}
)
#: How far before a name its qualifier may stand.
_QUALIFIER_REACH: Final = 32
_PREVIOUS: Final = re.compile(r"([A-Za-z0-9]+)[ \t]+$")
_FLAG_KEY: Final = re.compile(r"[a-z0-9]++(?:\.[a-z0-9_]++)++")
#: A ticket (`E42-T03`, `INC-2026-114`), an epic or finding key (`E03`, `F1`), an issue (`#412`).
_TICKET: Final = re.compile(r"[A-Z][A-Z0-9]*+(?:-[A-Z0-9]++)++|[A-Z]{1,3}[0-9]{1,4}|#[0-9]{1,6}")
_UUID: Final = re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}")
_SYMBOL: Final = re.compile(r"[0-9]*+[A-Z]{2,24}USDT")
_CAMEL: Final = re.compile(r"(?:[A-Z][a-z]++)++")
_NUMBER: Final = re.compile(r"[0-9]{1,5}(?:[./:][0-9]{1,5})?(?:%|/[smh]|ms|[smhx])?")
_SLUG: Final = re.compile(r"[a-z]{2,}+(?:-[a-z0-9]++)++")
_VERSION: Final = re.compile(r"v[0-9]{1,3}(?:\.[0-9]{1,3}){0,2}")
_HEX: Final = re.compile(r"[0-9a-f]{7,64}")

# ---- R2, R3: URLs and userinfo ------------------------------------------------------------------

#: A URL: from the start of the scheme run before a `://` to the next space.
_URL: Final = re.compile(r"(?<![A-Za-z0-9+.-])[A-Za-z0-9+.-]*+://\S*+")
#: A part of the text between spaces, `/` and `\`, which is where userinfo can sit.
_PART: Final = re.compile(r"[^\s/\\]++")
#: An image digest (`name:tag@sha256:...`): its `@` ends no userinfo.
_DIGEST: Final = re.compile(r"@sha(?:256|384|512):")
#: An address after one of these labels is an address, not userinfo (`mailto:ops@example.com`).
_ADDRESS_LABELS: Final = frozenset(
    {"mailto", "email", "e-mail", "mail", "cc", "bcc", "to", "from", "contact", "reply-to"}
)

# ---- R4, R5: schemes and credentials named in words ---------------------------------------------

_SCHEME: Final = re.compile(r"(?i)(?<![A-Za-z0-9_-])(?P<scheme>bearer|basic)\s++")
#: The qualified nouns come first: tried before the bare ones, `secret key` is read whole.
_SPOKEN: Final = re.compile(
    r"(?i)(?<![A-Za-z0-9_-])(?P<noun>"
    r"(?:api|secret|private|access|signing|client|master|exchange|demo|testnet|live)"
    r"[ _-]?(?:key|secret|token)"
    r"|(?:access|refresh|session|auth|bearer|id)[ _-]?token"
    r"|pass(?:word|phrase)|passwd|secret|token|jwt)s?+"
    r"\s++(?:(?:is|was|are|were)\s++)?+(?=\S)"
)
_PASSWORD_NOUNS: Final = ("password", "passphrase", "passwd", "secret")
_TOKEN: Final = re.compile(r"[A-Za-z0-9._~+/-]++=*+")
_BASE64: Final = re.compile(r"[A-Za-z0-9+/]{4,}+={0,2}+")
#: Not a token: a UUID, a version, a date, CamelCase words and numbers, a flag key.
_IDENTIFIER: Final = re.compile(
    _UUID.pattern + r"|v?[0-9]++(?:\.[0-9A-Za-z]++)++(?:[-+][0-9A-Za-z.]++)*+"
    r"|[0-9]{4}-[0-9]{2}-[0-9]{2}\S*+"
    r"|(?:[A-Z][a-z]++|[0-9]++)++"
    r"|[a-z0-9]++(?:\.[a-z0-9_]++)++"
)
_PW_SYMBOLS: Final = frozenset("!#$%&*+=?@^~")

# ---- R6: known formats --------------------------------------------------------------------------

#: Issuer-designed prefixes (GitHub `ghp_`, AWS `AKIA`, Slack `xox`, Google `AIza`, Tailscale
#: `tskey-`) and structural shapes (PEM armour, a JOSE header `eyJ`, base64url for `{"`), plus
#: CandleViewer's own recovery codes and backup download links. A new entry needs such a prefix
#: or shape, a test vector built by concatenation (#3482) and a C-10.2 review.
_KNOWN: Final = re.compile(
    r"(?i:-----BEGIN[ A-Z0-9_-]{0,40}PRIVATE KEY)"
    r"|(?<![A-Za-z0-9_-])eyJ[A-Za-z0-9_-]{7,}+\.(?:eyJ|[A-Za-z0-9_-]*+\.)"
    r"|(?<![A-Za-z0-9_])(?:gh[pousr]_[A-Za-z0-9]{20,}+|github_pat_[A-Za-z0-9_]{20,}+)"
    r"|(?<![A-Za-z0-9])(?:AKIA|ASIA)[A-Z0-9]{16}(?![A-Za-z0-9])"
    r"|(?<![A-Za-z0-9])xox[abprs]-[A-Za-z0-9-]{10,}+"
    r"|(?<![A-Za-z0-9_-])AIza[A-Za-z0-9_-]{35}"
    r"|(?<![A-Za-z0-9_-])tskey-[a-z]++-[A-Za-z0-9-]{10,}+"
    r"|(?<![A-Za-z0-9-])(?i:[2-9A-HJKMNP-Z]{4}(?:-[2-9A-HJKMNP-Z]{4}){6})(?![A-Za-z0-9-])"
    r"|/admin/backups/[^/\s]*+/download/[A-Za-z0-9_-]{20,}+"
)
#: An `sk-` API key (`sk-ant-...`, `sk-proj-...`): a body of mixed case and digits.
_SK: Final = re.compile(r"(?<![A-Za-z0-9_-])sk-[A-Za-z0-9_-]{20,}+")


def check_reason(reason: str | None) -> tuple[ReasonRule | None, str | None]:
    """`reason`'s refusal (`None` when it is absent or carries no credential) and the form every
    audit record of the request holds: a refused reason as `REDACTED_CREDENTIAL`, any other as
    sent."""
    if reason and credential_in_reason(reason):
        return CREDENTIAL_IN_REASON, REDACTED_CREDENTIAL
    return None, reason


def credential_in_reason(reason: str) -> bool:
    """Whether `reason`, as sent or in NFKC form, carries a credential (R1-R6, the module
    docstring)."""
    forms = dict.fromkeys((reason, unicodedata.normalize("NFKC", reason)))  # once when equal
    return any(_carries(form) for form in forms)


def _carries(text: str) -> bool:
    return (
        _KNOWN.search(text) is not None
        or _sk_key(text)
        or _pairs(text)
        or _url_credential(text)
        or _userinfo(text)
        or _schemes(text)
        or _spoken(text)
    )


# ---- R1 -----------------------------------------------------------------------------------------


def _pairs(text: str) -> bool:
    for pair in _PAIR.finditer(text):
        name = pair["name"]
        if not is_credential_name(name) or _SOURCE.fullmatch(name):
            continue
        if not _no_value(text, pair.start(), pair.end(), name):
            return True
    for option in _OPTION.finditer(text):
        name = option["name"]
        if is_credential_name(name) and not _no_value(text, option.start(), option.end(), name):
            return True
    return False


def _no_value(text: str, start: int, at: int, name: str) -> bool:
    """The value at `at` is none: a placeholder, or an everyday value after an everyday name that
    no word before it qualifies."""
    value, quoted = _value_at(text, at)
    if not quoted and value.strip("*_").lower() in _SCHEME_WORDS:  # `Authorization: Bearer x`
        gap = _SPACE.match(text, at + len(value))
        if gap is not None and gap.end() < len(text):
            value, quoted = _value_at(text, gap.end())
    if _placeholder(value):
        return True
    normal = name_key(name)
    if normal not in _EVERYDAY_NAMES:
        return False
    before = _PREVIOUS.search(text, max(0, start - _QUALIFIER_REACH), start)
    if before is not None and before[1].lower() in _QUALIFIERS:
        return False
    return _everyday(normal, value)


def _value_at(text: str, at: int) -> tuple[str, bool]:
    """The value at `at`, read at most `_VALUE_MAX` characters: a quoted one to its closing
    quote, else the run to the next space; and whether it was quoted."""
    if at < len(text) and text[at] in _QUOTES:
        end = text.find(text[at], at + 1, at + 1 + _VALUE_MAX)
        return text[at + 1 : end if end >= 0 else at + 1 + _VALUE_MAX], True
    run = _RUN.match(text, at, at + _VALUE_MAX)
    return (run.group() if run else ""), False


def _placeholder(value: str) -> bool:
    """A mask, a masked id, a named placeholder or a reference, with up to three closing
    characters after it (`<redacted>).`)."""
    core = value.strip("\\" + _QUOTES)
    if core.startswith(_TEMPLATE_START):
        return True
    for cut in range(min(4, len(core))):
        if cut and core[-cut] not in _CLOSING:
            break
        if _PLACEHOLDER.fullmatch(core[: len(core) - cut]):
            return True
    return False


def _everyday(name: str, value: str) -> bool:
    """The value's first word, to a `,`, `;` or `&`, is everyday: a word in lower, title or camel
    case or an acronym of up to five capitals, a number of up to five digits (a ratio, a decimal,
    `%` or a unit), a market symbol, a flag key, a ticket or an issue, a slug or a `v` version;
    after `pass` only a number, after `hash` a hex digest too. A UUID is not. A random token is
    next to never one of these."""
    words = _DELIMITERS.split(value, maxsplit=1)
    word = words[0].strip("([{").rstrip(_TRAILING + ")]}") if words else ""
    if not word or _UUID.fullmatch(word):
        return False
    if name == "pass":
        return _NUMBER.fullmatch(word) is not None
    if word.isalpha() and (word.islower() or word.istitle() or _CAMEL.fullmatch(word)):
        return True
    if (word.isalpha() and word.isupper() and len(word) <= 5) or _NUMBER.fullmatch(word):
        return True
    for shape in (_SYMBOL, _FLAG_KEY, _TICKET, _SLUG, _VERSION):
        if shape.fullmatch(word):
            return True
    return name == "hash" and _HEX.fullmatch(word) is not None


# ---- R2, R3 -------------------------------------------------------------------------------------


def _url_credential(text: str) -> bool:
    for match in _URL.finditer(text):
        url = match.group().lstrip("0123456789+.-")  # a scheme starts with a letter
        if check_evidence_url(url)[0] == "credential_in_url":
            return True
    return False


def _userinfo(text: str) -> bool:
    """A part between spaces, `/` and `\\` whose last `@` follows a `:` and one more character,
    unless the `@` starts a digest, or the part is an address, a time, a ratio or a price."""
    for match in _PART.finditer(text):
        part = _DIGEST.sub("", match.group())
        colon, at = part.find(":"), part.rfind("@")
        if not 0 <= colon < at - 1:
            continue
        user, secret, host = part[:colon].lstrip("<([\"'`*"), part[colon + 1 : at], part[at + 1 :]
        if user.lower() in _ADDRESS_LABELS or (user.isdigit() and secret.isdigit()):
            continue  # an address, a time or a ratio (`10:30@open`)
        if not host.isdigit():  # `BTC:USDT@62000` is a price
            return True
    return False


# ---- R4, R5 -------------------------------------------------------------------------------------


def _schemes(text: str) -> bool:
    for match in _SCHEME.finditer(text):
        value = _word(text, match.end())
        if _token_like(value, 8):
            return True
        if match["scheme"].lower() == "basic" and _basic_pair(value):
            return True
    return False


def _spoken(text: str) -> bool:
    for match in _SPOKEN.finditer(text):
        value = _word(text, match.end())
        if _token_like(value, 16):
            return True
        if match["noun"].lower().endswith(_PASSWORD_NOUNS) and _password_shaped(value):
            return True
    return False


def _word(text: str, at: int) -> str:
    """The value at `at` without its quotes and closing punctuation."""
    value, _ = _value_at(text, at)
    return value.strip(_QUOTES).rstrip(_TRAILING + ")]}" + _QUOTES)


def _token_like(value: str, minimum: int) -> bool:
    """`minimum` or more base64 or base64url characters with a digit or both cases, and no
    identifier."""
    if len(value) < minimum or not _TOKEN.fullmatch(value) or _IDENTIFIER.fullmatch(value):
        return False
    upper = any(c.isupper() for c in value)
    lower = any(c.islower() for c in value)
    return any(c.isdigit() for c in value) or (upper and lower)


def _password_shaped(value: str) -> bool:
    """Eight or more characters, no space, a letter, a digit and a capital or a symbol, and not
    an identifier or a bracketed ticket (`(SR-E27-20)`)."""
    if len(value) < 8 or any(c.isspace() for c in value):
        return False
    bracketed = value.startswith(("(", "[", "{")) and _TICKET.fullmatch(value.lstrip("([{"))
    if _IDENTIFIER.fullmatch(value) or bracketed:
        return False
    if not (any(c.isalpha() for c in value) and any(c.isdigit() for c in value)):
        return False
    return any(c.isupper() or c in _PW_SYMBOLS for c in value)


def _basic_pair(value: str) -> bool:
    """Base64 of RFC 7617's `user:password`."""
    if not _BASE64.fullmatch(value):
        return False
    try:
        decoded = base64.b64decode(value + "=" * (-len(value) % 4), validate=True).decode()
    except (binascii.Error, ValueError):
        return False
    return ":" in decoded and decoded.isprintable()


# ---- R6 -----------------------------------------------------------------------------------------


def _sk_key(text: str) -> bool:
    for match in _SK.finditer(text):
        body = match.group()[3:]
        if any(c.isupper() for c in body) and any(c.islower() for c in body):
            if any(c.isdigit() for c in body):
                return True
    return False

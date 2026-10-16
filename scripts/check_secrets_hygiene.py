"""Credential-hygiene gate (E43-T06; SR-140, SR-141, SR-144, SR-145, SR-146).

Subcommands (all offline, deterministic, exit 1 on violation):

* ``fixtures``  - no fixture holds a real-looking exchange key without ``DUMMY_PREFIX`` (SR-145),
  and no file of the accounts fault-injection pack holds a bare key-shaped token (E27-Q01)
* ``dev-env``   - ``.env`` gitignored, ``.env.example`` free of secret values (SR-144)
* ``workflows`` - no ``set -x`` / environment dump in workflows (SR-146)
* ``inventory`` - a secret-name list (JSON array) holds no live key / KEK (SR-140)
* ``logs``      - scan log/artefact files for secret shapes (SR-146)

A failure that implicates a real credential refers to runbook IR-02 (rotate first, SR-143).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

#: Documented dummy prefix; the gitleaks allowlist and the fixture test both assert it.
DUMMY_PREFIX = "DUMMYKEY_"
IR02 = "IR-02: rotate the credential FIRST, investigate second (docs/ci-runbook.md, SR-143)"

#: Same shapes as the gitleaks exchange-key rules in .gitleaks.toml (controls must agree).
_KEY_FIELD = re.compile(
    r"""(?i)["']?(api[_-]?key|api[_-]?secret)["']?\s*[:=]\s*["']([A-Za-z0-9_]{16,})["']"""
)
_HEADER = re.compile(r"(?i)X-BAPI-(API-KEY|SIGN)\s*[:=]\s*[\"']?([A-Za-z0-9_]{16,})")
_SIGN = re.compile(r"""(?i)"sign(ature)?"\s*:\s*"([A-Fa-f0-9]{32,})\"""")
_PRIVATE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_TOKEN = re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9]{20,})\b")
_REDACTED_MARKERS = ("REDACTED", "<redacted", "[redacted")

_FIXTURE_DIRS = ("services/api/tests/fixtures", "packages/fixtures", "tests/fixtures")

#: E27-Q01 (#833): an exchange API key is a bare 18-20 character alphanumeric token, a secret one of
#: 36. The accounts pack hyphenates every id by rule (``fixture-<scenario>-NNNN``), so in the pack
#: a bare token of that shape is a paste, whatever field or prose it sits in. The same rule as
#: ``packages/fixtures/scripts/accounts-pack.mjs`` (``findKeyShapedTokens``): a maximal run of
#: ``[A-Za-z0-9_-]`` that is purely alphanumeric counts when it holds a digit, or, letters only,
#: when it mixes at least ``_MIXED_CASE_MIN`` capitals and as many small letters. A tripwire for
#: accidental pastes, not a complete control.
_KEY_SHAPE_DIRS = ("packages/fixtures/accounts",)
_BARE_RUN = re.compile(r"[A-Za-z0-9_-]+")
_ALNUM = re.compile(r"[A-Za-z0-9]+")
_MIXED_CASE_MIN = 6
_TEXT_SUFFIXES = {
    ".json",
    ".jsonl",
    ".txt",
    ".md",
    ".yaml",
    ".yml",
    ".py",
    ".ts",
    ".mjs",
    ".csv",
}
_ENV_EXAMPLE_OK = re.compile(
    r"(?i)(KEY|SECRET|TOKEN|PASSWORD|KEK|DSN)[A-Z0-9_]*\s*=\s*(\S+)"
)


def _is_benign(value: str) -> bool:
    return value.startswith(DUMMY_PREFIX) or any(
        m.lower() in value.lower() for m in _REDACTED_MARKERS
    )


def scan_text(text: str) -> list[str]:
    """Return human descriptions of real-looking credentials found in ``text``."""
    hits: list[str] = []
    for rx in (_KEY_FIELD, _HEADER):
        for m in rx.finditer(text):
            if not _is_benign(m.group(2)):
                hits.append(f"exchange-key-shape ({m.group(1).lower()})")
    for m in _SIGN.finditer(text):
        hits.append("exchange-hmac-signature")
    if _PRIVATE.search(text):
        hits.append("private-key-block")
    for m in _TOKEN.finditer(text):
        if not _is_benign(m.group(0)):
            hits.append("token-shape")
    return hits


def _key_shape(length: int) -> str | None:
    if 18 <= length <= 20:
        return "api-key"
    if length == 36:
        return "api-secret"
    return None


def _looks_like_key(token: str) -> bool:
    if not _ALNUM.fullmatch(token) or not any(c.isalpha() for c in token):
        return False
    if any(c.isdigit() for c in token):
        return True
    capitals = sum(c.isupper() for c in token)
    return capitals >= _MIXED_CASE_MIN and len(token) - capitals >= _MIXED_CASE_MIN


def scan_key_shapes(text: str) -> list[str]:
    """Bare key- or secret-shaped tokens in ``text``: shape, length and offset, never the token."""
    hits: list[str] = []
    for m in _BARE_RUN.finditer(text):
        token = m.group(0)
        shape = _key_shape(len(token))
        if shape is not None and _looks_like_key(token):
            hits.append(f"bare {shape}-shaped token ({len(token)} chars at offset {m.start()})")
    return hits


def _check_key_shapes(root: Path) -> list[str]:
    """Every file of the accounts pack, whatever its suffix or name (plants live in tmp copies)."""
    errors: list[str] = []
    for d in _KEY_SHAPE_DIRS:
        base = root / d
        for path in sorted(base.rglob("*")) if base.is_dir() else []:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            rel = path.relative_to(root).as_posix()
            for hit in scan_key_shapes(text):
                errors.append(f"{rel}: {hit}; the token is never printed (E27-Q01)")
    return errors


def check_fixtures(root: Path) -> list[str]:
    errors: list[str] = _check_key_shapes(root)
    for d in _FIXTURE_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in _TEXT_SUFFIXES:
                continue
            rel = path.relative_to(root).as_posix()
            # Scanner self-tests plant fake keys on purpose (allowlisted in .gitleaks.toml).
            if (
                "/test/" in rel
                or ".test." in path.name
                or path.name.startswith("test_")
            ):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for hit in scan_text(text):
                errors.append(
                    f"{path.relative_to(root).as_posix()}: {hit} without {DUMMY_PREFIX} prefix"
                )
    return errors


def check_dev_env(root: Path) -> list[str]:
    errors: list[str] = []
    gi = root / ".gitignore"
    lines = (
        [ln.strip() for ln in gi.read_text(encoding="utf-8").splitlines()]
        if gi.exists()
        else []
    )
    if ".env" not in lines:
        errors.append(".gitignore: '.env' is not ignored")
    ex = root / ".env.example"
    if not ex.exists():
        errors.append(".env.example is missing")
    else:
        for n, ln in enumerate(ex.read_text(encoding="utf-8").splitlines(), 1):
            if ln.lstrip().startswith("#"):
                continue
            m = _ENV_EXAMPLE_OK.search(ln)
            if (
                m
                and m.group(2).strip("\"'")
                and not _is_benign(m.group(2).strip("\"'"))
            ):
                errors.append(
                    f".env.example:{n}: secret-named setting has a non-empty value"
                )
            if scan_text(ln):
                errors.append(f".env.example:{n}: credential-shaped value")
    return errors


_SET_X = re.compile(r"(^|[\s;&|])set\s+-[a-zA-Z]*x[a-zA-Z]*(\s|$)|--xtrace|bash\s+-x\b")
_ENV_DUMP = re.compile(
    r"(^|[;&|]\s*|^\s*-?\s*(run:\s*)?)(printenv|env|export\s+-p|set)\s*(\||$|>)"
)
_SKIP_ALLOW = "# secrets-hygiene: allow"


def check_workflows(root: Path) -> list[str]:
    errors: list[str] = []
    wf = root / ".github" / "workflows"
    for path in sorted(wf.glob("*.y*ml")) if wf.is_dir() else []:
        for n, ln in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if _SKIP_ALLOW in ln or ln.lstrip().startswith("#"):
                continue
            body = ln.strip().removeprefix("- run:").removeprefix("run:").strip()
            if _SET_X.search(body):
                errors.append(f"{path.name}:{n}: 'set -x' tracing (SR-146)")
            if _ENV_DUMP.search(body):
                errors.append(f"{path.name}:{n}: environment dump (SR-146)")
    return errors


_FORBIDDEN_SECRET = re.compile(
    r"(?i)(LIVE.*(API[_-]?(KEY|SECRET))|(API[_-]?(KEY|SECRET)).*(LIVE|PROD)|"
    r"(PROD|PRODUCTION).*KEK|KEK.*(PROD|PRODUCTION)|FUNDED)"
)
_LONG_LIVED = re.compile(
    r"(?i)(AWS_SECRET_ACCESS_KEY|GCP_SA_KEY|AZURE_CLIENT_SECRET|_PAT$)"
)


def check_inventory(
    names: list[str], release_bearing_protected: dict[str, bool] | None = None
) -> list[str]:
    errors: list[str] = []
    for name in names:
        if _FORBIDDEN_SECRET.search(name):
            errors.append(
                f"secret '{name}': production exchange credential / KEK in CI (SR-140); {IR02}"
            )
        if _LONG_LIVED.search(name):
            errors.append(f"secret '{name}': long-lived token; prefer OIDC (SR-141)")
    for name, ok in (release_bearing_protected or {}).items():
        if not ok:
            errors.append(
                f"secret '{name}': release-bearing but not environment-scoped with reviewers (SR-141)"
            )
    return errors


def check_logs(paths: list[Path]) -> list[str]:
    errors: list[str] = []
    for p in paths:
        files = [f for f in p.rglob("*") if f.is_file()] if p.is_dir() else [p]
        for f in files:
            text = f.read_text(encoding="utf-8", errors="replace")
            for hit in scan_text(text):
                errors.append(f"{f.as_posix()}: {hit} in log/artefact (SR-146); {IR02}")
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "check",
        choices=["fixtures", "dev-env", "workflows", "inventory", "logs", "all"],
    )
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--root", default=".")
    ns = ap.parse_args(argv)
    root = Path(ns.root).resolve()
    errors: list[str] = []
    if ns.check in ("fixtures", "all"):
        errors += check_fixtures(root)
    if ns.check in ("dev-env", "all"):
        errors += check_dev_env(root)
    if ns.check in ("workflows", "all"):
        errors += check_workflows(root)
    if ns.check == "inventory":
        errors += check_inventory(
            json.loads(Path(ns.paths[0]).read_text(encoding="utf-8"))
        )
    if ns.check == "logs":
        errors += check_logs([Path(p) for p in ns.paths])
    for e in errors:
        print(f"FAIL {e}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

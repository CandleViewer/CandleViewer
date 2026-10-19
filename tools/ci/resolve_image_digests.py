#!/usr/bin/env python3
"""Resolve and verify container image digest pins (SR-132, #1857).

Scans ``infra/docker-compose*.yml``, ``infra/compose/*.yml``, ``infra/images/*`` and
``.github/workflows/*.yml`` for ``repo:tag@sha256:<64 hex>`` references.

* default mode: resolve the real manifest digest of ``repo:tag`` from the registry and rewrite
  the reference in place when it differs.
* ``--check``: first compare the ledger ``infra/images/PINS.md`` with those pins, offline
  (#3571): each row's image, tag and digest must match a source pin, every source pin needs
  one row, and the "All N pins" line must count the rows. Its errors print before any registry
  call, so a registry that cannot be reached never hides them. Then HEAD every pinned
  manifest; fail on placeholder-shaped digests (repeated hex patterns, ``deadbeef``, all zeros)
  and on digests the registry does not know. ``--offline`` skips this registry part.

Resolution uses the registry HTTP API with an anonymous bearer token (Docker Hub, ghcr.io,
quay.io); docker is not required. No credentials are ever used. Stdlib only.

Error codes: CI-IMG-002 (placeholder or unresolvable digest), CI-IMG-007 (a ledger row and
the source pins disagree), CI-IMG-008 (count line wrong or missing), CI-IMG-009 (ledger table
unreadable; the check fails closed).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Protocol, TypeVar

T = TypeVar("T")
RETRY_ATTEMPTS = 3
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})

ROOT = Path(__file__).resolve().parents[2]
# repo[:tag]@sha256:digest. The repo may include a registry host.
REF_RE = re.compile(
    r"(?P<repo>[a-z0-9][a-z0-9._/-]*[a-z0-9])(?::(?P<tag>[A-Za-z0-9_][A-Za-z0-9._-]*))?"
    r"@sha256:(?P<digest>[0-9a-f]{64})"
)
LEDGER = "infra/images/PINS.md"
COUNT_RE = re.compile(r"^All (\d+) pins\b")
SEPARATOR_RE = re.compile(r"\|(?:\s*:?-+:?\s*\|)+")
Pin = tuple[str, str, str]  # (repo, tag or "", digest hex)
ACCEPT = (
    "application/vnd.oci.image.index.v1+json, "
    "application/vnd.docker.distribution.manifest.list.v2+json, "
    "application/vnd.oci.image.manifest.v1+json, "
    "application/vnd.docker.distribution.manifest.v2+json"
)


def with_retry(
    fn: Callable[[], T],
    attempts: int = RETRY_ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call ``fn``, retrying with exponential backoff on HTTP 429/5xx (not on 4xx)."""
    for i in range(attempts):
        try:
            return fn()
        except urllib.error.HTTPError as exc:
            if exc.code not in RETRY_STATUS or i == attempts - 1:
                raise
            sleep(2.0**i)
    raise AssertionError("unreachable")  # pragma: no cover


class RegistryClient(Protocol):
    def digest(self, repo: str, tag: str) -> str | None:
        """Return ``sha256:<hex>`` of the manifest for ``repo:tag`` or None if unpublished."""

    def exists(self, repo: str, digest: str) -> bool:
        """True if the registry serves a manifest with this digest."""


def split_repo(repo: str) -> tuple[str, str]:
    """Return (registry host, repository path), defaulting to Docker Hub ``library/``."""
    parts = repo.split("/")
    if len(parts) > 1 and (
        "." in parts[0] or ":" in parts[0] or parts[0] == "localhost"
    ):
        return parts[0], "/".join(parts[1:])
    path = repo if "/" in repo else f"library/{repo}"
    return "registry-1.docker.io", path


def is_placeholder(hexdigest: str) -> bool:
    """Heuristic for fabricated digests: tiny alphabet, short repeating period, deadbeef."""
    if "deadbeef" in hexdigest or len(set(hexdigest)) <= 2:
        return True
    return any(hexdigest == hexdigest[:n] * (64 // n) for n in (2, 4, 8, 16, 32))


class HttpRegistry:
    """Anonymous registry v2 client (no credentials)."""

    def __init__(self) -> None:
        self._tokens: dict[tuple[str, str], str | None] = {}

    def _token(self, host: str, path: str) -> str | None:
        key = (host, path)
        if key in self._tokens:
            return self._tokens[key]
        if host == "registry-1.docker.io":
            url = (
                "https://auth.docker.io/token?service=registry.docker.io"
                f"&scope=repository:{path}:pull"
            )
        elif host == "ghcr.io":
            url = f"https://ghcr.io/token?scope=repository:{path}:pull"
        elif host == "quay.io":
            url = (
                f"https://quay.io/v2/auth?service=quay.io&scope=repository:{path}:pull"
            )
        else:
            self._tokens[key] = None
            return None
        try:
            with urllib.request.urlopen(url, timeout=30) as r:  # nosec B310
                tok = str(json.load(r).get("token") or "") or None
        except (urllib.error.URLError, ValueError):
            tok = None
        self._tokens[key] = tok
        return tok

    def _head(self, repo: str, ref: str) -> str | None:
        host, path = split_repo(repo)
        req = urllib.request.Request(
            f"https://{host}/v2/{path}/manifests/{ref}", method="HEAD"
        )
        req.add_header("Accept", ACCEPT)
        tok = self._token(host, path)
        if tok:
            req.add_header("Authorization", f"Bearer {tok}")

        def _do() -> str | None:
            with urllib.request.urlopen(req, timeout=30) as r:  # nosec B310
                return str(r.headers.get("Docker-Content-Digest") or "") or None

        try:
            return with_retry(_do)
        except urllib.error.HTTPError as exc:
            if exc.code in (400, 401, 403, 404):
                return None
            raise

    def digest(self, repo: str, tag: str) -> str | None:
        return self._head(repo, tag)

    def exists(self, repo: str, digest: str) -> bool:
        return self._head(repo, digest) is not None


def iter_files(root: Path) -> list[Path]:
    pats = [
        "infra/docker-compose*.yml",
        "infra/compose/*.yml",
        "infra/images/*",
        ".github/workflows/*.yml",
    ]
    out: list[Path] = []
    for pat in pats:
        out.extend(
            p for p in sorted(root.glob(pat)) if p.is_file() and p.suffix != ".md"
        )
    return out


def find_refs(text: str) -> list[re.Match[str]]:
    return list(REF_RE.finditer(text))


class LedgerError(ValueError):
    """The ledger table cannot be read (CI-IMG-009)."""


def _ref(pin: Pin) -> str:
    repo, tag, digest = pin
    return f"{repo}{':' + tag if tag else ''}@sha256:{digest}"


def _cells(line: str) -> list[str]:
    inner = line.strip().removeprefix("|").removesuffix("|")
    return [c.strip() for c in inner.split("|")]


def source_pins(root: Path) -> dict[Pin, list[str]]:
    """Map each pin found by ``iter_files()`` to the ``file:line`` places that carry it."""
    pins: dict[Pin, list[str]] = {}
    for f in iter_files(root):
        text = f.read_text(encoding="utf-8")
        for m in find_refs(text):
            pin = (m.group("repo"), m.group("tag") or "", m.group("digest"))
            line = text.count("\n", 0, m.start()) + 1
            pins.setdefault(pin, []).append(f"{f.relative_to(root).as_posix()}:{line}")
    return pins


def read_ledger(
    root: Path,
) -> tuple[list[tuple[Pin, int]], int, list[tuple[int, int]]]:
    """Return the ledger's (pin, line) rows, its header line and each "All N pins" (N, line)."""
    try:
        lines = (root / LEDGER).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise LedgerError(f"{LEDGER}: cannot read ({type(exc).__name__})") from exc
    head = next((n for n, s in enumerate(lines) if s.startswith("|")), None)
    if head is None:
        raise LedgerError(f"{LEDGER}: no table")
    cols = _cells(lines[head])
    if any(cols.count(c) != 1 for c in ("Image", "Tag", "Digest")):
        raise LedgerError(f"{LEDGER}:{head + 1}: header needs one Image, Tag, Digest")
    sep = lines[head + 1].strip() if head + 1 < len(lines) else ""
    if not SEPARATOR_RE.fullmatch(sep) or len(_cells(sep)) != len(cols):
        raise LedgerError(f"{LEDGER}:{head + 2}: no separator row matching the header")
    rows: list[tuple[Pin, int]] = []
    for n in range(head + 2, len(lines)):
        if not lines[n].startswith("|"):
            break
        cells = _cells(lines[n])
        if len(cells) != len(cols):
            raise LedgerError(
                f"{LEDGER}:{n + 1}: {len(cells)} cells, header has {len(cols)}"
            )
        row = dict(zip(cols, cells, strict=True))
        tag = f":{row['Tag']}" if row["Tag"] else ""
        m = REF_RE.fullmatch(f"{row['Image']}{tag}@{row['Digest']}")
        if m is None:
            raise LedgerError(f"{LEDGER}:{n + 1}: cannot read the image, tag or digest")
        rows.append(((m.group("repo"), m.group("tag") or "", m.group("digest")), n + 1))
    counts = [
        (int(c[1]), n + 1) for n, s in enumerate(lines) if (c := COUNT_RE.match(s))
    ]
    return rows, head + 1, counts


def check_ledger(root: Path) -> list[str]:
    """Compare ``PINS.md`` with the source pins, one row per pin (CI-IMG-007..009); offline."""
    try:
        rows, head, counts = read_ledger(root)
    except LedgerError as exc:
        return [f"CI-IMG-009 {exc}"]
    src = source_pins(root)
    unrowed = set(src) - {pin for pin, _ in rows}
    first: dict[Pin, int] = {}
    errors: list[str] = []
    for pin, n in rows:
        where = f"CI-IMG-007 {LEDGER}:{n} {_ref(pin)}"
        if pin in first:
            errors.append(f"{where}: duplicate of {LEDGER}:{first[pin]}")
            continue
        first[pin] = n
        if pin in src:
            continue
        # Pair the row with a same-image source pin that has no row: same tag first.
        near = min(
            ((p[1] != pin[1], p[2] != pin[2], p) for p in unrowed if p[0] == pin[0]),
            default=None,
        )
        if near is None:
            errors.append(f"{where}: matches no source pin")
            continue
        tag_moved, digest_moved, p = near
        unrowed.discard(p)
        kind = ("tag and digest" if digest_moved else "tag") if tag_moved else "digest"
        errors.append(f"{where}: {kind} drift; {', '.join(src[p])} pins {_ref(p)}")
    errors += [
        f"CI-IMG-007 {', '.join(src[p])} {_ref(p)}: no row in the table at {LEDGER}:{head}"
        for p in sorted(unrowed)
    ]
    if not counts:
        errors.append(f"CI-IMG-008 {LEDGER}: no 'All N pins' count line")
    elif len(counts) > 1:
        places = ", ".join(f"{LEDGER}:{n}" for _, n in counts)
        errors.append(f"CI-IMG-008 {places}: more than one 'All N pins' count line")
    elif counts[0][0] != len(rows):
        errors.append(
            f"CI-IMG-008 {LEDGER}:{counts[0][1]}: says All {counts[0][0]} pins; "
            f"the table at {LEDGER}:{head} lists {len(rows)}"
        )
    return errors


def check(root: Path, client: RegistryClient) -> list[str]:
    errors: list[str] = []
    for f in iter_files(root):
        for m in find_refs(f.read_text(encoding="utf-8")):
            where = (
                f"{f.relative_to(root).as_posix()}: {m.group('repo')}:{m.group('tag')}"
            )
            d = m.group("digest")
            if is_placeholder(d):
                errors.append(f"CI-IMG-002 {where}: placeholder digest sha256:{d}")
            elif not client.exists(m.group("repo"), f"sha256:{d}"):
                errors.append(
                    f"CI-IMG-002 {where}: digest sha256:{d} not found in registry"
                )
    return errors


def resolve(root: Path, client: RegistryClient) -> list[tuple[str, str, str, str]]:
    """Rewrite pins in place; return (file, repo:tag, old, new) for each change."""
    changes: list[tuple[str, str, str, str]] = []
    for f in iter_files(root):
        text = f.read_text(encoding="utf-8")
        new_text = text
        for m in find_refs(text):
            repo, tag = m.group("repo"), m.group("tag")
            if not tag:
                continue
            cur = m.group("digest")
            if not is_placeholder(cur) and client.exists(repo, f"sha256:{cur}"):
                continue  # already a real pin; never drift a floating tag silently
            real = client.digest(repo, tag)
            if real is None:
                changes.append(
                    (f.name, f"{repo}:{tag}", m.group("digest"), "UNPUBLISHED")
                )
                continue
            if real != f"sha256:{m.group('digest')}":
                new_text = new_text.replace(m.group(0), f"{repo}:{tag}@{real}")
                changes.append((f.name, f"{repo}:{tag}", m.group("digest"), real))
        if new_text != text:
            f.write_text(new_text, encoding="utf-8", newline="\n")
    return changes


def main(argv: list[str] | None = None, client: RegistryClient | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true")
    ap.add_argument(
        "--offline",
        action="store_true",
        help="with --check: the ledger only, no registry",
    )
    ap.add_argument("--root", type=Path, default=ROOT)
    args = ap.parse_args(argv)
    if args.offline and not args.check:
        ap.error("--offline needs --check")
    cl: RegistryClient = client or HttpRegistry()
    if args.check:
        # Ledger first: its errors print before the registry part runs (and can raise).
        errs = check_ledger(args.root)
        for e in errs:
            print(e, file=sys.stderr)
        if not args.offline:
            reg = check(args.root, cl)
            for e in reg:
                print(e, file=sys.stderr)
            errs += reg
        print("resolve_image_digests: " + ("FAIL" if errs else "OK"))
        return 1 if errs else 0
    for name, ref, old, new in resolve(args.root, cl):
        print(f"{name}: {ref} {old[:12]} -> {new}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

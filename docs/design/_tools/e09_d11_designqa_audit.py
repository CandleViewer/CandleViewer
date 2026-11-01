"""E09-D11 (#291) audit: the design QA of the built auth, session and RBAC band.

Stdlib only, offline (`python3 -I -B`). It reads the spec, the pins file and `14` from the working
tree, and every cited or lifted file AS TEXT at the merge-base with `origin/main` (`git show`):
the copy deck and the composition map of E09-D12 / E09-D07, the states matrix of E09-D02, the
focus map and script of E09-D10, the token JSON, the band's built source, the auth a11y gate's
route list and `calendar_cv.sprint_range`. It runs no repo code and drives no browser.
Default-deny: a gate that cannot read its input FAILs.

Two modes, chosen by content, never by flag. PR-1 mode: the spec is absent at the merge-base; the
diff may touch only the three own files and the accepted rows' `14` lines. Post-merge mode: the
spec ships at the merge-base; every merged table row stands unchanged, and every cite is read at
the base the merged spec recorded (`audit:sha`), not at the merge-base with the moving main.

Gates (each FAIL led by its code):

- [G01-FILLED] no `{{KIND:key}}` slot is left in the spec.
- [G02-AUDIT] every `<!-- audit:key=value -->` marker is a known key, equals the recomputed value
  and stands right after its visible value.
- [G03-CITE] every cited endpoint resolves at the base to a non-blank line, and its pin matches.
- [G04-PINS] the pins file and the spec's cited endpoints match both ways.
- [G05-VERBATIM] every quoted string in a CP row's Built cell stands whole (a full string literal or
  JSX text run) on a line the row cites.
- [G06-COPY] the CP rows list every deck key that differs on a built screen, once; the FZ rows'
  statuses equal the recomputed ones, and a matching FZ row's cites hold the deck string; a CP
  finding is a DF row or "no divergence:" with a reason.
- [G07-TOKEN] TK-1 and TK-2 cite exactly the literal hits of the scan; no reference is unresolved.
- [G08-CONTRAST] a CN pair under its bar in any theme names a DF row; a pair at the bar names none;
  every "CN-n = P-m" claim names an E09-D12 pair with the same foreground and background.
- [G09-STATES] the ST rows are the states matrix of E09-D02, once each, with a ruled status; a
  removed state cites a merged design text; a reached state cites built code or a stub-run row;
  an unreachable state names a DF row.
- [G10-MAP] the OB rows cover E09-D10's map rows once each; a fail, unreachable or not-comparable
  row names a DF row, a known row a DF or F row, an owner-run row an OR row.
- [G11-SCRIPT] the SR rows are E09-D10's script steps once each, with a ruled status.
- [G12-COMP] the CM rows are the composition map's components; each FK component is published at
  its path at the base and imported by no band file.
- [G13-FINDINGS] every DF row has a class, severity, owner, target, G-T2, Focus and Rate from the
  ruled sets, a cited sentence and, for Blocking and Major, a reason; a Blocking row is listed as
  an issue and an accepted row is Info and edits `14`.
- [G14-CLASS] every DF id named anywhere is a row of the register, and every row is named outside it.
- [G15-ROUTE] targets and routing lines name open owners only (plus the closed originating design
  tickets of the accepted rows); the IS rows are exactly the Blocking and security rows.
- [G16-T2] section 11 states the T2 rule; every T2 row names a section 3.1 key of E09-D09, a
  section 3.2 verb where the key takes one, CMP-079 and CMP-019 `lock`.
- [G17-IDS] the ids of each table family are 1..n in order.
- [G18-HYGIENE] no lane-private word, URL, local path, uuid or closing keyword in the own files.
- [G19-RULED] section R lists BQ-01..BQ-28 once each with the ruling stamp; every "RULED BQ-nn"
  names a listed BQ.
- [G20-SCOPE] the changed paths are the own files and `14` only.
- [G21-P14] `14` differs from the base by the accepted rows' lines alone, each inside its entry:
  the States and Validation lines equal E09-D12's A-2 and A-6 text in full, and each design-QA line
  names the accepted DF rows of its entry.
- [G22-FREEZE] post-merge mode: every merged table row stands unchanged.
- [G23-WALK] the owner checklist holds at most ten items.
- [G24-SECRET] no secret-shaped value (a base32 run, a six-digit code, an otpauth URI) in the
  own files.
- [G25-AXE] the AX rows are the a11y gate's screens in order; "no" exactly where not shipped.
- [G26-SECURITY] a security-bearing row (a DF row whose clause is a frozen entry, `T Sec` or the
  never-list, and every CP, FZ, ST, OB, RN or SR row that names one or differs on a frozen entry)
  carries no built-code cite and no quoted string: id, class, clause and owner only (BQ-20).

`--json` prints the numbers and findings; `--check` exits 1 on any FAIL; `--fill` writes the
computed values into the spec's slots and markers; `--self-test` applies one mutation per gate to
an in-memory copy and passes only when each adds FAILs of its gate's code and the base run is
clean; `--repin-ruled` rewrites the pins file from the spec's cites and is its only writer.

Usage: python3 -I -B docs/design/_tools/e09_d11_designqa_audit.py [--check] [--json] [--fill]
       [--self-test] [--repin-ruled]
"""

from __future__ import annotations

import argparse
import codecs
import dataclasses
import functools
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SPEC_REL = "docs/design/E09/E09-D11.md"
TOOL_REL = "docs/design/_tools/e09_d11_designqa_audit.py"
PINS_REL = "docs/design/_tools/e09_d11_ruled_pins.txt"
P14_REL = "docs/plan/14-screens-catalogue.md"
OWN = {SPEC_REL, TOOL_REL, PINS_REL}
UPSTREAM = "origin/main"
DECK_REL = "docs/design/E09/E09-D12-copy.json"
COMP_REL = "docs/design/E09/E09-D07-composition.json"
CAL_REL = "docs/plan/backlog/_tools/calendar_cv.py"
TOKENS_DIR = "packages/ui/tokens"
UI_SRC = "packages/ui/src"
FEAT = "apps/web/src/features/"
RULED_STAMP = "RULED (orchestrator, 2026-10-31, #291 ruling 6547862379)"
DQA_MARK = "- **Design QA (E09-D11):**"

DESIGN = {f"D{n:02d}": f"docs/design/E09/E09-D{n:02d}.md" for n in (2, 3, 4, 5, 6, 8, 9, 10, 12)}
CODE = {
    "LOGIN": FEAT + "auth/LoginScreen.tsx",
    "AUTHAPI": FEAT + "auth/authApi.ts",
    "CPW": FEAT + "auth/ChangePasswordScreen.tsx",
    "LOCKD": FEAT + "session/SessionLockDialog.tsx",
    "ESC": FEAT + "session/SessionLockEscapes.tsx",
    "WARN": FEAT + "session/SessionTimeoutWarning.tsx",
    "HOST": FEAT + "session/SessionLockHost.tsx",
    "CHROME": FEAT + "session/chrome.ts",
    "SESS": FEAT + "session/SessionsSection.tsx",
    "STEPUP": FEAT + "stepUp/StepUpDialog.tsx",
    "GATE": FEAT + "stepUp/StepUpChallengeGate.tsx",
    "INVITE": FEAT + "invites/InviteAcceptScreen.tsx",
    "CHECK": FEAT + "onboarding/SetupChecklistCard.tsx",
    "TREE": "apps/web/src/routes/tree.tsx",
    "FOCUS": FEAT + "app-shell/useRouteFocus.ts",
    "A11Y": "apps/web/e2e/e09-auth-a11y.spec.ts",
    "SHELL": FEAT + "app-shell/shellMode.ts",
    "RBACR": "apps/web/src/routes/rbac.ts",
}
KEYS = {**DESIGN, "S03": "docs/design/E09/E09-S03.md", **CODE}
KEY_RE = "|".join(sorted(KEYS, key=len, reverse=True)) + r"|\d\d"
MD_CITE = re.compile(
    rf"`(?P<key>{KEY_RE})`:(?P<a>\d+)(?:[–-](?P<b>\d+))?(?P<more>(?:, :\d+(?:[–-]\d+)?)*)"
)
MORE = re.compile(r":(\d+)(?:[–-](\d+))?")
SLOT = re.compile(r"\{\{([A-Z]+):([\w.-]+)\}\}")
AUDIT = re.compile(r"<!-- audit:([\w.-]+)=([^>]*?) -->")
QUOTE = re.compile(r'"([^"]*)"')

# The band's built screens and the files that render each screen's strings (§5).
SCREEN_FILES: dict[str, tuple[str, ...]] = {
    "SCR-001": ("LOGIN", "AUTHAPI"),
    "SCR-002": (),
    "SCR-003": ("INVITE",),
    "SCR-005": ("LOCKD", "ESC", "HOST", "SESSAPI"),
    "CMP-098": ("WARN", "HOST"),
    "SCR-006": ("STEPUP", "GATE"),
    "SCR-017": ("INVITE",),
    "SCR-019": ("CHECK",),
    "SCR-112": ("SESS", "SESSLIST", "TREE"),
}
EXTRA_FILES = {
    "SESSAPI": FEAT + "session/sessionApi.ts",
    "SESSLIST": FEAT + "session/sessionsApi.ts",
}
BAND_DIRS = ("auth/", "session/", "stepUp/")
BAND_SINGLES = ("invites/InviteAcceptScreen.tsx", "onboarding/SetupChecklistCard.tsx")

# The published components the band re-builds (§6.2): id, export name, path under UI_SRC.
FORKS: dict[str, tuple[str, str]] = {
    "CMP-001": ("Button", "components/Button.tsx"),
    "CMP-007": ("TextInput", "components/TextInput.tsx"),
    "CMP-043": ("Dialog", "components/Dialog.tsx"),
    "CMP-044": ("ConfirmDialog", "components/ConfirmDialog.tsx"),
    "CMP-079": ("RbacGate", "components/RbacGate.tsx"),
    "CMP-019": ("Icon", "icons/Icon.tsx"),
}

# The built colour pairs of §3.2: fg, bg, bar.
CN_PAIRS: dict[str, tuple[str, str, str]] = {
    "cn1": ("color.text.primary", "color.surface.raised", "text"),
    "cn2": ("color.text.secondary", "color.surface.raised", "text"),
    "cn3": ("color.status.warning.default", "color.surface.raised", "text"),
    "cn4": ("color.text.on-action", "color.action.primary.default", "text"),
    "cn5": ("color.text.primary", "color.action.secondary.default", "text"),
    "cn6": ("color.border.default", "color.surface.raised", "non-text"),
    "cn7": ("color.text.primary", "color.surface.sunken", "text"),
}
BAR = {"text": 4.5, "non-text": 3.0}
THEMES = {
    "dark": ("primitives", "semantic-dark"),
    "light": ("primitives", "semantic-dark", "semantic-light"),
    "hc": ("primitives", "semantic-dark", "semantic-hc"),
}

CLASSES = ("implementation defect", "accepted divergence", "specification gap")
SEVERITIES = ("Blocking", "Major", "Minor", "Info")
OPEN = ("#2711", "#2110", "#188", "#190", "#194", "#293", "#297")
CLOSED_ORIGIN = ("#132", "#189")  # the accepted rows' originating design tickets (BQ-19)
NOT_OPEN = ("#4743", "#2490")  # closed: never an open owner (the ruling's cross-list)
TARGETS = (*OPEN, "register", "issue (listed)", "`14` (this PR)")
OWNER = re.compile(r"^`E09-D\d\d · area/auth-rbac`$")
FOCUS_CELL = re.compile(r"^(?:n/a|(?:kept|moves to|restored to|returns to) · \S.*)$")
RATE_UNITS = "episode|press|failure|change|open|arrival|step"
RATE = re.compile(rf"^(?:n/a|never|once per (?:{RATE_UNITS}))$")
ST_STATUS = ("reached", "unreachable-owned", "removed-by-design", "owner-run")
OB_STATUS = (
    "pass",
    "fail",
    "known",
    "unreachable-owned",
    "not-comparable-yet",
    "owner-run",
    "out-of-band",
)
SR_STATUS = ("tree-checked", "unreachable-owned", "known-gap", "owner-run")
FZ_OTHER = ("pass", "pass (source)", "owner-run", "not-comparable-yet")
# rot13 keeps the private list out of plain text; underscores stand for spaces.
BANNED_ROT13 = (
    "yrnx rkcbfrq olcnff rkcybvg nggnpx benpyr erirny haobhaqrq sybbq fgnyy qbf nqivfbel tufn "
    "cer-nhgu ucr-jbexre znva-bepurfgengbe"
)
BANNED = [w.replace("_", " ") for w in codecs.decode(BANNED_ROT13, "rot13").split()]
URL = re.compile(r"https?://|\bwww\.", re.IGNORECASE)
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
LOCAL_PATH = re.compile("|".join("/" + w + "/" for w in ("home", "mnt", "tmp")))
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?) #\d+", re.IGNORECASE)
SECURITY_CLAUSE = re.compile(r"frozen|T Sec|never-list")
SECRET = re.compile(r"\b[A-Z2-7]{16,}\b|(?<![\w.-])\d{6}(?![\w.-])|otpauth:")


# --------------------------------------------------------------------------------------- git


def git(*args: str) -> str:
    out = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )
    return out.stdout if out.returncode == 0 else ""


@functools.cache
def merge_base() -> str:
    return git("merge-base", "HEAD", UPSTREAM).strip()


@functools.cache
def show(rev: str, rel: str) -> str | None:
    out = subprocess.run(
        ["git", "show", f"{rev}:{rel}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=60,
    )
    return out.stdout if out.returncode == 0 else None


@functools.cache
def plan_path(nn: str, rev: str) -> str | None:
    for name in git("ls-tree", "--name-only", rev, "docs/plan/").split():
        if Path(name).name.startswith(f"{nn}-") and name.endswith((".md", ".yaml")):
            return name
    return None


def key_path(key: str, rev: str) -> str | None:
    if key in KEYS:
        return KEYS[key]
    return plan_path(key, rev) if re.fullmatch(r"\d\d", key) else None


def read(rel: str) -> str:
    p = ROOT / rel
    return p.read_text(encoding="utf-8") if p.exists() else ""


@functools.cache
def engine(name: str, rel: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {name}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ----------------------------------------------------------------------------------- parsing


def heading_level(line: str) -> int:
    m = re.match(r"(#{1,6}) ", line)
    return len(m[1]) if m else 0


def section(text: str, prefix: str) -> str:
    lines = text.split("\n")
    for i, line in enumerate(lines):
        lvl = heading_level(line)
        if lvl and line[lvl + 1 :].startswith(prefix):
            out = []
            for nxt in lines[i + 1 :]:
                n = heading_level(nxt)
                if n and n <= lvl:
                    break
                out.append(nxt)
            return "\n".join(out)
    return ""


def cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def rows(block: str, family: str) -> list[list[str]]:
    pat = re.compile(rf"^\|\s*{re.escape(family)}-\d+\s*\|")
    return [cells(ln) for ln in block.split("\n") if pat.match(ln)]


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("`", "").replace("*", "")).strip()


def line_hash(s: str) -> str:
    return hashlib.sha1(norm(s).encode("utf-8")).hexdigest()[:16]


def cite_spans(text: str) -> list[tuple[str, int, int]]:
    out: list[tuple[str, int, int]] = []
    for m in MD_CITE.finditer(text):
        a = int(m["a"])
        out.append((m["key"], a, int(m["b"]) if m["b"] else a))
        for mm in MORE.finditer(m["more"] or ""):
            x = int(mm[1])
            out.append((m["key"], x, int(mm[2]) if mm[2] else x))
    return out


def endpoints(spec: str) -> set[tuple[str, int]]:
    out: set[tuple[str, int]] = set()
    for key, a, b in cite_spans(spec):
        out.add((key, a))
        out.add((key, b))
    return out


def parse_pins(pins: str) -> dict[tuple[str, int], str]:
    out: dict[tuple[str, int], str] = {}
    for ln in pins.split("\n"):
        m = re.fullmatch(rf"({KEY_RE}):(\d+) ([0-9a-f]{{16}})", ln.strip())
        if m:
            out[(m[1], int(m[2]))] = m[3]
    return out


def ids_in(text: str, fam: str) -> list[int]:
    """`DF-3`, `T-8..T-18` and `SR-4..SR-11` style mentions, ranges expanded."""
    out: list[int] = []
    for m in re.finditer(rf"\b{fam}-(\d+)(?:\.\.{fam}-(\d+))?\b", text):
        a = int(m[1])
        out.extend(range(a, int(m[2]) + 1) if m[2] else [a])
    return out


def strip_code(text: str) -> str:
    """Comments out, JSX text runs joined: what a screen can render, as one line."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"(?m)(?<![:\"'])//.*$", "", text)
    text = re.sub(r"\{\s*\" \"\s*\}", " ", text)
    return re.sub(r"\s+", " ", text)


def deck_pattern(s: str) -> re.Pattern[str]:
    parts = re.split(r"\{[^}]*\}|\bN\b|\bM\b|\bm{1,2}:ss\b", s)
    return re.compile(r".{1,60}?".join(re.escape(p) for p in parts), re.DOTALL)


def key_glob(pattern: str, keys: list[str]) -> list[str]:
    rx = re.compile("^" + re.escape(pattern).replace(r"\*", "[^.]+") + "$")
    return [k for k in keys if rx.match(k)]


# ------------------------------------------------------------------------------------ context


@dataclasses.dataclass
class Ctx:
    spec: str
    pins: str
    tool: str
    p14: str
    p14_base: str
    changed: list[str]
    merged_spec: str | None
    base: str
    sources: dict[str, str]  # band file path -> text at the base
    deck: dict[str, Any]
    comp: list[dict[str, Any]]
    tokens: dict[str, dict[str, Any]]  # theme -> flat token map
    a11y: str

    def base_text(self, key: str) -> str | None:
        rel = key_path(key, self.base)
        if rel is None:
            return None
        if rel in self.sources:
            return self.sources[rel]
        return show(self.base, rel)

    def base_line(self, key: str, n: int) -> str | None:
        text = self.base_text(key)
        if text is None:
            return None
        lines = text.split("\n")
        return lines[n - 1] if 0 < n <= len(lines) else None


def flat_tokens(d: Any, path: tuple[str, ...] = ()) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(d, dict):
        if "$value" in d:
            out[".".join(path)] = d["$value"]
        else:
            for k, v in d.items():
                if not k.startswith("$"):
                    out.update(flat_tokens(v, (*path, k)))
    return out


def band_files(base: str) -> list[str]:
    names = git("ls-tree", "-r", "--name-only", base, FEAT).split()
    keep = [
        n
        for n in names
        if n.endswith((".ts", ".tsx"))
        and (
            any(n.startswith(FEAT + d) for d in BAND_DIRS)
            or any(n == FEAT + s for s in BAND_SINGLES)
        )
    ]
    return sorted(keep)


def frozen_base(merged_spec: str | None, mb: str) -> str:
    """PR-1: the merge-base. Post-merge: the base the merged spec recorded in its own
    `audit:sha` marker (the base its pins were read at), never the merge commit or moving main.
    Falls back to the merge-base when the marker is missing or does not resolve (G02 then FAILs).
    """
    if merged_spec is None:
        return mb
    for m in AUDIT.finditer(merged_spec):
        if m[1] == "sha" and re.fullmatch(r"[0-9a-f]{40}", m[2]):
            probe = subprocess.run(
                ["git", "cat-file", "-e", m[2] + "^{commit}"],
                cwd=ROOT,
                check=False,
                stderr=subprocess.DEVNULL,
                timeout=60,
            )
            if probe.returncode == 0:
                return m[2]
    return mb


def build_ctx() -> Ctx:
    mb = merge_base()
    merged_spec = show(mb, SPEC_REL)
    base = frozen_base(merged_spec, mb)
    changed = sorted(
        {
            *git("diff", "--name-only", mb).split(),
            *git("ls-files", "-o", "--exclude-standard").split(),
        }
    )
    rels = {*band_files(base), *CODE.values(), *EXTRA_FILES.values()}
    sources = {r: t for r in sorted(rels) if (t := show(base, r)) is not None}
    tokens: dict[str, dict[str, Any]] = {}
    for theme, sets in THEMES.items():
        flat: dict[str, Any] = {}
        for s in sets:
            flat.update(
                flat_tokens(json.loads(show(base, f"{TOKENS_DIR}/{s}.tokens.json") or "{}"))
            )
        tokens[theme] = flat
    return Ctx(
        spec=read(SPEC_REL),
        pins=read(PINS_REL),
        tool=read(TOOL_REL),
        p14=read(P14_REL),
        p14_base=show(mb, P14_REL) or "",  # this branch's own `14` edits, in both modes
        changed=changed,
        merged_spec=merged_spec,
        base=base,
        sources=sources,
        deck=json.loads(show(base, DECK_REL) or "{}").get("strings", {}),
        comp=json.loads(show(base, COMP_REL) or "{}").get("records", []),
        tokens=tokens,
        a11y=show(base, CODE["A11Y"]) or "",
    )


# ------------------------------------------------------------------------------- the numbers


def screen_text(ctx: Ctx, screen: str) -> str:
    parts = []
    for k in SCREEN_FILES.get(screen, ()):
        rel = CODE.get(k) or EXTRA_FILES[k]
        parts.append(strip_code(ctx.sources.get(rel, "")))
    return " ".join(parts)


def copy_status(ctx: Ctx) -> dict[str, str]:
    out: dict[str, str] = {}
    texts = {s: screen_text(ctx, s) for s in SCREEN_FILES}
    for key, entry in ctx.deck.items():
        screen = str(entry.get("screen", ""))
        if not SCREEN_FILES.get(screen):
            out[key] = "not-built"
            continue
        hit = deck_pattern(str(entry.get("string", ""))).search(texts[screen])
        out[key] = "match" if hit else "differs"
    return out


VAR = re.compile(r"var\(--([a-z0-9-]+)\)")
LITERAL = re.compile(r"(?<![\w-])(\d+(?:\.\d+)?px|#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(|transparent)")
MOTION = re.compile(
    r"(?<![.\w])(?:transition|animation|@keyframes|backdropFilter|backdrop-filter)\b"
    r"|(?<![.\w])filter\s*:"
)
CONSOLE = re.compile(r"\bconsole\.(?:log|info|warn|error|debug|trace)\(")
EMIT = re.compile(r"\b(?:track|trackEvent|logEvent|emitAudit|sendBeacon)\(")
UI_IMPORT = re.compile(r'import\s*(?:type\s*)?\{([^}]*)\}\s*from\s*"@candleviewer/ui"')


def band_scan(ctx: Ctx) -> dict[str, Any]:
    names = {k.replace(".", "-") for k in ctx.tokens["dark"]} | {
        k.replace(".", "-") for t in ctx.tokens.values() for k in t
    }
    refs = 0
    unresolved: list[str] = []
    literals: list[tuple[str, int, str]] = []
    motion = console = emit = 0
    imports: set[str] = set()
    rev = {v: k for k, v in CODE.items()}
    for rel in band_files(ctx.base):
        text = ctx.sources.get(rel, "")
        code = strip_code(text)
        motion += len(MOTION.findall(code))
        console += len(CONSOLE.findall(code))
        emit += len(EMIT.findall(code))
        for m in UI_IMPORT.finditer(text):
            imports |= {x.strip() for x in m[1].split(",") if x.strip()}
        for i, ln in enumerate(text.split("\n"), 1):
            if ln.strip().startswith(("//", "*", "/*")):
                continue
            for m in VAR.finditer(ln):
                refs += 1
                if m[1] not in names:
                    unresolved.append(f"{rel}:{i}")
            for m in LITERAL.finditer(ln):
                literals.append((rev.get(rel, rel), i, m[1]))
    return {
        "files": len(band_files(ctx.base)),
        "refs": refs,
        "unresolved": unresolved,
        "literals": literals,
        "motion": motion,
        "console": console,
        "emit": emit,
        "imports": sorted(imports),
    }


def hex_of(ctx: Ctx, theme: str, token: str) -> str:
    flat = ctx.tokens[theme]
    v: Any = flat[token]
    for _ in range(12):
        if isinstance(v, str) and v.startswith("{") and v.endswith("}"):
            v = flat[v[1:-1]]
        else:
            break
    return str(v)


def luminance(hex6: str) -> float:
    h = hex6.lstrip("#")[:6]
    chans = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in chans]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def ratio(a: str, b: str) -> float:
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def contrast(ctx: Ctx) -> dict[str, tuple[float, str]]:
    out: dict[str, tuple[float, str]] = {}
    for key, (fg, bg, bar) in CN_PAIRS.items():
        for theme in THEMES:
            r = ratio(hex_of(ctx, theme, fg), hex_of(ctx, theme, bg))
            out[f"{key}.{theme}"] = (r, bar)
    return out


def d02_states(ctx: Ctx) -> list[tuple[str, str]]:
    text = ctx.base_text("D02") or ""
    out: list[tuple[str, str]] = []
    for ln in section(text, "3. States matrix").split("\n"):
        m = re.match(r"^\|\s*(SCR-\d{3})\b[^|]*\|([^|]*)\|", ln)
        if not m:
            continue
        states = re.sub(r"\([^)]*\)", "", m[2])
        out += [(m[1], s.strip()) for s in states.split("·") if s.strip()]
    return out


def d10_ids(ctx: Ctx, fam: str, sec: str) -> list[int]:
    text = section(ctx.base_text("D10") or "", sec)
    return [int(m[1]) for m in re.finditer(rf"^\| {fam}-(\d+)\s*\|", text, re.MULTILINE)]


def comp_counts(ctx: Ctx) -> dict[str, dict[str, int]]:
    short = {"local with a dated plan": "local", "published at PR 3": "pr3", "held": "held"}
    out: dict[str, dict[str, int]] = {}
    for r in ctx.comp:
        tally = out.setdefault(str(r.get("component", "")), {"local": 0, "pr3": 0, "held": 0})
        kind = short.get(str(r.get("status")), "other")
        tally[kind] = tally.get(kind, 0) + 1
    return out


def a11y_screens(ctx: Ctx) -> list[tuple[str, bool]]:
    body = ctx.a11y.split("E09_SCREENS", 1)[-1].split("];", 1)[0]
    out: list[tuple[str, bool]] = []
    for m in re.finditer(r"\{\s*scr:\s*\"(SCR-\d+)\"(.*?)\}", body, re.DOTALL):
        out.append((m[1], "shipped: false" not in m[2]))
    return out


def d09_keys(ctx: Ctx) -> set[str]:
    text = section(ctx.base_text("D09") or "", "3.1 ")
    return set(re.findall(r"^\| `(rbac\.[a-z_]+)`", text, re.MULTILINE))


def d09_verbs(ctx: Ctx) -> str:
    return norm(section(ctx.base_text("D09") or "", "3.2 "))


def ob_rows(spec: str) -> list[list[str]]:
    return rows(section(spec, "7.1 "), "OB")


def df_rows(spec: str) -> list[list[str]]:
    return rows(section(spec, "12. "), "DF")


def fz_status(ctx: Ctx, status: dict[str, str], row: list[str]) -> str | None:
    keys = [k for k in re.findall(r"`([a-z_]+(?:\.[a-z_]+)+)`", row[2]) if k in ctx.deck]
    if not keys:
        return None
    return "differs" if any(status.get(k) != "match" for k in keys) else "match"


def compute(ctx: Ctx) -> dict[str, str]:
    spec = ctx.spec
    v: dict[str, str] = {"sha": ctx.base}
    scan = band_scan(ctx)
    v["tk.files"] = str(scan["files"])
    v["tk.refs"] = str(scan["refs"])
    v["tk.unresolved"] = str(len(scan["unresolved"]))
    v["tk.literals"] = str(len(scan["literals"]))
    v["mo.hits"] = str(scan["motion"])
    v["console"] = str(scan["console"])
    v["emit"] = str(scan["emit"])
    v["ui.imports"] = ", ".join(scan["imports"]) or "none"
    below: dict[str, list[str]] = {}
    for key, (rr, bar) in contrast(ctx).items():
        v[key] = f"{rr:.2f}:1"
        if rr < BAR[bar]:
            pair, theme = key.split(".")
            below.setdefault(f"CN-{pair[2:]}", []).append(theme)
    v["cn.below"] = "; ".join(f"{k} ({', '.join(t)})" for k, t in sorted(below.items())) or "none"
    st = rows(section(spec, "4. "), "ST")
    v["st"] = str(len(d02_states(ctx)))
    for s, k in (
        ("reached", "reached"),
        ("unreachable-owned", "unreachable"),
        ("removed-by-design", "removed"),
        ("owner-run", "ownerrun"),
    ):
        v[f"st.{k}"] = str(sum(1 for r in st if len(r) > 3 and r[3] == s))
    status = copy_status(ctx)
    v["deck"] = str(len(ctx.deck))
    v["deck.match"] = str(sum(1 for s in status.values() if s == "match"))
    v["deck.differs"] = str(sum(1 for s in status.values() if s == "differs"))
    v["deck.notbuilt"] = str(sum(1 for s in status.values() if s == "not-built"))
    fz = rows(section(spec, "5.1 "), "FZ")
    v["fz.differs"] = str(
        sum(1 for r in fz if len(r) > 2 and fz_status(ctx, status, r) == "differs")
    )
    counts = comp_counts(ctx)
    v["comp.records"] = str(len(ctx.comp))
    for kind in ("local", "pr3", "held"):
        v[f"comp.{kind}"] = str(sum(c.get(kind, 0) for c in counts.values()))
    for cid, c in counts.items():
        tag = cid.replace("CMP-", "cmp")
        for kind in ("local", "pr3", "held"):
            v[f"{tag}.{kind}"] = str(c.get(kind, 0))
    v["cm"] = str(len(rows(section(spec, "6.1 "), "CM")))
    v["fk"] = str(len(rows(section(spec, "6.2 "), "FK")))
    t_ids = d10_ids(ctx, "T", "6.2 ")
    v["map.rows"] = str(len(t_ids))
    tally = {s: 0 for s in OB_STATUS}
    for r in ob_rows(spec):
        if len(r) > 3 and r[3] in tally:
            tally[r[3]] += len(ids_in(r[1], "T"))
    short = {
        "pass": "pass",
        "fail": "fail",
        "known": "known",
        "unreachable-owned": "unreachable",
        "not-comparable-yet": "ncy",
        "owner-run": "ownerrun",
        "out-of-band": "oob",
    }
    for s, n in tally.items():
        v[f"ob.{short[s]}"] = str(n)
    sr = rows(section(spec, "7.3 "), "SR")
    v["sr"] = str(len(d10_ids(ctx, "SR", "13.3 ")))
    for s, k in (
        ("tree-checked", "tree"),
        ("unreachable-owned", "unreachable"),
        ("known-gap", "known"),
        ("owner-run", "ownerrun"),
    ):
        v[f"sr.{k}"] = str(sum(1 for r in sr if len(r) > 1 and r[1] == s))
    ax = a11y_screens(ctx)
    v["ax"] = str(len(ax))
    v["ax.covered"] = str(sum(1 for _, shipped in ax if shipped))
    v["ax.waived"] = str(sum(1 for _, shipped in ax if not shipped))
    df = df_rows(spec)
    v["df"] = str(len(df))
    for sev in SEVERITIES:
        v[f"df.{sev.lower()}"] = str(sum(1 for r in df if len(r) > 2 and r[2] == sev))
    for cls, k in zip(CLASSES, ("defect", "accepted", "gap"), strict=True):
        v[f"df.{k}"] = str(sum(1 for r in df if len(r) > 1 and r[1] == cls))
    cal = engine("calendar_cv", CAL_REL)
    for n in (4, 6):
        s, e = cal.sprint_range(n)
        v[f"s0{n}.start"], v[f"s0{n}.end"] = s.isoformat(), e.isoformat()
    return v


# ------------------------------------------------------------------------------------- gates


Findings = list[tuple[str, str]]
RUN_ERRORS = (
    OSError,
    ValueError,
    KeyError,
    IndexError,
    TypeError,
    AttributeError,
    RuntimeError,
    json.JSONDecodeError,
    subprocess.SubprocessError,
)


def g_filled(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for m in SLOT.finditer(ctx.spec):
        f.append(("G01-FILLED", f"slot {m[0]} is not filled"))


def g_audit(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for m in AUDIT.finditer(ctx.spec):
        key, val = m[1], m[2]
        if key not in vals:
            f.append(("G02-AUDIT", f"marker {key!r} is not a key the tool computes"))
            continue
        if vals[key] != val:
            f.append(("G02-AUDIT", f"{key}: the marker says {val!r}, the tool {vals[key]!r}"))
        if not ctx.spec[: m.start()].rstrip().rstrip("`").endswith(val):
            f.append(("G02-AUDIT", f"{key}: the visible value before the marker is not {val!r}"))


def g_cite(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    pins = parse_pins(ctx.pins)
    for key, n in sorted(endpoints(ctx.spec)):
        line = ctx.base_line(key, n)
        if line is None or not line.strip():
            f.append(("G03-CITE", f"{key}:{n} does not resolve to a non-blank line at the base"))
            continue
        if (key, n) in pins and pins[(key, n)] != line_hash(line):
            f.append(("G03-CITE", f"{key}:{n} moved: its pin no longer matches the base line"))


def g_pins(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    pins = set(parse_pins(ctx.pins))
    ends = endpoints(ctx.spec)
    for k, n in sorted(ends - pins):
        f.append(("G04-PINS", f"{k}:{n} is cited but not pinned"))
    for k, n in sorted(pins - ends):
        f.append(("G04-PINS", f"{k}:{n} is pinned but no longer cited"))


def g_verbatim(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for r in rows(section(ctx.spec, "5.2 "), "CP"):
        if len(r) < 5:
            f.append(("G05-VERBATIM", f"{r[0]}: {len(r)} cells"))
            continue
        hay = [
            " ".join(ctx.base_line(k, n) or "" for n in range(a, b + 1))
            for k, a, b in cite_spans(r[3])
        ]
        for q in QUOTE.findall(r[3]):
            if not any(f'"{q}"' in h or f">{q}<" in h for h in hay):
                f.append(("G05-VERBATIM", f"{r[0]}: {q[:40]!r} stands on no line the row cites"))


def g_copy(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    status = copy_status(ctx)
    differs = {k for k, s in status.items() if s == "differs"}
    keys = sorted(ctx.deck)
    listed: list[str] = []
    for r in rows(section(ctx.spec, "5.2 "), "CP"):
        if len(r) < 5:
            f.append(("G06-COPY", f"{r[0]}: {len(r)} cells"))
            continue
        for tok in re.findall(r"`([a-z0-9_*]+(?:\.[a-z0-9_*]+)+)`", r[1]):
            hit = key_glob(tok, keys) if "*" in tok else ([tok] if tok in ctx.deck else [])
            if not hit:
                f.append(("G06-COPY", f"{r[0]}: {tok} names no deck key"))
            listed += hit
        if not (re.fullmatch(r"DF-\d+", r[4]) or re.match(r"no divergence: \S", r[4])):
            f.append(("G06-COPY", f"{r[0]}: the finding is neither a DF row nor a reasoned no"))
    for k in sorted(differs - set(listed)):
        f.append(("G06-COPY", f"{k} differs on a built screen and no CP row lists it"))
    for k in sorted(set(listed) - differs):
        f.append(("G06-COPY", f"{k} is listed in a CP row but {status.get(k)!r}"))
    if len(listed) != len(set(listed)):
        f.append(("G06-COPY", "a deck key is listed twice"))
    frozen = section(ctx.base_text("D12") or "", "8.2 ")
    n_frozen = len(re.findall(r"^\| \(\d+\)", frozen, re.MULTILINE))
    fz = rows(section(ctx.spec, "5.1 "), "FZ")
    if len(fz) != n_frozen or n_frozen == 0:
        f.append(("G06-COPY", f"{len(fz)} FZ rows for {n_frozen} frozen entries"))
    for r in fz:
        want = fz_status(ctx, status, r) if len(r) > 3 else None
        if want is not None and r[3] != want:
            f.append(("G06-COPY", f"{r[0]}: status {r[3]!r}, the deck diff says {want!r}"))
        if want is None and len(r) > 3 and r[3] not in FZ_OTHER:
            f.append(("G06-COPY", f"{r[0]}: status {r[3]!r} is not from the set"))
        if want == "differs" and not (len(r) > 5 and re.fullmatch(r"DF-\d+", r[5])):
            f.append(("G06-COPY", f"{r[0]}: a frozen difference names no DF row"))
        if want == "match":
            text = strip_code(
                " ".join(
                    "\n".join(ctx.base_line(k, n) or "" for n in range(a, b + 1))
                    for k, a, b in cite_spans(r[4])
                )
            )
            for key in re.findall(r"`([a-z_]+(?:\.[a-z_]+)+)`", r[2]):
                if key in ctx.deck and not deck_pattern(str(ctx.deck[key]["string"])).search(text):
                    f.append(("G06-COPY", f"{r[0]}: {key} does not stand on the lines cited"))


def cited_lines(text: str) -> set[tuple[str, int]]:
    out: set[tuple[str, int]] = set()
    for k, a, b in cite_spans(text):
        out |= {(k, n) for n in range(a, b + 1)}
    return out


def g_token(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    scan = band_scan(ctx)
    hits = {(k, n) for k, n, _ in scan["literals"]}
    tk = {r[0]: r for r in rows(section(ctx.spec, "3.1 "), "TK")}
    listed: set[tuple[str, int]] = set()
    for rid in ("TK-1", "TK-2"):
        if rid not in tk:
            f.append(("G07-TOKEN", f"{rid} is missing"))
            continue
        listed |= cited_lines(tk[rid][2])
    for k, n in sorted(hits - listed):
        f.append(("G07-TOKEN", f"a literal at {k}:{n} is in no TK row"))
    for k, n in sorted(listed - hits):
        f.append(("G07-TOKEN", f"{k}:{n} is listed but holds no literal"))
    for u in scan["unresolved"]:
        f.append(("G07-TOKEN", f"an unresolved token reference at {u}"))


def g_contrast(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    measured = contrast(ctx)
    cn = rows(section(ctx.spec, "3.2 "), "CN")
    if len(cn) != len(CN_PAIRS):
        f.append(("G08-CONTRAST", f"{len(cn)} CN rows for {len(CN_PAIRS)} built pairs"))
    for r in cn:
        key = "cn" + r[0].split("-")[1]
        if key not in CN_PAIRS or len(r) < 9:
            f.append(("G08-CONTRAST", f"{r[0]}: not a built pair of the tool"))
            continue
        fg, bg, bar = CN_PAIRS[key]
        if r[1] != f"`{fg}`" or r[2] != f"`{bg}`" or r[6] != bar:
            f.append(("G08-CONTRAST", f"{r[0]}: the pair or its bar is not the tool's"))
        low = any(measured[f"{key}.{t}"][0] < BAR[bar] for t in THEMES)
        if low and not re.fullmatch(r"DF-\d+", r[8]):
            f.append(("G08-CONTRAST", f"{r[0]}: under the bar and no DF row named"))
        if not low and r[8] != "—":
            f.append(("G08-CONTRAST", f"{r[0]}: at the bar but a finding is named"))
    d12 = {
        m[1]: (m[2], m[3])
        for m in re.finditer(
            r"^\| (P-\d+) [^|]*\| `([\w.-]+)`\s*\| `([\w.-]+)`",
            section(ctx.base_text("D12") or "", "7.2 "),
            re.MULTILINE,
        )
    }
    claims = re.findall(r"\bCN-(\d+) = (P-\d+)\b", section(ctx.spec, "3.2 "))
    if not claims:
        f.append(("G08-CONTRAST", "no CN pair is mapped to an E09-D12 pair"))
    for n, pid in claims:
        fg, bg, _ = CN_PAIRS.get(f"cn{n}", ("", "", ""))
        if d12.get(pid) != (fg, bg):
            f.append(("G08-CONTRAST", f"CN-{n} is not E09-D12's {pid}"))


def g_states(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    want = d02_states(ctx)
    st = rows(section(ctx.spec, "4. "), "ST")
    got = [(r[1], r[2]) for r in st if len(r) > 2]
    if not want:
        f.append(("G09-STATES", "the states matrix could not be read at the base"))
    for p in sorted(set(want) - set(got)):
        f.append(("G09-STATES", f"{p[0]} {p[1]} has no ST row"))
    for p in sorted(set(got) - set(want)):
        f.append(("G09-STATES", f"{p[0]} {p[1]} is not a state of the matrix"))
    if len(got) != len(set(got)):
        f.append(("G09-STATES", "a state is listed twice"))
    for r in st:
        if len(r) < 6 or r[3] not in ST_STATUS:
            f.append(("G09-STATES", f"{r[0]}: status {r[3] if len(r) > 3 else ''!r}"))
            continue
        keys = {k for k, _, _ in cite_spans(r[4])}
        if r[3] == "removed-by-design" and not keys & set(DESIGN):
            f.append(("G09-STATES", f"{r[0]}: removed with no merged design cite"))
        if r[3] == "reached" and not (keys & set(CODE) or re.search(r"\bRN-\d+\b", r[4])):
            f.append(("G09-STATES", f"{r[0]}: reached with no built-code cite"))
        if r[3] == "unreachable-owned" and not re.search(r"\bDF-\d+\b", r[5]):
            f.append(("G09-STATES", f"{r[0]}: unreachable and no DF row named"))


def g_map(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    want = d10_ids(ctx, "T", "6.2 ")
    seen: list[int] = []
    for r in ob_rows(ctx.spec):
        if len(r) < 6 or r[3] not in OB_STATUS:
            f.append(("G10-MAP", f"{r[0]}: the row or its status is not from the set"))
            continue
        seen += ids_in(r[1], "T")
        fin = r[5]
        need = {
            "fail": r"\bDF-\d+\b",
            "unreachable-owned": r"\bDF-\d+\b",
            "not-comparable-yet": r"\bDF-\d+\b",
            "known": r"\b(?:DF|F)-\d+\b",
            "owner-run": r"\bOR-\d+\b",
        }.get(r[3])
        if need and not re.search(need, fin):
            f.append(("G10-MAP", f"{r[0]}: a {r[3]} row names no row it needs"))
        if r[3] == "out-of-band" and not cite_spans(r[4]):
            f.append(("G10-MAP", f"{r[0]}: out of band with no cite"))
    if not want:
        f.append(("G10-MAP", "the focus map could not be read at the base"))
    for t in sorted(set(want) - set(seen)):
        f.append(("G10-MAP", f"T-{t} is walked by no OB row"))
    for t in sorted(set(seen) - set(want)):
        f.append(("G10-MAP", f"T-{t} is not a row of the map"))
    if len(seen) != len(set(seen)):
        f.append(("G10-MAP", "a map row is walked twice"))


def g_script(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    want = d10_ids(ctx, "SR", "13.3 ")
    sr = rows(section(ctx.spec, "7.3 "), "SR")
    got = [int(r[0].split("-")[1]) for r in sr]
    if not want or got != want:
        f.append(("G11-SCRIPT", f"the SR rows are not the script's {len(want)} steps in order"))
    for r in sr:
        if len(r) < 3 or r[1] not in SR_STATUS:
            f.append(("G11-SCRIPT", f"{r[0]}: status {r[1] if len(r) > 1 else ''!r}"))


def g_comp(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    want = set(comp_counts(ctx))
    cm = rows(section(ctx.spec, "6.1 "), "CM")
    got = {m[0] for r in cm if len(r) > 1 and (m := re.match(r"CMP-\d{3}", r[1]))}
    if not want or got != want:
        f.append(("G12-COMP", f"the CM rows {sorted(got)} are not COMP's components"))
    for r in cm:
        if len(r) < 5 or not re.fullmatch(r"DF-\d+", r[4]):
            f.append(("G12-COMP", f"{r[0]}: a local component names no DF row"))
    imports = set(band_scan(ctx)["imports"])
    for r in rows(section(ctx.spec, "6.2 "), "FK"):
        m = re.match(r"CMP-\d{3}", r[1] if len(r) > 1 else "")
        if not m or m[0] not in FORKS:
            f.append(("G12-COMP", f"{r[0]}: not a published component of the tool"))
            continue
        name, rel = FORKS[m[0]]
        text = show(ctx.base, f"{UI_SRC}/{rel}") or ""
        if m[0] not in text or f"`{UI_SRC}/{rel}`" != r[2]:
            f.append(("G12-COMP", f"{r[0]}: {m[0]} is not published at the cited path"))
        if name in imports:
            f.append(("G12-COMP", f"{r[0]}: the band imports {name}: not a fork"))


def g_findings(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    keys = d09_keys(ctx)
    df = df_rows(ctx.spec)
    if not df:
        f.append(("G13-FINDINGS", "no DF row found"))
    for r in df:
        if len(r) < 11:
            f.append(("G13-FINDINGS", f"{r[0]}: {len(r)} cells, not 11"))
            continue
        if r[1] not in CLASSES:
            f.append(("G13-FINDINGS", f"{r[0]}: class {r[1]!r}"))
        if r[2] not in SEVERITIES:
            f.append(("G13-FINDINGS", f"{r[0]}: severity {r[2]!r}"))
        if not OWNER.match(r[4]):
            f.append(("G13-FINDINGS", f"{r[0]}: the owner is not one spec and its area"))
        if r[5] not in TARGETS:
            f.append(("G13-FINDINGS", f"{r[0]}: target {r[5]!r} is not from the set"))
        t2 = re.fullmatch(r"T2 · (rbac\.[a-z_]+)", r[6])
        if r[6] != "n/a" and not (t2 and t2[1] in keys):
            f.append(("G13-FINDINGS", f"{r[0]}: G-T2 {r[6]!r} is not from the set"))
        if not FOCUS_CELL.match(r[7]):
            f.append(("G13-FINDINGS", f"{r[0]}: Focus {r[7]!r} is not from the set"))
        if not RATE.match(r[8]):
            f.append(("G13-FINDINGS", f"{r[0]}: Rate {r[8]!r} is not from the set"))
        if not cite_spans(r[9]):
            f.append(("G13-FINDINGS", f"{r[0]}: the sentence cites no source line"))
        if r[2] in ("Blocking", "Major") and r[10] in ("", "—"):
            f.append(("G13-FINDINGS", f"{r[0]}: a {r[2]} row has no reason"))
        if r[2] == "Blocking" and r[5] != "issue (listed)":
            f.append(("G13-FINDINGS", f"{r[0]}: a Blocking row is not listed as an issue"))
        accepted = r[1] == "accepted divergence"
        if accepted != (r[2] == "Info" and r[5] == "`14` (this PR)"):
            f.append(("G13-FINDINGS", f"{r[0]}: an accepted row is Info and edits `14`, only it"))


def g_class(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    reg = section(ctx.spec, "12. ")
    have = {int(r[0].split("-")[1]) for r in df_rows(ctx.spec)}
    outside = ctx.spec.replace(reg, "")
    named = set(ids_in(outside, "DF"))
    for n in sorted(named - have):
        f.append(("G14-CLASS", f"DF-{n} is named but is no row of the register"))
    for n in sorted(have - named):
        f.append(("G14-CLASS", f"DF-{n} is a row no observation names"))


def security(r: list[str]) -> bool:
    return bool(SECURITY_CLAUSE.search(r[3]))


def g_route(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    df = {r[0]: r for r in df_rows(ctx.spec) if len(r) >= 11}
    for r in df.values():
        if r[5].startswith("#") and r[5] not in OPEN:
            f.append(("G15-ROUTE", f"{r[0]}: target {r[5]} is not an open owner"))
    sec = section(ctx.spec, "14. ")
    for r in rows(section(ctx.spec, "14.1 "), "RT"):
        if len(r) < 4 or r[1] not in (*OPEN, *CLOSED_ORIGIN):
            f.append(("G15-ROUTE", f"{r[0]}: {r[1] if len(r) > 1 else ''} is no open owner"))
    m = re.search(r"The open owners are ([^.]*)\.", sec)
    named = re.findall(r"#\d+", m[1]) if m else []
    if sorted(named) != sorted(OPEN):
        f.append(("G15-ROUTE", f"the open-owner list {named} is not the ruled set"))
    for bad in NOT_OPEN:
        if re.search(rf"{bad}\b", sec) or any(r[5] == bad for r in df.values()):
            f.append(("G15-ROUTE", f"{bad} is closed and is named as an owner"))
    want = {k for k, r in df.items() if r[2] == "Blocking" or security(r)}
    listed = rows(section(ctx.spec, "14.2 "), "IS")
    got = {r[1] for r in listed if len(r) > 1}
    if got != want:
        f.append(("G15-ROUTE", f"the IS rows {sorted(got)} are not the Blocking and security rows"))
    for r in listed:
        d = df.get(r[1] if len(r) > 1 else "")
        if d and (len(r) < 5 or (r[2], r[3], r[4]) != (d[1], d[3], d[4])):
            f.append(("G15-ROUTE", f"{r[0]}: its class, clause or owner is not {r[1]}'s"))


T2_RULE = (
    'aria-disabled="true"',
    "never `disabled`",
    "`aria-describedby` reason node in the DOM at mount",
    "CMP-079 RbacGate wrapping",
    "CMP-019 `lock` (`decorative={false}`",
    'name "Not available", leading the full label',
)


def g_t2(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    sec = section(ctx.spec, "11. ")
    for phrase in T2_RULE:
        if phrase not in sec:
            f.append(("G16-T2", f"section 11 does not state {phrase!r}"))
    keys = d09_keys(ctx)
    verbs = d09_verbs(ctx)
    t2 = rows(sec, "T2")
    if not t2:
        f.append(("G16-T2", "no T2 row found"))
    for r in t2:
        cell = r[4] if len(r) > 4 else ""
        m = re.match(r"^`(rbac\.[a-z_]+)`", cell)
        if not m or m[1] not in keys:
            f.append(("G16-T2", f"{r[0]}: no E09-D09 section 3.1 key"))
            continue
        if m[1] in ("rbac.permission", "rbac.owner_only"):
            verb = re.search(r'→ "([^"]+)"', cell)
            if not verb or f'"{verb[1]}"' not in verbs:
                f.append(("G16-T2", f"{r[0]}: no section 3.2 verb"))
        if "CMP-079" not in cell or "CMP-019 `lock`" not in cell:
            f.append(("G16-T2", f"{r[0]}: CMP-079 or CMP-019 `lock` is not named"))


ID_FAMILIES = {
    "TK": "3.1 ",
    "CN": "3.2 ",
    "ST": "4. ",
    "FZ": "5.1 ",
    "CP": "5.2 ",
    "CM": "6.1 ",
    "FK": "6.2 ",
    "OB": "7.1 ",
    "SR": "7.3 ",
    "MO": "8. ",
    "AX": "9. ",
    "PF": "10.2 ",
    "SC": "10.3 ",
    "T2": "11. ",
    "DF": "12. ",
    "DR": "13. ",
    "RT": "14.1 ",
    "IS": "14.2 ",
    "CO": "17. ",
    "OR": "18. ",
    "RN": "1.1 ",
}


def g_ids(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for fam, sec in ID_FAMILIES.items():
        ids = [r[0] for r in rows(section(ctx.spec, sec), fam)]
        nums = [int(i.rsplit("-", 1)[1]) for i in ids]
        if not ids or nums != list(range(1, len(ids) + 1)):
            f.append(("G17-IDS", f"{fam}: the ids are not 1..n in order ({ids[:3]}…)"))
    ps = re.findall(r"^- \*\*PS-(\d+) ", section(ctx.spec, "16. "), re.MULTILINE)
    if [int(n) for n in ps] != list(range(1, len(ps) + 1)) or not ps:
        f.append(("G17-IDS", "PS: the procedure steps are not 1..n in order"))


def added_p14(ctx: Ctx) -> list[str]:
    base = set(ctx.p14_base.split("\n"))
    return [ln for ln in ctx.p14.split("\n") if ln not in base]


def g_hygiene(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    texts = (
        ("the spec", ctx.spec),
        ("the tool", ctx.tool),
        ("the pins", ctx.pins),
        ("the `14` lines", "\n".join(added_p14(ctx))),
    )
    for name, text in texts:
        low = text.lower()
        for word in BANNED:
            if word in low:
                f.append(("G18-HYGIENE", f"{name}: a word from the private list"))
        for pat, what in ((URL, "a URL"), (UUID, "a uuid"), (LOCAL_PATH, "a local path")):
            m = pat.search(text)
            if m:
                f.append(("G18-HYGIENE", f"{name}: {what} {m[0][:24]!r}"))
    if CLOSING.search(ctx.spec):
        f.append(("G18-HYGIENE", "the spec carries a closing keyword before an issue number"))


def g_ruled(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    sec = section(ctx.spec, "R. ")
    listed = [r[0] for r in rows(sec, "BQ")]
    if listed != [f"BQ-{n:02d}" for n in range(1, 29)]:
        f.append(("G19-RULED", f"section R lists {len(listed)} BQ rows, not BQ-01..BQ-28"))
    for r in rows(sec, "BQ"):
        if r[-1] != RULED_STAMP:
            f.append(("G19-RULED", f"{r[0]}: the status is not the ruling stamp"))
    for m in re.finditer(r"RULED (BQ-\d\d)((?:, BQ-\d\d)*)", ctx.spec):
        for bq in [m[1], *re.findall(r"BQ-\d\d", m[2])]:
            if bq not in listed:
                f.append(("G19-RULED", f"a stamp names {bq}, which section R does not list"))


def g_scope(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for p in ctx.changed:
        # post-merge, a fix to this tool may ship in one bundle with its sibling design tools
        sibling = ctx.merged_spec is not None and p.startswith("docs/design/_tools/")
        if p not in OWN and p != P14_REL and not sibling:
            f.append(("G20-SCOPE", f"{p} is outside the edit set"))


ACCEPTED_14 = {
    "SCR-001": (
        "- **States:** idle · submitting · error (one message for every credential failure)",
    ),
    "SCR-006": (
        (
            "- **Validation:** typed confirmation must match exactly (case-sensitive); Confirm "
            "stays enabled; a press with an incomplete field is refused with focus to that field"
        ),
    ),
}


def entry_of(lines: list[str]) -> list[str]:
    out: list[str] = []
    entry = ""
    for ln in lines:
        m = re.match(r"### (SCR-\d+) ", ln)
        if m:
            entry = m[1]
        elif ln.startswith("## "):
            entry = ""
        out.append(entry)
    return out


def g_p14(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    base = ctx.p14_base.split("\n")
    wt = ctx.p14.split("\n")
    removed = [(e, ln) for e, ln in zip(entry_of(base), base, strict=True) if ln not in set(wt)]
    added = [(e, ln) for e, ln in zip(entry_of(wt), wt, strict=True) if ln not in set(base)]
    if (
        ctx.merged_spec is not None
    ):  # later tickets edit `14`; only the pack's four lines are its own
        for e, ln in added:
            if ln.startswith(DQA_MARK):
                f.append(("G21-P14", f"post-merge: a new design-QA line in {e or 'no entry'}"))
        own = {"SCR-001": "- **States:**", "SCR-006": "- **Validation:**"}
        for e, ln in removed:
            if e not in own:
                continue
            if (ln.startswith(DQA_MARK) and "E09-D11.md" in ln) or ln.startswith(own[e]):
                f.append(("G21-P14", f"post-merge: a line this pack landed in {e} changed"))
        return
    want_removed = {("SCR-001", "- **States:**"), ("SCR-006", "- **Validation:**")}
    got_removed = {(e, ln.split(" ", 2)[0] + " " + ln.split(" ", 2)[1]) for e, ln in removed}
    if len(removed) != 2 or got_removed != want_removed:
        f.append(("G21-P14", f"`14` lost {len(removed)} line(s), not the two accepted lines"))
    if len(added) != 4:
        f.append(("G21-P14", f"{len(added)} line(s) added to `14`, not four"))
    for e, ln in added:
        if ln.startswith(DQA_MARK):
            if e not in ("SCR-001", "SCR-006") or "E09-D11.md" not in ln:
                f.append(("G21-P14", f"a design-QA line sits in {e or 'no entry'}"))
            continue
        if not any(ln.startswith(p) for p in ACCEPTED_14.get(e, ())):
            f.append(("G21-P14", f"an added `14` line is no accepted row's text: {ln[:40]!r}"))
    for e in ("SCR-001", "SCR-006"):
        if not any(x == e and ln.startswith(DQA_MARK) for x, ln in added):
            f.append(("G21-P14", f"{e} has no design-QA line"))
    d12 = ctx.base_text("D12") or ""
    a2 = re.search(r'^\| A-2 .*States: "([^"]+)"', d12, re.MULTILINE)
    a6 = re.search(r'^\| A-6 [^|]*\|[^|]*\| "([^"]+)"', d12, re.MULTILINE)
    want_lines = {
        "SCR-001": f"- **States:** {a2[1]}." if a2 else "",
        "SCR-006": (
            "- **Validation:** typed confirmation must match exactly (case-sensitive); " f"{a6[1]}."
            if a6
            else ""
        ),
    }
    for e, want in want_lines.items():
        lead = want.split(" ", 2)[0] + " " + want.split(" ", 2)[1] if want else "?"
        got = [ln for x, ln in added if x == e and ln.startswith(lead)]
        if not want or got != [want]:
            f.append(("G21-P14", f"{e}: the accepted line is not E09-D12's A-row text in full"))
    base_entry = entry_of(base)
    owed: dict[str, set[str]] = {}
    for r in rows(section(ctx.spec, "15. "), "DF"):
        for n in re.findall(r"`14`:(\d+)", r[1] if len(r) > 1 else ""):
            idx = int(n) - 1
            if 0 <= idx < len(base_entry):
                owed.setdefault(base_entry[idx], set()).add(r[0])
    for e, ids in owed.items():
        line = next((ln for x, ln in added if x == e and ln.startswith(DQA_MARK)), "")
        for i in sorted(ids):
            if not re.search(rf"\b{i}\b", line):
                f.append(("G21-P14", f"{e}: its design-QA line does not name {i}"))


def g_freeze(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    if ctx.merged_spec is None:
        return
    now = set(ctx.spec.split("\n"))
    for ln in ctx.merged_spec.split("\n"):
        if ln.startswith("|") and not ln.startswith("| ---") and ln not in now:
            f.append(("G22-FREEZE", f"a merged row changed: {ln[:48]!r}"))


def g_walk(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    items = re.findall(r"^\d+\. ", section(ctx.spec, "18. "), re.MULTILINE)
    if not items or len(items) > 10:
        f.append(("G23-WALK", f"the owner checklist holds {len(items)} items, not 1..10"))


def g_secret(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    for name, text in (
        ("the spec", ctx.spec),
        ("the pins", ctx.pins),
        ("the `14` lines", "\n".join(added_p14(ctx))),
    ):
        m = SECRET.search(text)
        if m:
            f.append(("G24-SECRET", f"{name}: a secret-shaped value {m[0][:6]!r}…"))


def g_axe(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    want = a11y_screens(ctx)
    ax = rows(section(ctx.spec, "9. "), "AX")
    got = [(r[1], r[2] == "yes") for r in ax if len(r) > 2]
    if not want or got != want:
        f.append(
            ("G25-AXE", "the AX rows are not the gate's screens in order, or a scan flag is off")
        )


def g_security(ctx: Ctx, vals: dict[str, str], f: Findings) -> None:
    df = df_rows(ctx.spec)
    sec_ids = {r[0] for r in df if len(r) > 3 and security(r)}
    if not sec_ids:
        f.append(("G26-SECURITY", "no security-bearing row found"))
    checked: list[tuple[str, str]] = [(r[0], " | ".join(r)) for r in df if r[0] in sec_ids]
    for fam, sec in (
        ("CP", "5.2 "),
        ("FZ", "5.1 "),
        ("ST", "4. "),
        ("OB", "7.1 "),
        ("SR", "7.3 "),
        ("RN", "1.1 "),
    ):
        for r in rows(section(ctx.spec, sec), fam):
            named = set(re.findall(r"\bDF-\d+\b", " ".join(r)))
            if named & sec_ids or (fam == "FZ" and len(r) > 3 and r[3] == "differs"):
                checked.append((r[0], " | ".join(r)))
    for rid, text in checked:
        if any(k in CODE for k, _, _ in cite_spans(text)):
            f.append(("G26-SECURITY", f"{rid}: a security-bearing row cites built code"))
        if QUOTE.search(text):
            f.append(("G26-SECURITY", f"{rid}: a security-bearing row quotes a string"))


GATES: list[tuple[str, Callable[[Ctx, dict[str, str], Findings], None]]] = [
    ("G01-FILLED", g_filled),
    ("G02-AUDIT", g_audit),
    ("G03-CITE", g_cite),
    ("G04-PINS", g_pins),
    ("G05-VERBATIM", g_verbatim),
    ("G06-COPY", g_copy),
    ("G07-TOKEN", g_token),
    ("G08-CONTRAST", g_contrast),
    ("G09-STATES", g_states),
    ("G10-MAP", g_map),
    ("G11-SCRIPT", g_script),
    ("G12-COMP", g_comp),
    ("G13-FINDINGS", g_findings),
    ("G14-CLASS", g_class),
    ("G15-ROUTE", g_route),
    ("G16-T2", g_t2),
    ("G17-IDS", g_ids),
    ("G18-HYGIENE", g_hygiene),
    ("G19-RULED", g_ruled),
    ("G20-SCOPE", g_scope),
    ("G21-P14", g_p14),
    ("G22-FREEZE", g_freeze),
    ("G23-WALK", g_walk),
    ("G24-SECRET", g_secret),
    ("G25-AXE", g_axe),
    ("G26-SECURITY", g_security),
]


def run(ctx: Ctx) -> tuple[dict[str, str], Findings]:
    vals = compute(ctx)
    f: Findings = []
    for code, gate in GATES:
        try:
            gate(ctx, vals, f)
        except RUN_ERRORS as e:  # default-deny: an unreadable input is a FAIL
            f.append((code, f"the gate could not run: {type(e).__name__}: {e}"))
    return vals, f


# ---------------------------------------------------------------------------------- writers


def fill(ctx: Ctx) -> str:
    vals = compute(ctx)

    def slot(m: re.Match[str]) -> str:
        key = "sha" if m[1] == "SHA" else m[2]
        return f"{vals[key]} <!-- audit:{key}={vals[key]} -->" if key in vals else m[0]

    out = []
    for ln in SLOT.sub(slot, ctx.spec).split("\n"):
        for m in list(AUDIT.finditer(ln)):
            key, old = m[1], m[2]
            if key in vals and old != vals[key]:
                ln = ln.replace(
                    f"{old} <!-- audit:{key}={old} -->",
                    f"{vals[key]} <!-- audit:{key}={vals[key]} -->",
                )
        out.append(ln)
    return "\n".join(out)


def repin(ctx: Ctx) -> str:
    lines = [
        "# E09-D11 pins: one cited endpoint per line, `KEY:line sha1-16` of its words at the base.",
        "# Written only by `e09_d11_designqa_audit.py --repin-ruled`.",
    ]
    for key, n in sorted(endpoints(ctx.spec)):
        lines.append(f"{key}:{n} {line_hash(ctx.base_line(key, n) or '')}")
    return "\n".join(lines) + "\n"


# -------------------------------------------------------------------------------- self-test


def _swap(text: str, old: str, new: str) -> str:
    if old not in text:
        raise ValueError(f"mutation anchor missing: {old[:40]!r}")
    return text.replace(old, new, 1)


def set_cell(text: str, row_id: str, index: int, value: str) -> str:
    out = []
    done = False
    for ln in text.split("\n"):
        if not done and re.match(rf"^\|\s*{re.escape(row_id)}\s*\|", ln):
            parts = ln.split("|")
            parts[index + 1] = f" {value} "
            ln = "|".join(parts)
            done = True
        out.append(ln)
    if not done:
        raise ValueError(f"mutation anchor missing: row {row_id}")
    return "\n".join(out)


def cell(text: str, row_id: str, index: int) -> str:
    for ln in text.split("\n"):
        if re.match(rf"^\|\s*{re.escape(row_id)}\s*\|", ln):
            return cells(ln)[index]
    raise ValueError(f"mutation anchor missing: row {row_id}")


def spec_mut(fn: Callable[[str], str]) -> Callable[[Ctx], Ctx]:
    return lambda c: dataclasses.replace(c, spec=fn(c.spec))


MUTATIONS: list[tuple[str, Callable[[Ctx], Ctx]]] = [
    ("G01-FILLED", spec_mut(lambda s: s + "\n{{COUNT:st}}\n")),
    (
        "G02-AUDIT",
        spec_mut(lambda s: re.sub(r"<!-- audit:st=\d+ -->", "<!-- audit:st=999 -->", s, count=1)),
    ),
    (
        "G03-CITE",
        lambda c: dataclasses.replace(
            c,
            pins=re.sub(
                r"^(LOGIN:130) [0-9a-f]{16}$", r"\1 0000000000000000", c.pins, flags=re.MULTILINE
            ),
        ),
    ),
    ("G04-PINS", spec_mut(lambda s: s + "\nSee `D03`:5.\n")),
    (
        "G05-VERBATIM",
        spec_mut(lambda s: _swap(s, '"Authenticator code"', '"Authentication code"')),
    ),
    (
        "G06-COPY",
        spec_mut(lambda s: _swap(s, "`auth.login.busy`, `auth.unreachable`", "`auth.unreachable`")),
    ),
    ("G07-TOKEN", spec_mut(lambda s: _swap(s, "`STEPUP`:107, :116, :129", "`STEPUP`:107, :116"))),
    ("G08-CONTRAST", spec_mut(lambda s: set_cell(s, "CN-3", 8, "—"))),
    ("G09-STATES", spec_mut(lambda s: set_cell(s, "ST-5", 2, "account-locked"))),
    ("G10-MAP", spec_mut(lambda s: set_cell(s, "OB-3", 1, "T-3"))),
    ("G11-SCRIPT", spec_mut(lambda s: set_cell(s, "SR-5", 1, "skipped"))),
    ("G12-COMP", spec_mut(lambda s: set_cell(s, "CM-10", 1, "CMP-299 BuildFooter"))),
    ("G13-FINDINGS", spec_mut(lambda s: set_cell(s, "DF-8", 2, "Severe"))),
    ("G14-CLASS", spec_mut(lambda s: s + "\nSee DF-99.\n")),
    ("G15-ROUTE", spec_mut(lambda s: set_cell(s, "RT-1", 1, "#4743"))),
    (
        "G16-T2",
        spec_mut(lambda s: set_cell(s, "T2-1", 4, cell(s, "T2-1", 4).split(" · ", 1)[1])),
    ),
    ("G17-IDS", spec_mut(lambda s: _swap(s, "| AX-3 ", "| AX-2 "))),
    ("G18-HYGIENE", spec_mut(lambda s: s + "\n" + BANNED[0].upper() + "\n")),
    ("G19-RULED", spec_mut(lambda s: _swap(s, f"| {RULED_STAMP} |", "| pending |"))),
    ("G20-SCOPE", lambda c: dataclasses.replace(c, changed=[*c.changed, "docs/plan/15-x.md"])),
    (
        "G21-P14",
        lambda c: dataclasses.replace(
            c,
            p14="\n".join(
                ln for ln in c.p14.split("\n") if not (ln.startswith(DQA_MARK) and "DF-46" in ln)
            ),
        ),
    ),
    (
        "G22-FREEZE",
        lambda c: dataclasses.replace(c, merged_spec="| ST-99 | a merged row since |\n"),
    ),
    (
        "G23-WALK",
        spec_mut(
            lambda s: _swap(s, "10. Record approval on #291.", "10. Record it.\n11. And more.")
        ),
    ),
    ("G24-SECRET", spec_mut(lambda s: s + "\nABCDEFGHABCDEFGH\n")),
    ("G25-AXE", spec_mut(lambda s: set_cell(s, "AX-2", 2, "yes"))),
    (
        "G26-SECURITY",
        spec_mut(
            lambda s: _swap(s, "`auth.login.failed` (`D12`:325)", "`auth.login.failed` (`LOGIN`:8)")
        ),
    ),
    (
        "G21-P14",
        lambda c: dataclasses.replace(
            c,
            p14=_swap(
                c.p14, "rate-limited (from `Retry-After`) · server unreachable.", "server down."
            ),
        ),
    ),
    (
        "G21-P14",
        lambda c: dataclasses.replace(
            c, p14=_swap(c.p14, "(DF-47, accepted under", "(accepted under")
        ),
    ),
    ("G05-VERBATIM", spec_mut(lambda s: _swap(s, '"Signing in..."', '"Signing in"'))),
    ("G08-CONTRAST", spec_mut(lambda s: _swap(s, "CN-4 = P-6", "CN-4 = P-3"))),
    ("G06-COPY", spec_mut(lambda s: set_cell(s, "FZ-9", 4, "`SESS`:285"))),
]


def frozen_base_problems(ctx: Ctx) -> list[str]:
    """Post-merge cites freeze at the recorded base: a moved merge-base must not move them."""
    out: list[str] = []
    moved = "f" * 40  # stands for a main that has moved on since the pack merged
    if frozen_base(None, moved) != moved:
        out.append("PR-1 mode must read at the merge-base")
    if ctx.merged_spec is not None:
        if frozen_base(ctx.merged_spec, moved) != ctx.base:
            out.append("post-merge mode follows the merge-base, not the recorded base")
        no_marker = ctx.merged_spec.replace("audit:sha=", "audit:unused=")
        if frozen_base(no_marker, moved) != moved:
            out.append("post-merge mode with no recorded base must fall back, which G02 then fails")
        stale = re.sub(r"(audit:sha=)[0-9a-f]{40}", r"\g<1>" + "0" * 40, ctx.merged_spec)
        if frozen_base(stale, moved) != moved:
            out.append("an unresolvable recorded base was accepted")
    return out


def self_test(ctx: Ctx) -> tuple[int, int, list[str]]:
    _, base = run(ctx)
    problems: list[str] = []
    if base:
        problems.append(f"the base run is not clean: {len(base)} FAIL(s)")
    before = {code for code, _ in base}
    passed = 0
    for code, mutate in MUTATIONS:
        try:
            _, got = run(mutate(ctx))
        except RUN_ERRORS as e:
            problems.append(f"{code}: the mutation could not apply: {e}")
            continue
        if any(c == code for c, _ in got) and code not in before:
            passed += 1
        else:
            problems.append(f"{code}: the mutation added no FAIL of its gate")
    if {code for code, _ in GATES} - {code for code, _ in MUTATIONS}:
        problems.append("a gate has no mutation")
    problems += frozen_base_problems(ctx)
    return passed, len(MUTATIONS), problems


# ------------------------------------------------------------------------------------- main


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 on any FAIL (a bare run does too)")
    ap.add_argument("--json", action="store_true", help="print the numbers and findings as JSON")
    ap.add_argument("--fill", action="store_true", help="write the computed values into the spec")
    ap.add_argument("--self-test", action="store_true", help="the mutation self-test")
    ap.add_argument("--repin-ruled", action="store_true", help="rewrite the pins file")
    args = ap.parse_args(argv)
    ctx = build_ctx()
    mode = "post-merge" if ctx.merged_spec is not None else "PR-1"
    if args.repin_ruled:
        (ROOT / PINS_REL).write_text(repin(ctx), encoding="utf-8")
        print(f"pins rewritten: {len(endpoints(ctx.spec))} cited endpoints")
        return 0
    if args.fill:
        (ROOT / SPEC_REL).write_text(fill(ctx), encoding="utf-8")
        print("spec filled")
        return 0
    if args.self_test:
        passed, total, problems = self_test(ctx)
        for p in problems:
            print(f"SELF-TEST FAIL {p}")
        print(f"self-test: {passed}/{total} mutations caught; {len(GATES)} gates; mode {mode}")
        return 0 if passed == total and not problems else 1
    vals, f = run(ctx)
    if args.json:
        print(
            json.dumps({"mode": mode, "base": ctx.base, "numbers": vals, "findings": f}, indent=2)
        )
    else:
        for code, msg in f:
            print(f"FAIL [{code}] {msg}")
        print(f"mode {mode}; base {ctx.base[:12]}; {len(GATES)} gates; FAIL {len(f)} / WARN 0")
    return 1 if f else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

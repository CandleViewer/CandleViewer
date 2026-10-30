#!/usr/bin/env python3
"""E32-D06 (#926) audit: the design-system pack for CMP-158 and the native-SL affordance pattern.

Standalone, offline, stdlib only; it runs under `python3 -I`. It reads AS TEXT at the pinned base
(`git merge-base HEAD origin/main`, via `git show BASE:<path>`) the plan texts (`02`, `05`, `14`,
`15`, `16`), the constitution and the design rule file, the merged E32 design docs (D02 ... D05 and
the two hand-offs), E30-D02, E30-D04, E36-D03, E35-D02, E05-D03, E33-D03, E09-D09, the token JSON
(`themes.json` layering: dark = primitives + semantic-dark, light = + semantic-light,
hc = + semantic-hc), `pairs.mjs`, the CVD script, the sprint calendar and the E32 backlog JSON;
then the pack (`E32-D06.md`), its hand-off (`E32-D06-handoff.md`) and the pins from the working
tree. Every source it normalises is cached once per (revision, path); the contrast arithmetic is
imported from the sibling `contrast_check.py` (never copied) and the CVD matrices are parsed from
`cvd_sim.py`'s source at the base (never re-typed).

Gates (one mutation each in `--self-test`; the pins gate besides):
  (a) G-LEDGER    the A-row ledger re-pinned by content: every row of record's cited line carries
                  its backticked needle at the base (the cite resolved by content when it moved);
                  dispositions from the ruled set; "applied by #N" rows verified against the target
                  file's history and the target line; every A-id a row carries exists in §C.
  (b) G-AROW      every §C row well-formed, its Old cell equal to its line at the base byte for
                  byte, its New a bullet, the export applicable to the base with every anchor found
                  once.
  (c) G-TOKEN     every name the §7 table and the §C Tokens cells bind is shipped in `TOK` (a colour
                  resolves to a hex in all three themes); zero proposals; the PROPOSED `PAIRS` row's
                  tokens shipped.
  (d) G-CONTRAST  every pair of §11 unrounded in three themes; `registered` rows gated at 4.5 text /
                  3.0 non-text, PROPOSED rows measured and reported; the `PAIRS` column a read-only
                  cross-check of `tools/contrast/pairs.mjs`; every ratio and Reading cell compared
                  whole (no fill residue in front of an anchored value, in any table cell).
  (e) G-CVD       the V-rows through `cvd_sim.py`'s matrices and greyscale weights read from its
                  source at the base.
  (f) G-MOTION    every §8 row names a shipped duration and easing primitive or is a cut (`none`),
                  carries a `none` reduce cell and a non-motion carrier; no safety signal animates;
                  the rule row stands.
  (g) G-STRINGS   every sentence §4 quotes equals its source key's text at the base, verbatim.
  (h) G-STORIES   the Storybook unions: CMP-158 covers `15`'s list plus the two PROPOSED names,
                  CMP-119 covers `15`'s plus HA-6's six, CMP-120 equals D05 §4.2's list, CMP-228
                  covers `15`'s plus D04-A2's two.
      G-ENTRY     every field bullet in a New cell is declared (`15` §0.1 or the two lead-ins); the
                  hand-off carries `16` §11.4's lines in order; its ledger-by-component table equals
                  the derivation from §2 and §C; §R lists BQ-01 ... BQ-20 as RULED.
  (j) G-VERSION   values, never a sha: the calendar's sprint-1 start and length and the five sprint
                  fields at `origin/main` equal the base; each cite's content at the base stands at
                  `origin/main`, re-found inside the cited entry's heading span alone (moved once =
                  WARN; gone or ambiguous = FAIL).
  (i) G-HYGIENE   placeholders filled and re-derived, no `{{` left, every cite in range, non-blank
                  and content-pinned (a moved cite is a WARN until `--repin-ruled` records it or the
                  spec re-points it; an edited one a FAIL), the tree against the merge-base: PR 1 may
                  differ only in the pack's four files; PR 2 (`15` / `14` changed, the spec, the
                  hand-off and the tool unchanged) must equal the merge-base with §C applied exactly,
                  and may differ in the pins alone, by recorded cite moves only, the file byte for
                  byte what `--repin-ruled` writes from the merge-base's units (BQ-03); no closing
                  keyword, no local path, no agent name, no URL or Penpot host; the §22 list equal to
                  the tool's.
  G-RULED-PIN     a default-deny pin set over every unit of the pack and the hand-off
                  (`e32_d06_ruled_pins.txt`); `--repin-ruled` is the only writer.

Usage (from the repo root):
  python3 -I docs/design/_tools/e32_d06_ds_audit.py --check [--json] [--fill]
  python3 -I docs/design/_tools/e32_d06_ds_audit.py --self-test
  python3 -I docs/design/_tools/e32_d06_ds_audit.py --repin-ruled
  python3 -I docs/design/_tools/e32_d06_ds_audit.py --a-rows
Exit 0 = no FAIL; 1 = at least one FAIL. `--check` ends with the per-gate timings; the `--json` dump
carries values, findings and timings only.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC_REL = "docs/design/E32/E32-D06.md"
HAND_REL = "docs/design/E32/E32-D06-handoff.md"
PINS_REL = "docs/design/_tools/e32_d06_ruled_pins.txt"
TOOL_REL = "docs/design/_tools/e32_d06_ds_audit.py"
OWN_PATHS = (SPEC_REL, HAND_REL, PINS_REL, TOOL_REL)
PACK_TEXTS = (SPEC_REL, HAND_REL, TOOL_REL)  # PR 2 may touch none of these (BQ-03)
CAT_REL = "docs/plan/15-component-catalogue.md"
SCR_REL = "docs/plan/14-screens-catalogue.md"
DS_SRC = "packages/ui/tokens"
PAIRS_REL = "tools/contrast/pairs.mjs"
CVD_REL = "docs/design/_tools/cvd_sim.py"
CAL_REL = "docs/plan/backlog/_tools/calendar_cv.py"
E32J_REL = "docs/plan/backlog/E32.json"
CONTRAST_REL = "docs/design/_tools/contrast_check.py"
HEAD_REF = "origin/main"
ISSUE = "926"
RULING_ID = "6520464215"
PATHS: dict[str, str] = {
    "02": "docs/plan/02-definition-of-ready-done.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "14": SCR_REL,
    "15": CAT_REL,
    "16": "docs/plan/16-design-system-brief.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "23": "docs/plan/23-ws-protocol.md",
    "CONST": "CONSTITUTION.md",
    "RULE": ".claude/rules/32-design-specs.md",
    "D02": "docs/design/E32/E32-D02.md",
    "D03": "docs/design/E32/E32-D03.md",
    "D03H": "docs/design/E32/E32-D03-handoff.md",
    "D04": "docs/design/E32/E32-D04.md",
    "D05": "docs/design/E32/E32-D05.md",
    "D05H": "docs/design/E32/E32-D05-handoff.md",
    "E30D02": "docs/design/E30/E30-D02.md",
    "E30D04": "docs/design/E30/E30-D04.md",
    "E36D03": "docs/design/E36/E36-D03.md",
    "E35D02": "docs/design/E35/E35-D02.md",
    "E05D03": "docs/design/E05/E05-D03.md",
    "E33D03": "docs/design/E33/E33-D03.md",
    "E09D09": "docs/design/E09/E09-D09.md",
    "PAIRS": PAIRS_REL,
    "CVD": CVD_REL,
    "CAL": CAL_REL,
}
TOKEN_FILES = ("primitives", "semantic-dark", "semantic-light", "semantic-hc")
SHA_INPUTS: dict[str, tuple[str, ...]] = {
    "D02": (PATHS["D02"],),
    "D03": (PATHS["D03"], PATHS["D03H"]),
    "D04": (PATHS["D04"],),
    "D05": (PATHS["D05"], PATHS["D05H"]),
    "15": (CAT_REL,),
    "14": (SCR_REL,),
    "E30D02": (PATHS["E30D02"],),
    "E30D04": (PATHS["E30D04"],),
    "E36D03": (PATHS["E36D03"],),
    "E35D02": (PATHS["E35D02"],),
    "E05D03": (PATHS["E05D03"],),
    "TOK": tuple(f"{DS_SRC}/{f}.tokens.json" for f in TOKEN_FILES) + (f"{DS_SRC}/themes.json",),
    "CVD": (CVD_REL,),
    "CAL": (CAL_REL,),
}
THEMES = ("dark", "light", "hc")
BARS = {"text": 4.5, "non-text": 3.0}
DISPOSITIONS = ("applied-as-amended", "applied by #", "applied", "routed", "held")
BASE_FIELDS = ("Tier", "Purpose", "Props", "Variants", "States", "A11y", "Tokens", "Storybook",
               "Tests", "API sketch", "Data contract")  # fmt: skip
OPTIONAL_FIELDS = ("Forbidden", "Security", "Performance", "Observability")
LEAD_FIELDS = ("Motion (E32-D06)", "Usage (E32-D06)")
# the Storybook unions (BQ-15): A-row -> (`15` line at the base, the parent's cite and its lead, rule)
STORY_ROWS: dict[str, tuple[str, int, tuple[str, int, str] | None, str, tuple[str, ...]]] = {
    "158": ("A-6", 1886, None, "superset", ("InHeldPosition", "InDraftBuilder")),
    "119": ("A-15", 1427, ("D03", 332, "| HA-6 "), "superset", ()),
    "120": ("A-23", 1440, ("D05", 210, "**Storybook (PROPOSED, D05-A1):**"), "equal", ()),
    "228": ("A-28", 2857, ("D04", 417, "| D04-A2 "), "superset", ()),
}
# the sprint values the design-ahead section anchors (key in the backlog JSON -> anchor id)
SPRINT_KEYS = {
    "E32-D06": "d06",
    "E32-D07": "d07",
    "E32-S05": "s05",
    "E32-S07": "s07",
    "E32-S06": "s06",
}
CONSUMERS = ("s05", "s07", "s06")
# the CVD rows of §11 (V id -> the two token names)
V_PAIRS: dict[str, tuple[str, str]] = {
    "v1": ("color.status.info.strong", "color.status.info.subtle"),
    "v2": ("color.status.danger.default", "color.surface.app"),
    "v3": ("color.status.info.subtle", "color.status.danger.subtle"),
    "v4": ("color.status.success.subtle", "color.status.danger.subtle"),
}
# the safety signals that never animate (§8's rule row): a §8 row naming one must be a cut
SAFETY_WORDS = ("CMP-158", "unprotected", "boundary", "revert line", "refusal line", "outcome line",
                "validation", "error summary")  # fmt: skip

PLACEHOLDER = re.compile(r"\{\{([A-Z]+:[^{}]+?)\}\}")
# a filled value is one code span or one whitespace-free run, consumed whole on a refresh (so a
# re-fill never leaves the tail of a prior value in front of the anchor)
ANCHORED = re.compile(r"(`[^`\n]*`|[^\s<|`]+)<!--=([A-Z]+:[^>]+?)-->")
CODE = re.compile(r"`[^`\n]*`")
HEADING = re.compile(r"^(#{1,6}) (.+)$")
RULE = re.compile(r"^\s*\|?\s*:?-{3,}")
TOKEN_NAME = re.compile(
    r"^(?:color|size|space|radius|type|opacity|border|elevation|font|motion)\.[a-z0-9.\-]+$"
)
CITE = re.compile(
    r"(?:`([0-9]{2})`|\b(D0[2-5]H?|E30D0[24]|E36D03|E35D02|E05D03|E33D03|E09D09|PAIRS|CVD|CAL"
    r"|CONST|RULE)`?):(\d+)(?:[–-](\d+))?"
)
FIELD = re.compile(r"`(14|15)`:(\d+)")
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE)
# assembled, so the deny pattern never spells the strings it refuses
LOCAL_PATH = re.compile("/" + "home/|/Users/|[A-Za-z]:\\\\|\\bwt-" + "notes\\b")
AGENT_NAME = re.compile(r"\b[a-z]{2,4}-worker-\d\b")
URL_OR_HOST = re.compile(r"https?://|penpot\.[a-z]|team-id=|file-id=", re.IGNORECASE)
FULL_STOP = re.compile(r"(?<=[.!?])\s+(?=[*`\"(A-Z0-9§])")


# ---------------------------------------------------------------------------- git and caches


def git_raw(*args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=False)
    except OSError:
        return None
    return r.stdout.decode("utf-8", "surrogateescape") if r.returncode == 0 else None


def merge_base() -> str | None:
    out = git_raw("merge-base", "HEAD", HEAD_REF)
    return out.strip() if out and re.fullmatch(r"[0-9a-f]{40}\s*", out) else None


def changed_paths(base: str) -> list[str] | None:
    """Committed and uncommitted paths that differ from the merge-base; None when git fails."""
    a = git_raw("diff", "--name-only", base)
    b = git_raw("status", "--porcelain", "--untracked-files=all")
    if a is None or b is None:
        return None
    out = {p for p in a.split("\n") if p}
    for ln in b.split("\n"):
        if len(ln) > 3:
            out.add(ln[3:].split(" -> ")[-1].strip('"'))
    return sorted(out)


def pin_norm(text: str) -> str:
    return " ".join(text.split())


def line_hash(first: str, last: str) -> str:
    return hashlib.sha256((pin_norm(first) + "\n" + pin_norm(last)).encode()).hexdigest()[:12]


@dataclass
class Env:
    base: str
    memo: dict[str, object]

    def show(self, rev: str, rel: str) -> str | None:
        key = f"show:{rev}:{rel}"
        if key not in self.memo:
            self.memo[key] = git_raw("show", f"{rev}:{rel}")
        v = self.memo[key]
        return v if isinstance(v, str) else None

    def at_base(self, rel: str) -> str:
        t = self.show(self.base, rel)
        if t is None:
            raise SystemExit(f"{rel} is missing at the base {self.base[:10]}")
        return t

    def lines(self, rev: str, rel: str) -> list[str]:
        """The file's lines at `rev`, split once and cached."""
        key = f"lines:{rev}:{rel}"
        if key not in self.memo:
            t = self.show(rev, rel)
            self.memo[key] = t.split("\n") if t is not None else []
        v = self.memo[key]
        return v if isinstance(v, list) else []

    def hash_index(self, rev: str, rel: str, span: int) -> dict[str, list[int]]:
        """Content hash of (line i, line i + span) -> the 1-based line numbers i; cached once."""
        key = f"hidx:{rev}:{rel}:{span}"
        if key not in self.memo:
            ls = self.lines(rev, rel)
            idx: dict[str, list[int]] = {}
            for i in range(len(ls) - span):
                if ls[i].strip():
                    idx.setdefault(line_hash(ls[i], ls[i + span]), []).append(i + 1)
            self.memo[key] = idx
        v = self.memo[key]
        return v if isinstance(v, dict) else {}

    def log_subjects(self, rel: str) -> str:
        key = f"log:{rel}"
        if key not in self.memo:
            self.memo[key] = git_raw("log", "--format=%s", HEAD_REF, "--", rel) or ""
        v = self.memo[key]
        return v if isinstance(v, str) else ""


def read_raw(rel: str) -> str:
    with open(ROOT / rel, encoding="utf-8", newline="") as f:
        return f.read()


def write_text(rel: str, text: str) -> None:
    with open(ROOT / rel, "w", encoding="utf-8", newline="") as f:
        f.write(text)


# ---------------------------------------------------------------------------- text helpers


def lines_of(text: str) -> list[str]:
    return text.split("\n")


def split_row(line: str) -> list[str]:
    body = line.strip().removeprefix("|")
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return [c.strip() for c in re.split(r"(?<!\\)\|", body)]


def unescape(cell: str) -> str:
    return cell.replace("\\|", "|")


def tables(block: str) -> list[list[list[str]]]:
    out: list[list[list[str]]] = []
    cur: list[list[str]] = []
    for ln in lines_of(block):
        if ln.lstrip().startswith("|"):
            if RULE.match(ln):
                continue
            cur.append(split_row(ln))
        elif cur:
            out.append(cur)
            cur = []
    if cur:
        out.append(cur)
    return out


def table_after(block: str, header0: str) -> list[list[str]]:
    for t in tables(block):
        if t and t[0] and t[0][0] == header0:
            return t[1:]
    return []


def section(text: str, head_prefix: str) -> str:
    ls = lines_of(text)
    for i, ln in enumerate(ls):
        m = HEADING.match(ln)
        if m and (ln.startswith(head_prefix + " ") or ln == head_prefix):
            level = len(m[1])
            j = i + 1
            while j < len(ls):
                m2 = HEADING.match(ls[j])
                if m2 and len(m2[1]) <= level:
                    break
                j += 1
            return "\n".join(ls[i:j])
    return ""


def without_code(text: str) -> str:
    return CODE.sub("`…`", text)


def strip_anchors(text: str) -> str:
    return re.sub(r"<!--=[A-Z]+:[^>]+?-->", "", text)


def strip_parens(text: str) -> str:
    out, depth = [], 0
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif depth == 0:
            out.append(ch)
    return "".join(out)


# ---------------------------------------------------------------------------- colour math (imported)


def contrast_module() -> object:
    spec = importlib.util.spec_from_file_location("cv_contrast_check", ROOT / CONTRAST_REL)
    if spec is None or spec.loader is None:
        raise SystemExit(f"{CONTRAST_REL} cannot be imported")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_CONTRAST: object | None = None


def rgb(hex6: str) -> tuple[int, int, int]:
    h = hex6.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def contrast(a: str, b: str) -> float:
    global _CONTRAST
    if _CONTRAST is None:
        _CONTRAST = contrast_module()
    fn = getattr(_CONTRAST, "contrast_ratio", None)
    if fn is None:
        raise SystemExit(f"{CONTRAST_REL} has no contrast_ratio")
    return float(fn(rgb(a), rgb(b)))


def show_ratio(r: float) -> str:
    return f"{int(r * 100) / 100:.2f}"


def clip_byte(v: float) -> int:
    return max(0, min(255, round(v)))


def cvd_matrices(env: Env) -> dict[str, tuple[float, ...]]:
    """`cvd_sim.py`'s matrices and greyscale weights, parsed from its source at the base."""
    key = "cvd:matrices"
    if key not in env.memo:
        src = env.at_base(CVD_REL)
        out: dict[str, tuple[float, ...]] = {}
        for name, sim in (("DEUTERANOPIA_MATRIX", "deut"), ("PROTANOPIA_MATRIX", "prot")):
            m = re.search(name + r"\s*=\s*np\.array\(\s*\[(.*?)\]\s*\)", src, re.DOTALL)
            nums = re.findall(r"-?\d+\.\d+", m[1]) if m else []
            out[sim] = tuple(float(x) for x in nums)
        g = re.search(r"\*\s*(\d\.\d+)\s*\+.*?\*\s*(\d\.\d+)\s*\+.*?\*\s*(\d\.\d+)", src)
        out["grey"] = tuple(float(x) for x in g.groups()) if g else ()
        env.memo[key] = out
    v = env.memo[key]
    return v if isinstance(v, dict) else {}


def simulate(env: Env, hex6: str, sim: str) -> str:
    r, g, b = rgb(hex6)
    mats = cvd_matrices(env)
    if sim == "grey":
        w = mats.get("grey", ())
        if len(w) != 3:
            raise SystemExit("cvd_sim.py: the greyscale weights were not found")
        y = clip_byte(r * w[0] + g * w[1] + b * w[2])
        return f"#{y:02X}{y:02X}{y:02X}"
    m = mats.get(sim, ())
    if len(m) != 9:
        raise SystemExit(f"cvd_sim.py: the {sim} matrix was not found")
    rr = clip_byte(m[0] * r + m[1] * g + m[2] * b)
    gg = clip_byte(m[3] * r + m[4] * g + m[5] * b)
    bb = clip_byte(m[6] * r + m[7] * g + m[8] * b)
    return f"#{rr:02X}{gg:02X}{bb:02X}"


# ---------------------------------------------------------------------------- tokens


def token_file(env: Env, name: str) -> dict[str, object]:
    data = json.loads(env.at_base(f"{DS_SRC}/{name}.tokens.json"))
    return data if isinstance(data, dict) else {}


def layering(env: Env) -> dict[str, tuple[str, ...]]:
    data = json.loads(env.at_base(f"{DS_SRC}/themes.json"))
    out: dict[str, tuple[str, ...]] = {}
    for th in data.get("themes", []) if isinstance(data, dict) else []:
        if isinstance(th, dict) and th.get("group") == "theme":
            name = {"high-contrast": "hc"}.get(str(th.get("name")), str(th.get("name")))
            out[name] = tuple(str(x) for x in th.get("sets", []))
    return out


def theme(env: Env, name: str) -> dict[str, str]:
    key = f"theme:{name}"
    if key not in env.memo:
        merged: dict[str, str] = {}
        for f in layering(env).get(name, ()):
            for k, v in token_file(env, f).items():
                if isinstance(v, dict) and "$value" in v:
                    merged[k] = v["$value"] if isinstance(v["$value"], str) else "(composite)"
        env.memo[key] = merged
    out = env.memo[key]
    return out if isinstance(out, dict) else {}


def shipped_names(env: Env) -> frozenset[str]:
    out: set[str] = set()
    for t in THEMES:
        out |= set(theme(env, t))
    return frozenset(out)


def resolve(env: Env, t: str, name: str, depth: int = 0) -> str | None:
    if depth > 24:
        return None
    m = re.fullmatch(r"\{([^{}]+)\}", name)
    if m:
        name = m[1]
    if re.fullmatch(r"#[0-9A-Fa-f]{6}", name):
        return name.upper()
    v = theme(env, t).get(name)
    return resolve(env, t, v, depth + 1) if v is not None else None


def pairs_registered(env: Env) -> frozenset[tuple[str, str]]:
    src = env.at_base(PAIRS_REL)
    return frozenset(re.findall(r'fg:\s*"([^"]+)",\s*bg:\s*"([^"]+)"', src))


# ---------------------------------------------------------------------------- cites


def cites_in(text: str) -> list[tuple[str, int, int]]:
    out = []
    for ln in lines_of(text):
        for m in CITE.finditer(ln):
            key = m[1] or m[2]
            if key in PATHS:
                a = int(m[3])
                out.append((key, a, int(m[4]) if m[4] else a))
    return out


def label_of(key: str, a: int, b: int) -> str:
    return f"{key}:{a}" if a == b else f"{key}:{a}–{b}"


CitePin = tuple[str, tuple[int, int] | None]  # (hash, the recorded move)


@dataclass(frozen=True)
class Texts:
    env: Env
    spec: str
    hand: str
    pins: str
    cat15: str
    cat14: str
    changed: list[str] | None
    values: dict[str, str]


def cite_pins(pins: str) -> dict[str, CitePin]:
    out: dict[str, CitePin] = {}
    for ln in pins.split("\n"):
        parts = ln.split("\t")
        if len(parts) >= 3 and parts[0] == "cite":
            at = None
            if len(parts) > 3 and parts[3].startswith("@"):
                m = re.fullmatch(r"@(\d+)(?:–(\d+))?", parts[3])
                if m:
                    at = (int(m[1]), int(m[2]) if m[2] else int(m[1]))
            out[parts[1]] = (parts[2], at)
    return out


def heading_before(ls: list[str], n: int) -> str:
    """The nearest heading line at or above the 1-based line `n` (the entry a cite sits in)."""
    for i in range(min(n, len(ls)) - 1, -1, -1):
        if ls[i].startswith("#"):
            return ls[i]
    return ""


def found_in_entry(env: Env, rev: str, rel: str, h: str, span: int, heading: str) -> list[int]:
    """The 1-based lines at `rev` whose content hashes to `h`, kept only inside the entry whose
    heading is `heading` (a re-find never crosses into another component's entry)."""
    ls = env.lines(rev, rel)
    return [
        n for n in env.hash_index(rev, rel, span).get(h, []) if heading_before(ls, n) == heading
    ]


def resolve_cite(t: Texts, key: str, a: int, b: int) -> tuple[int, int, str]:
    """The effective lines of a cite at the base and its status: `ok` (the pinned content stands at
    its number), `recorded` (moved, the move recorded in the pins), `moved` (found by content once,
    inside the cited entry's heading span), `gone` (edited, deleted, or standing twice in the entry),
    `unpinned`, `range` (past the end of the file)."""
    ls = t.env.lines(t.env.base, PATHS[key])
    if not (0 < a <= b <= len(ls)):
        return a, b, "range"
    pinned = cite_pins(t.pins).get(label_of(key, a, b))
    here = line_hash(ls[a - 1], ls[b - 1])
    if pinned is None:
        return a, b, "unpinned"
    h, at = pinned
    if h == here:
        return a, b, "ok"
    if at and 0 < at[0] <= at[1] <= len(ls) and line_hash(ls[at[0] - 1], ls[at[1] - 1]) == h:
        return at[0], at[1], "recorded"
    found = found_in_entry(t.env, t.env.base, PATHS[key], h, b - a, heading_before(ls, a))
    if len(found) == 1:
        return found[0], found[0] + (b - a), "moved"
    return a, b, "gone"


def cite_line(t: Texts, key: str, n: int) -> str:
    a, _, status = resolve_cite(t, key, n, n)
    ls = t.env.lines(t.env.base, PATHS[key])
    return ls[a - 1] if status != "range" and 0 < a <= len(ls) else ""


def all_cites(t: Texts) -> list[tuple[str, int, int]]:
    """Every distinct cite of the pack and the hand-off (the ledger's rows of record included, so a
    needle is looked up at the cite's content-resolved line)."""
    seen: list[tuple[str, int, int]] = []
    for c in cites_in(t.spec) + cites_in(t.hand):
        if c not in seen:
            seen.append(c)
    return seen


def cite_problems(t: Texts) -> tuple[list[str], list[str]]:
    """(FAILs, WARNs) over every distinct cite: range, blank, unpinned, gone, moved."""
    bad: list[str] = []
    warn: list[str] = []
    for key, a, b in all_cites(t):
        label = label_of(key, a, b)
        a2, b2, status = resolve_cite(t, key, a, b)
        ls = t.env.lines(t.env.base, PATHS[key])
        if status == "range":
            bad.append(f"{label} is past the end of the file ({len(ls)} lines)")
            continue
        for n in (a2, b2):
            if not ls[n - 1].strip():
                bad.append(f"{label} is a blank line")
        if status == "unpinned":
            bad.append(f"cite {label} is unpinned: verify it by content, then --repin-ruled")
        elif status == "gone":
            bad.append(
                f"cite {label}: the pinned content stands nowhere once inside its entry at the base "
                "(edited, or ambiguous)"
            )
        elif status == "moved":
            warn.append(
                f"cite {label}: the pinned content moved to :{a2} — re-point it (PR 1) or "
                "--repin-ruled records the move (PR 2)"
            )
    return bad, warn


# ---------------------------------------------------------------------------- the pack's rows


def sec(spec: str, prefix: str) -> str:
    return section(spec, prefix)


def ledger_rows(spec: str) -> list[list[str]]:
    return [r for r in table_after(sec(spec, "## 2."), "L") if r and r[0].startswith("L-")]


def c_rows(spec: str) -> list[list[str]]:
    return [r for r in table_after(sec(spec, "## §C"), "A") if r and r[0].startswith("A-")]


def a_row(spec: str, aid: str) -> list[str] | None:
    return next((r for r in c_rows(spec) if r[0] == aid), None)


def new_of(spec: str, aid: str) -> str:
    r = a_row(spec, aid)
    return strip_anchors(unescape(r[5])) if r and len(r) == 7 else ""


def bq_rows(spec: str) -> list[list[str]]:
    return [r for r in table_after(sec(spec, "## R."), "BQ") if r and r[0].startswith("BQ-")]


def s_rows(spec: str) -> list[list[str]]:
    return [r for r in table_after(sec(spec, "## 4."), "S") if r and r[0].startswith("S-")]


def token_rows(spec: str) -> list[list[str]]:
    return [r for r in table_after(sec(spec, "## 7."), "Token") if r and r[0].startswith("`")]


def m_rows(spec: str) -> list[list[str]]:
    return [r for r in table_after(sec(spec, "## 8."), "M") if r and r[0].startswith("M-")]


def p_rows(spec: str) -> list[list[str]]:
    return [r for r in table_after(sec(spec, "## 11."), "P") if r and r[0].startswith("P-")]


def v_rows(spec: str) -> list[list[str]]:
    return [r for r in table_after(sec(spec, "## 11."), "V") if r and r[0].startswith("V-")]


def contradiction_rows(spec: str) -> list[list[str]]:
    return [r for r in table_after(sec(spec, "## 16."), "C") if r and r[0].startswith("C-")]


def g_rows(spec: str) -> list[list[str]]:
    return [r for r in table_after(sec(spec, "## 17."), "G") if r and r[0].startswith("G-")]


def board_rows(spec: str) -> list[list[str]]:
    return [r for r in table_after(sec(spec, "## 19."), "#") if r and re.fullmatch(r"\d\d", r[0])]


def consumer_rows(spec: str) -> list[list[str]]:
    return [r for r in table_after(sec(spec, "## 14."), "Surface") if r and r[0].startswith("SCR-")]


def disposition(cell: str) -> str:
    for word in DISPOSITIONS:
        if cell.startswith(word):
            return word
    return ""


def a_ids(cell: str) -> list[str]:
    """`A-1, A-3` and `A-18 … A-24` forms; `—` is none."""
    out: list[str] = []
    for part in re.split(r",\s*", cell):
        m = re.fullmatch(r"A-(\d+)\s*…\s*A-(\d+)", part.strip())
        if m:
            out += [f"A-{i}" for i in range(int(m[1]), int(m[2]) + 1)]
        elif re.fullmatch(r"A-\d+", part.strip()):
            out.append(part.strip())
    return out


def stories_of(line: str) -> list[str]:
    body = line.split("**Storybook**:", 1)[-1] if "**Storybook**:" in line else line
    body = strip_parens(body).split(";", 1)[0].strip().rstrip(".")
    return [x.strip() for x in body.split(",") if re.fullmatch(r"[A-Z][A-Za-z0-9]*", x.strip())]


def parent_stories(t: Texts, key: str, n: int, lead: str) -> list[str]:
    ln = cite_line(t, key, n)
    if not ln.startswith(lead) and lead not in ln:
        return []
    if key == "D05":
        body = ln.split("**Tests")[0]
        return re.findall(r"`([A-Z][A-Za-z0-9]*)`", body)
    m = re.search(r"Storybook(?: \(:\d+\))? → \+ (.*?)(?: \||$)", ln) or re.search(
        r"\+ ((?:[A-Z][A-Za-z0-9]*,? ?)+)", strip_parens(ln)
    )
    return re.findall(r"`?([A-Z][A-Za-z0-9]+)`?", m[1]) if m else []


# ---------------------------------------------------------------------------- values


def sha_of(env: Env, paths: tuple[str, ...]) -> str:
    out = git_raw("log", "-1", "--format=%h", "--abbrev=10", env.base, "--", *paths)
    return out.strip() if out and out.strip() else "0000000000"


def calendar_values(src: str) -> tuple[datetime.date | None, int | None]:
    m = re.search(r"SPRINT01_START\s*=\s*datetime\.date\((\d+),\s*(\d+),\s*(\d+)\)", src)
    d = re.search(r"^SPRINT_DAYS\s*=\s*(\d+)", src, re.MULTILINE)
    start = datetime.date(int(m[1]), int(m[2]), int(m[3])) if m else None
    return start, int(d[1]) if d else None


def sprint_fields(src: str) -> dict[str, int]:
    data = json.loads(src)
    items = (
        data
        if isinstance(data, list)
        else data.get("tickets", []) if isinstance(data, dict) else []
    )
    out: dict[str, int] = {}
    for it in items:
        if isinstance(it, dict) and it.get("key") in SPRINT_KEYS:
            m = re.search(r"(\d+)", str(it.get("sprint", "")))
            if m:
                out[SPRINT_KEYS[str(it["key"])]] = int(m[1])
    return out


def date_values(env: Env) -> dict[str, str]:
    vals: dict[str, str] = {}
    start, days = calendar_values(env.at_base(CAL_REL))
    sprints = sprint_fields(env.at_base(E32J_REL))
    for k, n in sprints.items():
        vals[f"SPRINT:{k}"] = str(n)
        if start and days:
            vals[f"DATE:{k}.start"] = (start + datetime.timedelta(days=(n - 1) * days)).isoformat()
    if "d06" in sprints and all(c in sprints for c in CONSUMERS):
        vals["COUNT:ahead.min"] = str(min(sprints[c] for c in CONSUMERS) - sprints["d06"])
    return vals


def pair_values(env: Env, spec: str) -> dict[str, str]:
    vals: dict[str, str] = {}
    gated = failing = reported = 0
    for r in p_rows(spec):
        if len(r) < 10:
            continue
        pid = r[0].lower().replace("-", "")
        fg, bg, kind, status = r[2].strip("`"), r[3].strip("`"), r[4], r[9]
        ratios: dict[str, float] = {}
        for t in THEMES:
            a, b = resolve(env, t, fg), resolve(env, t, bg)
            if a and b:
                ratios[t] = contrast(a, b)
                vals[f"CONTRAST:{pid}.{t}"] = show_ratio(ratios[t])
        below = [t for t in THEMES if t in ratios and kind in BARS and ratios[t] < BARS[kind]]
        reading = "meets" if not below else "below:" + "+".join(below)
        if status == "PROPOSED":
            reported += 1
            reading += "/reported"
        else:
            gated += 1
            if below:
                failing += 1
        vals[f"PAIR:{pid}"] = f"`{reading}`"
    vals["COUNT:pairs"] = str(len(p_rows(spec)))
    vals["COUNT:pairs.gated"] = str(gated)
    vals["COUNT:pairs.reported"] = str(reported)
    vals["COUNT:pairs.failing"] = str(failing)
    return vals


def cvd_values(env: Env, spec: str) -> dict[str, str]:
    vals: dict[str, str] = {}
    for vid, (a, b) in V_PAIRS.items():
        for t in THEMES:
            ha, hb = resolve(env, t, a), resolve(env, t, b)
            if ha and hb:
                for sim in ("grey", "deut", "prot"):
                    vals[f"CVD:{vid}.{sim}.{t}"] = show_ratio(
                        contrast(simulate(env, ha, sim), simulate(env, hb, sim))
                    )
    vals["COUNT:cvd"] = str(len(v_rows(spec)))
    return vals


def bound_names(spec: str) -> list[str]:
    names = [r[0].strip("`") for r in token_rows(spec)]
    for r in c_rows(spec):
        if len(r) == 7 and r[1].endswith("Tokens"):
            names += [n for n in re.findall(r"`([a-z][a-z0-9.\-]+)`", new_of(spec, r[0]))
                      if TOKEN_NAME.match(n)]  # fmt: skip
    return list(dict.fromkeys(names))


def count_values(t: Texts) -> dict[str, str]:
    spec = t.spec
    vals: dict[str, str] = {}
    rows = ledger_rows(spec)
    disp = [disposition(r[3]) for r in rows]
    vals["COUNT:ledger"] = str(len(rows))
    vals["COUNT:ledger.applied"] = str(sum(d == "applied" for d in disp))
    vals["COUNT:ledger.amended"] = str(sum(d == "applied-as-amended" for d in disp))
    vals["COUNT:ledger.routed"] = str(sum(d == "routed" for d in disp))
    vals["COUNT:ledger.held"] = str(sum(d == "held" for d in disp))
    vals["COUNT:ledger.appliedby"] = str(sum(d == "applied by #" for d in disp))
    vals["COUNT:arows"] = str(len(c_rows(spec)))
    vals["COUNT:crows"] = str(len(contradiction_rows(spec)))
    vals["COUNT:grows"] = str(len(g_rows(spec)))
    vals["COUNT:bq"] = str(len(bq_rows(spec)))
    vals["COUNT:strings"] = str(len(s_rows(spec)))
    vals["COUNT:motion"] = str(len(m_rows(spec)))
    vals["COUNT:boards"] = str(len(board_rows(spec)))
    vals["COUNT:twins"] = str(sum("twin" in r[3] for r in board_rows(spec) if len(r) > 3))
    vals["COUNT:consumers"] = str(len(consumer_rows(spec)))
    vals["COUNT:tokens"] = str(len(bound_names(spec)))
    vals["COUNT:tokens.proposed"] = str(sum("PROPOSED" in r[0] for r in token_rows(spec)))
    for cid, (aid, _, _, _, _) in STORY_ROWS.items():
        vals[f"COUNT:stories.{cid}"] = str(len(stories_of(new_of(spec, aid))))
    vals["COUNT:mutations"] = str(len(MUTATIONS))
    return vals


def compute(t: Texts) -> dict[str, str]:
    env = t.env
    vals: dict[str, str] = {"SHA:BASE": env.base[:10]}
    for k, paths in SHA_INPUTS.items():
        vals[f"SHA:{k}"] = sha_of(env, paths)
    vals.update(pair_values(env, t.spec))
    vals.update(cvd_values(env, t.spec))
    vals.update(date_values(env))
    vals.update(count_values(t))
    return vals


# ---------------------------------------------------------------------------- placeholders


def code_spans(line: str) -> list[tuple[int, int]]:
    return [(m.start(), m.end()) for m in CODE.finditer(line)]


def fill(text: str, values: dict[str, str]) -> tuple[str, list[str]]:
    missing: list[str] = []
    out_lines = []
    for ln in text.split("\n"):
        spans = code_spans(ln)

        def ph(m: re.Match[str], spans: list[tuple[int, int]] = spans) -> str:
            if any(a <= m.start() < b for a, b in spans):
                return m[0]
            if m[1] not in values:
                missing.append(m[1])
                return m[0]
            return f"{values[m[1]]}<!--={m[1]}-->"

        out_lines.append(PLACEHOLDER.sub(ph, ln))
    text = "\n".join(out_lines)

    def refresh(m: re.Match[str]) -> str:
        return f"{values[m[2]]}<!--={m[2]}-->" if m[2] in values else m[0]

    return ANCHORED.sub(refresh, text), missing


def unfill(text: str) -> str:
    return ANCHORED.sub(r"<!--=\2-->", text)


def anchored(text: str) -> list[tuple[str, str, int]]:
    return [
        (m[1], m[2], i) for i, ln in enumerate(text.split("\n"), 1) for m in ANCHORED.finditer(ln)
    ]


def unfilled(text: str) -> list[str]:
    return [m[1] for ln in lines_of(text) for m in PLACEHOLDER.finditer(without_code(ln))]


# ---------------------------------------------------------------------------- pins

Unit = tuple[str, str, str]


def line_form(line: str) -> str:
    if re.match(r"^\s*[-*+] ", line):
        return "b"
    if re.match(r"^\s*\d+\. ", line):
        return "n"
    return "p"


def units(text: str, doc: str) -> list[Unit]:
    out: list[Unit] = []
    path: list[tuple[int, str]] = []
    seen: dict[str, int] = {}
    region, k, shape = f"{doc}:(top)#1", 0, ""
    rows: dict[str, int] = {}
    for raw in unfill(text).split("\n"):
        m = HEADING.match(raw)
        if m:
            out.append((region, "shape", shape))
            level = len(m[1])
            path = [p for p in path if p[0] < level] + [(level, pin_norm(m[2]))]
            key = f"{doc}:" + " › ".join(p[1] for p in path)
            seen[key] = seen.get(key, 0) + 1
            region, k, shape, rows = f"{key}#{seen[key]}", 0, "h", {}
            out.append((region, "heading", pin_norm(raw)))
            continue
        if not raw.strip():
            shape += "."
        elif RULE.match(raw):
            shape += "r"
            out.append((region, f"rule {shape.count('r')}", pin_norm(re.sub(r"-+", "-", raw))))
        elif raw.lstrip().startswith("|"):
            shape += "t"
            cells = split_row(raw)
            lead = pin_norm(cells[0]) or "(blank)"
            rows[lead] = rows.get(lead, 0) + 1
            loc = f"row {lead}" + (f"#{rows[lead]}" if rows[lead] > 1 else "")
            out.append((region, loc, " | ".join(pin_norm(c) for c in cells)))
        else:
            indent = len(raw) - len(raw.lstrip())
            sents = [x for x in FULL_STOP.split(raw.strip()) if x.strip()]
            shape += (f">{indent}" if indent else "") + f"{line_form(raw)}{len(sents)}"
            for x in sents:
                k += 1
                out.append((region, f"s{k}", pin_norm(x)))
    out.append((region, "shape", shape))
    return out


def all_units(spec: str, hand: str) -> list[Unit]:
    return units(spec, "spec") + units(hand, "hand")


def fresh_cite_pins(t: Texts) -> dict[str, CitePin]:
    """Every distinct cite -> the hash of its line(s) at its own number (PR 1's pins)."""
    out: dict[str, CitePin] = {}
    for key, a, b in all_cites(t):
        ls = t.env.lines(t.env.base, PATHS[key])
        if 0 < a <= b <= len(ls):
            out[label_of(key, a, b)] = (line_hash(ls[a - 1], ls[b - 1]), None)
    return out


def write_pins(us: list[Unit], cites: dict[str, CitePin]) -> str:
    head = (
        "# E32-D06 pins (every unit of the pack and the hand-off): region, location, the exact "
        f"normalised text; {len(us)} units, then {len(cites)} cite pins (`cite`, the cite, a hash "
        "of the cited line at the base, and `@n` once a move was recorded in PR 2).\n# Written by "
        "`--repin-ruled` only; `--check` reads it (never hand-edit; see the tool's G-RULED-PIN and "
        "G-HYGIENE).\n"
    )
    body = "".join("\t".join(u) + "\n" for u in us)
    for label, (h, at) in cites.items():
        tail = (
            "" if at is None else ("\t@" + (str(at[0]) if at[0] == at[1] else f"{at[0]}–{at[1]}"))
        )
        body += f"cite\t{label}\t{h}{tail}\n"
    return head + body


def parse_pins(text: str) -> list[Unit]:
    out: list[Unit] = []
    for ln in text.split("\n"):
        parts = ln.split("\t")
        if ln and not ln.startswith("#") and len(parts) == 3 and parts[0] != "cite":
            out.append((parts[0], parts[1], parts[2]))
    return out


def pin_problems(pinned: list[Unit], current: list[Unit]) -> list[str]:
    bad: list[str] = []
    old_r = list(dict.fromkeys(u[0] for u in pinned))
    new_r = list(dict.fromkeys(u[0] for u in current))
    for r in new_r:
        if r not in old_r:
            bad.append(f"region '{r[-60:]}' is unpinned (new)")
    for r in old_r:
        if r not in new_r:
            bad.append(f"region '{r[-60:]}' deleted or renamed")
    common = [r for r in new_r if r in old_r]
    if common != [r for r in old_r if r in new_r]:
        bad.append("a pinned region moved (the heading order changed)")
    for r in common:
        was = [(u[1], u[2]) for u in pinned if u[0] == r]
        now = [(u[1], u[2]) for u in current if u[0] == r]
        if was == now:
            continue
        wd = dict(was)
        what = "units moved or reordered"
        for loc, txt in now:
            if loc not in wd:
                what = f"{loc} unpinned (new): {txt[:40]!r}"
                break
            if wd[loc] != txt:
                what = f"{loc} changed: {txt[:40]!r}"
                break
        else:
            gone = [loc for loc, _ in was if loc not in dict(now)]
            if gone:
                what = f"{gone[0]} deleted"
        bad.append(f"'{r[-48:]}' {what}")
    return bad


def pins_diff_problems(t: Texts, mb: str) -> list[str]:
    """PR 2's one tolerated pack change: the pins differ from the merge-base by recorded cite moves
    alone — the same units in the same order, the same cite labels and hashes, every new `@n` the
    place where the pinned content stands at the base, and the file byte for byte what
    `--repin-ruled` writes from those (no stray line) (BQ-03)."""
    old = t.env.show(mb, PINS_REL)
    if old is None:
        return [f"{PINS_REL} is absent at the merge-base; PR 2 cannot rewrite it"]
    bad: list[str] = []
    if parse_pins(old) != parse_pins(t.pins):
        bad.append("PR 2 rewrote a pinned unit; the pins may record cite moves alone")
    oc, nc = cite_pins(old), cite_pins(t.pins)
    if list(oc) != list(nc):
        bad.append("PR 2 added, dropped or reordered a cite pin")
    for label, (h, at) in nc.items():
        if label not in oc:
            continue
        if oc[label][0] != h:
            bad.append(f"PR 2 changed the pinned content of cite {label}")
        elif at != oc[label][1]:
            m = re.fullmatch(r"([A-Z0-9]+):(\d+)(?:–(\d+))?", label)
            key = m[1] if m else ""
            ls = t.env.lines(t.env.base, PATHS.get(key, "")) if key in PATHS else []
            ok = (
                bool(at)
                and at is not None
                and 0 < at[0] <= at[1] <= len(ls)
                and (line_hash(ls[at[0] - 1], ls[at[1] - 1]) == h)
            )
            if not ok:
                bad.append(
                    f"PR 2 recorded a move for cite {label} that its content does not stand at"
                )
    if not bad and t.pins != write_pins(parse_pins(old), nc):
        bad.append(
            "PR 2's pins are not the merge-base's units with the cite moves re-serialised byte for "
            "byte (a stray or re-ordered line; `--repin-ruled` is the only writer)"
        )
    return bad


# ---------------------------------------------------------------------------- findings


@dataclass(frozen=True)
class Finding:
    level: str
    gate: str
    msg: str


def one(gate: str, problems: list[str], level: str = "FAIL") -> list[Finding]:
    return [Finding(level, gate, p) for p in problems]


ANCHOR_GATE = (
    ("COUNT:ledger", "G-LEDGER"),
    ("COUNT:arows", "G-AROW"),
    ("COUNT:tokens", "G-TOKEN"),
    ("CONTRAST:", "G-CONTRAST"), ("PAIR:", "G-CONTRAST"), ("COUNT:pairs", "G-CONTRAST"),
    ("CVD:", "G-CVD"), ("COUNT:cvd", "G-CVD"),
    ("COUNT:motion", "G-MOTION"),
    ("COUNT:strings", "G-STRINGS"),
    ("COUNT:stories", "G-STORIES"),
    ("COUNT:bq", "G-ENTRY"),
    ("DATE:", "G-VERSION"), ("SPRINT:", "G-VERSION"), ("COUNT:ahead", "G-VERSION"),
)  # fmt: skip


def anchor_gate(key: str) -> str:
    for prefix, gate in ANCHOR_GATE:
        if key.startswith(prefix):
            return gate
    return "G-HYGIENE"


def anchor_problems(t: Texts, gate: str) -> list[str]:
    bad: list[str] = []
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for value, key, ln in anchored(text):
            if anchor_gate(key) != gate:
                continue
            want = t.values.get(key)
            if want is None:
                bad.append(f"{doc}:{ln} anchors `{key}`, which the tool does not compute")
            elif want != value:
                bad.append(f"{doc}:{ln} `{key}` reads {value}; the tool derives {want}")
        bad += residue_problems(doc, text, gate)
    return bad


def residue_problems(doc: str, text: str, gate: str) -> list[str]:
    """In a table cell nothing stands in front of an anchored value but the cell's start, the end of
    the previous anchor or a bare `/` separator: the tail of an earlier fill is a FAIL of the
    value's gate, not a WARN (the three Reading cells of §11 once read a value three times)."""
    bad: list[str] = []
    for i, ln in enumerate(text.split("\n"), 1):
        if not ln.lstrip().startswith("|"):
            continue
        for cell in split_row(ln):
            pos = 0
            for m in ANCHORED.finditer(cell):
                if anchor_gate(m[2]) == gate and cell[pos : m.start()].strip() not in ("", "/"):
                    bad.append(
                        f"{doc}:{i} `{m[2]}`: the cell carries text in front of its value "
                        f"({cell[pos : m.start()].strip()[:40]!r}); re-fill the cell"
                    )
                pos = m.end()
    return bad


# ---------------------------------------------------------------------------- the gates


def g_ledger(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-LEDGER")
    rows = ledger_rows(t.spec)
    ids = [r[0] for r in rows]
    if ids != [f"L-{i}" for i in range(1, len(ids) + 1)]:
        bad.append("the ledger's rows are not L-1 ... L-n in order")
    have = {r[0] for r in c_rows(t.spec)}
    for r in rows:
        if len(r) != 5:
            bad.append(f"{r[0]}: {len(r)} cells, not 5")
            continue
        m = re.fullmatch(r"`([^`]+)` \(([A-Z0-9]+):(\d+)\)", r[1])
        if not m or m[2] not in PATHS:
            bad.append(f"{r[0]}: the row of record is not `needle` (KEY:line)")
            continue
        if m[1] not in cite_line(t, m[2], int(m[3])):
            bad.append(f"{r[0]}: {m[2]}:{m[3]} does not carry `{m[1]}` at the base")
        d = disposition(r[3])
        if not d:
            bad.append(f"{r[0]}: disposition {r[3][:30]!r} is not in the ruled set")
        if d == "applied by #":
            pm = re.match(r'applied by #(\d+): "([^"]+)"', r[3])
            fm = FIELD.search(r[2])
            if not pm or not fm:
                bad.append(
                    f'{r[0]}: an applied-by row needs `applied by #N: "words"` and a `15`/`14` cite'
                )
                continue
            rel = CAT_REL if fm[1] == "15" else SCR_REL
            if f"(#{pm[1]})" not in t.env.log_subjects(rel):
                bad.append(f"{r[0]}: no merged PR #{pm[1]} in {rel}'s history at {HEAD_REF}")
            if pm[2] not in cite_line(t, fm[1], int(fm[2])):
                bad.append(f"{r[0]}: `{fm[1]}`:{fm[2]} does not carry {pm[2]!r} at the base")
        here = a_ids(r[4])
        if r[4] != "—" and not here:
            bad.append(f"{r[0]}: the Here cell is neither — nor A-ids")
        for a in here:
            if a not in have:
                bad.append(f"{r[0]}: carries {a}, which §C lacks")
    return one("G-LEDGER", bad)


def g_arow(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-AROW")
    rows = c_rows(t.spec)
    if [r[0] for r in rows] != [f"A-{i}" for i in range(1, len(rows) + 1)]:
        bad.append("§C's rows are not A-1 ... A-n in order")
    for r in rows:
        if len(r) != 7:
            bad.append(f"{r[0]} has {len(r)} cells, not 7")
            continue
        m = FIELD.fullmatch(r[2])
        if not m:
            bad.append(f"{r[0]}: the Field cell is not `15`:n or `14`:n")
            continue
        ls = t.env.lines(t.env.base, CAT_REL if m[1] == "15" else SCR_REL)
        n = int(m[2])
        line = ls[n - 1] if 0 < n <= len(ls) else None
        new = new_of(t.spec, r[0])
        if r[3] == "replace":
            if line is None or unescape(r[4]) != line:
                bad.append(f"{r[0]}: Old is not `{m[1]}`:{n} at the base, byte for byte")
            if new == (line or ""):
                bad.append(f"{r[0]}: New equals Old")
        elif r[3] == "insert after":
            if r[4] != "—":
                bad.append(f"{r[0]}: an insert carries an Old cell")
        else:
            bad.append(f"{r[0]}: op {r[3]!r} is neither replace nor insert after")
        for ln in new.split("<br>"):
            if not ln.startswith("- **"):
                bad.append(f"{r[0]}: a New line is not an entry bullet")
    export = a_rows_export(t.spec, t.env.at_base(CAT_REL), t.env.at_base(SCR_REL))
    for rel in (CAT_REL, SCR_REL):
        _, probs = apply_rows(t.env.at_base(rel), [x for x in export if x["file"] == rel])
        bad += probs
    return one("G-AROW", bad)


def g_token(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-TOKEN")
    shipped = shipped_names(t.env)
    for name in bound_names(t.spec):
        if name.startswith("color."):
            miss = [th for th in THEMES if not resolve(t.env, th, name)]
            if miss:
                bad.append(f"`{name}` does not resolve to a hex in {', '.join(miss)}")
        elif name not in shipped:
            bad.append(f"`{name}` is not a shipped token")
    for r in token_rows(t.spec):
        if "PROPOSED" in r[0]:
            bad.append(f"{r[0]}: a token proposal; the pack rules zero (BQ-10)")
    for fg, bg in re.findall(r'fg: "([^"]+)", bg: "([^"]+)"', sec(t.spec, "## 7.")):
        for name in (fg, bg):
            if not all(resolve(t.env, th, name) for th in THEMES):
                bad.append(f"the PROPOSED PAIRS row names `{name}`, which does not resolve")
    return one("G-TOKEN", bad)


def g_contrast(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-CONTRAST")
    reg = pairs_registered(t.env)
    for r in p_rows(t.spec):
        if len(r) != 10:
            bad.append(f"{r[0]} has {len(r)} cells, not 10")
            continue
        fg, bg, kind, status = r[2].strip("`"), r[3].strip("`"), r[4], r[9]
        pid = r[0].lower().replace("-", "")
        # the whole cell against the computed value, not the anchored tail alone
        for th, cell in zip(THEMES, r[5:8]):
            want = t.values.get(f"CONTRAST:{pid}.{th}")
            if want is not None and strip_anchors(cell) != f"{want}:1":
                bad.append(f"{r[0]}: the {th} cell reads {strip_anchors(cell)!r}, not {want}:1")
        want_reading = t.values.get(f"PAIR:{pid}")
        if want_reading is not None and strip_anchors(r[8]) != want_reading:
            bad.append(
                f"{r[0]}: the Reading cell reads {strip_anchors(r[8])!r}, not {want_reading}"
            )
        if kind not in BARS:
            bad.append(f"{r[0]}: kind {kind!r} is neither text nor non-text")
        if status == "registered" and (fg, bg) not in reg:
            bad.append(f"{r[0]}: {PAIRS_REL} has no row for this fg / bg")
        if status == "PROPOSED" and (fg, bg) in reg:
            bad.append(f"{r[0]}: marked PROPOSED but {PAIRS_REL} registers it")
        if status not in ("registered", "PROPOSED"):
            bad.append(f"{r[0]}: PAIRS column {status!r}")
        for th in THEMES:
            a, b = resolve(t.env, th, fg), resolve(t.env, th, bg)
            if not (a and b):
                bad.append(f"{r[0]}: a token does not resolve in {th}")
            elif status != "PROPOSED" and kind in BARS and contrast(a, b) < BARS[kind]:
                bad.append(f"{r[0]}: below {BARS[kind]} in {th}")
    return one("G-CONTRAST", bad)


def g_cvd(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-CVD")
    mats = cvd_matrices(t.env)
    if (
        len(mats.get("deut", ())) != 9
        or len(mats.get("prot", ())) != 9
        or len(mats.get("grey", ())) != 3
    ):
        bad.append(f"{CVD_REL} at the base: the matrices or the greyscale weights were not parsed")
    ids = [r[0].lower().replace("-", "") for r in v_rows(t.spec)]
    if ids != list(V_PAIRS):
        bad.append(f"§11's V-rows are {ids}; the tool computes {list(V_PAIRS)}")
    return one("G-CVD", bad)


def g_motion(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-MOTION")
    shipped = shipped_names(t.env)
    for r in m_rows(t.spec):
        if len(r) != 9:
            bad.append(f"{r[0]} has {len(r)} cells, not 9")
            continue
        _, transition, element, prop, safe, reduce, tokens, carrier, _ = r
        cut = prop == "`none`"
        names = re.findall(r"`(motion\.[a-z.]+)`", tokens)
        if cut:
            if tokens != "—" or "a cut" not in safe:
                bad.append(f"{r[0]}: a cut carries a token or no cut in its motion-safe cell")
        else:
            if not any(n.startswith("motion.duration.") for n in names) or not any(
                n.startswith("motion.easing.") for n in names
            ):
                bad.append(f"{r[0]}: an animated row needs a shipped duration and easing primitive")
            for n in names:
                if n not in shipped:
                    bad.append(f"{r[0]}: `{n}` is not a shipped primitive")
        if "`none`" not in reduce:
            bad.append(f"{r[0]}: the reduce cell is not `none` (E05-D03 §3)")
        if carrier in ("", "—"):
            bad.append(f"{r[0]}: no non-motion carrier")
        if any(w.lower() in f"{transition} {element}".lower() for w in SAFETY_WORDS) and not cut:
            bad.append(f"{r[0]}: a safety signal animates (the rule row forbids it)")
    rule = sec(t.spec, "## 8.")
    if "CMP-158 never animates" not in rule or "never animated" not in rule:
        bad.append(
            "§8's rule row does not state that CMP-158 and the `unprotected` banner never animate"
        )
    return one("G-MOTION", bad)


def g_strings(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-STRINGS")
    for r in s_rows(t.spec):
        if len(r) != 5:
            bad.append(f"{r[0]} has {len(r)} cells, not 5")
            continue
        cites = cites_in(r[4])
        quotes = re.findall(r'"([^"]+)"', unescape(r[3]))
        if not cites or not quotes:
            bad.append(f"{r[0]}: no source cite or no quoted sentence")
            continue
        key, a, _ = cites[0]
        src = unescape(cite_line(t, key, a))
        for q in quotes:
            if q not in src:
                bad.append(f"{r[0]}: {q[:50]!r} is not on {key}:{a} at the base, verbatim")
    return one("G-STRINGS", bad)


def g_stories(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-STORIES")
    for cid, (aid, n, parent, rule, extra) in STORY_ROWS.items():
        new = stories_of(new_of(t.spec, aid))
        base = stories_of(cite_line(t, "15", n))
        want = list(extra)
        if parent:
            want += parent_stories(t, *parent)
            if not parent_stories(t, *parent):
                bad.append(
                    f"CMP-{cid}: the parent's story row ({parent[0]}:{parent[1]}) was not read"
                )
        if rule == "superset":
            for s in base + want:
                if s not in new:
                    bad.append(f"CMP-{cid}: {aid} drops {s}")
        elif set(new) != set(want) or len(new) != len(want):
            bad.append(f"CMP-{cid}: {aid}'s list is not the parent's list")
        if len(set(new)) != len(new):
            bad.append(f"CMP-{cid}: {aid} repeats a story")
    return one("G-STORIES", bad)


def checklist_labels(t: Texts) -> tuple[str, ...]:
    """`16` §11.4's checklist lines, in order (the block's fenced example holds a heading, so the
    section is cut by hand at the next unfenced heading)."""
    ls = t.env.lines(t.env.base, PATHS["16"])
    start = next((i for i, ln in enumerate(ls) if ln.startswith("### 11.4 ")), None)
    if start is None:
        return ()
    out: list[str] = []
    fenced = False
    for ln in ls[start + 1 :]:
        if ln.startswith("```"):
            fenced = not fenced
            continue
        if not fenced and re.match(r"^#{1,3} ", ln):
            break
        m = re.match(r"^- \[ \] \*\*([^*]+?)\*\*", ln)
        if m:
            out.append(m[1])
    return tuple(out)


def derived_components(spec: str) -> list[tuple[str, str, str]]:
    """(component, ledger rows, A-rows) per §C target, in §C order."""
    carriers: dict[str, list[str]] = {}
    for r in ledger_rows(spec):
        for a in a_ids(r[4]) if len(r) == 5 else []:
            carriers.setdefault(a, []).append(r[0])
    out: list[tuple[str, str, str]] = []
    comps: dict[str, list[str]] = {}
    for r in c_rows(spec):
        comps.setdefault(r[1].split(" ")[0], []).append(r[0])
    for comp, aids in comps.items():
        ls = sorted({l for a in aids for l in carriers.get(a, [])}, key=lambda x: int(x[2:]))
        arange = (
            aids[0]
            if len(aids) == 1
            else (f"{aids[0]}, {aids[1]}" if len(aids) == 2 else f"{aids[0]} … {aids[-1]}")
        )
        out.append((comp, ", ".join(ls) or "—", arange))
    return out


def g_entry(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-ENTRY")
    declared = set(BASE_FIELDS) | set(OPTIONAL_FIELDS) | set(LEAD_FIELDS)
    head = cite_line(t, "15", 18)
    for f in OPTIONAL_FIELDS:
        if f"**{f}**" not in head:
            bad.append(f"`15`:18 at the base does not declare the optional field {f}")
    for r in c_rows(t.spec):
        if len(r) != 7 or not r[2].startswith("`15`"):
            continue  # the `14` lines keep the screen template's fields
        for ln in new_of(t.spec, r[0]).split("<br>"):
            m = re.match(r"- \*\*([^*]+?)\*\*", ln)
            if m and m[1].rstrip(":") not in declared and not m[1].startswith("Design ("):
                bad.append(
                    f"{r[0]}: the field **{m[1]}** is declared neither in §0.1 nor as a lead-in"
                )
    want = checklist_labels(t)
    got = tuple(re.findall(r"^- \[[ x]\] \*\*([^*]+?)\*\*", t.hand, re.MULTILINE))
    if not want:
        bad.append("`16` §11.4's checklist labels were not read at the base")
    elif got != want:
        bad.append(
            f"the hand-off's checklist lines are not `16` §11.4's in order ({len(got)} vs {len(want)})"
        )
    table = [tuple(r) for r in table_after(sec(t.hand, "## The A-row ledger"), "Component")]
    if table != derived_components(t.spec):
        bad.append(
            "the hand-off's ledger-by-component table differs from the derivation from §2 and §C"
        )
    bq = bq_rows(t.spec)
    if [r[0] for r in bq] != [f"BQ-{i:02d}" for i in range(1, 21)]:
        bad.append("§R does not list BQ-01 ... BQ-20 in order")
    for r in bq:
        if len(r) != 3 or r[2] != "RULED":
            bad.append(f"{r[0]}: status {r[2] if len(r) > 2 else '?'!r}, not RULED")
    if RULING_ID not in sec(t.spec, "## R."):
        bad.append("§R does not name the ruling of record")
    return one("G-ENTRY", bad)


def g_version(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-VERSION")
    warn: list[str] = []
    env = t.env
    head_cal = env.show(HEAD_REF, CAL_REL)
    if head_cal is None:
        bad.append(f"{HEAD_REF} does not resolve or lacks {CAL_REL}; fetch origin first")
    elif calendar_values(head_cal) != calendar_values(env.at_base(CAL_REL)):
        bad.append(f"the calendar's sprint-1 start or length changed at {HEAD_REF}")
    head_j = env.show(HEAD_REF, E32J_REL)
    if head_j is not None:
        a, b = sprint_fields(env.at_base(E32J_REL)), sprint_fields(head_j)
        for k in SPRINT_KEYS.values():
            if a.get(k) != b.get(k):
                bad.append(
                    f"the sprint field of {k} changed at {HEAD_REF} ({a.get(k)} → {b.get(k)})"
                )
    for key, a0, b0 in all_cites(t):
        rel = PATHS[key]
        if env.show(HEAD_REF, rel) == env.show(env.base, rel):
            continue
        a2, b2, status = resolve_cite(t, key, a0, b0)
        if status in ("range", "unpinned", "gone"):
            continue  # G-HYGIENE's finding
        ls = env.lines(env.base, rel)
        h = line_hash(ls[a2 - 1], ls[b2 - 1])
        hl = env.lines(HEAD_REF, rel)
        label = label_of(key, a0, b0)
        if 0 < a2 <= b2 <= len(hl) and line_hash(hl[a2 - 1], hl[b2 - 1]) == h:
            continue
        # re-find inside the cited entry alone (A-24's "unit, visual, axe." stands in many entries)
        at = found_in_entry(env, HEAD_REF, rel, h, b2 - a2, heading_before(ls, a2))
        if len(at) == 1:
            warn.append(
                f"cite {label} stands at :{at[0]} at {HEAD_REF} (moved; re-pin at the next edit)"
            )
        elif at:
            bad.append(
                f"cite {label}: its content stands {len(at)} times in its entry at {HEAD_REF}"
            )
        else:
            bad.append(
                f"cite {label}: its content stands nowhere in its entry at {HEAD_REF} (edited)"
            )
    return one("G-VERSION", bad) + one("G-VERSION", warn, "WARN")


def mutation_paragraph(spec: str) -> str:
    block = sec(spec, "## 22.")
    return next((ln for ln in lines_of(block) if "M-1 " in ln), "")


def g_hygiene(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-HYGIENE")
    for doc, text in (("spec", t.spec), ("hand", t.hand)):
        for key in unfilled(text):
            bad.append(f"{doc}: the placeholder `{key}` is unfilled (run --check --fill)")
        for i, ln in enumerate(lines_of(text), 1):
            if "{{" in ln:
                bad.append(f"{doc}:{i} carries `{{{{` (a placeholder outside the fill, or a stray)")
            if CLOSING.search(ln):
                bad.append(f"{doc}:{i} carries a closing keyword (PR 3 alone closes #{ISSUE})")
            if LOCAL_PATH.search(ln):
                bad.append(f"{doc}:{i} carries a local filesystem path or a notes-folder name")
            if AGENT_NAME.search(ln):
                bad.append(f"{doc}:{i} carries an agent name")
            if URL_OR_HOST.search(ln):
                bad.append(f"{doc}:{i} carries a URL, a host or a Penpot id parameter")
    fails, warns = cite_problems(t)
    bad += fails
    # the tree against the merge-base
    if t.changed is None:
        bad.append("cannot list the changed paths (`git diff` / `git status` failed)")
    else:
        other = [p for p in t.changed if p not in OWN_PATHS]
        pr2 = bool({CAT_REL, SCR_REL} & set(t.changed))
        if not pr2:
            for p in other:
                bad.append(f"PR 1 changes {p}, outside the pack's four files")
        else:
            for p in t.changed:
                if p in PACK_TEXTS:
                    bad.append(
                        f"PR 2 changes {p}: the pack is byte-identical to the merged PR 1 (BQ-03)"
                    )
                elif p not in OWN_PATHS and p not in (CAT_REL, SCR_REL):
                    bad.append(f"PR 2 changes {p}, outside `15`, `14` and the pins")
            rows = a_rows_export(t.spec, t.env.at_base(CAT_REL), t.env.at_base(SCR_REL))
            want15, b15 = apply_rows(
                t.env.at_base(CAT_REL), [r for r in rows if r["file"] == CAT_REL]
            )
            want14, b14 = apply_rows(
                t.env.at_base(SCR_REL), [r for r in rows if r["file"] == SCR_REL]
            )
            bad += b15 + b14
            if t.cat15 != want15:
                bad.append("PR 2: `15` is not the base with §C applied exactly (an extra byte)")
            if t.cat14 != want14:
                bad.append("PR 2: `14` is not the base with §C's `14` rows applied exactly")
            if PINS_REL in t.changed:
                bad += pins_diff_problems(t, t.env.base)
    para = mutation_paragraph(t.spec)
    gates_named = re.findall(r"\*\*(G-[A-Z-]+)\*\*", para)
    if len(re.findall(r"\bM-\d+\b", para)) != len(MUTATIONS):
        bad.append(
            f"§22 lists {len(re.findall(r'\\bM-\\d+\\b', para))} mutations; the tool has {len(MUTATIONS)}"
        )
    if gates_named != [g.__name__.upper().replace("G_", "G-") for g in GATES] + ["G-RULED-PIN"]:
        bad.append("§22 does not name each gate once, in the tool's order")
    return one("G-HYGIENE", bad) + one("G-HYGIENE", warns, "WARN")


def g_pins(t: Texts) -> list[Finding]:
    pinned = parse_pins(t.pins)
    if not pinned:
        return one("G-RULED-PIN", [f"{PINS_REL} is empty or missing (run --repin-ruled)"])
    return one("G-RULED-PIN", pin_problems(pinned, all_units(t.spec, t.hand)))


GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_ledger, g_arow, g_token, g_contrast, g_cvd, g_motion, g_strings, g_stories, g_entry,
    g_version, g_hygiene,
)  # fmt: skip


def audit(t: Texts, timings: dict[str, float] | None = None) -> list[Finding]:
    found: list[Finding] = []
    for g in GATES:
        t0 = time.perf_counter()
        found += g(t)
        if timings is not None:
            timings[g.__name__.upper().replace("G_", "G-")] = time.perf_counter() - t0
    t0 = time.perf_counter()
    pins = g_pins(t)
    if timings is not None:
        timings["G-RULED-PIN"] = time.perf_counter() - t0
    if any(f.level == "FAIL" for f in found):
        pins = [replace(f, level="NOTE") for f in pins]
    return found + pins


# ---------------------------------------------------------------------------- §C export and PR 2


def a_rows_export(spec: str, base15: str, base14: str) -> list[dict[str, object]]:
    """§C as data for PR 2: anchors dropped, escapes undone; each row carries its file, its entry
    heading and its anchor line at the base so PR 2 re-points by content."""
    out: list[dict[str, object]] = []
    for r in c_rows(spec):
        if len(r) != 7:
            continue
        m = FIELD.fullmatch(r[2])
        if not m:
            continue
        rel = CAT_REL if m[1] == "15" else SCR_REL
        lines = lines_of(base15 if rel == CAT_REL else base14)
        n = int(m[2])
        anchor = lines[n - 1] if 0 < n <= len(lines) else ""
        head = next((lines[i] for i in range(min(n, len(lines)) - 1, -1, -1)
                     if lines[i].startswith("### ")), "")  # fmt: skip
        out.append(
            {
                "id": r[0],
                "target": r[1],
                "file": rel,
                "line": n,
                "entry": head,
                "anchor": anchor,
                "op": r[3],
                "old": [] if r[4] == "—" else [unescape(r[4])],
                "new": strip_anchors(unescape(r[5])).split("<br>"),
                "from": r[6],
            }
        )
    return out


def apply_rows(text: str, rows: list[dict[str, object]]) -> tuple[str, list[str]]:
    """`text` with every row applied, re-pointed by content: its entry heading, then its anchor
    line inside that entry, each found once; (result, problems)."""
    lines = lines_of(text)
    bad: list[str] = []
    plan: list[tuple[int, int, dict[str, object]]] = []
    for k, r in enumerate(rows):
        heads = [i for i, ln in enumerate(lines) if ln == r["entry"]]
        if len(heads) != 1:
            bad.append(f"{r['id']}: its entry heading stands {len(heads)} times")
            continue
        end = next(
            (i for i in range(heads[0] + 1, len(lines)) if lines[i].startswith("#")), len(lines)
        )
        hits = [i for i in range(heads[0], end) if lines[i] == r["anchor"]]
        if len(hits) != 1:
            bad.append(f"{r['id']}: its anchor stands {len(hits)} times in its entry")
            continue
        plan.append((hits[0], k, r))
    for i, _, r in sorted(plan, key=lambda p: (-p[0], -p[1])):
        new = [str(x) for x in r["new"]] if isinstance(r["new"], list) else []
        if str(r["op"]).startswith("replace"):
            lines[i : i + 1] = new
        else:
            lines[i + 1 : i + 1] = new
    return "\n".join(lines), bad


# ---------------------------------------------------------------------------- load, mutations, self-test


def load() -> Texts:
    base = merge_base()
    if base is None:
        raise SystemExit(f"`git merge-base HEAD {HEAD_REF}` does not resolve; fetch origin first")
    env = Env(base, {})
    pins = read_raw(PINS_REL) if (ROOT / PINS_REL).exists() else ""
    t = Texts(env, read_raw(SPEC_REL), read_raw(HAND_REL), pins, read_raw(CAT_REL),
              read_raw(SCR_REL), changed_paths(base), {})  # fmt: skip
    return replace(t, values=compute(t))


@dataclass(frozen=True)
class Mutation:
    gate: str
    what: str
    apply: Callable[[Texts], Texts]


def flex(old: str) -> re.Pattern[str]:
    return re.compile(r"\s+".join(re.escape(p) for p in old.split(" ") if p != ""))


def subst(old: str, new: str, doc: str = "spec") -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        text = getattr(t, doc)
        m = flex(old).search(text)
        if not m:
            raise SystemExit(f"self-test: {doc} lacks {old[:60]!r}")
        return replace(t, **{doc: text[: m.start()] + new + text[m.end() :]})

    return f


def anchor_edit(key: str, new_value: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        rx = re.compile(rf"([^\s<|]+)<!--={re.escape(key)}-->")
        m = rx.search(t.spec)
        if not m:
            raise SystemExit(f"self-test: the spec has no anchored {key}")
        return replace(
            t, spec=t.spec[: m.start()] + f"{new_value}<!--={key}-->" + t.spec[m.end() :]
        )

    return f


def with_text(t: Texts, rev: str, rel: str, text: str) -> Texts:
    """`t` with `rel` at `rev` replaced in a copy of the env (never the shared one)."""
    stale = re.compile(rf"(?:show|lines|hidx):{re.escape(rev)}:{re.escape(rel)}(?::\d+)?")
    memo = {k: v for k, v in t.env.memo.items() if not stale.fullmatch(k)}
    memo[f"show:{rev}:{rel}"] = text
    return replace(t, env=Env(t.env.base, memo))


def head_sprint_days(t: Texts) -> Texts:
    src = t.env.at_base(CAL_REL)
    return with_text(
        t,
        HEAD_REF,
        CAL_REL,
        re.sub(
            r"^SPRINT_DAYS = (\d+)",
            lambda m: f"SPRINT_DAYS = {int(m[1]) + 1}",
            src,
            count=1,
            flags=re.MULTILINE,
        ),
    )


def pr2_texts(t: Texts, extra15: str = "", extra_changed: tuple[str, ...] = ()) -> Texts:
    rows = a_rows_export(t.spec, t.env.at_base(CAT_REL), t.env.at_base(SCR_REL))
    c15, _ = apply_rows(t.env.at_base(CAT_REL), [r for r in rows if r["file"] == CAT_REL])
    c14, _ = apply_rows(t.env.at_base(SCR_REL), [r for r in rows if r["file"] == SCR_REL])
    return replace(t, cat15=c15 + extra15, cat14=c14, changed=[CAT_REL, SCR_REL, *extra_changed])


def pr2_moved(
    t: Texts,
    unit_edit: bool = False,
    stray: bool = False,
    wrong_at: bool = False,
    hash_edit: str = "",
    drop: str = "",
) -> Texts:
    """PR 2 after a rebase that moved every D02 line down by one: the pins carry `@n` moves for the
    D02 cites (a `--repin-ruled` rewrite); the merge-base holds PR 1's pins. The flags plant one
    defect each: a unit edit, a stray line, one `@n` off by one, one cite hash altered, one cite
    pin dropped."""
    shifted = "added line\n" + t.env.at_base(PATHS["D02"])
    t2 = with_text(t, t.env.base, PATHS["D02"], shifted)
    t2 = with_text(t2, HEAD_REF, PATHS["D02"], shifted)  # the rebase's new base is the head
    memo = dict(t2.env.memo)
    memo[f"show:{t.env.base}:{PINS_REL}"] = t.pins
    t2 = replace(t2, env=Env(t.env.base, memo))
    cites = cite_pins(t.pins)
    moved = {}
    first_d02 = True
    for label, (h, at) in cites.items():
        m = re.fullmatch(r"D02:(\d+)(?:–(\d+))?", label)
        if m:
            a = int(m[1]) + 1
            b = (int(m[2]) if m[2] else int(m[1])) + 1
            if wrong_at and first_d02:
                a, b, first_d02 = a + 1, b + 1, False
            moved[label] = (h, (a, b))
        elif label == hash_edit:
            moved[label] = (h[::-1] if h[::-1] != h else "0" * len(h), at)
        elif label == drop:
            continue
        else:
            moved[label] = (h, at)
    us = parse_pins(t.pins)
    if unit_edit and us:
        us[0] = (us[0][0], us[0][1], us[0][2] + " x")
    pins = write_pins(us, moved) + ("# a stray line\n" if stray else "")
    return replace(pr2_texts(t2, extra_changed=(PINS_REL,)), pins=pins)


M = Mutation
# grouped by gate, in the tool's order; §22 lists them under the same numbers
MUTATIONS: tuple[Mutation, ...] = (
    M("G-LEDGER", "swap a ledger row's needle for one its cited line does not carry",
      subst("| L-1 | `A-16` (D02:937)", "| L-1 | `A-17` (D02:937)")),
    M("G-LEDGER", "change an applied-by row's PR number to one the file's history lacks",
      subst("applied by #4198:", "applied by #4199:")),
    M("G-AROW", "misquote A-3's Old cell by one letter",
      subst("no hover, no dismiss, no loading). |", "no hover, no dismis, no loading). |")),
    M("G-TOKEN", "bind a §7 row to a token name no theme resolves",
      subst("| `color.status.info.subtle` | the note's fill", "| `color.status.info.subtl` | the note's fill")),
    M("G-CONTRAST", "type a ratio by hand in §11", anchor_edit("CONTRAST:p1.dark", "9.99")),
    M("G-CVD", "alter a simulated value in §11's V-table", anchor_edit("CVD:v1.grey.dark", "9.99")),
    M("G-MOTION", "give the pending → applied row a duration token (a safety signal animated)",
      subst("the same cut | — | glyph + word + role",
            "the same cut | `motion.duration.fast` · `motion.easing.standard` | glyph + word + role")),
    M("G-STRINGS", "alter one word of S-1 in §4",
      subst("`14` SCR-064 Validation | \"Every position keeps a native stop — you can move it, not delete it.\"",
            "`14` SCR-064 Validation | \"Every position keeps a native stop — you can move it, not remove it.\"")),
    M("G-STORIES", "drop HA-6's ProfileDefault from A-15",
      subst("LadderNotSplittable, ProfileDefault, RoundedTowardCaption (E32-D03 HA-6).",
            "LadderNotSplittable, RoundedTowardCaption (E32-D03 HA-6).")),
    M("G-ENTRY", "add an undeclared field bullet to A-8",
      subst("the rule row).<br>- **Usage (E32-D06)**: the native-SL affordance pattern",
            "the rule row).<br>- **Composition**: a note.<br>- **Usage (E32-D06)**: the native-SL affordance pattern")),
    M("G-VERSION", "move the calendar's sprint length by one day at origin/main", head_sprint_days),
    M("G-HYGIENE", "write a closing keyword against #926 in §23",
      subst("The closing line rides on PR 3 alone", "Closes #926")),
    M("G-HYGIENE", "leave a `{{` placeholder inside a code span of §0",
      subst("**Nothing here is built or published.**", "**Nothing here is built or published.** (`{{SHA:BASE}}`)")),
    M("G-HYGIENE", "simulate PR 2 with one byte more than §C in `15`", lambda t: pr2_texts(t, "x")),
    M("G-HYGIENE", "simulate PR 2 with the spec changed beside the pins",
      lambda t: pr2_texts(t, extra_changed=(SPEC_REL, PINS_REL))),
    M("G-HYGIENE", "simulate PR 2 with a pins rewrite that alters a unit, not a cite move",
      lambda t: pr2_moved(t, unit_edit=True)),
    M("G-HYGIENE", "simulate PR 2 with a stray line in the pins beside the recorded moves",
      lambda t: pr2_moved(t, stray=True)),
    M("G-HYGIENE", "simulate PR 2 with a recorded @n the cite's content does not stand at",
      lambda t: pr2_moved(t, wrong_at=True)),
    M("G-HYGIENE", "simulate PR 2 with one cite pin's hash changed",
      lambda t: pr2_moved(t, hash_edit="CONST:443–444")),
    M("G-HYGIENE", "simulate PR 2 with one cite pin dropped",
      lambda t: pr2_moved(t, drop="CONST:164–166")),
    M("G-RULED-PIN", "re-word one pinned sentence of §12",
      subst("The control is E32-T01's single submission choke point (#931).",
            "The control is E32-T01's one submission choke point (#931).")),
)  # fmt: skip

NEGATIVES: tuple[tuple[str, Callable[[Texts], Texts]], ...] = (
    ("N-1 PR 2 with §C applied exactly", lambda t: pr2_texts(t)),
    ("N-2 PR 2 after a rebase moved D02, the pins recording the moves", lambda t: pr2_moved(t)),
)


def digest(t: Texts) -> str:
    return hashlib.sha256((t.spec + "\0" + t.hand + "\0" + t.pins).encode()).hexdigest()


def ascii_line(s: str) -> str:
    for a, b in (("→", "->"), ("›", ">"), ("…", "..."), ("—", "-"), ("–", "-"), ("×", "x"),
                 ("§", "S"), ("·", "|"), ("≤", "<="), ("≥", ">=")):  # fmt: skip
        s = s.replace(a, b)
    return s.encode("ascii", "replace").decode()[:100]


def selftest() -> tuple[bool, list[str]]:
    t0 = time.perf_counter()
    base = replace(load(), changed=[SPEC_REL])  # the PR-1 view; N-1 / N-2 plant the PR-2 one
    disk = [hashlib.sha256(read_raw(r).encode()).hexdigest() for r in OWN_PATHS]
    before = digest(base)
    base_found = [f for f in audit(base) if f.level == "FAIL"]
    out = [f"self-test: baseline {len(base_found)} FAIL"]
    ok = not base_found
    for f in base_found:
        out.append(ascii_line(f"  baseline {f.gate}: {f.msg}"))
    for i, m in enumerate(MUTATIONS, 1):
        fails = [f for f in audit(m.apply(base)) if f.level == "FAIL"]
        gates = sorted({f.gate for f in fails})
        good = bool(fails) and gates == [m.gate]
        ok &= good
        out.append(
            ascii_line(
                f"{'ok  ' if good else 'FAIL'} M-{i} {m.gate}: {m.what} -> {', '.join(gates) or 'none'}"
            )
        )
    for name, scenario in NEGATIVES:
        extra = [f for f in audit(scenario(base)) if f.level in ("FAIL", "WARN")]
        ok &= not extra
        shown = ", ".join(sorted({f"{f.gate} ({f.level})" for f in extra})) or "none"
        out.append(ascii_line(f"{'ok  ' if not extra else 'FAIL'} {name} -> {shown}"))
    restored = digest(base) == before and disk == [
        hashlib.sha256(read_raw(r).encode()).hexdigest() for r in OWN_PATHS
    ]
    ok &= restored
    out.append(
        f"self-test: {len(MUTATIONS)} mutations, {len(NEGATIVES)} negatives, texts restored: {'yes' if restored else 'NO'}"
    )
    out.append(f"self-test: {'PASS' if ok else 'FAIL'} in {time.perf_counter() - t0:.1f} s")
    return ok, out


def render(found: list[Finding]) -> list[str]:
    return [ascii_line(f"{f.level} {f.gate}: {f.msg}") for f in found]


def pr2_mode(t: Texts) -> bool:
    return (
        bool(t.changed)
        and bool({CAT_REL, SCR_REL} & set(t.changed or []))
        and not any(p in PACK_TEXTS for p in t.changed or [])
    )


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0] if __doc__ else "")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="the default mode")
    g.add_argument("--self-test", action="store_true")
    g.add_argument("--repin-ruled", action="store_true")
    g.add_argument("--a-rows", action="store_true")
    ap.add_argument("--json", action="store_true", help="--check's dump; alone it implies --check")
    ap.add_argument("--fill", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        ok, lines = selftest()
        print("\n".join(lines))
        return 0 if ok else 1
    t = load()
    if a.a_rows:
        print(
            json.dumps(
                a_rows_export(t.spec, t.env.at_base(CAT_REL), t.env.at_base(SCR_REL)),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if a.repin_ruled:
        for doc, text in (("spec", t.spec), ("hand", t.hand)):
            if unfilled(text):
                print(f"refused: {doc} has an unfilled placeholder (run --check --fill)")
                return 1
        other = [
            f
            for f in audit(t)
            if f.level == "FAIL" and f.gate != "G-RULED-PIN" and not f.msg.startswith("cite ")
        ]
        if other:
            print(f"refused: {len(other)} FAIL outside the pins (first: {other[0].gate}); fix them")
            return 1
        if pr2_mode(t):
            # PR 2: the units stand; record the cite moves found by content (BQ-03)
            pins = cite_pins(t.pins)
            for key, a0, b0 in all_cites(t):
                a2, b2, status = resolve_cite(t, key, a0, b0)
                if status == "moved":
                    pins[label_of(key, a0, b0)] = (pins[label_of(key, a0, b0)][0], (a2, b2))
            write_text(PINS_REL, write_pins(parse_pins(t.pins), pins))
            print(f"wrote {PINS_REL} (PR 2: cite moves recorded, units untouched)")
            return 0
        moved = [
            label_of(k, x, y) for k, x, y in all_cites(t) if resolve_cite(t, k, x, y)[2] == "moved"
        ]
        if moved:
            print(
                f"refused: {len(moved)} cite(s) moved at the base; re-point them by content first ({moved[0]} ...)"
            )
            return 1
        write_text(PINS_REL, write_pins(all_units(t.spec, t.hand), fresh_cite_pins(t)))
        print(f"wrote {PINS_REL}")
        return 0
    if a.fill:
        spec, miss1 = fill(t.spec, t.values)
        hand, miss2 = fill(t.hand, t.values)
        write_text(SPEC_REL, spec)
        write_text(HAND_REL, hand)
        for m in miss1 + miss2:
            print(f"unfilled: {m}")
        t = load()
    timings: dict[str, float] = {}
    found = audit(t, timings)
    fails = [f for f in found if f.level == "FAIL"]
    if a.json:
        dump = {"base": t.env.base, "values": t.values,
                "findings": [{"level": f.level, "gate": f.gate, "msg": f.msg} for f in found],
                "timings_ms": {k: round(v * 1000, 1) for k, v in timings.items()}}  # fmt: skip
        print(json.dumps(dump, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for ln in render(found):
            print(ln)
        notes = sum(f.level == "NOTE" for f in found)
        warns = sum(f.level == "WARN" for f in found)
        print(f"{len(fails)} FAIL / {warns} WARN / {notes} NOTE ({len(GATES) + 1} gates)")
        print("timings: " + " ".join(f"{k}={v * 1000:.0f}ms" for k, v in timings.items())
              + f" total={sum(timings.values()) * 1000:.0f}ms")  # fmt: skip
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

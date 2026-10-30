#!/usr/bin/env python3
"""E15-D10 (#364) audit: the hi-fi of SCR-027, the floating panel window — its title bar, the OS
title string, the measured sweep, the states, the browser build and the copy-ready `14` / `15` rows.

Standalone, offline; it runs under `python3 -I` and reads AS TEXT at the pinned base
(`git merge-base HEAD origin/main`, via `git show BASE:<path>`) the plan texts, the constitution,
the design rule file and the design README, the merged E10 and E15 design docs and hand-offs, the
shipped shell code (`ShellPort.ts`, `BrowserShellAdapter.ts`, the preload allow-list, the main
process), the sprint calendar, the E15 backlog JSON and E15-D03's audit tool (the house glyph-advance
table); then the pack (`E15-D10.md`, `E15-D10-handoff.md`) and the pins from the working tree.
Token values are resolved through the shipped token sets (`themes.json`'s layering) with the token
tests' own verifier, contrast through the design tools' shared `contrast_check`, colour vision
through the research CVD script — imported, never re-implemented. Every source it normalises is
cached once per (revision, path). Every number the spec carries is a placeholder the tool fills
and re-derives; nothing is typed.

Gates (one mutation each in `--self-test`; the pins gate besides):
  (a) G-TABLE     §R lists BQ-01 … BQ-25 once each with a status (RULED / pending); every "RULED
                  BQ-nn" stamp names a listed BQ; every ledger needle stands in its cited line; the
                  consumer table, the ≤ 10-item walkthrough and the state table are well-formed.
  (b) G-SLOTS     §2.1 carries SL-1 … SL-9 with the never-leave set as E10-D03 §8 states it; every
                  bar frame of the register lists the never-leave slots (SL-5 on an order-capable
                  kind).
  (c) G-TITLE     every bar frame's OS title equals the composition rule's output for its fixture
                  (`{Kind} · {symbol} · {ENV}`; the environment word for every kind — the BQ-05
                  addendum, 6529482068); S-1 is the rule's output for the merged fixture and TS-3's
                  example the output for the non-order fixture.
  (d) G-BOUND     the title's longest form is computed from D-5's kind words, the contract's
                  `Symbol` pattern and the badge's words — never typed.
  (e) G-SWEEP     the slot widths, the step thresholds, the minimum widths and the comfortable bar
                  are the tool's sums of token values and glyph advances (the house table read from
                  E15-D03's tool); the thresholds fall step by step.
  (f) G-CONTRAST  every pair of §9.1 reproduced to the hundredth from the token sets; E15-D13's six
                  pairs and E10-D03's caption figures equal the parents' anchors; every gated pair
                  meets its floor in three themes.
  (g) G-CHROME    no bar frame draws a lock, CMP-079 or `aria-disabled`; §8 states that no T2
                  control exists on the chrome.
  (h) G-SAFETY    every bar frame carries the badge, the chip, the banner slot and — on an
                  order-capable kind — the arm state; §4 states the rule ("never under a scrim,
                  never in a fading layer, never dimmed"); `opacity.disabled` appears only where it
                  is forbidden.
  (h2) G-R5       §4 carries the standing R5 / C-2.6 sentence verbatim (the ruling's rider on
                  BQ-11): a floating window never gates, hides or blocks cancel, close, flatten or
                  set-or-tighten stop; no window state changes a trading capability; the chrome
                  displays the arm state and never decides it (C-2.21).
  (i) G-STRING    every §5.10 quoted string equals its source line's text at the base, verbatim.
  (j) G-FRAMES    every state names a register frame or its reason for none; every frame stands on
                  exactly the board its row names; the board plan and the register reconcile.
  (k) G-CITE      every cite in range, non-blank and content-pinned (a moved cite is a WARN until
                  `--repin-ruled` records it or the spec re-points it; an edited one a FAIL).
  (l) G-VERSION   values, never a sha: the calendar's sprint-1 start and length and the sprint fields
                  at `origin/main` equal the base; each cite's content at the base stands at
                  `origin/main`, re-found inside the cited entry alone.
  (m) G-AROW      every §C row well-formed; a replace's Old stands once inside its entry at the
                  Field's number (PR-1 mode; by content alone in PR-2 mode), an insert's anchor the
                  same; New one bullet in the entry's own form, PROPOSED or "owner approval pending";
                  Via `base` for a replace, `—` for an insert; the apply to both files succeeds.
  (n) G-HYGIENE   placeholders filled and re-derived, no `{{` left, no closing keyword, no local
                  path, no agent name, no URL or host (the hand-off scanned too); the tree against
                  the merge-base: PR 1 may differ only in the pack's four files; PR 2 (`14` and / or
                  `15` changed, the spec, the hand-off and the tool unchanged) must equal the
                  merge-base with §C applied exactly, every Old found by content inside its entry,
                  its `SHA:` anchors PR 1's record (not re-derived; `SHA:BASE` an ancestor of the
                  merge-base — E32-D06's rule), and may differ in the pins alone, by
                  recorded cite moves only (BQ-03); the §M list equal to the tool's.
  G-RULED-PIN     a default-deny pin set over every unit of the pack (`e15_d10_ruled_pins.txt`);
                  `--repin-ruled` is the only writer.

Usage (from the repo root):
  python3 -I docs/design/_tools/e15_d10_window_audit.py --check [--json] [--fill]
  python3 -I docs/design/_tools/e15_d10_window_audit.py --self-test
  python3 -I docs/design/_tools/e15_d10_window_audit.py --repin-ruled
  python3 -I docs/design/_tools/e15_d10_window_audit.py --a-rows
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
from types import ModuleType

ROOT = Path(__file__).resolve().parents[3]
SPEC_REL = "docs/design/E15/E15-D10.md"
HANDOFF_REL = "docs/design/E15/E15-D10-handoff.md"
PINS_REL = "docs/design/_tools/e15_d10_ruled_pins.txt"
TOOL_REL = "docs/design/_tools/e15_d10_window_audit.py"
OWN_PATHS = (SPEC_REL, HANDOFF_REL, PINS_REL, TOOL_REL)
PACK_TEXTS = (SPEC_REL, HANDOFF_REL, TOOL_REL)  # PR 2 may touch none of them (BQ-03)
CAT_REL = "docs/plan/15-component-catalogue.md"
SCR_REL = "docs/plan/14-screens-catalogue.md"
TARGETS = (SCR_REL, CAT_REL)
TOKENS_DIR = "packages/ui/tokens"
TOK_REL = f"{TOKENS_DIR}/primitives.tokens.json"
CAL_REL = "docs/plan/backlog/_tools/calendar_cv.py"
E15J_REL = "docs/plan/backlog/E15.json"
HEAD_REF = "origin/main"
ISSUE = "364"
PATHS: dict[str, str] = {
    "02": "docs/plan/02-definition-of-ready-done.md",
    "04": "docs/plan/04-security-program.md",
    "05": "docs/plan/05-accessibility-standard.md",
    "06": "docs/plan/06-performance-and-load-standard.md",
    "11": "docs/plan/11-user-stories.md",
    "12": "docs/plan/12-sitemap.md",
    "14": SCR_REL,
    "15": CAT_REL,
    "16": "docs/plan/16-design-system-brief.md",
    "20": "docs/plan/20-architecture.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "CONST": "CONSTITUTION.md",
    "RULE": ".claude/rules/32-design-specs.md",
    "README": "docs/design/README.md",
    "TOK": TOK_REL,
    "CAL": CAL_REL,
    "ADR11": "docs/plan/27-adrs/ADR-0011-electron-vs-tauri.md",
    "E10D02": "docs/design/E10/E10-D02.md",
    "E10D03": "docs/design/E10/E10-D03.md",
    "E10D04": "docs/design/E10/E10-D04.md",
    "NAMES": "docs/design/E10/E10-D04-names.json",
    "D02": "docs/design/E15/E15-D02.md",
    "D03": "docs/design/E15/E15-D03.md",
    "D03H": "docs/design/E15/E15-D03-handoff.md",
    "D04": "docs/design/E15/E15-D04.md",
    "D04H": "docs/design/E15/E15-D04-handoff.md",
    "D05": "docs/design/E15/E15-D05.md",
    "D07": "docs/design/E15/E15-D07.md",
    "D07H": "docs/design/E15/E15-D07-handoff.md",
    "D08": "docs/design/E15/E15-D08.md",
    "D13": "docs/design/E15/E15-D13.md",
    "D13H": "docs/design/E15/E15-D13-handoff.md",
    "D14": "docs/design/E15/E15-D14.md",
    "D15": "docs/design/E15/E15-D15.md",
    "RESP": "docs/design/specs/e15-responsive-and-degraded.md",
    "FLOWS": "docs/design/specs/e15-layout-flows.md",
    "PORT": "apps/web/src/shell/ShellPort.ts",
    "BSA": "apps/web/src/shell/BrowserShellAdapter.ts",
    "ALLOW": "apps/desktop/src/preload/allowList.ts",
    "MAIN": "apps/desktop/src/main/index.ts",
    "D03T": "docs/design/_tools/e15_d03_workspace_audit.py",
}
SHA_INPUTS: dict[str, tuple[str, ...]] = {
    "E10D03": (PATHS["E10D03"],),
    "D02": (PATHS["D02"],),
    "D03": (PATHS["D03"], PATHS["D03H"]),
    "D04": (PATHS["D04"], PATHS["D04H"]),
    "D07": (PATHS["D07"], PATHS["D07H"]),
    "D13": (PATHS["D13"], PATHS["D13H"]),
    "D15": (PATHS["D15"],),
    "14": (SCR_REL,),
    "15": (CAT_REL,),
    "16": (PATHS["16"],),
    "TOK": (TOK_REL,),
    "PORT": (PATHS["PORT"],),
    "CAL": (CAL_REL,),
}
THEMES = ("dark", "light", "hc")
THEME_SET = {"dark": "dark", "light": "light", "hc": "high-contrast"}
# the sprint values §13 anchors (key in the backlog JSON -> anchor id)
SPRINT_KEYS = {
    "E15-D10": "d10", "E15-D16": "d16", "E15-T02": "t02", "E15-S02": "s02", "E15-S08": "s08",
    "E15-Q02": "q02", "E15-Q04": "q04", "E15-Q06": "q06", "E15-K01": "k01",
}  # fmt: skip
BUILDERS = ("s02", "t02", "s08")  # the building consumers the design-ahead distance is read against
ORDER_KINDS = ("chart", "dom", "positions")  # D-4 (`D03`:169), read as the fixture's Kind word
NEVER_LEAVE = ("SL-1", "SL-2", "SL-3", "SL-4", "SL-8", "SL-9")  # + SL-5 on an order-capable kind
NEVER_LEAVE_PHRASE = "the kind, symbol, badge, feed chip, arm state, ⋮ and × never leave"
SAFETY_RULE = "never under a scrim, never in a fading layer, never dimmed"
T2_RULE = "No T2 control exists on SCR-027's chrome"
# the ruling's rider on BQ-11 (R5 / C-2.6), verbatim; §4 carries it and G-R5 reads it
R5_SENTENCE = (
    "a floating window never gates, hides or blocks cancel, close, flatten or set-or-tighten stop, "
    "and no window state (focus, width, pinned, unconfirmed) changes a trading capability; the chrome "
    "displays the arm state and never decides it (C-2.21"
)
CHROME_FORBIDDEN = ("lock", "CMP-079", "aria-disabled")
CARRIER_WORDS = ("badge", "chip", "banner")  # + "arm" on an order-capable kind
DISPOSITIONS = ("applied-as-amended", "applied", "routed", "held", "confirmed", "superseded by #")
# the §2.1 fixture strings the sweep is computed from (the merged forms, G-STRING-checked where quoted)
FIXTURE = {
    "order": {"title": "DOM · BTCUSDT", "kind": "DOM"},
    "market": {"title": "Tape · BTCUSDT", "kind": "Tape"},
    "env": "LIVE",
    "chip": "Live · 42 ms",
    "sync": "A · symbol",
    "sync_short": "A · 1",
    "arm": "ARMED",
    "countdown": "0:00",  # the countdown fixture: four glyphs ("m:ss"), PROPOSED in §2.1
    "ret": "Return to workspace",
    "ret_short": "Return",
    "pin": "Pin on top",
}
SEP = " · "
# the non-order OS-title fixture (the BQ-05 addendum, 6529482068: the word for every kind);
# G-TITLE reads TS-3's example against compose(*NON_ORDER_TITLE)
NON_ORDER_TITLE = ("Tape", "BTCUSDT", "LIVE")
# the D13 anchors this tool must reproduce to the hundredth (its key -> the parent's anchor key)
REPRO_D13 = {
    f"CR:env.{what}.{where}.{th}": f"CR:env.{what}.{where}.{th}"
    for what in ("live", "demo", "word")
    for where in ("focused", "unfocused")
    for th in THEMES
}

PLACEHOLDER = re.compile(r"\{\{([A-Z0-9]+:[^{}]+?)\}\}")
ANCHORED = re.compile(r"(`[^`\n]*`|[^\s<|`(]+)<!--=([A-Z0-9]+:[^>]+?)-->")
CODE = re.compile(r"`[^`\n]*`")
HEADING = re.compile(r"^(#{1,6}) (.+)$")
RULE = re.compile(r"^\s*\|?\s*:?-{3,}")
CITE = re.compile(
    r"(?:`([0-9]{2})`|`?\b(D0[2-9]H?|D1[345]H?|E10D0[234]|NAMES|RESP|FLOWS|PORT|BSA|ALLOW|MAIN"
    r"|D03T|ADR11|CAL|CONST|RULE|README|TOK)`?)"
    r":(\d+)(?:[–-](\d+))?"
)
FIELD_BASE = re.compile(r"`(14|15)`:(\d+)")
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE)
# assembled, so the deny pattern never spells the strings it refuses
LOCAL_PATH = re.compile("/" + "home/|/Users/|[A-Za-z]:\\\\|\\bwt-" + "notes\\b")
AGENT_NAME = re.compile(r"\b[a-z]{2,4}-worker-\d\b")
URL_OR_HOST = re.compile(r"https?://|penpot\.[a-z]|team-id=|file-id=", re.IGNORECASE)
FULL_STOP = re.compile(r"(?<=[.!?])\s+(?=[*`\"(A-Z0-9§])")
NEEDLE = re.compile(r"^`([^`]+)` \((?:`([0-9]{2})`|`?([A-Z0-9]+)`?):(\d+)")
FRAME_ID = re.compile(r"\bF-(\d+)\b")


# ---------------------------------------------------------------------------- imports (shared tools)


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sys.path.insert(0, str(ROOT / TOKENS_DIR / "tests"))
VERIFY = _load(ROOT / TOKENS_DIR / "tests" / "verify_tokens.py", "verify_tokens")
CONTRAST = _load(ROOT / "docs" / "design" / "_tools" / "contrast_check.py", "contrast_check")
CVD = _load(ROOT / "docs" / "research" / "_tools" / "cvd_simulate.py", "cvd_simulate")


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
    return re.sub(r"<!--=[A-Z0-9]+:[^>]+?-->", "", text)


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


def f2(x: float) -> str:
    return f"{x:.2f}"


# ---------------------------------------------------------------------------- tokens, colour, glyphs


def theme_set(theme: str) -> dict[str, object]:
    files = [VERIFY.PRIMITIVES, *VERIFY.THEMES[THEME_SET[theme]]]
    merged: dict[str, object] = VERIFY.merged_set(files)
    return merged


_THEME_CACHE: dict[str, dict[str, object]] = {}


def value(name: str, theme: str = "dark") -> object:
    if theme not in _THEME_CACHE:
        _THEME_CACHE[theme] = theme_set(theme)
    t = _THEME_CACHE[theme]
    entry = t[name]
    return VERIFY.resolve(entry["$value"], t) if isinstance(entry, dict) else None


def px(name: str) -> int:
    return int(float(str(value(name))))


def hexof(name: str, theme: str) -> str:
    return str(value(name, theme)).upper()


def rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def ratio(a: str, b: str) -> float:
    r: float = CONTRAST.contrast_ratio(rgb(a), rgb(b))
    return r


def grey(h: str) -> str:
    r, g, b = rgb(h)
    y = round(0.299 * r + 0.587 * g + 0.114 * b)
    return f"#{y:02X}{y:02X}{y:02X}"


def sim(h: str, kind: str) -> str:
    s: str = grey(h) if kind == "greyscale" else str(CVD.simulate(h, kind)).upper()
    return s


def de(a: str, b: str) -> float:
    d: float = CVD.delta_e76(a, b)
    return d


# the measured pairs of §9.1 (anchor key -> (foreground token, background token))
PAIRS: dict[str, tuple[str, str]] = {
    "env.live.focused": ("color.env.live", "color.surface.raised"),
    "env.live.unfocused": ("color.env.live", "color.surface.app"),
    "env.demo.focused": ("color.env.demo", "color.surface.raised"),
    "env.demo.unfocused": ("color.env.demo", "color.surface.app"),
    "env.word.focused": ("color.text.primary", "color.surface.raised"),
    "env.word.unfocused": ("color.text.primary", "color.surface.app"),
    "icon.focused": ("color.text.secondary", "color.surface.raised"),
    "icon.unfocused": ("color.text.secondary", "color.surface.app"),
    "note": ("color.text.primary", "color.status.info.subtle"),
    "pressed": ("color.border.selected", "color.surface.selected"),
    "sync.focused": ("color.sync.a", "color.surface.raised"),
    "sync.unfocused": ("color.sync.a", "color.surface.app"),
    "unconf": ("color.text.secondary", "color.surface.raised"),
    "hairline": ("color.border.default", "color.surface.raised"),
}


def contrast_values() -> dict[str, str]:
    vals: dict[str, str] = {}
    for key, (fg, bg) in PAIRS.items():
        for th in THEMES:
            vals[f"CR:{key}.{th}"] = f2(ratio(hexof(fg, th), hexof(bg, th)))
    for th in THEMES:
        live, demo = hexof("color.env.live", th), hexof("color.env.demo", th)
        for kind in ("greyscale", "deuteranopia", "protanopia", "tritanopia"):
            vals[f"CVD:rule.{kind}.{th}"] = f"{de(sim(live, kind), sim(demo, kind)):.1f}"
    return vals


def glyph_table(env: Env) -> tuple[dict[str, float], float, float]:
    """E15-D03's house table at the base: per-capital em bounds, EM_SAFE and EM_HEADROOM — read
    from the tool's text, never typed here."""
    src = env.at_base(PATHS["D03T"])
    m = re.search(r"INTER_CAPS_EM: dict\[str, float\] = \{([^}]*)\}", src, re.DOTALL)
    caps: dict[str, float] = {}
    if m:
        for k, v in re.findall(r'"([A-Z])": ([0-9.]+)', m[1]):
            caps[k] = float(v)
    mm = re.search(r"EM_SAFE, EM_HEADROOM = ([0-9.]+), ([0-9.]+)", src)
    safe, head = (float(mm[1]), float(mm[2])) if mm else (0.0, 0.0)
    return caps, safe, head


def advance(env: Env, text: str, size: int, weight: int) -> float:
    caps, safe, head = glyph_table(env)
    factor = 1.05 if weight >= 600 else 1.02 if weight >= 500 else 1.0
    em = sum(caps.get(c, safe) if c.isupper() else safe for c in text)
    return em * size * factor * head


def token_px_values() -> dict[str, str]:
    vals: dict[str, str] = {}
    for name in (
        "space.inset.sm", "space.1", "space.2", "font.size.sm", "font.size.xs",
        "size.control.compact", "size.control.comfortable", "size.target.min", "size.icon.lg",
        "size.icon.md", "size.icon.sm", "border.thick", "border.hairline", "border.focus",
    ):  # fmt: skip
        vals[f"TOKPX:{name}"] = str(px(name))
    return vals


def d03_arm_pill(env: Env) -> str:
    text = env.at_base(PATHS["D03"])
    m = re.search(r"(\d+)<!--=BUDGET:mc\.arm\.ARMED\.pill-->", text)
    return m[1] if m else "0"


def slot_widths(env: Env, kind: str, density: str, steps: int) -> dict[str, float]:
    """Each slot's width after `steps` shortening steps, for an order or a market panel."""
    size, label_w, bold_w = px("font.size.sm"), 500, 600
    s1, s2, ins = px("space.1"), px("space.2"), px("space.inset.sm")
    icon_md, icon_sm, tgt, thick = (
        px("size.icon.md"),
        px("size.icon.sm"),
        px("size.target.min"),
        px("border.thick"),
    )
    fx = FIXTURE[kind]
    w: dict[str, float] = {}
    w["SL-1"] = advance(env, str(fx["title"]), size, label_w)
    w["SL-2"] = 2 * s2 + icon_md + s1 + advance(env, FIXTURE["env"], size, bold_w) + 2 * thick
    w["SL-3"] = 2 * s2 + icon_sm + s1 + advance(env, FIXTURE["chip"], size, label_w)
    w["SL-4"] = advance(env, FIXTURE["sync_short" if steps >= 3 else "sync"], size, label_w)
    if str(fx["kind"]).lower() in ORDER_KINDS:
        pill = 2 * s2 + advance(env, FIXTURE["arm"], size, bold_w)
        w["SL-5"] = (
            pill if steps >= 4 else pill + s1 + advance(env, FIXTURE["countdown"], size, label_w)
        )
    w["SL-6"] = 2 * ins + advance(env, FIXTURE["ret_short" if steps >= 1 else "ret"], size, label_w)
    if steps < 2:
        w["SL-7"] = 2 * ins + advance(env, FIXTURE["pin"], size, label_w)
    w["SL-8"] = float(tgt)
    w["SL-9"] = float(tgt)
    del density  # the horizontal model is the same in both densities; heights differ (§2.2)
    return w


def bar_width(env: Env, kind: str, density: str, steps: int) -> int:
    w = slot_widths(env, kind, density, steps)
    s2, ins = px("space.2"), px("space.inset.sm")
    total = sum(w.values()) + s2 * (len(w) - 1) + 2 * ins
    return int(-(-total // 1))  # ceil


def sweep_values(env: Env) -> dict[str, str]:
    vals: dict[str, str] = {}
    for density in ("compact", "comfortable"):
        for kind, last in (("order", 4), ("market", 3)):
            for k in range(last + 1):
                if kind == "market" and k in (1, 2):
                    continue
                vals[f"SWEEP:{kind}.{density}.w{k}"] = str(bar_width(env, kind, density, k))
            vals[f"SWEEP:{kind}.{density}.min"] = vals[f"SWEEP:{kind}.{density}.w{last}"]
    pill = 2 * px("space.2") + advance(env, FIXTURE["arm"], px("font.size.sm"), 600)
    vals["SLOT:arm.pill.compact"] = str(int(-(-pill // 1)))
    vals["TOKPX:d03.arm.pill"] = d03_arm_pill(env)
    vals["BAR:comfortable"] = str(px("size.control.comfortable") + 2 * px("space.1"))
    return vals


def bound_values(env: Env) -> dict[str, str]:
    """The OS title's longest form: D-5's kind words (`D03`:170), the contract's `Symbol` pattern
    (`22`) and the badge's words (`E10D03`:97)."""
    vals: dict[str, str] = {}
    d03 = env.at_base(PATHS["D03"])
    m = re.search(r"\| D-5 .*", d03)
    kinds = re.findall(r'"([A-Z][A-Za-z]+), [A-Za-z ]+', m[0]) if m else []
    longest = max(kinds, key=len) if kinds else ""
    api = env.at_base(PATHS["22"])
    mm = re.search(
        r'Symbol:\s*\n\s*type: string\s*\n\s*pattern: "\^\[A-Z0-9\]\{2,(\d+)\}(USDT)\$"', api
    )
    sym = int(mm[1]) + len(mm[2]) if mm else 0
    e10 = env.at_base(PATHS["E10D03"])
    me = re.search(r"\*\*word\*\* (DEMO) / (LIVE)", e10)
    env_len = max(len(me[1]), len(me[2])) if me else 0
    vals["BOUND:kind"] = longest
    vals["BOUND:kind.len"] = str(len(longest))
    vals["BOUND:symbol.max"] = str(sym)
    vals["BOUND:chars"] = str(len(longest) + 2 * len(SEP) + sym + env_len)
    return vals


def compose(kind: str, symbol: str, env_word: str) -> str:
    """§3's composition: every floating window's OS title carries the environment word, whatever
    the hosted kind (the BQ-05 addendum, 6529482068); ORDER_KINDS governs the arm state, not the
    title."""
    return f"{kind}{SEP}{symbol}{SEP}{env_word}"


# ---------------------------------------------------------------------------- cites and pins

CitePin = tuple[str, tuple[int, int] | None, str]


def heading_hash(heading: str) -> str:
    return hashlib.sha256(pin_norm(heading).encode()).hexdigest()[:12]


@dataclass(frozen=True)
class Texts:
    env: Env
    spec: str
    handoff: str
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
            hh = ""
            for extra in parts[3:]:
                m = re.fullmatch(r"@(\d+)(?:–(\d+))?", extra)
                if m:
                    at = (int(m[1]), int(m[2]) if m[2] else int(m[1]))
                elif extra.startswith("h:"):
                    hh = extra[2:]
            out[parts[1]] = (parts[2], at, hh)
    return out


def heading_before(ls: list[str], n: int) -> str:
    for i in range(min(n, len(ls)) - 1, -1, -1):
        if ls[i].startswith("#"):
            return ls[i]
    return ""


def found_under(env: Env, rev: str, rel: str, h: str, span: int, hh: str) -> list[int]:
    ls = env.lines(rev, rel)
    hits = env.hash_index(rev, rel, span).get(h, [])
    return [n for n in hits if not hh or heading_hash(heading_before(ls, n)) == hh]


def resolve_cite(t: Texts, key: str, a: int, b: int) -> tuple[int, int, str]:
    """`ok`, `recorded`, `moved`, `gone`, `unpinned` or `range`."""
    rev = t.env.base
    ls = t.env.lines(rev, PATHS[key])
    if not (0 < a <= b <= len(ls)):
        return a, b, "range"
    pinned = cite_pins(t.pins).get(label_of(key, a, b))
    here = line_hash(ls[a - 1], ls[b - 1])
    if pinned is None:
        return a, b, "unpinned"
    h, at, hh = pinned
    if h == here:
        return a, b, "ok"
    if at and 0 < at[0] <= at[1] <= len(ls) and line_hash(ls[at[0] - 1], ls[at[1] - 1]) == h:
        return at[0], at[1], "recorded"
    found = found_under(t.env, rev, PATHS[key], h, b - a, hh)
    if len(found) == 1:
        return found[0], found[0] + (b - a), "moved"
    return a, b, "gone"


def cite_line(t: Texts, key: str, n: int) -> str:
    a, _, status = resolve_cite(t, key, n, n)
    ls = t.env.lines(t.env.base, PATHS[key])
    return ls[a - 1] if status != "range" and 0 < a <= len(ls) else ""


def pack_text(t: Texts) -> str:
    return t.spec + "\n" + t.handoff


def all_cites(t: Texts) -> list[tuple[str, int, int]]:
    """Every distinct cite of the pack, the §C rows' Field cells excepted (G-AROW verifies those
    lines itself, by content)."""
    seen: list[tuple[str, int, int]] = []
    text = "\n".join(ln for ln in lines_of(pack_text(t)) if not ln.startswith("| A-"))
    for c in cites_in(text):
        if c not in seen:
            seen.append(c)
    return seen


def cite_problems(t: Texts) -> tuple[list[str], list[str]]:
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
            bad.append(f"cite {label}: the pinned content stands nowhere once inside its entry")
        elif status == "moved":
            warn.append(
                f"cite {label}: the pinned content moved to :{a2} — re-point it (PR 1) or "
                "--repin-ruled records the move (PR 2)"
            )
    return bad, warn


# ---------------------------------------------------------------------------- the pack's rows


def rows_with(spec: str, prefix: str, header0: str, idp: str) -> list[list[str]]:
    return [r for r in table_after(section(spec, prefix), header0) if r and r[0].startswith(idp)]


def sl_rows(spec: str) -> list[list[str]]:
    return rows_with(spec, "## 2.", "SL", "SL-")


def w_rows(spec: str) -> list[list[str]]:
    return rows_with(spec, "## 2.", "W", "W-")


def ts_rows(spec: str) -> list[list[str]]:
    return rows_with(spec, "## 3.", "TS", "TS-")


def e_rows(spec: str) -> list[list[str]]:
    return rows_with(spec, "## 4.", "E", "E-")


def f_rows(spec: str) -> list[list[str]]:
    return rows_with(spec, "## 5.", "F", "F-")


def st_rows(spec: str) -> list[list[str]]:
    return rows_with(spec, "## 5.", "ST", "ST-")


def s_rows(spec: str) -> list[list[str]]:
    return rows_with(spec, "## 5.", "S", "S-")


def kb_rows(spec: str) -> list[list[str]]:
    return rows_with(spec, "## 7.", "KB", "KB-")


def fm_rows(spec: str) -> list[list[str]]:
    return rows_with(spec, "## 7.", "FM", "FM-")


def p_rows(spec: str) -> list[list[str]]:
    return rows_with(spec, "## 9.", "P", "P-")


def motion_rows(spec: str) -> list[list[str]]:
    return table_after(section(spec, "## 10."), "Transition")


def ledger_rows(spec: str) -> list[list[str]]:
    return rows_with(spec, "## 12.", "L", "L-")


def c_rows(spec: str) -> list[list[str]]:
    return rows_with(spec, "## 12.", "C", "C-")


def g_rows(spec: str) -> list[list[str]]:
    return rows_with(spec, "## 12.", "G", "G-")


def bq_rows(spec: str) -> list[list[str]]:
    return rows_with(spec, "## R.", "BQ", "BQ-")


def consumer_rows(spec: str) -> list[list[str]]:
    return rows_with(spec, "## 13.", "Consumer", "E15-")


def walk_items(spec: str) -> list[str]:
    return [ln for ln in lines_of(section(spec, "## 15.")) if re.match(r"^\s+\d+\. ", ln)]


def board_rows(spec: str) -> list[list[str]]:
    return table_after(section(spec, "## B."), "#")


def a_rows(spec: str) -> list[list[str]]:
    return rows_with(spec, "## §C", "A", "A-")


def disposition(cell: str) -> str:
    for d in DISPOSITIONS:
        if cell.startswith(d):
            return d
    return ""


def a_row_target(r: list[str]) -> tuple[str, int] | None:
    """(file key `14` / `15`, the line at the base) a §C row's Field cell names."""
    m = FIELD_BASE.fullmatch(r[2])
    return (m[1], int(m[2])) if m else None


def entry_id(target: str) -> str:
    m = re.match(r"((?:CMP|SCR)-\d{3})", target)
    return m[1] if m else ""


def is_bar(r: list[str]) -> bool:
    return len(r) > 2 and r[2] == "yes"


def frame_ids(cell: str) -> list[int]:
    return [int(n) for n in FRAME_ID.findall(cell)]


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
    sprints = sprint_fields(env.at_base(E15J_REL))
    for k, n in sprints.items():
        vals[f"SPRINT:{k}"] = str(n)
        if start and days:
            s0 = start + datetime.timedelta(days=(n - 1) * days)
            vals[f"DATE:{k}.start"] = s0.isoformat()
            vals[f"DATE:{k}.end"] = (s0 + datetime.timedelta(days=days - 1)).isoformat()
    if "d10" in sprints and all(c in sprints for c in BUILDERS):
        vals["COUNT:ahead.min"] = str(min(sprints[c] for c in BUILDERS) - sprints["d10"])
    return vals


def count_values(t: Texts) -> dict[str, str]:
    spec = t.spec
    vals: dict[str, str] = {}
    vals["COUNT:slots"] = str(len(sl_rows(spec)))
    vals["COUNT:sweep"] = str(len(w_rows(spec)))
    vals["COUNT:titles"] = str(len(ts_rows(spec)))
    vals["COUNT:env"] = str(len(e_rows(spec)))
    fr = f_rows(spec)
    vals["COUNT:frames"] = str(len(fr))
    vals["COUNT:frames.bar"] = str(sum(is_bar(r) for r in fr))
    vals["COUNT:frames.other"] = str(sum(not is_bar(r) for r in fr))
    vals["COUNT:states"] = str(len(st_rows(spec)))
    vals["COUNT:strings"] = str(len(s_rows(spec)))
    vals["COUNT:keys"] = str(len(kb_rows(spec)))
    vals["COUNT:focus"] = str(len(fm_rows(spec)))
    vals["COUNT:pairs"] = str(len(p_rows(spec)))
    vals["COUNT:motion"] = str(len(motion_rows(spec)))
    led = ledger_rows(spec)
    disp = [disposition(r[2]) for r in led if len(r) > 2]
    vals["COUNT:ledger"] = str(len(led))
    vals["COUNT:ledger.applied"] = str(disp.count("applied"))
    vals["COUNT:ledger.amended"] = str(disp.count("applied-as-amended"))
    vals["COUNT:ledger.routed"] = str(disp.count("routed"))
    vals["COUNT:ledger.held"] = str(disp.count("held"))
    vals["COUNT:ledger.confirmed"] = str(disp.count("confirmed"))
    vals["COUNT:ledger.superseded"] = str(disp.count("superseded by #"))
    vals["COUNT:crows"] = str(len(c_rows(spec)))
    vals["COUNT:grows"] = str(len(g_rows(spec)))
    ar = a_rows(spec)
    vals["COUNT:arows"] = str(len(ar))
    vals["COUNT:arows.14"] = str(sum(len(r) > 2 and r[2].startswith("`14`") for r in ar))
    vals["COUNT:arows.15"] = str(sum(len(r) > 2 and r[2].startswith("`15`") for r in ar))
    vals["COUNT:arows.replace"] = str(sum(len(r) > 3 and r[3] == "replace" for r in ar))
    vals["COUNT:arows.new"] = str(sum(len(r) > 3 and r[3] == "insert after" for r in ar))
    bq = bq_rows(spec)
    vals["COUNT:bq"] = str(len(bq))
    vals["COUNT:bq.ruled"] = str(sum(len(r) > 2 and r[2] == "RULED" for r in bq))
    vals["COUNT:bq.pending"] = str(sum(len(r) > 2 and r[2] == "pending" for r in bq))
    vals["COUNT:consumers"] = str(len(consumer_rows(spec)))
    vals["COUNT:walk"] = str(len(walk_items(spec)))
    vals["COUNT:boards"] = str(len(board_rows(spec)))
    vals["COUNT:mutations"] = str(len(MUTATIONS))
    return vals


def compute(t: Texts) -> dict[str, str]:
    env = t.env
    vals: dict[str, str] = {"SHA:BASE": env.base[:10]}
    for k, paths in SHA_INPUTS.items():
        vals[f"SHA:{k}"] = sha_of(env, paths)
    vals.update(token_px_values())
    vals.update(sweep_values(env))
    vals.update(bound_values(env))
    vals.update(contrast_values())
    vals.update(date_values(env))
    vals.update(count_values(t))
    vals["M:LIST"] = mutation_paragraph_text()
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
            if m[1] == "M:LIST":
                return values[m[1]]
            return f"{values[m[1]]}<!--={m[1]}-->"

        out_lines.append(PLACEHOLDER.sub(ph, ln))
    text = "\n".join(out_lines)

    def refresh(m: re.Match[str]) -> str:
        return f"{values[m[2]]}<!--={m[2]}-->" if m[2] in values else m[0]

    text = ANCHORED.sub(refresh, text)
    # §M's paragraph is the tool's own text, re-written whole on every fill (no anchor: it carries
    # back-ticks and stops)
    if "M:LIST" in values:
        ls = text.split("\n")
        for i, ln in enumerate(ls):
            if ln.startswith("Each M-n is a violation planted in memory;"):
                ls[i] = values["M:LIST"]
        text = "\n".join(ls)
    return text, missing


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


def pack_units(t: Texts) -> list[Unit]:
    return units(t.spec, "spec") + units(t.handoff, "handoff")


def fresh_cite_pins(t: Texts) -> dict[str, CitePin]:
    out: dict[str, CitePin] = {}
    for key, a, b in all_cites(t):
        ls = t.env.lines(t.env.base, PATHS[key])
        if 0 < a <= b <= len(ls):
            hh = heading_hash(heading_before(ls, a))
            out[label_of(key, a, b)] = (line_hash(ls[a - 1], ls[b - 1]), None, hh)
    return out


def write_pins(us: list[Unit], cites: dict[str, CitePin]) -> str:
    head = (
        "# E15-D10 pins (every unit of the pack — the spec and the hand-off): region, location, "
        f"the exact normalised text; {len(us)} units, then {len(cites)} cite pins (`cite`, the cite, "
        "a hash of the cited line at the base, `h:` the hash of the entry heading it sits under, and "
        "`@n` once a move was recorded in PR 2).\n# Written by `--repin-ruled` only; `--check` reads "
        "it (never hand-edit; see the tool's G-RULED-PIN and G-HYGIENE).\n"
    )
    body = "".join("\t".join(u) + "\n" for u in us)
    for label, (h, at, hh) in cites.items():
        tail = (
            "" if at is None else ("\t@" + (str(at[0]) if at[0] == at[1] else f"{at[0]}–{at[1]}"))
        )
        tail += f"\th:{hh}" if hh else ""
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
    alone (BQ-03)."""
    old = t.env.show(mb, PINS_REL)
    if old is None:
        return [f"{PINS_REL} is absent at the merge-base; PR 2 cannot rewrite it"]
    bad: list[str] = []
    if parse_pins(old) != parse_pins(t.pins):
        bad.append("PR 2 rewrote a pinned unit; the pins may record cite moves alone")
    oc, nc = cite_pins(old), cite_pins(t.pins)
    if list(oc) != list(nc):
        bad.append("PR 2 added, dropped or reordered a cite pin")
    for label, (h, at, hh) in nc.items():
        if label not in oc:
            continue
        if oc[label][0] != h or oc[label][2] != hh:
            bad.append(f"PR 2 changed the pinned content of cite {label}")
        elif at != oc[label][1]:
            m = re.fullmatch(r"([A-Z0-9]+):(\d+)(?:–(\d+))?", label)
            key = m[1] if m else ""
            ls = t.env.lines(t.env.base, PATHS[key]) if key in PATHS else []
            ok = (
                at is not None
                and 0 < at[0] <= at[1] <= len(ls)
                and line_hash(ls[at[0] - 1], ls[at[1] - 1]) == h
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
    ("COUNT:bq", "G-TABLE"), ("COUNT:ledger", "G-TABLE"), ("COUNT:crows", "G-TABLE"),
    ("COUNT:grows", "G-TABLE"), ("COUNT:consumers", "G-TABLE"), ("COUNT:walk", "G-TABLE"),
    ("COUNT:keys", "G-TABLE"), ("COUNT:focus", "G-TABLE"), ("COUNT:motion", "G-TABLE"),
    ("COUNT:titles", "G-TITLE"), ("COUNT:env", "G-SAFETY"),
    ("COUNT:slots", "G-SLOTS"),
    ("BOUND:", "G-BOUND"),
    ("SWEEP:", "G-SWEEP"), ("SLOT:", "G-SWEEP"), ("BAR:", "G-SWEEP"), ("TOKPX:", "G-SWEEP"),
    ("COUNT:sweep", "G-SWEEP"),
    ("CR:", "G-CONTRAST"), ("CVD:", "G-CONTRAST"), ("COUNT:pairs", "G-CONTRAST"),
    ("COUNT:strings", "G-STRING"),
    ("COUNT:frames", "G-FRAMES"), ("COUNT:states", "G-FRAMES"), ("COUNT:boards", "G-FRAMES"),
    ("DATE:", "G-VERSION"), ("SPRINT:", "G-VERSION"), ("COUNT:ahead", "G-VERSION"),
    ("COUNT:arows", "G-AROW"),
)  # fmt: skip


def anchor_gate(key: str) -> str:
    for prefix, gate in ANCHOR_GATE:
        if key.startswith(prefix):
            return gate
    return "G-HYGIENE"


def in_pr2(t: Texts) -> bool:
    return bool(t.changed) and bool(set(TARGETS) & set(t.changed or []))


def anchor_problems(t: Texts, gate: str) -> list[str]:
    bad: list[str] = []
    pr2 = in_pr2(t)
    for value_, key, ln in anchored(t.spec):
        if anchor_gate(key) != gate:
            continue
        if pr2 and key.startswith("SHA:"):
            continue  # PR 2: the `SHA:` anchors are PR 1's record (E32-D06's rule; `SHA:BASE` checked as an ancestor)
        want = t.values.get(key)
        if want is None:
            bad.append(f"spec:{ln} anchors `{key}`, which the tool does not compute")
        elif want != value_:
            bad.append(f"spec:{ln} `{key}` reads {value_}; the tool derives {want}")
    bad += residue_problems(t.spec, gate)
    return bad


def residue_problems(text: str, gate: str) -> list[str]:
    bad: list[str] = []
    for i, ln in enumerate(text.split("\n"), 1):
        if not ln.lstrip().startswith("|"):
            continue
        for cell in split_row(ln):
            pos = 0
            for m in ANCHORED.finditer(cell):
                if anchor_gate(m[2]) == gate and cell[pos : m.start()].strip() not in (
                    "", "/", "·", "(",
                ):  # fmt: skip
                    bad.append(
                        f"spec:{i} `{m[2]}`: the cell carries text in front of its value "
                        f"({cell[pos : m.start()].strip()[:40]!r}); re-fill the cell"
                    )
                pos = m.end()
    return bad


# ---------------------------------------------------------------------------- the gates


def g_table(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-TABLE")
    bq = bq_rows(t.spec)
    ids = [r[0] for r in bq]
    if ids != [f"BQ-{n:02d}" for n in range(1, 26)]:
        bad.append("§R does not list BQ-01 … BQ-25 once each, in order")
    for r in bq:
        if len(r) != 3 or r[2] not in ("RULED", "pending"):
            bad.append(f"§R {r[0]}: the status is not RULED / pending")
    for m in re.finditer(r"RULED BQ-(\d\d)", pack_text(t)):
        if f"BQ-{m[1]}" not in ids:
            bad.append(f"a row is stamped RULED BQ-{m[1]}, which §R does not list")
    for r in ledger_rows(t.spec):
        if len(r) != 4:
            bad.append(f"{r[0]} has {len(r)} cells, not 4")
            continue
        if not disposition(r[2]):
            bad.append(f"{r[0]}: the disposition {r[2][:30]!r} is not in the ruled set")
        m = NEEDLE.match(r[1])
        if not m:
            bad.append(f"{r[0]}: the row of record is not `needle` (`KEY`:line)")
            continue
        key = m[2] or m[3]
        if key not in PATHS:
            bad.append(f"{r[0]}: the cite key {key} is unknown")
        elif m[1] not in cite_line(t, key, int(m[4])):
            bad.append(f"{r[0]}: `{m[1]}` is not in {key}:{m[4]}")
    for r in c_rows(t.spec) + g_rows(t.spec):
        if len(r) != 3 or any(c in ("", "—") for c in r[1:]):
            bad.append(f"{r[0]}: a contradiction or gap row with an empty cell")
    for k, r in enumerate(st_rows(t.spec), 1):
        if len(r) != 4 or r[0] != f"ST-{k}":
            bad.append(f"state row {k} is malformed or misnumbered ({r[0] if r else '?'})")
    for r in kb_rows(t.spec):
        if len(r) != 6 or not CITE.search(r[5]):
            bad.append(f"{r[0]}: a keyboard row without six cells or a source cite")
    for r in fm_rows(t.spec):
        if len(r) != 5 or not CITE.search(r[4]):
            bad.append(f"{r[0]}: a focus row without five cells or a source cite")
    for r in motion_rows(t.spec):
        if len(r) != 4 or r[1] not in ("cut", "OS", "row 2a"):
            bad.append(f"§10 {r[0]!r}: the verdict is not cut / OS / row 2a")
    if not consumer_rows(t.spec):
        bad.append("§13 lists no consumer")
    if len(walk_items(t.spec)) > 10:
        bad.append("§15's walkthrough exceeds ten items")
    return one("G-TABLE", bad)


def g_slots(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-SLOTS")
    sl = sl_rows(t.spec)
    if [r[0] for r in sl] != [f"SL-{n}" for n in range(1, 10)]:
        bad.append("§2.1 does not list SL-1 … SL-9 once each, in order")
    for r in sl:
        if len(r) != 8:
            bad.append(f"{r[0]} has {len(r)} cells, not 8")
            continue
        stays = r[6].startswith("yes")
        if (r[0] in NEVER_LEAVE or r[0] == "SL-5") != stays:
            bad.append(f"{r[0]}: the never-leaves cell disagrees with E10-D03 §8's set")
    if NEVER_LEAVE_PHRASE not in cite_line(t, "E10D03", 302):
        bad.append("E10-D03 §8 no longer states the never-leave set at the base")
    for r in f_rows(t.spec):
        if len(r) != 12 or not is_bar(r):
            continue
        need = list(NEVER_LEAVE) + (["SL-5"] if r[3].lower() in ORDER_KINDS else [])
        missing = [s for s in need if not re.search(rf"\b{s}\b", r[7])]
        if missing:
            bad.append(f"{r[0]}: the bar frame lacks {', '.join(missing)} (the never-leave set)")
    return one("G-SLOTS", bad)


def g_title(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-TITLE")
    for r in f_rows(t.spec):
        if len(r) != 12 or not is_bar(r):
            continue
        want = compose(r[3], r[4], r[5])
        if r[6] != want:
            bad.append(f"{r[0]}: the OS title {r[6]!r} is not the composition's {want!r}")
        if r[5] not in r[6]:
            bad.append(
                f"{r[0]}: the window's title lacks its environment word ({r[3]}, the BQ-05 addendum)"
            )
    s1 = next((r for r in s_rows(t.spec) if r[0] == "S-1"), None)
    if not s1 or unescape(s1[1]).strip().strip('"') != compose("DOM", "BTCUSDT", "LIVE"):
        bad.append("S-1 is not the composition rule's output for the merged fixture")
    kind, sym, env_word = NON_ORDER_TITLE
    non_order = compose(kind, sym, env_word)
    ts3 = next((r for r in ts_rows(t.spec) if r[0] == "TS-3"), None)
    if env_word not in non_order or not ts3 or unescape(ts3[2]).strip().strip('"') != non_order:
        bad.append(
            f"TS-3's example is not the composition's output for the non-order fixture ({non_order!r})"
        )
    for r in ts_rows(t.spec):
        if len(r) != 5 or not CITE.search(r[4]):
            bad.append(f"{r[0]}: a title row without five cells or a source cite")
    return one("G-TITLE", bad)


def g_bound(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-BOUND")
    v = t.values
    if not v.get("BOUND:kind") or v.get("BOUND:symbol.max", "0") == "0":
        bad.append("the bound's inputs could not be read (D-5's kinds or `22`'s Symbol pattern)")
    return one("G-BOUND", bad)


def g_sweep(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-SWEEP")
    v = t.values
    for density in ("compact", "comfortable"):
        seq = [int(v.get(f"SWEEP:order.{density}.w{k}", "0")) for k in range(5)]
        if any(seq[i] <= seq[i + 1] for i in range(len(seq) - 1)):
            bad.append(f"the order panel's thresholds do not fall step by step ({density})")
        mk = [
            int(v.get(f"SWEEP:market.{density}.w0", "0")),
            int(v.get(f"SWEEP:market.{density}.w3", "0")),
        ]
        if mk[0] <= mk[1]:
            bad.append(
                f"the market panel's step-3 bar is not narrower than its full bar ({density})"
            )
    rows = w_rows(t.spec)
    if [r[0] for r in rows] != [f"W-{n}" for n in range(7)]:
        bad.append("§2.3 does not list W-0 … W-6 once each, in order")
    ids = {int(n) for r in f_rows(t.spec) for n in [r[0][2:]]}
    for r in rows:
        if len(r) != 7 or not any(n in ids for n in frame_ids(r[5])):
            bad.append(f"{r[0]}: a sweep row without seven cells or a register frame")
    caps, safe, head = glyph_table(t.env)
    if len(caps) != 26 or not safe or not head:
        bad.append("the house glyph table could not be read from E15-D03's tool at the base")
    return one("G-SWEEP", bad)


def parent_anchor(t: Texts, key: str, akey: str) -> str | None:
    text = t.env.at_base(PATHS[key])
    m = re.search(r"(\d[\d.]*)<!--=" + re.escape(akey) + r"-->", text)
    return m[1] if m else None


def g_contrast(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-CONTRAST")
    v = t.values
    for mine, theirs in REPRO_D13.items():
        got = parent_anchor(t, "D13", theirs)
        if got != v.get(mine):
            bad.append(f"{mine} {v.get(mine)} does not reproduce `D13`'s {theirs} ({got})")
    m = re.search(
        r"measured ([\d.]+) / ([\d.]+) / ([\d.]+) on the pill", cite_line(t, "E10D03", 214)
    )
    if not m or [m[1], m[2], m[3]] != [v.get(f"CR:unconf.{th}") for th in THEMES]:
        bad.append("the unconfirmed caption's figures do not reproduce `E10D03`:214")
    for r in p_rows(t.spec):
        if len(r) != 8:
            bad.append(f"{r[0]} has {len(r)} cells, not 8")
            continue
        fm = re.fullmatch(r"([\d.]+):1", r[2])
        gated = r[6].startswith(("gated", "reproduces"))
        if gated and not fm:
            bad.append(f"{r[0]}: a gated pair without a floor")
            continue
        if fm:
            for i, th in enumerate(THEMES, 3):
                val = strip_anchors(r[i])
                if gated and (not re.fullmatch(r"[\d.]+", val) or float(val) < float(fm[1])):
                    bad.append(f"{r[0]}: {val} below {r[2]} in {th}")
    return one("G-CONTRAST", bad)


def g_chrome(t: Texts) -> list[Finding]:
    bad: list[str] = []
    for r in f_rows(t.spec):
        if len(r) == 12 and is_bar(r):
            text = " ".join(r)
            hits = [w for w in CHROME_FORBIDDEN if re.search(rf"(?<!\w){re.escape(w)}(?!\w)", text)]
            if hits:
                bad.append(
                    f"{r[0]}: a chrome frame draws {', '.join(hits)} (§8: no T2 on the chrome)"
                )
    if T2_RULE not in section(t.spec, "## 8."):
        bad.append("§8 does not state that no T2 control exists on the chrome")
    return one("G-CHROME", bad)


def g_safety(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-SAFETY")
    for r in f_rows(t.spec):
        if len(r) != 12 or not is_bar(r):
            continue
        need = list(CARRIER_WORDS) + (["arm"] if r[3].lower() in ORDER_KINDS else [])
        missing = [w for w in need if not re.search(rf"\b{w}\b", r[8], re.IGNORECASE)]
        if missing:
            bad.append(f"{r[0]}: the carrier cell lacks {', '.join(missing)}")
    if SAFETY_RULE not in section(t.spec, "## 4."):
        bad.append(f"§4 does not state the rule ({SAFETY_RULE!r})")
    for i, ln in enumerate(lines_of(t.spec), 1):
        if "`opacity.disabled`" in ln and "Never" not in ln and "never" not in ln:
            bad.append(f"spec:{i} names `opacity.disabled` outside a prohibition")
    for r in e_rows(t.spec):
        if len(r) != 4 or not CITE.search(r[3]):
            bad.append(f"{r[0]}: an environment row without four cells or a source cite")
    return one("G-SAFETY", bad)


def g_r5(t: Texts) -> list[Finding]:
    """The standing sentence of R5 / C-2.6 (the ruling's rider on BQ-11) stands verbatim in §4."""
    bad: list[str] = []
    if R5_SENTENCE not in section(t.spec, "## 4."):
        bad.append("§4 does not carry the standing R5 / C-2.6 sentence verbatim")
    return one("G-R5", bad)


def g_string(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-STRING")
    for r in s_rows(t.spec):
        if len(r) != 4:
            bad.append(f"{r[0]} has {len(r)} cells, not 4")
            continue
        text = unescape(r[1]).strip().strip('"')
        cites = cites_in(r[3])
        if not cites:
            bad.append(f"{r[0]}: no source cite")
            continue
        key, a, _ = cites[0]
        if text not in cite_line(t, key, a):
            bad.append(f"{r[0]}: {text[:40]!r} is not in {key}:{a}")
    return one("G-STRING", bad)


def g_frames(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-FRAMES")
    fr = f_rows(t.spec)
    ids = [int(r[0][2:]) for r in fr]
    if ids != list(range(1, len(ids) + 1)):
        bad.append("the register does not number F-1 … F-n in order")
    boards = {r[0]: r for r in board_rows(t.spec) if len(r) == 5}
    on_board: dict[int, str] = {}
    for num, r in boards.items():
        for n in frame_ids(r[2]):
            if n in on_board:
                bad.append(f"F-{n} stands on two boards ({on_board[n]} and {num})")
            on_board[n] = num
    for r in fr:
        if len(r) != 12:
            bad.append(f"{r[0]} has {len(r)} cells, not 12")
            continue
        n = int(r[0][2:])
        if not r[1].startswith("`SCR-027/"):
            bad.append(f"{r[0]}: the frame name is not `SCR-027/…`")
        if r[2] not in ("yes", "no"):
            bad.append(f"{r[0]}: Bar is not yes / no")
        if r[10] not in boards:
            bad.append(f"{r[0]}: board {r[10]!r} is not in §B")
        elif on_board.get(n) != r[10]:
            bad.append(
                f"{r[0]}: the register says board {r[10]}, §B puts it on {on_board.get(n, 'none')}"
            )
        if not CITE.search(r[11]) and "§" not in r[11]:
            bad.append(f"{r[0]}: the source cell carries no cite")
    for n in on_board:
        if n not in ids:
            bad.append(f"§B lists F-{n}, which the register lacks")
    for r in st_rows(t.spec):
        if len(r) != 4:
            continue
        named = frame_ids(r[2])
        if not named and not re.search(r"\bnone\b|\bcited\b", r[2]):
            bad.append(f"{r[0]}: names no frame and no reason for none")
        for n in named:
            if n not in ids:
                bad.append(f"{r[0]}: names F-{n}, which the register lacks")
    return one("G-FRAMES", bad)


def g_cite(t: Texts) -> list[Finding]:
    fails, warns = cite_problems(t)
    return one("G-CITE", fails) + one("G-CITE", warns, "WARN")


def g_version(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-VERSION")
    warn: list[str] = []
    env = t.env
    head_cal = env.show(HEAD_REF, CAL_REL)
    if head_cal is None:
        bad.append(f"{HEAD_REF} does not resolve or lacks {CAL_REL}; fetch origin first")
    elif calendar_values(head_cal) != calendar_values(env.at_base(CAL_REL)):
        bad.append(f"the calendar's sprint-1 start or length changed at {HEAD_REF}")
    head_j = env.show(HEAD_REF, E15J_REL)
    if head_j is not None:
        a, b = sprint_fields(env.at_base(E15J_REL)), sprint_fields(head_j)
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
            continue
        ls = env.lines(env.base, rel)
        h = line_hash(ls[a2 - 1], ls[b2 - 1])
        hl = env.lines(HEAD_REF, rel)
        label = label_of(key, a0, b0)
        if 0 < a2 <= b2 <= len(hl) and line_hash(hl[a2 - 1], hl[b2 - 1]) == h:
            continue
        at = found_under(env, HEAD_REF, rel, h, b2 - a2, heading_hash(heading_before(ls, a2)))
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


def entry_heading(lines: list[str], ent: str) -> list[int]:
    return [i for i, ln in enumerate(lines) if ln.startswith(f"### {ent} ")]


def entry_span(lines: list[str], start: int) -> int:
    return next((i for i in range(start + 1, len(lines)) if lines[i].startswith("#")), len(lines))


def field_prefix(line: str) -> str:
    m = re.match(r"- \*\*[^*]+\*\*:?", line)
    return m[0] if m else ""


def g_arow(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-AROW")
    pr2 = bool(t.changed) and bool(set(TARGETS) & set(t.changed or []))
    for r in a_rows(t.spec):
        if len(r) != 8:
            bad.append(f"{r[0]} has {len(r)} cells, not 8")
            continue
        aid, target, _, op, via, old, new, _ = r
        ent = entry_id(target)
        tgt = a_row_target(r)
        if op not in ("replace", "insert after") or tgt is None or not ent or old == "—":
            bad.append(f"{aid}: the op, the Field, the target or the Old is malformed")
            continue
        key, n = tgt
        base_lines = t.env.lines(t.env.base, PATHS[key])
        heads = entry_heading(base_lines, ent)
        if len(heads) != 1:
            bad.append(f"{aid}: the entry {ent} stands {len(heads)} times in `{key}` at the base")
            continue
        end = entry_span(base_lines, heads[0])
        want = unescape(old)
        hits = [i for i in range(heads[0], end) if base_lines[i] == want]
        if len(hits) != 1:
            bad.append(f"{aid}: Old stands {len(hits)} times inside {ent} at the base")
        elif not pr2 and hits[0] != n - 1:
            bad.append(
                f"{aid}: Old stands at `{key}`:{hits[0] + 1}, not at `{key}`:{n} (PR 1's base)"
            )
        if op == "insert after" and via != "—":
            bad.append(f"{aid}: a new line's Via is `—`")
        if op == "replace" and via != "base":
            bad.append(f"{aid}: a replace's Via is `base`")
        text = strip_anchors(unescape(new))
        if not text.startswith("- **") or "<br>" in text or "\n" in text:
            bad.append(f"{aid}: New is not one bullet line")
        if op == "replace" and field_prefix(text) != field_prefix(want):
            bad.append(f"{aid}: New does not keep Old's field ({field_prefix(want)!r})")
        if "PROPOSED" not in text and "owner approval pending" not in text:
            bad.append(f"{aid}: New is neither PROPOSED nor marked owner approval pending")
    rows = a_rows_export(t)
    for rel in TARGETS:
        _, problems = apply_rows(t.env.at_base(rel), [x for x in rows if x["file"] == rel])
        bad += problems
    return one("G-AROW", bad)


def mutation_paragraph(spec: str) -> str:
    block = section(spec, "## §M")
    return next((ln for ln in lines_of(block) if "M-1 " in ln), "")


def hygiene_lines(doc: str, text: str) -> list[str]:
    bad: list[str] = []
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
    return bad


def g_hygiene(t: Texts) -> list[Finding]:
    bad = anchor_problems(t, "G-HYGIENE")
    for key in unfilled(t.spec):
        bad.append(f"the placeholder `{key}` is unfilled (run --check --fill)")
    bad += hygiene_lines("spec", t.spec) + hygiene_lines("handoff", t.handoff)
    if t.changed is None:
        bad.append("cannot list the changed paths (`git diff` / `git status` failed)")
    else:
        other = [p for p in t.changed if p not in OWN_PATHS]
        pr2 = bool(set(TARGETS) & set(t.changed))
        if not pr2:
            for p in other:
                bad.append(f"PR 1 changes {p}, outside the pack's four files")
        else:
            for p in t.changed:
                if p in PACK_TEXTS:
                    bad.append(
                        f"PR 2 changes {p}: the pack is byte-identical to the merged PR 1 (BQ-03)"
                    )
                elif p not in OWN_PATHS and p not in TARGETS:
                    bad.append(f"PR 2 changes {p}, outside `14`, `15` and the pins")
            rows = a_rows_export(t)
            for rel, have in ((CAT_REL, t.cat15), (SCR_REL, t.cat14)):
                want, problems = apply_rows(
                    t.env.at_base(rel), [x for x in rows if x["file"] == rel]
                )
                for p in problems:
                    bad.append(
                        f"PR 2: {p} (a target line is absent at the merge-base: edited or moved out of its entry)"
                    )
                if not problems and have != want:
                    bad.append(
                        f"PR 2: {rel} is not the merge-base with §C applied exactly (an extra byte)"
                    )
            for value_, key, _ in anchored(t.spec):
                if (
                    key == "SHA:BASE"
                    and git_raw("merge-base", "--is-ancestor", value_, t.env.base) is None
                ):
                    bad.append(
                        f"PR 2: the recorded `SHA:BASE` {value_} is no ancestor of the merge-base"
                    )
                    break
            if PINS_REL in t.changed:
                bad += pins_diff_problems(t, t.env.base)
    para = mutation_paragraph(t.spec)
    if pin_norm(para) != pin_norm(mutation_paragraph_text()):
        bad.append("§M is not the tool's mutation list (run --check --fill)")
    gates_named = re.findall(r"\*\*(G-[A-Z0-9-]+)\*\*", para)
    if gates_named != [g.__name__.upper().replace("G_", "G-") for g in GATES] + ["G-RULED-PIN"]:
        bad.append("§M does not name each gate once, in the tool's order")
    return one("G-HYGIENE", bad)


def g_pins(t: Texts) -> list[Finding]:
    pinned = parse_pins(t.pins)
    if not pinned:
        return one("G-RULED-PIN", [f"{PINS_REL} is empty or missing (run --repin-ruled)"])
    return one("G-RULED-PIN", pin_problems(pinned, pack_units(t)))


GATES: tuple[Callable[[Texts], list[Finding]], ...] = (
    g_table, g_slots, g_title, g_bound, g_sweep, g_contrast, g_chrome, g_safety, g_r5, g_string,
    g_frames, g_cite, g_version, g_arow, g_hygiene,
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


def a_rows_export(t: Texts) -> list[dict[str, object]]:
    """§C as data for PR 2: each row carries its file, its entry (`### SCR-nnn` / `### CMP-nnn`),
    its anchor line (the line replaced, or the line an insert follows), its Old and New, and
    `via`. Every number is PR 1's base's; PR 2 re-points by content."""
    out: list[dict[str, object]] = []
    for r in a_rows(t.spec):
        tgt = a_row_target(r) if len(r) == 8 else None
        if tgt is None:
            continue
        aid, target, _, op, via, old, new, frm = r
        out.append(
            {
                "id": aid,
                "target": target,
                "file": PATHS[tgt[0]],
                "entry": entry_id(target),
                "line": tgt[1],
                "anchor": unescape(old),
                "op": op,
                "via": via if via != "—" else None,
                "old": [unescape(old)] if op == "replace" else [],
                "new": [strip_anchors(unescape(new))],
                "from": frm,
            }
        )
    return out


def apply_rows(text: str, rows: list[dict[str, object]]) -> tuple[str, list[str]]:
    lines = lines_of(text)
    bad: list[str] = []
    plan: list[tuple[int, int, dict[str, object]]] = []
    for k, r in enumerate(rows):
        heads = entry_heading(lines, str(r["entry"]))
        if len(heads) != 1:
            bad.append(f"{r['id']}: the entry {r['entry']} stands {len(heads)} times")
            continue
        end = entry_span(lines, heads[0])
        hits = [i for i in range(heads[0], end) if lines[i] == r["anchor"]]
        if len(hits) != 1:
            bad.append(f"{r['id']}: its target line stands {len(hits)} times in its entry")
            continue
        plan.append((hits[0], k, r))
    for i, _, r in sorted(plan, key=lambda p: (-p[0], -p[1])):
        new = [str(x) for x in r["new"]] if isinstance(r["new"], list) else []
        if str(r["op"]) == "replace":
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
    handoff = read_raw(HANDOFF_REL) if (ROOT / HANDOFF_REL).exists() else ""
    t = Texts(
        env,
        read_raw(SPEC_REL),
        handoff,
        pins,
        read_raw(CAT_REL),
        read_raw(SCR_REL),
        changed_paths(base),
        {},
    )
    return replace(t, values=compute(t))


@dataclass(frozen=True)
class Mutation:
    gate: str
    what: str
    apply: Callable[[Texts], Texts]


def flex(old: str) -> re.Pattern[str]:
    return re.compile(r"\s+".join(re.escape(p) for p in old.split(" ") if p != ""))


def subst(old: str, new: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        m = flex(old).search(t.spec)
        if not m:
            raise SystemExit(f"self-test: the spec lacks {old[:60]!r}")
        return replace(t, spec=t.spec[: m.start()] + new + t.spec[m.end() :])

    return f


def anchor_edit(key: str, new_value: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        rx = re.compile(rf"(`[^`\n]*`|[^\s<|`]+)<!--={re.escape(key)}-->")
        m = rx.search(t.spec)
        if not m:
            raise SystemExit(f"self-test: the spec has no anchored {key}")
        return replace(
            t, spec=t.spec[: m.start()] + f"{new_value}<!--={key}-->" + t.spec[m.end() :]
        )

    return f


def with_text(t: Texts, rev: str, rel: str, text: str) -> Texts:
    stale = re.compile(rf"(?:show|lines|hidx):{re.escape(rev)}:{re.escape(rel)}(?::\d+)?")
    memo = {k: v for k, v in t.env.memo.items() if not stale.fullmatch(k)}
    memo[f"show:{rev}:{rel}"] = text
    return replace(t, env=Env(t.env.base, memo))


def head_sprint_days(t: Texts) -> Texts:
    src = t.env.at_base(CAL_REL)
    return with_text(
        t, HEAD_REF, CAL_REL,
        re.sub(r"^SPRINT_DAYS = (\d+)", lambda m: f"SPRINT_DAYS = {int(m[1]) + 1}", src, count=1, flags=re.MULTILINE),
    )  # fmt: skip


def record_moves(t: Texts) -> tuple[str, int]:
    pins = cite_pins(t.pins)
    n = 0
    for key, a0, b0 in all_cites(t):
        a2, b2, status = resolve_cite(t, key, a0, b0)
        if status == "moved":
            h, _, hh = pins[label_of(key, a0, b0)]
            pins[label_of(key, a0, b0)] = (h, (a2, b2), hh)
            n += 1
    return write_pins(parse_pins(t.pins), pins), n


def pr2_texts(
    t: Texts,
    edited: str = "",
    extra15: str = "",
    extra_changed: tuple[str, ...] = (),
    sha_base: str = "",
) -> Texts:
    """PR 2's view: the merge-base holds `14` / `15` as at the base (with the §C row `edited`'s
    target line altered by a later PR, when named) and PR 1's pins; the working tree has §C applied
    to both files, the cite moves recorded, and only `14`, `15` (plus the pins, plus `extra_changed`)
    differ."""
    t2 = t
    if edited:
        row = next(r for r in a_rows_export(t) if r["id"] == edited)
        rel = str(row["file"])
        sim_ = t.env.at_base(rel).replace(str(row["anchor"]), str(row["anchor"]) + " x", 1)
        t2 = with_text(with_text(t, t.env.base, rel, sim_), HEAD_REF, rel, sim_)
    memo = dict(t2.env.memo)
    memo[f"show:{t.env.base}:{PINS_REL}"] = t.pins
    t2 = replace(t2, env=Env(t.env.base, memo))
    rows = a_rows_export(t2)
    c15, _ = apply_rows(t2.env.at_base(CAT_REL), [r for r in rows if r["file"] == CAT_REL])
    c14, _ = apply_rows(t2.env.at_base(SCR_REL), [r for r in rows if r["file"] == SCR_REL])
    pins, moves = record_moves(t2)
    changed = [SCR_REL, CAT_REL, *extra_changed] + (
        [PINS_REL] if moves and PINS_REL not in extra_changed else []
    )
    spec = t2.spec
    if sha_base:
        spec = re.sub(r"[0-9a-f]{10}<!--=SHA:BASE-->", f"{sha_base}<!--=SHA:BASE-->", spec)
    return replace(t2, spec=spec, cat15=c15 + extra15, cat14=c14, pins=pins, changed=changed)


def pr2_moved(
    t: Texts,
    unit_edit: bool = False,
    stray: bool = False,
    wrong_at: bool = False,
    hash_edit: str = "",
    drop: str = "",
) -> Texts:
    """PR 2 after a rebase that moved every D02 line down by one: the pins carry `@n` moves for
    the D02 cites; the merge-base holds PR 1's pins. The flags plant one defect each."""
    shifted = "added line\n" + t.env.at_base(PATHS["D02"])
    t2 = with_text(t, t.env.base, PATHS["D02"], shifted)
    t2 = with_text(t2, HEAD_REF, PATHS["D02"], shifted)
    t2 = pr2_texts(t2, extra_changed=(PINS_REL,))
    moved: dict[str, CitePin] = {}
    first = True
    for label, (h, at, hh) in cite_pins(t2.pins).items():
        m = re.fullmatch(r"D02:(\d+)(?:–(\d+))?", label)
        if m:
            a = int(m[1]) + 1
            b = (int(m[2]) if m[2] else int(m[1])) + 1
            if wrong_at and first:
                a, b, first = a + 1, b + 1, False
            moved[label] = (h, (a, b), hh)
        elif label == hash_edit:
            moved[label] = (h[::-1] if h[::-1] != h else "0" * len(h), at, hh)
        elif label == drop:
            continue
        else:
            moved[label] = (h, at, hh)
    us = parse_pins(t2.pins)
    if unit_edit and us:
        us[0] = (us[0][0], us[0][1], us[0][2] + " x")
    pins = write_pins(us, moved) + ("# a stray line\n" if stray else "")
    return replace(t2, pins=pins)


M = Mutation
# grouped by gate, in the tool's order; §M lists them under the same numbers (filled from here)
MUTATIONS: tuple[Mutation, ...] = (
    M("G-TABLE", "renumber BQ-25 in §R",
      subst("| BQ-25 | the nineteen contradictions", "| BQ-XX | the nineteen contradictions")),
    M("G-TABLE", "swap L-1's needle for one its cited line does not carry",
      subst("| L-1  | `E15-D10 draws this window` (`D04`:229)", "| L-1  | `E15-D10 paints this window` (`D04`:229)")),
    M("G-SLOTS", "drop the badge slot from F-1's bar",
      subst("| SL-1 SL-2 SL-3 SL-4 SL-5 SL-6 SL-7 SL-8 SL-9 (the full bar, W-0)", "| SL-1 SL-3 SL-4 SL-5 SL-6 SL-7 SL-8 SL-9 (the full bar, W-0)")),
    M("G-TITLE", "give the DEMO window a LIVE title",
      subst("| DEMO | DOM · BTCUSDT · DEMO            | SL-1 SL-2 SL-3 SL-4 SL-5 SL-6 SL-7 SL-8 SL-9                                  |",
            "| DEMO | DOM · BTCUSDT · LIVE            | SL-1 SL-2 SL-3 SL-4 SL-5 SL-6 SL-7 SL-8 SL-9                                  |")),
    M("G-TITLE", "drop the environment from the market window's title (a non-order kind)",
      subst("| DEMO | Tape · BTCUSDT · DEMO | SL-1 SL-2 SL-3 SL-4 SL-6 SL-7 SL-8 SL-9 at W-5",
            "| DEMO | Tape · BTCUSDT | SL-1 SL-2 SL-3 SL-4 SL-6 SL-7 SL-8 SL-9 at W-5")),
    M("G-BOUND", "type the title's bound by hand", anchor_edit("BOUND:chars", "99")),
    M("G-SWEEP", "type the full bar's width by hand", anchor_edit("SWEEP:order.compact.w0", "900")),
    M("G-CONTRAST", "alter a reproduced ratio by a hundredth", anchor_edit("CR:env.live.focused.dark", "4.41")),
    M("G-CHROME", "draw a lock on the pinned window's bar",
      subst("| SL-1 SL-2 SL-3 SL-4 SL-5 SL-6 SL-7 (pressed) SL-8 SL-9", "| SL-1 SL-2 SL-3 SL-4 SL-5 SL-6 SL-7 (pressed, with a lock) SL-8 SL-9")),
    M("G-SAFETY", "drop the badge from the unfocused frame's carriers",
      subst("on `color.surface.app`           | badge · arm · chip · banner slot (empty)              | dark compact     | 01    | `D13`:206–211; RULED BQ-06",
            "on `color.surface.app`           | arm · chip · banner slot (empty)              | dark compact     | 01    | `D13`:206–211; RULED BQ-06")),
    M("G-SAFETY", "weaken §4's rule",
      subst("**never under a scrim, never in a fading layer, never dimmed**", "**never under a scrim, never in a fading layer**")),
    M("G-R5", "weaken the standing R5 sentence",
      subst("never gates, hides or blocks cancel, close, flatten or set-or-tighten stop, and no window state",
            "never gates, hides or blocks cancel, close or flatten, and no window state")),
    M("G-STRING", "alter one word of S-5",
      subst("| S-5 | \"This window was on a display that's no longer connected, so it opened here.\"",
            "| S-5 | \"This window was on a display that's no longer connected, so it opened there.\"")),
    M("G-FRAMES", "point a state at a frame the register lacks",
      subst("| ST-6  | always-on-top on                                  | F-10", "| ST-6  | always-on-top on                                  | F-99")),
    M("G-FRAMES", "move the pinned frame to another board in the register alone",
      subst("| dark compact | 03 | `E10D03`:302; `NAMES`:404", "| dark compact | 05 | `E10D03`:302; `NAMES`:404")),
    M("G-CITE", "cite a line past the end of D02",
      subst("`D02`:201 (a leafless pane", "`D02`:9999 (a leafless pane")),
    M("G-CITE", "cite an unpinned line",
      subst("`D04`:234 (the compact view and its disarm; the kinds' minimums)", "`D04`:235 (the compact view and its disarm; the kinds' minimums)")),
    M("G-VERSION", "move the calendar's sprint length by one day at origin/main", head_sprint_days),
    M("G-AROW", "misquote A-4's Old by one letter",
      subst("| - **Props**: `title` · `environment: \"demo\"\\|\"live\"` · `onRedock` · `onClose` · `alwaysOnTop?: boolean`.",
            "| - **Props**: `title` · `environment: \"demo\"\\|\"live\"` · `onRedock` · `onClose` · `alwaysOnTop?: bool`.")),
    M("G-AROW", "drop PROPOSED from A-8's New",
      subst("the combined budget `14-screens-catalogue.md` SCR-027's (PROPOSED).", "the combined budget `14-screens-catalogue.md` SCR-027's.")),
    M("G-AROW", "point A-3's Field at the line before its anchor",
      subst("| `14`:673  | insert after |", "| `14`:672  | insert after |")),
    M("G-HYGIENE", "write a closing keyword against #364",
      subst("The closing line rides on PR 3 alone", "Closes #364")),
    M("G-HYGIENE", "leave a double-brace placeholder inside §0",
      subst("**Nothing here is built or published.**", "**Nothing here is built or published.** (`{{SHA:BASE}}`)")),
    M("G-HYGIENE", "simulate PR 2 with one byte more than §C in `15`", lambda t: pr2_texts(t, extra15="x")),
    M("G-HYGIENE", "simulate PR 2 with the spec changed beside the pins", lambda t: pr2_texts(t, extra_changed=(SPEC_REL, PINS_REL))),
    M("G-AROW+G-HYGIENE", "simulate PR 2 against a merge-base where a later PR edited A-6's line", lambda t: pr2_texts(t, edited="A-6")),
    M("G-HYGIENE", "simulate PR 2 with a pins rewrite that alters a unit, not a cite move", lambda t: pr2_moved(t, unit_edit=True)),
    M("G-HYGIENE", "simulate PR 2 with a stray line in the pins beside the recorded moves", lambda t: pr2_moved(t, stray=True)),
    M("G-HYGIENE", "simulate PR 2 with a recorded @n the cite's content does not stand at", lambda t: pr2_moved(t, wrong_at=True)),
    M("G-HYGIENE+G-CITE", "simulate PR 2 with one cite pin's hash changed", lambda t: pr2_moved(t, hash_edit="E10D03:302")),
    M("G-HYGIENE+G-CITE", "simulate PR 2 with one cite pin dropped", lambda t: pr2_moved(t, drop="CONST:158")),
    M("G-HYGIENE", "simulate PR 2 with a `SHA:BASE` record that is no ancestor of its base", lambda t: pr2_texts(t, sha_base="0000000000")),
    M("G-RULED-PIN", "re-word one pinned sentence of §3",
      subst("The spec writes no new string:", "The spec writes no string of its own:")),
)  # fmt: skip

NEGATIVES: tuple[tuple[str, Callable[[Texts], Texts]], ...] = (
    ("N-1 PR 2 with §C applied exactly on the base", lambda t: pr2_texts(t)),
    ("N-2 PR 2 after a rebase moved D02, the pins recording the moves", lambda t: pr2_moved(t)),
)


def mutation_paragraph_text() -> str:
    """§M's one paragraph, written from MUTATIONS so the list and the tool never drift."""
    gates = [g.__name__.upper().replace("G_", "G-") for g in GATES] + ["G-RULED-PIN"]
    parts: list[str] = []
    for gate in gates:
        items = [(i, m) for i, m in enumerate(MUTATIONS, 1) if m.gate.split("+")[0] == gate]
        parts.append(f"**{gate}** " + "; ".join(f"M-{i} {m.what}" for i, m in items) + ".")
    return (
        "Each M-n is a violation planted in memory; `--self-test` expects exactly one FAIL from the "
        "gate it names (two where a second gate must also see it), then restores every text byte for "
        f"byte; two negatives (PR 2 with §C applied exactly on the base; PR 2 after a rebase moved "
        f"D02, the pins recording the moves) must raise nothing. {len(MUTATIONS)} mutations, at least "
        "one per gate, grouped by gate in the tool's order: " + " ".join(parts)
    )


def digest(t: Texts) -> str:
    return hashlib.sha256((t.spec + "\0" + t.handoff + "\0" + t.pins).encode()).hexdigest()


def ascii_line(s: str) -> str:
    for a, b in (("→", "->"), ("›", ">"), ("…", "..."), ("—", "-"), ("–", "-"), ("×", "x"),
                 ("§", "S"), ("·", "|"), ("≤", "<="), ("≥", ">="), ("⋮", ":")):  # fmt: skip
        s = s.replace(a, b)
    return s.encode("ascii", "replace").decode()[:110]


def selftest() -> tuple[bool, list[str]]:
    t0 = time.perf_counter()
    base = replace(load(), changed=[SPEC_REL])
    disk = [hashlib.sha256(read_raw(r).encode()).hexdigest() for r in OWN_PATHS]
    before = digest(base)
    base_all = audit(base)
    base_found = [f for f in base_all if f.level == "FAIL"]
    drift = {(f.gate, f.msg) for f in base_all if f.level == "WARN"}
    out = [
        f"self-test: baseline {len(base_found)} FAIL, {len(drift)} WARN (drift, subtracted from the negatives)"
    ]
    ok = not base_found
    for f in base_found:
        out.append(ascii_line(f"  baseline {f.gate}: {f.msg}"))
    for i, m in enumerate(MUTATIONS, 1):
        fails = [f for f in audit(m.apply(base)) if f.level == "FAIL"]
        gates = sorted({f.gate for f in fails})
        good = bool(fails) and gates == sorted(m.gate.split("+"))
        ok &= good
        out.append(
            ascii_line(
                f"{'ok  ' if good else 'FAIL'} M-{i} {m.gate}: {m.what} -> {', '.join(gates) or 'none'}"
            )
        )
    for name, scenario in NEGATIVES:
        extra = [
            f
            for f in audit(scenario(base))
            if f.level in ("FAIL", "WARN") and (f.gate, f.msg) not in drift
        ]
        ok &= not extra
        shown = ", ".join(sorted({f"{f.gate} ({f.level})" for f in extra})) or "none"
        out.append(ascii_line(f"{'ok  ' if not extra else 'FAIL'} {name} -> {shown}"))
        for f in extra[:3]:
            out.append(ascii_line(f"      {f.gate}: {f.msg}"))
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
        and bool(set(TARGETS) & set(t.changed or []))
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
        print(json.dumps(a_rows_export(t), ensure_ascii=False, indent=2))
        return 0
    if a.repin_ruled:
        if unfilled(t.spec):
            print("refused: the spec has an unfilled placeholder (run --check --fill)")
            return 1
        other = [
            f
            for f in audit(t)
            if f.level == "FAIL"
            and f.gate not in ("G-RULED-PIN", "G-CITE")
            and not f.msg.startswith("cite ")
        ]
        if other:
            print(
                f"refused: {len(other)} FAIL outside the pins (first: {other[0].gate}: {other[0].msg[:80]}); fix them"
            )
            return 1
        if pr2_mode(t):
            pins, moves = record_moves(t)
            write_text(PINS_REL, pins)
            print(f"wrote {PINS_REL} (PR 2: {moves} cite move(s) recorded, units untouched)")
            return 0
        moved = [
            label_of(k, x, y) for k, x, y in all_cites(t) if resolve_cite(t, k, x, y)[2] == "moved"
        ]
        if moved:
            print(
                f"refused: {len(moved)} cite(s) moved; re-point them by content first ({moved[0]} ...)"
            )
            return 1
        write_text(PINS_REL, write_pins(pack_units(t), fresh_cite_pins(t)))
        print(f"wrote {PINS_REL}")
        return 0
    if a.fill:
        spec, miss = fill(t.spec, t.values)
        write_text(SPEC_REL, spec)
        for m in miss:
            print(f"unfilled: {m}")
        t = load()
    timings: dict[str, float] = {}
    found = audit(t, timings)
    fails = [f for f in found if f.level == "FAIL"]
    if a.json:
        dump = {"base": t.env.base, "values": {k: v for k, v in t.values.items() if k != "M:LIST"},
                "findings": [{"level": f.level, "gate": f.gate, "msg": f.msg} for f in found],
                "timings_ms": {k: round(v * 1000, 1) for k, v in timings.items()}}  # fmt: skip
        print(json.dumps(dump, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for ln in render(found):
            print(ln)
        notes = sum(f.level == "NOTE" for f in found)
        warns = sum(f.level == "WARN" for f in found)
        print(f"{len(fails)} FAIL / {warns} WARN / {notes} NOTE ({len(GATES) + 1} gates)")
        print("timings: " + " ".join(f"{k}={v * 1000:.0f}ms" for k, v in timings.items()) + f" total={sum(timings.values()) * 1000:.0f}ms")  # fmt: skip
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""E45-D02 (#1251) audit: the hi-fi spec, motion and hand-off of the discrepancy flow, and its
copy deck (SCR-143's Discrepancies view, confirms and tiles; SCR-144's drill rows; SCR-146).

Standalone and offline, shaped on the E45-D01 and E34-D05 tools. It reads the spec, the deck and
the pins from the working tree; every cited file AS TEXT with `git show` at the pinned base
(`BASE`); and E45-D01 at its review head (`D01_HEAD`, request row R-1). Default-deny: a gate that
cannot read its input FAILs.

Gates (each FAIL led by its name):
  G-DECK      the header names the fields, statuses and kinds; every row carries exactly those
              fields, a unique `e45.` id on its screen, a known kind and status, `frozen: true`,
              well-formed {slots}; every .one has its .other with the same slots; no row holds a
              never-word, a deny word or a credential-shaped value.
  G-SOURCE    a merged row stands on its cited line at the base (a "; condition" may follow the
              cite); an E45-D01 row stands in its cited row or section at D01_HEAD; RULED is K-05
              alone; the E45-D02 rows are exactly the ids §11's list paragraph names.
  G-FRAMES    §0 maps H01 … H28 one to one onto D01's drawn frames W01 … W28 by name; widths are
              1280 or "1280, 1920"; the stated total equals 2 × the frames at each width.
  G-BOARDS    BQ-02: at most ten boards, light twins at most a third of them; the dark 1280 boards
              hold every H-row once, the dark 1920 board the width-bearing ones, each light board
              twins a dark one; every H-row's "Drawn on" and §0's counts follow from the boards.
  G-TOKEN     every token the spec names exists at the base; the disabled text token and the
              disabled opacity appear only on a "never" line; no raw hex value.
  G-CONTRAST  every CR-row recomputed from the token JSON (dark, light, high contrast) equals the
              spec to 0.01 and meets its bar; the T2, danger and focus pairs are present.
  G-MOTION    every M-row moves only `opacity` or `transform` or is a status (one frame / a cut,
              the same when reduced); each is PROPOSED and names its duration token or "no
              duration token"; the ticket's transitions are present; `16`:259 is quoted.
  G-PROTECT   C-2.6: §1 quotes `22`:17468; Attach takes no code; Cancel at Bybit and Attach stay
              enabled under §5.3; no line gates either; the reassurance is conditioned on no
              missing_native_sl row in §1 and on its deck row.
  G-ENFORCE   C-2.21: no deck string says the UI unlocks, blocks, prevents or enforces; §1 item 2.
  G-T2        §1 quotes G-T2.1b and G-T2.3 verbatim and names the CMP-019 `lock`; every row that
              shows T2 names its rendering; §4 lists CMP-079 and the lock; T-09 binds G-T2.2;
              every gated frame names its T2 (G-T2.6); §4 maps Re-read, Re-run and the toggle.
  G-LADDER    BQ-03: §4 gives CMP-044 `variant="standard"`, an explicit `confirmVariant` and no
              `rung`; C-3 and C-4 cite the ladder lines and are PROPOSED to their owners.
  G-REQUEST   R6: #5776, #5182, #1220 and #5233 appear only on an R-row, a G-row, the pre-stage
              paragraph or a line that points at an R-row.
  G-CITE      every cite in range, non-blank at its base, and equal to the pins.
  G-HYGIENE   no closing keyword, local path, URL or host, agent name or double-brace slot; no
              deny word in the spec, the deck, this tool or the pins.
  G-SCOPE     the diff touches only the spec, the deck, this tool and the pins.

Usage (from the repo root):
  python3 -I docs/design/_tools/e45_d02_handoff_audit.py --check
  python3 -I docs/design/_tools/e45_d02_handoff_audit.py --self-test
  python3 -I docs/design/_tools/e45_d02_handoff_audit.py --repin-ruled (the pins' only writer)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SPEC_REL = "docs/design/E45/E45-D02.md"
DECK_REL = "docs/design/E45/E45-D02-copy-deck.jsonl"
TOOL_REL = "docs/design/_tools/e45_d02_handoff_audit.py"
PINS_REL = "docs/design/_tools/e45_d02_ruled_pins.txt"
OWN_PATHS = (SPEC_REL, DECK_REL, TOOL_REL, PINS_REL)
BASE = "62089f77c77be246d1d37c300eae3c51f1607c46"  # origin/main when written; re-pinned by content
D01_HEAD = "e3ff07d71237304572025535eec8a6da1659a865"  # #5776 head (R-1); re-pin at its merge
D01_REL = "docs/design/E45/E45-D01.md"
PATHS: dict[str, str] = {
    "05": "docs/plan/05-accessibility-standard.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "15": "docs/plan/15-component-catalogue.md",
    "16": "docs/plan/16-design-system-brief.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "24": "docs/plan/24-internal-schemas.md",
    "E29D03": "docs/design/E29/E29-D03.md",
    "E42D02": "docs/design/E42/E42-D02.md",
    "E42D04": "docs/design/E42/E42-D04.md",
    "DS": ".claude/rules/32-design-specs.md",
}
TOKENS = "packages/ui/tokens"
THEMES = {
    "dark": ("primitives", "semantic-dark"),
    "light": ("primitives", "semantic-dark", "semantic-light"),
    "hc": ("primitives", "semantic-dark", "semantic-hc"),
}
BARS = {"text": 4.5, "ui": 3.0}
BOARD_CAP = 10  # the standing cap (BQ-02): ten boards, light twins at most a third
CITE = re.compile(r"`(\d\d|E29D03|E42D02|E42D04|DS)`:(\d+(?:–\d+)?(?:, :\d+(?:–\d+)?)*)")
TOKEN_RX = re.compile(
    r"`((?:color|space|type|radius|elevation|motion|size|border|opacity|font)\.[a-z0-9.-]+)`"
)
FIELDS = ["id", "screen", "kind", "text", "status", "owner", "source", "consumer", "frozen"]
STATUSES = ["merged", "RULED", "PROPOSED"]
SCREENS = {"s143": "SCR-143", "s144": "SCR-144", "s146": "SCR-146"}
ID_RX = re.compile(r"e45\.(s14[346])\.[a-z0-9_.]+")
SLOT = re.compile(r"\{([a-z_]+)\}")
RULED_SOURCES = {"E45-D01 K-05"}
REQUIRED_PAIRS = {
    ("color.text.tertiary", "color.surface.raised"),
    ("color.text.secondary", "color.surface.raised"),
    ("color.text.on-action", "color.status.danger.default"),
    ("color.focus.ring", "color.surface.overlay"),
}
TRANSITIONS = ("starts resolving", "new discrepancy row arrives", "healthy → degraded → stale",
               "confirm enters", "confirm exits")  # fmt: skip
PROTECTIVE = re.compile(
    r"(Cancel at Bybit|Cancel at exchange|Attach stop|Attach protective stop now)[^|.]*\b"
    r"(T2|disabled|gated|locked)\b"
)
ENFORCE = re.compile(r"\b(unlock|enforc|prevent|block)", re.IGNORECASE)
RENDERING = re.compile(r"rendering (2a|2b|the sentence form)")
GATED_FRAMES = ("H09", "H12", "H14", "H15", "H16", "H26")
REQUESTS = ("#5776", "#5182", "#1220", "#5233")
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE)
LOCAL_PATH = re.compile("/" + "home/|/Users/|/" + "tmp/|[A-Za-z]:\\\\|\\bnotes/")  # assembled
AGENT_NAME = re.compile(r"\b[a-z]{2,9}-worker-\d\b")
URL_OR_HOST = re.compile(r"https?://|penpot\.[a-z]|team-id=|file-id=", re.IGNORECASE)
HEX = re.compile(r"#[0-9A-Fa-f]{6}\b")
DENY = (
    "le" + "ak", "expo" + "sed", "by" + "pass", "ex" + "ploit", "att" + "ack", "ora" + "cle",
    "rev" + "eal", "unbou" + "nded", "flo" + "od", "st" + "all", "advi" + "sory", "gh" + "sa",
    "pre-" + "auth",
)  # fmt: skip
DENY_WORD = re.compile(r"\bd" + r"os\b", re.IGNORECASE)
CRED_RUN = re.compile(r"(?<![A-Za-z0-9])(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{20,}")
CRED_NAMED = re.compile(
    r"x-bapi-|api_key\s*[:=]|\bsign=|\bbearer\s+[A-Za-z0-9._~+/-]{8,}", re.IGNORECASE
)


@dataclass(frozen=True)
class Texts:
    spec: str
    deck: str
    pins: str
    tool: str
    changed: list[str] | None
    memo: dict[str, str | None]


def git(*args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, check=False)
    except OSError:
        return None
    return r.stdout.decode("utf-8", "surrogateescape") if r.returncode == 0 else None


def show(t: Texts, rev: str, rel: str) -> str:
    memo_key = f"{rev}:{rel}"
    if memo_key not in t.memo:
        t.memo[memo_key] = git("show", memo_key)
    text = t.memo[memo_key]
    if text is None:
        raise LookupError(f"{rel} does not resolve at {rev[:10]}; fetch first")
    return text


def at(t: Texts, key: str) -> str:
    return show(t, BASE, PATHS[key])


def d01(t: Texts) -> str:
    return show(t, D01_HEAD, D01_REL)


def norm(s: str) -> str:
    return " ".join(s.split())


def table_rows(text: str, lead: str) -> list[list[str]]:
    return [
        [c.strip() for c in ln.strip().strip("|").split("|")]
        for ln in text.split("\n")
        if ln.startswith("| " + lead)
    ]


def section(text: str, head: str) -> str:
    i = text.find("\n" + head)
    if i < 0:
        raise LookupError(f"no `{head}` section")
    depth = head.split(" ")[0]
    j = text.find("\n" + depth + " ", i + 1)
    return text[i : j if j > 0 else len(text)]


def matches(text: str, where: str) -> bool:
    """A slot matches itself or up to 40 characters with no brace, pipe or quote."""
    bits = SLOT.split(norm(text))
    rx = "".join(
        re.escape(b) if i % 2 == 0 else r"(?:\{" + b + r"\}|[^{}|\"]{1,40}?)"
        for i, b in enumerate(bits)
    )
    return re.search(rx, norm(where)) is not None


# ---------------------------------------------------------------------------- deck


def deck_rows(t: Texts) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    lines = [ln for ln in t.deck.split("\n") if ln.strip()]
    if not lines:
        raise LookupError("the deck is empty")
    try:
        parsed = [json.loads(ln) for ln in lines]
    except json.JSONDecodeError as e:
        raise LookupError(f"the deck is not JSONL: {e}") from e
    return parsed[0], parsed[1:]


def g_deck(t: Texts) -> list[str]:
    bad = []
    head, rows = deck_rows(t)
    if head.get("fields") != FIELDS or head.get("statuses") != STATUSES:
        bad.append("the header does not name the fields and statuses")
    kinds, never = set(head.get("kinds", [])), [w.lower() for w in head.get("never", [])]
    seen: set[str] = set()
    for r in rows:
        rid = str(r.get("id"))
        if list(r) != FIELDS:
            bad.append(f"{rid}: fields are not {FIELDS}")
            continue
        m = ID_RX.fullmatch(rid)
        if not m or SCREENS[m[1]] != r["screen"]:
            bad.append(f"{rid}: not an `e45.` id on its own screen")
        if rid in seen:
            bad.append(f"{rid}: id twice")
        seen.add(rid)
        if r["kind"] not in kinds or r["status"] not in STATUSES or r["frozen"] is not True:
            bad.append(f"{rid}: kind, status or frozen is not allowed")
        text = str(r["text"])
        if not text or SLOT.sub("", text).count("{") or SLOT.sub("", text).count("}"):
            bad.append(f"{rid}: empty text or a malformed slot")
        low = text.lower()
        if any(w in low for w in never) or any(d in low for d in DENY) or DENY_WORD.search(text):
            bad.append(f"{rid}: carries a never-word or a deny word")
        if CRED_RUN.search(text) or CRED_NAMED.search(text):
            bad.append(f"{rid}: carries a credential-shaped value")
    texts = {str(r.get("id")): str(r.get("text")) for r in rows}
    for rid, text in texts.items():
        for a, b in ((".one", ".other"), (".other", ".one")):
            if rid.endswith(a):
                twin = rid[: -len(a)] + b
                if twin not in texts:
                    bad.append(f"{rid}: no {b} twin")
                elif a == ".one" and set(SLOT.findall(text)) - set(SLOT.findall(texts[twin])):
                    bad.append(f"{rid}: its slots are not in {twin}")
    plural = [r for r in rows if str(r.get("id")).endswith((".one", ".other"))]
    bad += [f"{r['id']}: a plural row is not PROPOSED" for r in plural if r["status"] != "PROPOSED"]
    return bad


def d01_place(t: Texts, ref: str) -> str:
    doc = d01(t)
    if ref.startswith("§"):
        num = ref[1:]
        return section(doc, ("### " if "." in num else "## ") + num + ("" if "." in num else "."))
    rows = table_rows(doc, ref + " ")
    if len(rows) != 1:
        raise LookupError(f"E45-D01 carries {len(rows)} `{ref}` rows at {D01_HEAD[:10]}")
    return " | ".join(rows[0])


def g_source(t: Texts) -> list[str]:
    bad = []
    _, rows = deck_rows(t)
    eleven = section(t.spec, "## 11.")
    i = eleven.find("The rows this ticket adds")
    if i < 0:
        raise LookupError("§11 has no list of the rows this ticket adds")
    j = eleven.find("\n\n", eleven.find("\n\n", i) + 2)
    listed = set(re.findall(r"`(e45\.[a-z0-9_.]+)`", eleven[i : j if j > 0 else len(eleven)]))
    own = {str(r["id"]) for r in rows if r.get("owner") == "E45-D02"}
    for rid in sorted(own ^ listed):
        bad.append(f"{rid}: E45-D02 rows and §11's list differ")
    for r in rows:
        rid, src, status = str(r.get("id")), str(r.get("source")), r.get("status")
        if (status == "RULED") != (src in RULED_SOURCES):
            bad.append(f"{rid}: RULED is K-05 alone")
        if status == "merged":
            m = re.fullmatch(r"(\d\d|E29D03|E42D02|DS):(\d+)(?:; .+)?", src)
            if not m:
                bad.append(f"{rid}: a merged row cites no `KEY:line`")
                continue
            ls = at(t, m[1]).split("\n")
            n = int(m[2])
            if not 0 < n <= len(ls) or not matches(str(r["text"]), ls[n - 1]):
                bad.append(f"{rid}: does not stand on {src} at the base")
        elif r.get("owner") == "E45-D01":
            if not src.startswith("E45-D01 "):
                bad.append(f"{rid}: an E45-D01 row cites no E45-D01 place")
            elif not matches(str(r["text"]), d01_place(t, src[8:])):
                bad.append(f"{rid}: does not stand in {src} at {D01_HEAD[:10]}")
        elif r.get("owner") == "E45-D02" and not re.fullmatch(r"D02 §\d+(\.\d+)?", src):
            bad.append(f"{rid}: an E45-D02 row cites no section of this spec")
    return bad


# ---------------------------------------------------------------------------- frames, tokens


def g_frames(t: Texts) -> list[str]:
    bad = []
    zero = section(t.spec, "## 0.")
    hs = [r for r in table_rows(zero, "H") if re.fullmatch(r"H\d\d", r[0])]
    w01 = {r[0]: r[1] for r in table_rows(section(d01(t), "## 0."), "W") if "to draw" in r[-1]}
    if [r[0] for r in hs] != [f"H{i:02d}" for i in range(1, len(hs) + 1)]:
        bad.append("§0's H-rows are not H01 … in order")
    mapped = [r[1] for r in hs]
    if sorted(mapped) != sorted(w01):
        bad.append(f"§0 maps {len(set(mapped))} D01 frames, not D01's {len(w01)} drawn ones")
    for r in hs:
        if r[1] in w01 and r[2] != w01[r[1]]:
            bad.append(f"{r[0]}: its name is not D01's {r[1]}")
        if r[3] not in ("1280", "1280, 1920"):
            bad.append(f"{r[0]}: widths `{r[3]}`")
    wide = sum(1 for r in hs if r[3] == "1280, 1920")
    total = re.search(r"\*\*Total: (\d+) frames\*\* \((\d+) × 2 themes at 1280, plus (\d+) ×", zero)
    if not total or (int(total[1]), int(total[2]), int(total[3])) != (
        2 * (len(hs) + wide),
        len(hs),
        wide,
    ):
        bad.append(f"§0's total is not {2 * (len(hs) + wide)} ({len(hs)} + {wide} at 1920)")
    return bad


def g_boards(t: Texts) -> list[str]:
    bad = []
    zero = section(t.spec, "## 0.")
    hs = {r[0]: r for r in table_rows(zero, "H") if re.fullmatch(r"H\d\d", r[0])}
    bs = [r for r in table_rows(zero, "B-") if len(r) == 5]
    light = [b for b in bs if b[1] == "light"]
    if len(bs) > BOARD_CAP:
        bad.append(f"{len(bs)} boards, over the cap of {BOARD_CAP}")
    if 3 * len(light) > len(bs):
        bad.append(f"{len(light)} light twins on {len(bs)} boards, over a third")
    frames = {b[0]: re.findall(r"H\d\d", b[4]) for b in bs}
    dark = {b[3]: frames[b[0]] for b in bs if b[1:3] == ["dark", "1280"]}
    if sorted(h for fs in dark.values() for h in fs) != sorted(hs):
        bad.append("the dark 1280 boards do not hold every H-row once")
    wide = sorted(h for h, r in hs.items() if r[3] == "1280, 1920")
    if sorted({h for b in bs if b[1:3] == ["dark", "1920"] for h in frames[b[0]]}) != wide:
        bad.append("the dark 1920 boards do not hold exactly the width-bearing frames")
    for b in light:
        if b[2] != "1280" or frames[b[0]] != dark.get(b[3]):
            bad.append(f"{b[0]} is not a light twin of D01 board {b[3]}")
    for h, r in hs.items():
        on = ", ".join(b[0] for b in bs if h in frames[b[0]])
        if r[4] != on:
            bad.append(f"{h}: drawn on `{r[4]}`, the boards say `{on}`")
    drawn = {(b[1], b[2], h) for b in bs for h in frames[b[0]]}
    total = 2 * (len(hs) + len(wide))
    m = re.search(r"\*\*Boards: (\d+)\*\*.*?\*\*Drawn: (\d+) frames\. Bound as text: (\d+)", zero)
    if not m or (int(m[1]), int(m[2]), int(m[3])) != (len(bs), len(drawn), total - len(drawn)):
        bad.append(
            f"§0 does not state {len(bs)} boards, {len(drawn)} drawn, {total - len(drawn)} text"
        )
    return bad


def token_values(t: Texts, theme: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name in THEMES[theme]:
        raw = json.loads(show(t, BASE, f"{TOKENS}/{name}.tokens.json"))
        out |= {k: v["$value"] for k, v in raw.items() if isinstance(v, dict) and "$value" in v}
    return out


def g_token(t: Texts) -> list[str]:
    bad = []
    names = set().union(*(token_values(t, th) for th in THEMES))
    for i, ln in enumerate(t.spec.split("\n"), 1):
        for name in TOKEN_RX.findall(ln):
            if name not in names:
                bad.append(f"spec:{i} names `{name}`, which the base does not define")
        if re.search(r"color\.text\.disabled|opacity\.disabled", ln) and "never" not in ln:
            bad.append(f"spec:{i} binds a disabled token")
        if HEX.search(ln):
            bad.append(f"spec:{i} carries a raw colour value")
    return bad


def resolve(vals: dict[str, Any], name: str) -> str:
    v = vals[name]
    for _ in range(12):
        if not (isinstance(v, str) and v.startswith("{")):
            return str(v)
        v = vals[v[1:-1]]
    raise LookupError(f"{name} does not resolve")


def ratio(a: str, b: str) -> float:
    def lum(h: str) -> float:
        c = [int(h.lstrip("#")[i : i + 2], 16) / 255 for i in (0, 2, 4)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    la, lb = lum(a), lum(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def g_contrast(t: Texts) -> list[str]:
    bad = []
    vals = {th: token_values(t, th) for th in THEMES}
    pairs = set()
    for r in table_rows(t.spec, "CR-"):
        names = re.findall(r"`([a-z0-9.-]+)`", r[1])
        if len(names) != 2 or r[3] not in BARS or len(r) != 7:
            bad.append(f"{r[0]}: not `fg` on `bg` with a bar and three themes")
            continue
        pairs.add((names[0], names[1]))
        for th, cell in zip(THEMES, r[4:7], strict=True):
            try:
                v = ratio(resolve(vals[th], names[0]), resolve(vals[th], names[1]))
            except KeyError as e:
                bad.append(f"{r[0]}: {e} is not a token in {th}")
                continue
            if f"{v:.2f}" != cell:
                bad.append(f"{r[0]} {th}: the base computes {v:.2f}, the spec says {cell}")
            if v < BARS[r[3]]:
                bad.append(f"{r[0]} {th}: {v:.2f} is under the {r[3]} bar")
    bad += [f"the pair {a} on {b} is not measured" for a, b in sorted(REQUIRED_PAIRS - pairs)]
    return bad


# ---------------------------------------------------------------------------- behaviour


def g_motion(t: Texts) -> list[str]:
    bad = []
    seven = section(t.spec, "## 7.")
    rows = table_rows(seven, "M-")
    for r in rows:
        prop, safe, reduce = r[2], r[3], r[4]
        if not prop.startswith(("none", "`opacity`", "`transform`")):
            bad.append(f"{r[0]} moves `{prop}`, not opacity or transform")
        if prop.startswith("none") and (
            not re.search(r"one frame|a cut", safe) or reduce != "the same"
        ):
            bad.append(f"{r[0]} is a status but animates or differs when reduced")
        if not reduce:
            bad.append(f"{r[0]} has no reduced-motion twin")
        if not CITE.search(r[-1]) or "PROPOSED" not in r[-1]:
            bad.append(f"{r[0]} cites no `16` row or is not marked PROPOSED")
        if "`motion.duration." not in safe and "no duration token" not in safe:
            bad.append(f"{r[0]} names no duration token")
        for name in TOKEN_RX.findall(safe):
            if not name.startswith("motion."):
                bad.append(f"{r[0]} times itself with `{name}`")
    for need in TRANSITIONS:
        if not any(need in r[1] for r in rows):
            bad.append(f"§7 has no row for `{need}`")
    rule = norm(at(t, "16").split("\n")[258])
    quote = "a status change is applied in the frame it is known and never animated"
    if quote not in rule or quote.capitalize() + " (`16`:259)" not in seven:
        bad.append("§7 does not quote `16`:259's rule")
    if "nothing beneath it moves or speaks" not in seven:
        bad.append("§7 lets the view move or speak under an open confirm")
    return bad


def g_protect(t: Texts) -> list[str]:
    bad = []
    one = section(t.spec, "## 1.")
    quote = "attaching a missing native SL, tightening a stop or re-arming a protective trigger"
    if quote not in one or quote not in at(t, "22").split("\n")[17467]:
        bad.append("§1 item 3 does not quote `22`:17468's carve-out")
    if not one_cell(t.spec, "CF-03", 4).startswith("none"):
        bad.append("CF-03 asks a code before attaching a stop")
    if "For CF-01 and CF-03 the line is text only and the confirm stays enabled" not in t.spec:
        bad.append("§5.3 does not keep Cancel at Bybit and Attach enabled")
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if PROTECTIVE.search(ln) and "never" not in ln:
            bad.append(f"spec:{i} gates a protective action")
    if "is said for an account only while that account has no `missing_native_sl` row" not in one:
        bad.append("§1 does not hold the reassurance to accounts with no missing stop")
    _, rows = deck_rows(t)
    src = next((str(r["source"]) for r in rows if r.get("id") == "e45.s143.disc.reassure"), "")
    if "only while the account has no missing_native_sl row" not in src:
        bad.append("e45.s143.disc.reassure carries no missing-stop condition")
    return bad


def one_cell(text: str, lead: str, col: int) -> str:
    rows = table_rows(text, lead + " ")
    if len(rows) != 1:
        raise LookupError(f"the spec carries {len(rows)} `{lead}` rows, not 1")
    return rows[0][col]


def g_enforce(t: Texts) -> list[str]:
    _, rows = deck_rows(t)
    bad = [f"{r['id']}: claims the UI enforces" for r in rows if ENFORCE.search(str(r["text"]))]
    if "(C-2.21).** No string or frame says this screen locks" not in section(t.spec, "## 1."):
        bad.append("§1 item 2 (statecharts record, synchronous code enforces) is missing")
    return bad


def g_t2(t: Texts) -> list[str]:
    bad = []
    ds = at(t, "DS").split("\n")
    one = norm(section(t.spec, "## 1."))
    for n, lead, cut in ((28, "`aria-disabled", None), (47, "`Enter`", "; arrow keys")):
        src = norm(ds[n - 1] + " " + ds[n])
        quote = src[src.find(lead) :]
        quote = quote.split(cut)[0] if cut else quote.rstrip(".")
        if quote not in one:
            bad.append(f"§1 item 6 does not quote `DS`:{n} verbatim")
    if "CMP-019 `lock`" not in one:
        bad.append("§1 item 6 does not name the CMP-019 `lock`")
    ls = t.spec.split("\n")
    for i, ln in enumerate(ls[:-1]):
        if not ln.startswith("| ") or ln.startswith("| CR-") or ls[i + 1].startswith("| ---"):
            continue
        if re.search(r"\bT2\b", ln) and not RENDERING.search(ln) and "never T2" not in ln:
            bad.append(f"spec:{i + 1} shows T2 and names no rendering")
    four = section(t.spec, "## 4.")
    gate_row = one_cell(four, "T2", 1)
    if "CMP-079" not in gate_row or "CMP-019 `lock`" not in gate_row:
        bad.append("§4 does not list CMP-079 and the CMP-019 `lock` (G-T2.6)")
    for h in GATED_FRAMES:
        if not RENDERING.search(one_cell(t.spec, h, 5)):
            bad.append(f"{h} shows a gated control and names no T2 rendering (G-T2.6)")
    for lead in ("Re-read", "Re-run reconciliation", "Include drills"):
        if not table_rows(four, lead):
            bad.append(f"§4 has no row for {lead}")
    t09 = one_cell(t.spec, "T-09", 2)
    if "`color.text.tertiary`" not in t09 or "reason `color.text.secondary`" not in t09:
        bad.append("T-09 does not bind G-T2.2's label and reason tokens")
    return bad


def g_ladder(t: Texts) -> list[str]:
    bad = []
    confirm = " ".join(one_cell(section(t.spec, "## 4."), "confirms", 2).split())
    for need in ('`variant="standard"`', "explicit `confirmVariant`", "no `rung`"):
        if need not in confirm:
            bad.append(f"§4 does not give CMP-044 {need} (BQ-03)")
    for c, cite, owner in (("C-3", "`E42D04`:201", "E42-D04"), ("C-4", "`E42D02`:174", "E42-D02")):
        rows = table_rows(t.spec, c + " ")
        if len(rows) != 1 or cite not in rows[0][1] or f"PROPOSED to {owner}" not in rows[0][2]:
            bad.append(f"{c} does not record the ladder departure at {cite}, PROPOSED to {owner}")
    return bad


def g_request(t: Texts) -> list[str]:
    bad = []
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if not any(r in ln for r in REQUESTS):
            continue
        if ln.startswith(("| R-", "| G-", "**Pre-stage.**")) or re.search(r"\(R-\d\)", ln):
            continue
        bad.append(f"spec:{i} cites unmerged work outside a request row")
    return bad


# ---------------------------------------------------------------------------- cites, hygiene


def cites(text: str) -> list[tuple[str, int, int]]:
    out = []
    for m in CITE.finditer(text):
        for part in m[2].split(", :"):
            a, _, b = part.partition("–")
            out.append((m[1], int(a), int(b or a)))
    return out


def cite_hashes(t: Texts) -> tuple[dict[str, str], list[str]]:
    hashes: dict[str, str] = {}
    bad: list[str] = []
    for key, a, b in cites(t.spec):
        label = f"{key}:{a}" if a == b else f"{key}:{a}–{b}"
        if label in hashes:
            continue
        ls = at(t, key).split("\n")
        if not 0 < a <= b <= len(ls):
            bad.append(f"{label} is past the end of {PATHS[key]} ({len(ls)} lines)")
            continue
        if not ls[a - 1].strip() or not ls[b - 1].strip():
            bad.append(f"{label}: a cited line is blank at its base")
            continue
        joined = norm(ls[a - 1]) + "\n" + norm(ls[b - 1])
        hashes[label] = hashlib.sha256(joined.encode()).hexdigest()[:12]
    return hashes, bad


def g_cite(t: Texts) -> list[str]:
    hashes, bad = cite_hashes(t)
    pinned = {}
    for ln in t.pins.split("\n"):
        parts = ln.split("\t")
        if len(parts) == 2 and not ln.startswith("#"):
            pinned[parts[0]] = parts[1]
    for label, h in hashes.items():
        if label not in pinned:
            bad.append(f"cite {label} is unpinned: verify it by content, then --repin-ruled")
        elif pinned[label] != h:
            bad.append(f"cite {label}: the line at its base is not the pinned content")
    return bad


def g_hygiene(t: Texts) -> list[str]:
    bad = []
    checks = ((CLOSING, "a closing keyword (PR 2 alone closes #1251)"), (LOCAL_PATH, "a local path"),
              (AGENT_NAME, "an agent name"), (URL_OR_HOST, "a URL or a host"))  # fmt: skip
    for label, text in (("spec", t.spec), ("deck", t.deck)):
        for i, ln in enumerate(text.split("\n"), 1):
            for rx, what in checks:
                if rx.search(ln):
                    bad.append(f"{label}:{i} carries {what}")
            if "{{" in ln:
                bad.append(f"{label}:{i} carries a double-brace slot")
    for label, text in (("spec", t.spec), ("deck", t.deck), ("tool", t.tool), ("pins", t.pins)):
        for i, ln in enumerate(text.split("\n"), 1):
            if any(d in ln.lower() for d in DENY) or DENY_WORD.search(ln):
                bad.append(f"{label}:{i} carries a public-text deny word")
    return bad


def g_scope(t: Texts) -> list[str]:
    if t.changed is None:
        return ["cannot list the changed paths (git failed)"]
    own = ", ".join(OWN_PATHS)
    return [f"{p} is touched; this PR owns {own}" for p in t.changed if p not in OWN_PATHS]


GATES: dict[str, Callable[[Texts], list[str]]] = {
    "G-DECK": g_deck, "G-SOURCE": g_source, "G-FRAMES": g_frames, "G-BOARDS": g_boards,
    "G-TOKEN": g_token,
    "G-CONTRAST": g_contrast, "G-MOTION": g_motion, "G-PROTECT": g_protect,
    "G-ENFORCE": g_enforce, "G-T2": g_t2, "G-LADDER": g_ladder, "G-REQUEST": g_request,
    "G-CITE": g_cite,
    "G-HYGIENE": g_hygiene, "G-SCOPE": g_scope,
}  # fmt: skip


def audit(t: Texts) -> list[tuple[str, str]]:
    out = []
    for g, fn in GATES.items():
        try:
            out += [(g, m) for m in fn(t)]
        except (LookupError, KeyError, ValueError, IndexError) as e:
            out.append((g, f"{type(e).__name__}: {e}"))
    return out


# ---------------------------------------------------------------------------- load, self-test


def changed_paths() -> list[str] | None:
    mb = git("merge-base", "HEAD", "origin/main")
    if not mb:
        return None
    a = git("diff", "--name-only", mb.strip())
    b = git("status", "--porcelain", "--untracked-files=all")
    if a is None or b is None:
        return None
    out = {p for p in a.split("\n") if p}
    out |= {ln[3:].split(" -> ")[-1].strip('"') for ln in b.split("\n") if len(ln) > 3}
    return sorted(out)


def load() -> Texts:
    def read(rel: str) -> str:
        p = ROOT / rel
        return p.read_text(encoding="utf-8") if p.exists() else ""

    return Texts(read(SPEC_REL), read(DECK_REL), read(PINS_REL), read(TOOL_REL), changed_paths(),
                 {})  # fmt: skip


def sub(old: str, new: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        if t.spec.count(old) != 1:
            raise SystemExit(f"self-test: the spec carries {old[:50]!r} {t.spec.count(old)} times")
        return replace(t, spec=t.spec.replace(old, new))

    return f


def set_cell(lead: str, col: int, value: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        ls = t.spec.split("\n")
        i = next(k for k, ln in enumerate(ls) if ln.startswith(f"| {lead} "))
        cells = [c.strip() for c in ls[i].strip().strip("|").split("|")]
        cells[col] = value
        ls[i] = "| " + " | ".join(cells) + " |"
        return replace(t, spec="\n".join(ls))

    return f


def drop_row(lead: str) -> Callable[[Texts], Texts]:
    return lambda t: replace(
        t, spec="\n".join(x for x in t.spec.split("\n") if not x.startswith(lead))
    )


def add_line(text: str) -> Callable[[Texts], Texts]:
    return lambda t: replace(t, spec=t.spec + "\n" + text + "\n")


def deck_edit(rid: str, field: str, value: Any) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        out = []
        for ln in t.deck.split("\n"):
            if ln.startswith('{"id": "' + rid + '"'):
                row = json.loads(ln)
                row[field] = value
                ln = json.dumps(row, ensure_ascii=False)
            out.append(ln)
        return replace(t, deck="\n".join(out))

    return f


def insert_after(lead: str, rows: str) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        ls = t.spec.split("\n")
        i = next(k for k, ln in enumerate(ls) if ln.startswith(f"| {lead} "))
        return replace(t, spec="\n".join([*ls[: i + 1], rows, *ls[i + 1 :]]))

    return f


def chain(*fns: Callable[[Texts], Texts]) -> Callable[[Texts], Texts]:
    def f(t: Texts) -> Texts:
        for fn in fns:
            t = fn(t)
        return t

    return f


def deck_drop(rid: str) -> Callable[[Texts], Texts]:
    return lambda t: replace(
        t, deck="\n".join(x for x in t.deck.split("\n") if not x.startswith('{"id": "' + rid + '"'))
    )


MUTATIONS: tuple[tuple[str, str, Callable[[Texts], Texts]], ...] = (
    ("G-DECK", "unfreeze a row", deck_edit("e45.s143.disc.sending", "frozen", False)),
    ("G-DECK", "break a slot", deck_edit("e45.s143.tile.count.one", "text", "{n discrepancy")),
    ("G-DECK", "give a .one a slot its .other lacks", deck_edit("e45.s143.tile.count.one", "text", "{n} discrepancy on {account}")),
    ("G-DECK", "write a never-word", deck_edit("e45.s143.confirm.force.button", "text", "Flatten")),
    ("G-DECK", "put a row on the wrong screen", deck_edit("e45.s144.drills.badge", "screen", "SCR-143")),
    ("G-SOURCE", "misquote a merged line", deck_edit("e45.s143.confirm.stepup.line", "text", "This needs a fresh code.")),
    ("G-SOURCE", "misquote an E45-D01 string", deck_edit("e45.s143.confirm.cancel.body", "text", "Cancel order {order_id} on {account}. This removes a live order at Bybit.")),
    ("G-SOURCE", "mark a PROPOSED row RULED", deck_edit("e45.s143.disc.unknown", "status", "RULED")),
    ("G-SOURCE", "drop a row §11 lists", deck_drop("e45.s143.disc.delta.higher")),
    ("G-SOURCE", "leave an E45-D02 row out of §11", sub("`e45.s143.tile.count.one`, ", "")),
    ("G-FRAMES", "drop a frame", chain(drop_row("| H17 "), *(set_cell(b, 4, "H11, H12, H13, H14, H15, H16") for b in ("B-3", "B-7")), sub("**Drawn: 56 frames.", "**Drawn: 54 frames."))),
    ("G-FRAMES", "rename a frame away from D01", set_cell("H05", 2, "`SCR-143/discrepancies/dense`")),
    ("G-FRAMES", "misstate the total", sub("**Total: 72 frames**", "**Total: 70 frames**")),
    ("G-BOARDS", "draw an eleventh board", chain(insert_after("B-9", "| B-10 | dark | 1920 | — | — |\n| B-11 | dark | 1920 | — | — |"), sub("**Boards: 9**", "**Boards: 11**"))),
    ("G-BOARDS", "draw a fourth light twin", chain(insert_after("B-9", "| B-10 | light | 1280 | 1 | H01, H02, H03, H04, H05 |"), *(set_cell(h, 4, "B-1, B-10") for h in ("H01", "H02", "H03")), *(set_cell(h, 4, "B-1, B-9, B-10") for h in ("H04", "H05")), sub("**Boards: 9**", "**Boards: 10**"), sub("**Drawn: 56 frames. Bound as text: 16", "**Drawn: 61 frames. Bound as text: 11"))),
    ("G-BOARDS", "move a wide frame off the 1920 board", set_cell("B-9", 4, "H04, H05, H09, H10, H11, H18, H20")),
    ("G-TOKEN", "name a token the base lacks", set_cell("T-15", 2, "`color.text.hyperlink`")),
    ("G-TOKEN", "bind the disabled text token", add_line("A T2 label uses `color.text.disabled`.")),
    ("G-TOKEN", "write a raw value", add_line("The row tint is #1C222B.")),
    ("G-CONTRAST", "misstate a ratio", set_cell("CR-06", 4, "5.80")),
    ("G-CONTRAST", "drop the T2 label pair", drop_row("| CR-06 ")),
    ("G-CONTRAST", "measure a pair under its bar", set_cell("CR-21", 3, "text")),
    ("G-MOTION", "animate a height", set_cell("M-03", 2, "`height`")),
    ("G-MOTION", "animate a status", set_cell("M-05", 3, "a fade over `motion.duration.normal`")),
    ("G-MOTION", "drop the dialog entry", drop_row("| M-06 ")),
    ("G-MOTION", "drop a row's PROPOSED mark", set_cell("M-06", 6, "`16`:249")),
    ("G-MOTION", "let the view speak under a confirm", sub("nothing beneath it moves or speaks", "the view keeps speaking")),
    ("G-PROTECT", "ask a code before attaching a stop", set_cell("CF-03", 4, "K-17, inside")),
    ("G-PROTECT", "gate Cancel at Bybit on a row change", sub("For CF-01 and CF-03 the line is text only and the confirm stays enabled", "For CF-01 and CF-03 the confirm turns off")),
    ("G-PROTECT", "gate Attach on the stale standing", add_line("Attach stop is T2 while the account is stale, rendering 2a.")),
    ("G-PROTECT", "drop the reassurance's condition from the deck", deck_edit("e45.s143.disc.reassure", "source", "14:3115")),
    ("G-PROTECT", "say the reassurance on every account", sub("is said for an account only while that account has no `missing_native_sl` row", "is said for every account")),
    ("G-ENFORCE", "claim the UI unlocks", deck_edit("e45.s143.confirm.resolve_stale.body", "text", "This unlocks {account}.")),
    ("G-T2", "drop a T2 row's rendering", set_cell("T-09", 1, "T2 control")),
    ("G-T2", "let a T2 control leave the Tab order", sub("never the `disabled` attribute — it stays in the Tab order", "or the `disabled` attribute")),
    ("G-T2", "drop the lock from §4", set_cell("T2", 1, "CMP-079 RbacGate")),
    ("G-T2", "leave the stale frame's T2 unnamed", set_cell("H09", 5, "—")),
    ("G-T2", "drop the toggle from §4", drop_row("| Include drills (SCR-144) ")),
    ("G-LADDER", "give CMP-044 a rung", sub("and no `rung`", "and `rung` 1")),
    ("G-LADDER", "drop the ladder departure's owner", set_cell("C-3", 2, "`primary` (BQ-03, AMEND)")),
    ("G-REQUEST", "lean on #5182 outside a request row", add_line("Per #5182, Force resolve takes no code.")),
    ("G-CITE", "re-point a cite to an unpinned line", sub("(`15`:1046)", "(`15`:1047)")),
    ("G-HYGIENE", "write a closing keyword", add_line("This PR closes #1251.")),
    ("G-HYGIENE", "put a deny word into the tool", lambda t: replace(t, tool=t.tool + "\n# " + DENY[9] + "\n")),
    ("G-SCOPE", "touch `14` in the diff", lambda t: replace(t, changed=[*OWN_PATHS, PATHS["14"]])),
)  # fmt: skip


def selftest() -> tuple[bool, list[str]]:
    base = replace(load(), changed=list(OWN_PATHS))
    before = (base.spec, base.deck)
    found = audit(base)
    out = [f"self-test: baseline {len(found)} FAIL"] + [f"  baseline {g}: {m}" for g, m in found]
    ok = not found
    for i, (gate, what, fn) in enumerate(MUTATIONS, 1):
        gates = sorted({g for g, _ in audit(fn(base))})
        good = gates == [gate]
        ok &= good
        out.append(
            f"{'ok  ' if good else 'FAIL'} M-{i} {gate}: {what} -> {', '.join(gates) or 'none'}"
        )
    after = load()
    restored = (after.spec, after.deck) == before
    ok &= restored
    out.append(
        f"self-test: {len(MUTATIONS)} mutations, text restored: {'yes' if restored else 'NO'}"
    )
    out.append(f"self-test: {'PASS' if ok else 'FAIL'}")
    return ok, out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="E45-D02 hand-off audit")
    g = ap.add_mutually_exclusive_group()
    for flag in ("--check", "--self-test", "--repin-ruled"):
        g.add_argument(flag, action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        ok, lines = selftest()
        print("\n".join(lines))
        return 0 if ok else 1
    t = load()
    if a.repin_ruled:
        hashes, bad = cite_hashes(t)
        if bad:
            print(f"refused: {bad[0]}")
            return 1
        head = "# E45-D02 cite pins: the cite, a hash of its cited line(s) at its base. Written by --repin-ruled only.\n"
        body = "".join(f"{k}\t{h}\n" for k, h in hashes.items())
        (ROOT / PINS_REL).write_text(head + body, encoding="utf-8")
        print(f"wrote {PINS_REL} ({len(hashes)} cites)")
        return 0
    found = audit(t)
    for gate, msg in found:
        print(f"FAIL {gate}: {msg}")
    print(f"{len(found)} FAIL ({len(GATES)} gates)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

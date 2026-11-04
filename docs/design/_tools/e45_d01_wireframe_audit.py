#!/usr/bin/env python3
"""E45-D01 (#1250) audit: the wireframe spec of the reconciliation, discrepancy and drill surfaces
(SCR-143's Discrepancies view and tiles, SCR-144's drill rows, SCR-146's last restore drill).

Standalone and offline, shaped on the E43-D01 and E41-D02 tools. It reads the spec and the pins
file from the working tree, and every cited file AS TEXT with `git show` at the pinned base
(`BASE`); the pins hash content, so a cite holds wherever its line is read. Default-deny: a gate
that cannot read its input FAILs.

Gates (each FAIL led by its name):
  G-STATE     §0 lists every frame once; every state row (DV-, CF-, RT-, DT-, IN-, BD-) names a
              §0 frame; AC-1 … AC-5 each map to §0 frames; the ticket's required states exist;
              every §0 frame is named by a state row, an AC row or an inset.
  G-CONFIRM   AC-2: the Cancel at exchange copy names the order id, the account and the symbol,
              says it can't be undone, and §4.2 places the step-up inside the dialog; Cancel,
              Accept and Force resolve take the `accounts` class; Attach takes none (C-2.6).
  G-PROTECT   C-2.6: the stale state leaves Cancel at exchange and Attach protective stop now
              enabled; no line gates either on the stale standing.
  G-REASSURE  BQ-08: SCR-152's reassurance is quoted only on K-15, §1 item 9 and C-3, and §1
              item 9 makes it conditional on the account having no missing stop.
  G-T2        §1 item 7 quotes G-T2.1b and G-T2.3 verbatim from `DS` at the base and names the
              CMP-019 `lock`; every row that shows a T2 control names its rendering; §10 lists
              CMP-079 and the CMP-019 `lock` (G-T2.6).
  G-COPY      every `K-nn` the spec names is a §11.1 row; a K-row citing a source carries a
              string or key that stands on its cited line at the base.
  G-SECRET    §1 item 8 holds; DV-13 shows `[redacted]`; no credential-shaped value anywhere.
  G-REQUEST   R6: #1220, #5182 and #5233 appear only on an R-row, a G-row, the pre-stage
              paragraph or a line that points at an R-row.
  G-CITE      every cite in range, on a non-blank line at its base, and equal to the pins.
  G-HYGIENE   no closing keyword, local path, URL or host, agent name, double-brace slot or
              deny word in the spec; no deny word in this tool's text or the pins.
  G-SCOPE     the diff touches only the spec, this tool and the pins file.

Usage (from the repo root):
  python3 -I docs/design/_tools/e45_d01_wireframe_audit.py --check
  python3 -I docs/design/_tools/e45_d01_wireframe_audit.py --self-test
  python3 -I docs/design/_tools/e45_d01_wireframe_audit.py --repin-ruled (the pins' only writer)
"""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC_REL = "docs/design/E45/E45-D01.md"
TOOL_REL = "docs/design/_tools/e45_d01_wireframe_audit.py"
PINS_REL = "docs/design/_tools/e45_d01_ruled_pins.txt"
OWN_PATHS = (SPEC_REL, TOOL_REL, PINS_REL)
BASE = "8d4149f9a39846fb919c2b0c413a5ee833dea479"  # origin/main when written; re-pinned by content
PATHS: dict[str, str] = {
    "12": "docs/plan/12-sitemap.md",
    "14": "docs/plan/14-screens-catalogue.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "24": "docs/plan/24-internal-schemas.md",
    "E29D03": "docs/design/E29/E29-D03.md",
    "E42D02": "docs/design/E42/E42-D02.md",
    "E42D05": "docs/design/E42/E42-D05.md",
    "E09D09": "docs/design/E09/E09-D09.md",
    "DS": ".claude/rules/32-design-specs.md",
}
CITE = re.compile(r"`(\d\d|E29D03|E42D02|E42D05|E09D09|DS)`:(\d+(?:–\d+)?(?:, :\d+(?:–\d+)?)*)")
FRAME_ID = re.compile(r"\bW\d\d\b")
STATE_LEADS = ("DV-", "CF-", "RT-", "DT-", "IN-", "BD-")
ACS = ("AC-1", "AC-2", "AC-3", "AC-4", "AC-5")
REQUIRED_STATES = {
    "DV-01": "loading", "DV-02": "empty", "DV-03": "one", "DV-04": "populated",
    "DV-05": "dense", "DV-06": "resolving", "DV-08": "action error", "DV-09": "stale account",
    "RT-01": "healthy", "RT-02": "degraded", "RT-03": "stale", "RT-04": "unknown",
    "DT-01": "healthy", "DT-02": "degraded", "DT-03": "stale", "DT-04": "unknown",
}  # fmt: skip
RENDERING = re.compile(r"rendering (2a|2b|the sentence form)")
REASSURE = "stop-losses are unaffected"
REQUESTS = ("#1220", "#5182", "#5233")
KREF = re.compile(r"\bK-(\d\d)\b")
CLOSING = re.compile(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#\d+", re.IGNORECASE)
LOCAL_PATH = re.compile("/" + "home/|/Users/|/" + "tmp/|[A-Za-z]:\\\\|\\bnotes/")  # assembled
AGENT_NAME = re.compile(r"\b[a-z]{2,9}-worker-\d\b")
URL_OR_HOST = re.compile(r"https?://|penpot\.[a-z]|team-id=|file-id=", re.IGNORECASE)
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


def at(t: Texts, key: str) -> str:
    rel = PATHS[key]
    memo_key = f"{BASE}:{rel}"
    if memo_key not in t.memo:
        t.memo[memo_key] = git("show", memo_key)
    text = t.memo[memo_key]
    if text is None:
        raise LookupError(f"{rel} does not resolve at {BASE[:10]}; fetch first")
    return text


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
        raise LookupError(f"the spec has no `{head}` section")
    depth = head.split(" ")[0]
    j = text.find("\n" + depth + " ", i + 1)
    return text[i : j if j > 0 else len(text)]


def one_row(text: str, lead: str) -> list[str]:
    rows = table_rows(text, lead + " ")
    if len(rows) != 1:
        raise LookupError(f"the spec carries {len(rows)} `{lead}` rows, not 1")
    return rows[0]


def state_rows(t: Texts) -> list[list[str]]:
    return [r for lead in STATE_LEADS for r in table_rows(t.spec, lead)]


# ---------------------------------------------------------------------------- cites


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
        blank = [n for n in (a, b) if not ls[n - 1].strip()]
        if blank:
            bad.append(f"{label}: line {blank[0]} is blank at its base")
            continue
        joined = norm(ls[a - 1]) + "\n" + norm(ls[b - 1])
        hashes[label] = hashlib.sha256(joined.encode()).hexdigest()[:12]
    return hashes, bad


def parse_pins(text: str) -> dict[str, str]:
    out = {}
    for ln in text.split("\n"):
        parts = ln.split("\t")
        if len(parts) == 2 and not ln.startswith("#"):
            out[parts[0]] = parts[1]
    return out


def cited_text(t: Texts, cell: str) -> str:
    out = []
    for key, a, b in cites(cell):
        out += at(t, key).split("\n")[a - 1 : b]
    return norm(" ".join(out))


# ---------------------------------------------------------------------------- gates


def g_state(t: Texts) -> list[str]:
    bad = []
    zero = section(t.spec, "## 0.")
    frames = [r[0] for r in table_rows(zero, "W") if FRAME_ID.fullmatch(r[0])]
    if len(frames) != len(set(frames)):
        bad.append("§0 lists a frame twice")
    listed = set(frames)
    named: set[str] = set()
    for r in state_rows(t):
        ws = set(FRAME_ID.findall(r[-1]))
        if not ws:
            bad.append(f"{r[0]} names no frame")
        for w in ws - listed:
            bad.append(f"{r[0]} names {w}, which §0 does not list")
        named |= ws
    for ac in ACS:
        rows = table_rows(zero, ac + " ")
        if len(rows) != 1:
            bad.append(f"{ac} is not mapped once in §0")
            continue
        ws = set(FRAME_ID.findall(rows[0][-1]))
        if not ws or ws - listed:
            bad.append(f"{ac} maps to no frame §0 lists")
        named |= ws
    inset = re.search(r"\*\*Insets.*", zero)
    if inset:
        named |= set(FRAME_ID.findall(inset[0]))
    have = {r[0]: r for r in state_rows(t)}
    for sid, word in REQUIRED_STATES.items():
        if sid not in have or word not in " ".join(have[sid]).lower():
            bad.append(f"{sid} ({word}) is not a state row")
    bad += [f"§0's {w} is named by no state, AC or inset" for w in sorted(listed - named)]
    return bad


def g_confirm(t: Texts) -> list[str]:
    bad = []
    k02 = one_row(t.spec, "K-02")[1]
    for need in ("{order_id}", "{account}", "{symbol}", "can't be undone", "at Bybit"):
        if need not in k02:
            bad.append(f"K-02 lacks {need}")
    s42 = section(t.spec, "### 4.2")
    if "The step-up appears inside this dialog" not in s42 or "K-02" not in s42:
        bad.append("§4.2 does not place the step-up inside the Cancel at exchange dialog")
    for cf in ("CF-01", "CF-02", "CF-04", "CF-06"):
        if "`accounts`" not in one_row(t.spec, cf)[3]:
            bad.append(f"{cf} does not spend the `accounts` class")
    if not one_row(t.spec, "CF-03")[3].startswith("none"):
        bad.append("CF-03 asks a step-up before attaching a missing stop (C-2.6)")
    if "Cancel first in focus" not in section(t.spec, "### 4.1"):
        bad.append("§4.1 does not start every confirm on Cancel")
    return bad


def g_protect(t: Texts) -> list[str]:
    bad = []
    dv09 = " ".join(one_row(t.spec, "DV-09"))
    if "Cancel and Attach enabled" not in dv09:
        bad.append("DV-09 does not keep Cancel and Attach enabled on a stale account")
    if "never consult the stale standing" not in section(t.spec, "## 1."):
        bad.append("§1 item 3 does not keep the protective paths off the stale standing")
    gate = re.compile(
        r"(Cancel at exchange|Attach protective stop now|Cancel and Attach)[^.|]*\b"
        r"(T2|disabled|locked until|gated)\b"
    )
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if gate.search(ln) and "never" not in ln and "No frame gates" not in ln:
            bad.append(f"spec:{i} gates a protective action")
    return bad


def g_reassure(t: Texts) -> list[str]:
    bad = []
    if "only while that account has no `missing_native_sl` row" not in section(t.spec, "## 1."):
        bad.append("§1 item 9 does not make the reassurance conditional")
    allowed = ("| K-15 ", "| C-3 ", "| Your exchange-side")
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if REASSURE in ln and not ln.startswith(allowed):
            bad.append(f"spec:{i} states the reassurance outside K-15")
    if "only where" not in one_row(t.spec, "K-15")[1]:
        bad.append("K-15 is not conditional")
    return bad


def g_t2(t: Texts) -> list[str]:
    bad = []
    ds = at(t, "DS").split("\n")
    one = section(t.spec, "## 1.")
    for line_no, lead in ((28, "`aria-disabled"), (47, "`Enter`")):
        src = norm(ds[line_no - 1] + " " + ds[line_no])
        quote = src[src.find(lead) :].split(" (")[0].rstrip(".")
        quote = quote.split(" — it stays")[0] if lead.startswith("`aria") else quote
        if quote[:60] not in norm(one):
            bad.append(f"§1 item 7 does not quote `DS`:{line_no} verbatim")
    if "CMP-019 `lock`" not in one:
        bad.append("§1 item 7 does not name the CMP-019 `lock`")
    for r in state_rows(t):
        cells = " ".join(r)
        if re.search(r"\bT2\b", cells) and not RENDERING.search(cells):
            bad.append(f"{r[0]} shows a T2 control and names no rendering")
    ten = section(t.spec, "## 10.")
    if "CMP-079" not in ten or "CMP-019 `lock`" not in ten:
        bad.append("§10 does not list CMP-079 and the CMP-019 `lock` (G-T2.6)")
    return bad


def g_copy(t: Texts) -> list[str]:
    bad = []
    rows = {r[0]: r for r in table_rows(t.spec, "K-")}
    for n in sorted(set(KREF.findall(t.spec))):
        if f"K-{n}" not in rows:
            bad.append(f"K-{n} is named but has no §11.1 row")
    for k, r in rows.items():
        if not cites(r[1]):
            continue
        src = cited_text(t, r[1])
        quoted = re.findall(r'"([^"{}]+)"', r[1]) or re.findall(r"`([a-z]+\.[a-z.]+)`", r[1])
        for q in quoted:
            if norm(q) not in src:
                bad.append(f"{k}: {q[:40]!r} does not stand on its cited line")
    return bad


def g_secret(t: Texts) -> list[str]:
    bad = []
    if "8. **No secret material (C-2.7, C-12.6).**" not in t.spec:
        bad.append("§1 item 8 (no secret material) is missing")
    if "`[redacted]`" not in " ".join(one_row(t.spec, "DV-13")):
        bad.append("DV-13 does not draw the payload redacted")
    for i, ln in enumerate(t.spec.split("\n"), 1):
        if CRED_RUN.search(ln) or CRED_NAMED.search(ln):
            bad.append(f"spec:{i} carries a credential-shaped value")
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


def g_cite(t: Texts) -> list[str]:
    hashes, bad = cite_hashes(t)
    pinned = parse_pins(t.pins)
    for label, h in hashes.items():
        if label not in pinned:
            bad.append(f"cite {label} is unpinned: verify it by content, then --repin-ruled")
        elif pinned[label] != h:
            bad.append(f"cite {label}: the line at its base is not the pinned content")
    return bad


def g_hygiene(t: Texts) -> list[str]:
    bad = []
    checks = ((CLOSING, "a closing keyword (PR 2 alone closes #1250)"), (LOCAL_PATH, "a local path"),
              (AGENT_NAME, "an agent name"), (URL_OR_HOST, "a URL or a host"))  # fmt: skip
    for i, ln in enumerate(t.spec.split("\n"), 1):
        for rx, what in checks:
            if rx.search(ln):
                bad.append(f"spec:{i} carries {what}")
        if "{{" in ln:
            bad.append(f"spec:{i} carries a double-brace slot")
    for label, text in (("spec", t.spec), ("tool", t.tool), ("pins", t.pins)):
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
    "G-STATE": g_state, "G-CONFIRM": g_confirm, "G-PROTECT": g_protect,
    "G-REASSURE": g_reassure, "G-T2": g_t2, "G-COPY": g_copy, "G-SECRET": g_secret,
    "G-REQUEST": g_request, "G-CITE": g_cite, "G-HYGIENE": g_hygiene, "G-SCOPE": g_scope,
}  # fmt: skip


def audit(t: Texts) -> list[tuple[str, str]]:
    out = []
    for g, fn in GATES.items():
        try:
            out += [(g, m) for m in fn(t)]
        except LookupError as e:
            out.append((g, str(e)))
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
    spec = (ROOT / SPEC_REL).read_text(encoding="utf-8")
    pins = (ROOT / PINS_REL).read_text(encoding="utf-8") if (ROOT / PINS_REL).exists() else ""
    tool = (ROOT / TOOL_REL).read_text(encoding="utf-8")
    return Texts(spec, pins, tool, changed_paths(), {})


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


MUTATIONS: tuple[tuple[str, str, Callable[[Texts], Texts]], ...] = (
    ("G-STATE", "drop the stale-account frame", drop_row("| W09 ")),
    ("G-STATE", "drop the AC-2 mapping", drop_row("| AC-2 ")),
    ("G-STATE", "drop the dense state", drop_row("| DV-05 ")),
    ("G-STATE", "point a state at an unlisted frame", set_cell("RT-04", 3, "W99")),
    ("G-STATE", "leave a frame unnamed", sub("| W31 | `SCR-146/restore-drill/none`", "| W32 | `SCR-146/restore-drill/extra` | 5 | to draw (PR 2) |\n| W31 | `SCR-146/restore-drill/none`")),
    ("G-CONFIRM", "drop the order id from K-02", set_cell("K-02", 1, '"Cancel this order on {account} ({symbol}). This removes a live order at Bybit. This can\'t be undone."')),
    ("G-CONFIRM", "drop the irreversibility from K-02", set_cell("K-02", 1, '"Cancel order {order_id} on {account} ({symbol}). This removes a live order at Bybit."')),
    ("G-CONFIRM", "move the step-up out of the dialog", sub("The step-up appears inside this dialog", "The step-up appears on a separate page")),
    ("G-CONFIRM", "ask a code before attaching a stop", set_cell("CF-03", 3, "yes, class `accounts`")),
    ("G-CONFIRM", "let Accept skip the step-up", set_cell("CF-02", 3, "none")),
    ("G-CONFIRM", "start a confirm on its confirm button", sub("Cancel first in focus", "the confirm button first in focus")),
    ("G-PROTECT", "lock Cancel on a stale account", sub("Cancel and Attach enabled", "Cancel and Attach locked")),
    ("G-PROTECT", "gate Attach on the stale standing", add_line("Attach protective stop now is T2 while the account is stale.")),
    ("G-PROTECT", "drop §1 item 3's rule", sub("never consult the stale standing (`24`:2174)", "follow the standing (`24`:2174)")),
    ("G-REASSURE", "make the reassurance unconditional", sub("only while that account has no `missing_native_sl` row", "on every account")),
    ("G-REASSURE", "say the reassurance in a state row", set_cell("DV-02", 3, "K-01; Your exchange-side stop-losses are unaffected.")),
    ("G-T2", "drop a stale control's rendering", set_cell("DV-09", 3, "the group's line K-10; Re-run, Accept and Force resolve T2 `recon.stale_locked`; Cancel and Attach enabled; Resolve stale account… present")),
    ("G-T2", "let a T2 control leave the Tab order (G-T2.1b)", sub("never the `disabled` attribute — it stays in the Tab order", "or the `disabled` attribute")),
    ("G-T2", "make a T2 press act (G-T2.3)", sub("changes nothing and re-shows the reason inline with one polite announcement", "acts")),
    ("G-T2", "drop the lock from §10", sub("CMP-079 RbacGate and the CMP-019 `lock` (every T2 control, G-T2.6)", "CMP-079 RbacGate")),
    ("G-COPY", "name a K-row that does not exist", add_line("The banner reads K-99.")),
    ("G-COPY", "misquote the SCR-152 line", set_cell("K-15", 1, '"Your exchange-side stops are fine." (`14`:3114), only where §1 item 9 allows')),
    ("G-COPY", "cite the wrong E29-D03 key", set_cell("K-10", 1, "the account's stale line, `acct.desync.line` (`E29D03`:314)")),
    ("G-SECRET", "drop the redacted payload", set_cell("DV-13", 3, "CMP-068 with the raw payload")),
    ("G-SECRET", "draw a key-shaped value", add_line("| X-1 | the payload carries api" + "_key = [value] |")),
    ("G-SECRET", "draw a signature header", add_line("| X-2 | X-BAPI-" + "SIGN 9f2c4e1a |")),
    ("G-REQUEST", "lean on #5182 outside a request row", add_line("Per #5182, Force resolve takes no code.")),
    ("G-CITE", "re-point a cite to an unpinned line", sub("(`14`:2531)", "(`14`:2532)")),
    ("G-HYGIENE", "write a closing keyword against #1250", add_line("This PR closes #1250.")),
    ("G-HYGIENE", "put a deny word into the tool's own text", lambda t: replace(t, tool=t.tool + "\n# " + DENY[9] + "\n")),
    ("G-SCOPE", "touch `14` in the diff", lambda t: replace(t, changed=[*OWN_PATHS, PATHS["14"]])),
)  # fmt: skip


def selftest() -> tuple[bool, list[str]]:
    base = replace(load(), changed=list(OWN_PATHS))
    before = base.spec
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
    restored = load().spec == before
    ok &= restored
    out.append(
        f"self-test: {len(MUTATIONS)} mutations, text restored: {'yes' if restored else 'NO'}"
    )
    out.append(f"self-test: {'PASS' if ok else 'FAIL'}")
    return ok, out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="E45-D01 wireframe audit")
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
        head = "# E45-D01 cite pins: the cite, a hash of its cited line(s) at its base. Written by --repin-ruled only.\n"
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

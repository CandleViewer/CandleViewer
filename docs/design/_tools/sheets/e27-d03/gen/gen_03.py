#!/usr/bin/env python3
"""gen_03.py: E27-D03 (#816) board 03, `E27-D03 / 03 components-and-looks` (offline; no Penpot, no network).

Draws (§0 L220): the three §0 frames (E27-D02 frames 3-5; hi-fi rows L942-944) — CMP-203's check list in its
four variants, the T2 anatomy with the E27 state keys beside the validity look, the rung 1 and rung 3 dialogs with
the loading state between them — and, as specimen cells (build notes §1.1: "the CMP sets on 03"), CMP-176's rows
(ok, blocked, the two disabled forms; BQ-7) and their 200 % card, CMP-178 inline, CMP-201 write-only, the CMP-028
KEK notice, CMP-035 and CMP-066. Every frame string comes from the deck / §12.2 / the pinned text (k.copy, k.reason,
k.say, k.fixture). The helpers here (row176, card200, health178, step066) are reused by gen_10.py.

Run: python3 -I -B docs/design/_tools/sheets/e27-d03/gen/gen_03.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
KIT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT_DIR))
import e27d03kit as k

NN = 3
F3, F4, F5 = k.BOARDS[NN].frames
S = k.say
ROW_W = 944  # the record at SCR-125's content width (§3.1: 944 inside)
COL = (
    208,
    244,
    238,
    254,
)  # §3.1 block H gives 240 · 240 · 272 · 192 (k.COLS); the specimen widens the actions
# column so [Start the compromise response] and [Actions for sub_002 · LIVE] stay whole (a full label never clips)
G1, G8, G12, DG1 = "G-1, #895 / #896", "G-8, #895 / #898", "G-12, #3657", "D03-G1, #896"


# --- CMP-176 AccountKeyRow (§2.2 L465-613): two lines, four cells each (k.COLS), the state slot the worst state.
def _cell(name: str, kids: list[Any], w: int, *, pad: str = k.INSET_MD) -> k.Node:
    """One table cell: a flex row holding kids, space.inset.md inline / space.inset.xs block (§2.2 sizes)."""
    return k.hbox(
        name,
        kids,
        {"padX": pad, "padY": k.INSET_XS, "gap": k.INSET_XS, "wrap": "wrap", "align": "center"},
        w=w,
    )


def identity(label: str, uid: str, env: str, *, w: int | None = None) -> k.Node:
    """The row header: label (body-strong), UID (num.base), the environment as word and badge (§2.2 row header);
    w= wraps it (a narrow record grows by lines, §3.6)."""
    return k.hbox(
        "th · identity",
        [
            k.text("label", k.fixture(label), k.BODY_STRONG, k.TEXT_1),
            k.tglyph("·", k.TEXT_2),
            k.text("uid", k.fixture(uid), k.NUM_BASE, k.TEXT_1),
            k.env_pill(env),
        ],
        {"gap": k.INSET_XS, "wrap": "wrap" if w else None},
        w=w,
        note='th scope="row" rowspan="2"',
    )


def wrap_button(label: str, w: int, *, lead: str | None = None) -> k.Node:
    """A CMP-001 secondary whose label wraps at w (a narrow record, §3.6 / §11 R1: "cells wrap, records grow",
    never truncated): min-height the density's control instead of a fixed h."""
    k._fallback("DENSITY")
    kids: list[Any] = [
        k.glyph(lead, k.TEXT_1) if lead else None,
        k.text("label", label, k.BODY_STRONG, k.TEXT_1, w=w - 24 - (20 if lead else 0)),
    ]
    return k.hbox(
        "CMP-001 button · secondary · wrapping",
        kids,
        {
            "fill": k.ACTION["secondary"],
            "padX": k.BTN_PADX,
            "padY": k.INSET_XS,
            "gap": k.INSET_XS,
            "radius": k.R_CONTROL,
            "minH": k.dens().control_tok,
        },
        w=w,
    )


def health178(state: str, n: int | None = None) -> k.Node:
    """CMP-178 inline (§2.4 L844-874; HD10): glyph · word (type.ui.body color.text.primary) · the age (type.num.base
    color.text.secondary); healthy / degraded / down / none."""
    look = {
        "healthy": ("check", k.STATUS["success.strong"]),
        "degraded": ("triangle", k.STATUS["warning.strong"]),
        "down": ("octagon", k.STATUS["danger.strong"]),
        "none": ("dash", k.TEXT_2),
    }[state]
    word = {
        "healthy": S("Healthy"),
        "degraded": k.copy("e27.scr125.chip.degraded"),
        "down": k.copy("e27.scr125.chip.down"),
        "none": k.copy("e27.scr125.row.health_none"),
    }[state]
    kids: list[Any] = [k.glyph(look[0], look[1]), k.text("word", word, k.BODY, k.TEXT_1)]
    if state == "healthy" and n is not None:
        kids += [k.tglyph("·", k.TEXT_2), k.text("age", S(f"{n} s"), k.NUM_BASE, k.TEXT_2)]
    return k.hbox(f"CMP-178 health · {state}", kids, {"gap": k.INSET_XS})


def row176(form: str, *, w: int = ROW_W) -> k.Node:
    """A CMP-176 record (two lines; BQ-7): form ok (Main), blocked (sub_002, the danger fill and 4 px rule),
    disabled (sub_001, the owner's disable) or policy (demo-1, off by policy). Nothing in a disabled row is dimmed.
    """
    iw = w - (4 if form == "blocked" else 0)  # the blocked row's 4 px rule sits before the lines
    c = [round(x * iw / 944) for x in COL]
    c[3] = iw - sum(c[:3])
    fx = {
        "ok": ("Main", "1234567", "LIVE", "...a1b2"),
        "blocked": ("sub_002", "1234569", "LIVE", "...e5f6"),
        "disabled": ("sub_001", "1234568", "LIVE", "...c3d4"),
        "policy": ("demo-1", "9000001", "DEMO", "...a7b8"),
    }
    label, uid, env, kid = fx[form]
    narrow = w < ROW_W
    slot = {
        "ok": k.state_badge("OK"),
        "blocked": (
            k.cmp175("withdrawal-detected (critical)", w=c[1] - 24 - 60)
            if narrow
            else k.state_badge("BLOCKED — fund right found")
        ),
        "disabled": k.state_badge("Disabled"),
        "policy": k.state_badge("Off by policy"),
    }[form]
    acts: list[Any] = []
    aw = c[3] - 24
    if form == "blocked":
        lab = k.copy("e27.scr125.blocked.action")
        acts.append(wrap_button(lab, aw) if narrow else k.button(lab, "secondary"))
    lab = k.copy("e27.scr125.row.actions", label=label, ENV=env)
    acts.append(
        wrap_button(lab, aw, lead="more") if narrow else k.button(lab, "secondary", lead="more")
    )
    # the blocked record (frame 13, L1087) is the chip, [Start the compromise response] and line 2: its key cell
    # carries the masked id alone (no "Withdrawal OFF ✓ · verified" pass facet beside a detected fund right; §2.1)
    facets: list[Any] = (
        []
        if form == "blocked"
        else [
            k.cmp175("trade-only", "inline"),
            k.cmp175("verified", "inline", hh_mm="14:02", w=c[2] - 48),
        ]
    )
    key = k.hbox(
        "key and rights",
        [k.masked_id(kid), *facets],
        {"gap": k.INSET_SM, "wrap": "wrap"},
        w=c[2] - 24,
    )
    line1 = k.hbox(
        "line 1",
        [
            _cell("identity", [identity(label, uid, env, w=c[0] - 24 if narrow else None)], c[0]),
            _cell("state", [slot], c[1]),
            _cell("key", [key], c[2]),
            _cell("actions", acts, c[3]),
        ],
        {"align": "start"},
        w=iw,
    )
    if form == "ok":
        line2 = k.hbox(
            "line 2",
            [
                _cell("allowlist", [k.cmp175("allowlist matches", "inline")], c[0] + c[1]),
                _cell(
                    "age",
                    [
                        k.text(
                            "age",
                            k.copy("e27.scr125.row.age", n=41, date="2026-12-11"),
                            k.NUM_BASE,
                            k.TEXT_2,
                            w=c[2] - 24 if narrow else None,
                        )
                    ],
                    c[2],
                ),
                _cell("health", [health178("healthy", 2)], c[3]),
            ],
            {"align": "start"},
            w=iw,
        )
    else:
        sent = {
            "blocked": k.copy("e27.scr125.blocked.line2", label=label),
            "disabled": k.copy("e27.scr125.outcome.disabled", hh_mm="14:12"),
            "policy": k.copy("e27.scr128.off_by_policy"),
        }[form]
        ctl = (
            k.button(k.copy("e27.scr125.menu.enable"), "secondary") if form == "disabled" else None
        )
        line2 = k.hbox(
            "line 2 · notice",
            [
                _cell(
                    "notice",
                    [k.text("sentence", sent, k.BODY, k.TEXT_2, w=iw - c[3] - 40), ctl],
                    iw,
                )
            ],
            {"align": "start"},
            w=iw,
        )
    o: dict[str, Any] = {"fill": k.RAISED}
    if form == "blocked":
        o["fill"] = k.STATUS["danger.subtle"]
        k._fallback("RULE4")
    inner = k.vbox("lines", [line1, line2], {}, w=iw)
    kids: list[Any] = [inner]
    if form == "blocked":
        kids.insert(
            0,
            k.rect(
                "rule · 4 px inline-start", 4, round(k.est_height(inner)), k.STATUS["danger.strong"]
            ),
        )
    return k.hbox(
        f"CMP-176 AccountKeyRow · {form}",
        kids,
        {**o, "align": "start", "stroke": k.BORDER_DEFAULT, "strokeWidth": k.HAIRLINE},
        w=w,
        note="two <tr> lines, th scope=row rowspan=2; a plain table, never a grid (D22)",
    )


def card200(*, w: int = 608) -> k.Node:
    """CMP-176 at 200 % zoom (§2.2 sizes; §3.6; D02:1087-1088): one card per account, the label line first with
    [Actions] after it, then the facts as label–value pairs (the table headers as labels)."""
    h = k.copies(
        "e27.scr125.table.headers"
    )  # label · UID · env | state | key · rights | actions | IP allowlist |
    # key age · rotation due | health

    def pair(lab: str, val: k.Node) -> k.Node:
        return k.hbox(
            f"pair · {lab}",
            [k.text("term", lab, k.LABEL, k.TEXT_2, w=140), val],
            {"gap": k.INSET_SM, "align": "start"},
            w=w - 32,
        )

    head = k.hbox(
        "label line",
        [
            identity("Main", "1234567", "LIVE"),
            k.button(
                k.copy("e27.scr125.row.actions", label="Main", ENV="LIVE"), "secondary", lead="more"
            ),
        ],
        {"justify": "space-between", "wrap": "wrap", "gap": k.INSET_SM},
        w=w - 32,
    )
    kr, ar = h[2].split(" · "), h[5].split(
        " · "
    )  # "key", "rights"; "key age", "rotation due" (issued parts)
    pairs = [
        pair(h[1], k.state_badge("OK")),
        pair(kr[0], k.masked_id("...a1b2")),
        pair(
            kr[1],
            k.vbox(
                "rights",
                [k.cmp175("trade-only", "inline"), k.cmp175("verified", "inline", hh_mm="14:02")],
                {"gap": k.STACK_XS},
            ),
        ),
        pair(h[4], k.cmp175("allowlist matches", "inline", lead=False)),
        pair(ar[0], k.text("age", S("41 d"), k.NUM_BASE, k.TEXT_2)),
        pair(ar[1], k.text("due", S("2026-12-11 UTC"), k.NUM_BASE, k.TEXT_2)),
        pair(h[6], health178("healthy", 2)),
    ]
    return k.vbox(
        "CMP-176 card · 200 %",
        [head, *pairs],
        {
            "fill": k.RAISED,
            "pad": k.INSET_LG,
            "gap": k.STACK_SM,
            "radius": k.R_CARD,
            "stroke": k.BORDER_DEFAULT,
            "strokeWidth": k.HAIRLINE,
        },
        w=w,
    )


# --- CMP-066 Stepper (§2.4 L808-843; HD9): done / current / todo / error, glyph and word, markers 24 px.
def _marker(status: str, num: str) -> k.Node:
    """A 24 px stepper marker: done the check (success.strong), current a filled action.primary disc with its
    numeral (text.on-action), todo a 1 px text.tertiary ring with its numeral (text.secondary), error the octagon.
    """
    if status == "done":
        return k.hbox(
            "marker · done",
            [k.glyph("check", k.STATUS["success.strong"])],
            {"justify": "center"},
            w=24,
            h=24,
        )
    if status == "error":
        return k.hbox(
            "marker · error",
            [k.glyph("octagon", k.STATUS["danger.strong"])],
            {"justify": "center"},
            w=24,
            h=24,
        )
    if status == "current":
        return k.hbox(
            "marker · current",
            [k.text("n", k.say(num), k.CAPTION, k.TEXT_ON_ACTION)],
            {"justify": "center", "fill": k.ACTION["primary"], "radius": k.R_PILL},
            w=24,
            h=24,
        )
    return k.hbox(
        "marker · todo",
        [k.text("n", k.say(num), k.CAPTION, k.TEXT_2)],
        {"justify": "center", "stroke": k.TEXT_3, "strokeWidth": k.HAIRLINE, "radius": k.R_PILL},
        w=24,
        h=24,
    )


def step066(
    labels: list[str],
    statuses: list[str],
    *,
    form: str = "list",
    meta: dict[int, str] | None = None,
    w: int = 600,
) -> k.Node:
    """CMP-066 in its list (SCR-127) or nav (SCR-126) form: per step the marker, the label (current
    type.ui.body-strong text.primary, the rest text.secondary) and the status word (e27.scr127.stepper.status).
    """
    words = k.copies(
        "e27.scr127.stepper.status"
    )  # Done · Current · Not started · Refused — nothing changed
    word = {"done": words[0], "current": words[1], "todo": words[2], "error": words[3]}
    k._fallback("PILL")
    items = []
    for i, (lab, st) in enumerate(zip(labels, statuses), 1):
        cur = st == "current"
        kids: list[Any] = [
            _marker(st, str(i)),
            k.text("label", lab, k.BODY_STRONG if cur else k.BODY, k.TEXT_1 if cur else k.TEXT_2),
            k.text("status", word[st], k.CAPTION, k.TEXT_2),
        ]
        if meta and i in meta:
            kids.append(k.text("meta", meta[i], k.NUM_BASE, k.TEXT_2))
        items.append(
            k.hbox(
                f"step {i} · {st}",
                kids,
                {"gap": k.INSET_SM},
                w=w,
                note='aria-current="step"' if cur else None,
            )
        )
    return k.vbox(
        f"CMP-066 Stepper · {form}",
        items,
        {"gap": k.STACK_SM},
        w=w,
        note="<ol>" if form == "list" else "<nav> holding the <ol>",
    )


# --- Frame 3: CMP-203's checks form (hi-fi L942), four variants on demo-1's key.
def _variant(title: str, rows: list[tuple[str, str, str]]) -> k.Node:
    return k.vbox(
        f"variant · {title}",
        [k.text("variant", title, k.LABEL, k.TEXT_2), k.check_list(rows, w=580)],
        {"gap": k.STACK_SM},
        w=600,
    )


def f3() -> dict[str, Any]:
    n = k.copies("e27.checks.names")
    nc = k.copy("e27.checks.not_checked")
    ok = [
        (n[0], "passed", k.copy("e27.checks.env.passed", ENV="DEMO")),
        (n[1], "passed", k.copy("e27.checks.withdrawal.passed", hh_mm="14:02")),
        (n[2], "passed", k.copy("e27.checks.rights.passed")),
        (n[3], "passed", k.copy("e27.checks.trade.passed")),
        (n[4], "passed", k.copy("e27.checks.uta.passed")),
        (n[5], "passed", k.copy("e27.checks.uid.passed", uid="9000001")),
        (n[6], "passed", k.copy("e27.checks.allowlist.passed", egress_ip="203.0.113.10")),
        (n[7], "passed", k.copy("e27.checks.expiry.passed")),
        (n[8], "passed", k.copy("e27.checks.probe.passed", n=4)),
    ]
    refused = [ok[0], (n[1], "failed", S("failed"))] + [(x, "not checked", nc) for x in n[2:]]
    mixed = ok[:6] + [
        (n[6], "failed", k.copy("e27.scr126.refused.ip_read", ips="203.0.113.10 and 198.51.100.7")),
        (n[7], "not checked", nc),
        (n[8], "not checked", nc),
    ]
    warn = ok[:7] + [
        (n[7], "warning", k.copy("e27.checks.expiry.expiring", date="2026-11-01", n=9)),
        (n[8], "warning", k.copy("e27.checks.probe.skew", n=640)),
    ]
    k.gap(
        "frame 3 refused variant: the deck has no e27.checks.withdrawal.failed row; the row reads "
        '"Withdrawal and transfer: failed" (§2.5\'s outcome word, L942 "\'Withdrawal and transfer\' failed"); '
        "CP-5's sentence (e27.scr126.refused.withdrawal) carries the rule's words on the result card (frame 23)"
    )
    vs = [
        _variant(S("all passed"), ok),
        _variant(S("a refused variant"), refused),
        _variant(S("a mixed variant"), mixed),
        _variant(S("a warning variant"), warn),
    ]
    return {
        "kids": [
            k.hbox("variants", vs, {"wrap": "wrap", "gap": k.INSET_XL, "align": "start"}, w=1232)
        ]
    }


# --- Frame 4: the T2 anatomy (hi-fi L943; §10.1) beside the validity look and the rejected dimmed specimen.
def _keys_list() -> k.Node:
    keys = [
        "keys.kek_unavailable",
        "keys.not_signable",
        "keys.test_throttled",
        "keys.compromise_path",
        "accounts.never_keyed",
        "accounts.mode_locked",
        "accounts.stop_missing",
        "accounts.key_rejected",
        "accounts.disabled",
        "accounts.no_key",
    ]
    rows = []
    for key in keys:
        fills = {"hh_mm_ss": "14:03:02"} if key == "keys.test_throttled" else {}
        rows.append(
            k.hbox(
                f"key · {key}",
                [
                    k.text("key", S(key), k.NUM_BASE, k.TEXT_1, w=220),
                    k.text("string", k.reason(key, **fills), k.BODY, k.TEXT_2, w=420),
                ],
                {"gap": k.INSET_MD, "align": "start"},
                w=656,
            )
        )
    return k.vbox(
        "§12.2 · the ten PROPOSED E27 keys",
        [k.text("h", S("the ten PROPOSED E27 keys"), k.LABEL, k.TEXT_2), *rows],
        {"gap": k.STACK_XS},
        w=656,
    )


def t2_radio_wrap(label: str, reason_key: str, *, w: int = 560) -> k.Node:
    """k.t2_radio() with its label wrapping at w (the kit's t2_label() takes no width, so a long full label ran on
    one line): ring, then the lock leading the full label (color.text.tertiary) and the reason as its second line.
    """
    k._choice("t2")
    ring = k.box(
        "ring",
        [k.at(k.ellipse("outer", 16, 16, {"stroke": k.TEXT_3, "strokeWidth": k.HAIRLINE}), 0, 0)],
        w=16,
        h=16,
    )
    lab = k.hbox(
        "T2 label",
        [k.lock(), k.text("label", label, k.BODY, k.TEXT_3, w=w - 48)],
        {"gap": k.INSET_XS, "align": "start"},
    )
    txt = k.vbox("text", [lab, k.t2_reason(k.reason(reason_key), w=w - 24)], {"gap": k.STACK_XS})
    return k.hbox(
        f"T2 · CMP-079 RbacGate · radio · {label[:32]}",
        [ring, txt],
        {"gap": k.INSET_SM, "align": "start"},
        w=w,
        note='role="radio" kept, aria-disabled="true"; an arrow onto it checks nothing',
    )


def _dimmed_specimen() -> k.Node:
    """The rejected dimmed look as a struck-through specimen (§9 t2-dimmed 2.86): never drawn in
    color.text.disabled / opacity.disabled (the kit refuses both), so the label is struck in danger.strong and the
    pair is named in words."""
    lab = k.text("label", S("Rotate key…"), k.BODY, k.TEXT_3)
    struck = k.box(
        "struck label",
        [k.at(lab, 8, 4), k.at(k.rect("strike", 92, 2, k.STATUS["danger.strong"]), 4, 13)],
        {
            "fill": k.RAISED,
            "stroke": k.BORDER_DEFAULT,
            "strokeWidth": k.HAIRLINE,
            "radius": k.R_CONTROL,
        },
        w=104,
        h=28,
    )
    return k.vbox(
        "rejected · t2-dimmed",
        [
            struck,
            k.hbox(
                "pair",
                [
                    k.glyph("octagon", k.STATUS["danger.strong"]),
                    k.text("pair id", S("t2-dimmed"), k.NUM_BASE, k.TEXT_1),
                    k.text("ratio", S("2.86"), k.NUM_BASE, k.TEXT_2),
                ],
                {"gap": k.INSET_XS},
            ),
        ],
        {"gap": k.STACK_XS},
    )


def f4() -> dict[str, Any]:
    mi = k.copies(
        "e27.scr125.menu.items"
    )  # Edit… · Add a key… · Rotate key… · Test key… · Revoke key… · …
    gate_menu = k.menu(
        [
            k.menu_item(mi[0]),
            k.menu_item(mi[2], reason_key="keys.kek_unavailable", focused=True),
            k.menu_item(mi[4], second=k.copy("e27.scr125.menu.ask.keys")),
        ],
        w=312,
    )
    btn = k.t2_button(k.copy("e27.scr126.buttons"), "keys.kek_unavailable", "primary", w=280)
    rad = t2_radio_wrap(k.copy("e27.scr129.choice.leave"), "accounts.stop_missing", w=736)
    step = k.vbox(
        "T2 · CMP-079 RbacGate · checklist step",
        [
            k.t2_label(k.copy("e27.scr019.task.key")),
            k.t2_reason(k.reason("rbac.owner_only", verb="manage API keys"), w=280),
        ],
        {"gap": k.STACK_XS},
        note='aria-disabled="true"; CMP-097 step, its reason the second line',
    )
    t2s = k.vbox(
        "the four gated controls (CMP-079)",
        [
            k.hbox(
                "menu and button",
                [gate_menu, k.vbox("button and step", [btn, step], {"gap": k.STACK_LG})],
                {"gap": k.INSET_XL, "align": "start"},
            ),
            rad,
        ],
        {"gap": k.STACK_LG},
        w=760,
    )
    valid = k.vbox(
        "validity look (E42-D03; not T2)",
        [
            k.button(k.copy("e27.scr129.confirm.choose"), "destructive", "validity"),
            k.text("hint", k.copy("e27.scr129.hint.choose"), k.CAPTION, k.TEXT_2),
            k.button(
                k.copy("e27.scr129.confirm.disable", label="sub_002"), "destructive", "validity"
            ),
            k.text(
                "hint · typed",
                k.copy("e27.scr129.hint.typed", label="sub_002"),
                k.CAPTION,
                k.TEXT_2,
            ),
            _dimmed_specimen(),
        ],
        {"gap": k.STACK_SM},
        w=400,
        note='aria-disabled="true", focusable, no lock, no CMP-079',
    )
    return {
        "kids": [
            k.hbox("anatomy", [t2s, valid], {"gap": k.INSET_XL, "align": "start"}, w=1232),
            _keys_list(),
        ]
    }


# --- Frame 5: rung 1, the loading state, rung 3 (hi-fi L944; §2.4 CMP-044; HD8).
DW = 600  # kit choice: the three dialogs at 600 (not CMP-043 Large's 640) so two sit side by side in the 1280 frame


def _loading() -> k.Node:
    """consequenceState loading: the title, "Reading what sub_002 holds…", Cancel only — no confirm in the DOM."""
    iw = DW - 48
    cancel = k.button(k.copy("e27.shared.cancel"), "secondary", "focus")
    return k.vbox(
        "CMP-044 ConfirmDialog · rung 3 · loading",
        [
            k.text(
                "title",
                k.copy("e27.scr129.disable.title", label="sub_002", ENV="LIVE"),
                k.HEADING_MD,
                k.TEXT_1,
                w=iw,
            ),
            k.hbox(
                "summary",
                [
                    k.rect("CMP-015 skeleton", 16, 12, k.HOVER, o={"radius": k.R_CONTROL}),
                    k.text(
                        "loading", k.copy("e27.scr129.loading", label="sub_002"), k.BODY, k.TEXT_2
                    ),
                ],
                {"gap": k.INSET_XS},
            ),
            k.hbox("footer", [cancel], {"justify": "end"}, w=iw),
        ],
        {
            "fill": k.OVERLAY,
            "shadow": k.E_DIALOG,
            "radius": k.R_DIALOG,
            "pad": k.DIALOG_PAD,
            "gap": k.STACK_MD,
        },
        w=DW,
        note='role="alertdialog"; only Cancel is rendered while the summary loads; "Still reading…" after 1 s',
    )


def f5() -> dict[str, Any]:
    r1 = k.rung_dialog(
        k.copy("e27.scr129.revoke.title", key_id_masked="...e5f6", label="sub_002", ENV="LIVE"),
        [k.copy("e27.scr129.revoke.not_last", label="sub_002", new="...d9e0")],
        rung=1,
        confirm=k.button(
            k.copy("e27.scr129.revoke.confirm", key_id_masked="...e5f6"), "destructive"
        ),
        marker="e27.scr129.marker.revoke",
        w=DW,
    )
    hist = k.copies("e27.scr129.disable.history")
    cons = [
        k.copy("e27.scr129.disable.stops", label="sub_002"),
        S("sub_002 holds 2 positions, 3 working orders and 1 running algo."),
        k.copy("e27.scr129.disable.users", users="alex", label="sub_002"),
        *hist,
    ]
    choices = k.vbox(
        "choices",
        [
            k.text(
                "lead", k.copy("e27.scr129.choice.lead", label="sub_002"), k.BODY_STRONG, k.TEXT_1
            ),
            k.two_choices(
                [
                    k.radio(k.copy("e27.scr129.choice.leave"), w=DW - 60),
                    k.radio(
                        k.copy("e27.scr129.choice.flatten", m=3, k=1, n=2, verb=S("disable")),
                        w=DW - 60,
                    ),
                ]
            ),
        ],
        {"gap": k.STACK_SM},
    )
    typed = k.field(k.copy("e27.scr129.typed", label="sub_002"), None, w=DW - 48)
    conf = k.vbox(
        "confirm · validity",
        [
            k.button(k.copy("e27.scr129.confirm.choose"), "destructive", "validity"),
            k.text("hint", k.copy("e27.scr129.hint.choose"), k.CAPTION, k.TEXT_2),
        ],
        {"gap": k.STACK_XS, "align": "end"},
    )
    r3 = k.rung_dialog(
        k.copy("e27.scr129.disable.title", label="sub_002", ENV="LIVE"),
        cons,
        rung=3,
        confirm=conf,
        choices=choices,
        typed=typed,
        marker="e27.scr129.marker",
        w=DW,
    )
    return {
        "kids": [
            k.hbox(
                "rung 1 and loading",
                [r1, _loading()],
                {"gap": k.INSET_XL, "align": "start"},
                w=1232,
            ),
            r3,
        ]
    }


# --- Specimen cells (board chrome around product looks; the copy rule still holds inside each card).
def strip_on(cell: k.Node, gap_owner: str, what: str) -> k.Node:
    """A "not yet served" strip appended to a SPECIMEN cell's annotation layer (specimen() takes no strips=): the
    pill sits outside the specimen card, and the cell's facts gain it so the annotation column lists it.
    """
    pill = k.not_served(gap_owner, what, w=round(k.est_width(cell)) - 16)
    k._META[cell["name"]]["strips"].append(pill["kids"][0]["chars"])
    n = (
        sum(1 for x in cell["kids"] if str(x.get("name", "")).startswith("strip · not yet served"))
        + 1
    )
    return dict(cell, kids=[*cell["kids"], dict(pill, name=f"strip · not yet served · {n}")])


def specimens03() -> list[k.Node]:
    rows = k.specimen(
        "CMP-176 AccountKeyRow · ok, blocked and the two disabled forms (§2.2)",
        [row176("ok"), row176("blocked"), row176("disabled"), row176("policy")],
        notes=[
            (
                "nothing in a disabled row is dimmed: color.text.primary / .secondary on "
                "color.surface.raised (§2.2 L556-566); the blocked row: danger.subtle fill, the 4 px "
                "inline-start rule as a rect (FALLBACKS RULE4), [Start the compromise response] first"
            )
        ],
        proposed=["HD3", "HD4"],
        w=976,
    )
    rows = strip_on(rows, G1, "the blocked row form (until G-1 attributes the failure to a key)")
    rows = strip_on(rows, G12, "Off by policy (no served operation turns it back on)")
    c200 = k.specimen(
        "CMP-176 at 200 % zoom · one card per account (§2.2 sizes; §3.6)",
        [card200()],
        notes=[
            (
                "640 CSS px at 200 %: the label line first, [Actions] after it, then the facts as "
                "label–value pairs (D02:1087-1088)"
            )
        ],
        proposed=["HD12"],
        w=640,
    )
    h178 = k.specimen(
        "CMP-178 inline · per-key health (§2.4 L844-874)",
        [
            health178("healthy", 2),
            health178("degraded"),
            health178("down"),
            health178("none"),
            k.text(
                "down detail",
                k.copy("e27.scr125.details.down", n=45, hh_mm_ss="14:01:26"),
                k.BODY,
                k.TEXT_2,
            ),
        ],
        notes=["no live region of its own; the age never ticks"],
        proposed=["HD10"],
        w=480,
    )
    wo = k.specimen(
        "CMP-201 PasswordField · writeOnly (§2.3 L659-686)",
        [
            k.field(k.copy("e27.scr126.key.label"), None, w=560, write_only=True),
            k.field(
                k.copy("e27.scr126.secret.label"),
                None,
                w=560,
                write_only=True,
                hint=k.copy("e27.scr126.secret.help"),
            ),
            k.field(
                k.copy("e27.scr126.key.label"),
                None,
                w=560,
                write_only=True,
                focused=True,
                hint=k.copy("e27.scr126.invalid.key_format"),
                name="CMP-201 writeOnly · format error",
            ),
        ],
        notes=[
            (
                "no Show / Hide toggle in the DOM; the well never shows a value back; CMP-007's well "
                "(color.surface.app, 1 px color.text.tertiary) — HD11"
            )
        ],
        proposed=["HD5", "HD11"],
        w=608,
    )
    kek = k.specimen(
        "CMP-028 · the KEK-unavailable notice (§2.4 L705-734)",
        [
            k.banner("e27.shell.banner.kek", w=880),
            k.kek_notice(w=880),
            k.t2_button(k.copy("e27.scr125.menu.items", 1), "keys.kek_unavailable", w=320),
        ],
        notes=[
            (
                "one notice, many pointers: the T2 control's reason is sentence 1's node (BQ-9); CMP-092's row "
                "above is the one announcement"
            )
        ],
        proposed=["HD6"],
        w=912,
    )
    ov = k.specimen(
        "CMP-035 · the 900 s rotation overlap (§2.4 L735-760)",
        [
            k.hbox(
                "countdown",
                [
                    k.text("absolute", S("until 10:55:01 UTC"), k.NUM_BASE, k.TEXT_1),
                    k.tglyph("—", k.TEXT_2),
                    k.text("left", S("14:12 left"), k.NUM_BASE, k.TEXT_2),
                ],
                {"gap": k.INSET_XS},
            ),
            k.hbox(
                "at zero",
                [
                    k.text("absolute", S("until 10:55:01 UTC"), k.NUM_BASE, k.TEXT_1),
                    k.tglyph("—", k.TEXT_2),
                    k.text("left", S("0:00 left"), k.NUM_BASE, k.TEXT_2),
                ],
                {"gap": k.INSET_XS},
            ),
            k.text(
                "row line", k.copy("e27.scr125.busy.overlap", hh_mm_ss="10:55:01"), k.BODY, k.TEXT_2
            ),
            k.text(
                "at 60 s",
                k.copy("e27.scr127.overlap.at60", old="...e5f6", hh_mm_ss="10:55:01"),
                k.CAPTION,
                k.TEXT_2,
            ),
            k.text(
                "at 10 s",
                k.copy("e27.scr127.overlap.at10", old="...e5f6", hh_mm_ss="10:55:01"),
                k.CAPTION,
                k.TEXT_2,
            ),
        ],
        notes=[
            (
                "aria-live=off; polite at 60 s and 10 s; no colour under a threshold; at 0 it "
                "waits for the server's completed"
            )
        ],
        proposed=["HD7"],
        w=520,
    )
    lab127 = k.copies("e27.scr127.stepper")
    lab126 = k.copies("e27.scr126.stepper")
    st = k.specimen(
        "CMP-066 Stepper · list, nav, error and collapsed (§2.4 L808-843)",
        [
            step066(
                lab127,
                ["done", "done", "current", "todo", "todo"],
                meta={3: k.copy("e27.scr127.stage3.meta", n="2.4")},
            ),
            step066(lab127, ["done", "done", "error", "todo", "todo"]),
            step066(lab126, ["done", "current"], form="nav"),
            k.text(
                "collapsed",
                k.copy("e27.scr127.stepper.collapsed", n=2, stage=lab127[1]),
                k.BODY_STRONG,
                k.TEXT_1,
            ),
        ],
        notes=["markers 24 px in both densities; meta is the stage's real elapsed time"],
        proposed=["HD9"],
        w=640,
    )
    return [rows, c200, h178, wo, kek, ov, st]


def cells() -> list[k.Node]:
    c3 = k.frame(
        F3,
        f3,
        proposed=["HD17", "D03-C15"],
        notes=[
            (
                "on a card (row-pass-glyph, row-warning-glyph, c175-critical-border, row-secondary); the "
                "dialog binding (step-done / step-warning / step-refused) is text only"
            ),
            (
                "copy gap: the deck has no e27.checks.withdrawal.failed row; the refused variant reads "
                '"Withdrawal and transfer: failed" from L942\'s prose until the deck issues one'
            ),
        ],
    )
    c4 = k.frame(
        F4,
        f4,
        notes=[
            (
                "T2 per §10.1: lock leading the full label, aria-disabled, the reason the 2a second "
                "line; the dimmed look is the rejected t2-dimmed row, struck through"
            )
        ],
    )
    c5 = k.frame(
        F5,
        f5,
        strips=[(G8, "rung 3's ask line (disable)")],
        proposed=["HD8"],
        notes=[
            "between the rungs the loading state: Cancel alone, no confirm in the DOM (D02:260-291)"
        ],
    )
    return [c3, c4, c5, *specimens03()]


def main() -> int:
    k.reset_notes()
    cs = cells()
    bd = k.board(
        NN,
        cs,
        source="E27-D03 §0 L220; §2.6 L942-944; §2.2 L465-613; §2.3 L659-686; §2.4 L687-874; "
        "§2.5 L909-932; §10.1 L1828-1859; §12.2 L2479-2515",
        cols=3,
        not_drawn=[
            "the dialog binding of the check list (step-done, step-warning, step-refused): text only",
            (
                "CMP-176 hover and focus rows, the details line and the compact row (board 10 draws the "
                "125 % specimen)"
            ),
            "CMP-066's SCR-016 six-step nav (E09's wizard)",
        ],
        notes=[
            "frames 3-5 are 1280 doc surfaces; the CMP sets are specimen cells (build notes §1.1)",
            (
                "frame 5's dialogs are 600 wide (kit choice dialog is 640) so rung 1 and the loading state "
                "sit side by side inside the 1280 frame"
            ),
        ],
    )
    path = k.KIT_DIR / f"{k.stem(NN)}.json"
    res = k.write_sheet(path, bd)
    rep = k.compact_sheet(path)
    md = k.write_board_md(
        NN,
        bd,
        checks=[
            "§0's three frames, exact names",
            ("every frame string issued by the deck, " "§12.2 or the pinned text"),
            "T2 on frame 4 and the CMP-028 specimen (keys.kek_unavailable, §10.1)",
            f"validator: {res}",
        ],
    )
    print(res)
    print(rep)
    print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

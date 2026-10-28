#!/usr/bin/env python3
"""gen_07 — E27-D03 (#816) board 07 `E27-D03 / 07 scr-127-rotate` (offline; no Penpot, no network).

Builds §0's nine frames of board 07 (L224): SCR-127's modal wizard (CMP-043, 720 px) over SCR-125's route in CMP-087
at 1280 x 800, comfortable, from §5's anatomy (L1228-1294) and hi-fi rows L1295-1303; frame 41 is SCR-125 with the
row menu open (Rotate key… T2). Writes 07-scr-127-rotate.json / .md beside the kit and compacts it.
Run: python3 -I -B docs/design/_tools/sheets/e27-d03/gen/gen_07.py

LOCAL HELPERS (kit unchanged; gen_06's helpers imported): stepper127() (CMP-066 list form: glyph, "{n}" and label,
status word, meta), dialog127() (CMP-043 at 720 px: title + CMP-075, stepper, stage h2, body, sticky footer; a body
taller than the viewport less 48 px above and below clips and scrolls), ordered() (a numbered static list),
checkbox() (CMP-005 unchecked), route() (SCR-125 behind the dialog).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
GEN_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(GEN_DIR.parent))
sys.path.insert(0, str(GEN_DIR))
import gen_06 as g

import e27d03kit as k

NN = 7
FR = list(k.BOARDS[NN].frames)
DLG_W, DLG_IW = k.WIZARD_W, k.WIZARD_W - 48  # 720, 672 (space.dialog.padding 24)
DLG_MAX_H = k.FRAME_H - 2 * 48  # the viewport less 48 px (space.12) above and below
MM_SS = "14:32"  # stage 4's relative time at the drawn instant (overlap_until 10:55:01 UTC)


def _marker(n: int, status: str) -> dict[str, Any]:
    if status == "done":
        return k.glyph("check", k.STATUS["success.strong"], name="status glyph · done")
    if status == "error":
        return k.glyph("octagon", k.STATUS["danger.strong"], name="status glyph · error")
    if status == "current":
        return k.box(
            "status glyph · current",
            [
                k.at(k.ellipse("dot", 16, 16, {"fill": k.ACTION["primary"]}), 0, 0),
                k.at(k.tglyph(str(n), k.TEXT_ON_ACTION, k.CAPTION, name="numeral"), 5, 1),
            ],
            w=16,
            h=16,
        )
    return k.box(
        "status glyph · todo",
        [k.at(k.ellipse("ring", 16, 16, {"stroke": k.TEXT_3, "strokeWidth": k.HAIRLINE}), 0, 0)],
        w=16,
        h=16,
    )


def stepper127(statuses: tuple[str, ...], metas: dict[int, str] | None = None) -> dict[str, Any]:
    """CMP-066's list form (BQ-12, HD9): five items in one row, each its status glyph, "{n} {label}", its status word
    and meta (type.ui.caption)."""
    labels = k.copies("e27.scr127.stepper")
    words = dict(zip(("done", "current", "todo", "error"), k.copies("e27.scr127.stepper.status")))
    iw = (DLG_IW - 4 * 8) // 5
    items = []
    for i, (lab, st) in enumerate(zip(labels, statuses), 1):
        ink = k.TEXT_1 if st in ("current", "error") else k.TEXT_2
        head = k.hbox(
            "label row",
            [
                _marker(i, st),
                k.tglyph(str(i), ink, k.LABEL, name="n"),
                k.text("label", lab, k.LABEL, ink, w=iw - 36),
            ],
            {"gap": k.INSET_XS, "align": "start"},
        )
        meta = (metas or {}).get(i)
        items.append(
            k.vbox(
                f"step {i} · {st}",
                [
                    head,
                    k.text("status", words[st], k.CAPTION, ink, w=iw),
                    k.text("meta", meta, k.CAPTION, k.TEXT_2) if meta else None,
                ],
                {"gap": k.STACK_XS},
                w=iw,
                note='aria-current="step"' if st == "current" else None,
            )
        )
    return k.hbox(
        "CMP-066 Stepper · list",
        items,
        {"gap": k.INSET_SM, "align": "start"},
        w=DLG_IW,
        note="statuses by E42-D05's names (contract pending)",
    )


def dialog127(
    statuses: tuple[str, ...],
    h2: str,
    body: list[Any],
    footer: list[Any],
    *,
    metas: dict[int, str] | None = None,
) -> dict[str, Any]:
    """CMP-043 size lg at 720 px: color.surface.overlay, radius.dialog, elevation.dialog, a 1 px
    color.border.default edge; the title with CMP-075, the stepper, the stage h2 (tabindex -1), the body, the
    sticky footer (Cancel first)."""
    full = k.copy("e27.scr127.title", label="sub_002", key_id_masked="...e5f6", ENV="LIVE")
    title = k.hbox(
        "title row",
        [k.text("title", full.split(" · ")[0], k.HEADING_MD, k.TEXT_1), k.env_pill("LIVE")],
        {"gap": k.INSET_SM},
        note=f'the dialog\'s name: "{full}"',
    )
    head = [
        title,
        stepper127(statuses, metas),
        k.text("h2", h2, k.HEADING_SM, k.TEXT_1, w=DLG_IW, note='tabindex="-1"; the focus target'),
    ]
    foot = g.buttons(footer, w=DLG_IW, name="footer · sticky")
    bod = k.vbox(
        "stage body", body, {"gap": k.STACK_SM}, w=DLG_IW, note="a region labelled by the h2"
    )
    fixed = sum(k.est_height(n) for n in [*head, foot]) + 2 * 24 + 16 * 4
    room = DLG_MAX_H - fixed
    if k.est_height(bod) > room:
        bod = dict(
            bod,
            h=int(room),
            o=dict(bod["o"], clip=True),
            note="the body scrolls; the footer stays sticky",
        )
    dlg = k.vbox(
        "CMP-043 Dialog · lg · SCR-127",
        [*head, bod, foot],
        {
            "fill": k.OVERLAY,
            "stroke": k.BORDER_DEFAULT,
            "strokeWidth": k.HAIRLINE,
            "radius": k.R_DIALOG,
            "shadow": k.E_DIALOG,
            "pad": k.DIALOG_PAD,
            "gap": k.STACK_LG,
        },
        w=DLG_W,
        note='role="dialog", aria-modal="true", labelled by its title; the page behind inert',
    )
    dlg["h"] = min(
        DLG_MAX_H, round(k.est_height(dlg) * 1.06) + 16
    )  # live text runs ~5 % taller than the estimate
    return dlg


def route(
    *,
    overlays: list[Any],
    name: str,
    banners: list[Any] | None = None,
    notices: list[Any] | None = None,
    verdict: Any = None,
    content: list[Any] | None = None,
) -> dict[str, Any]:
    """SCR-125's route behind (the accounts route in CMP-087), at 1280 x 800."""
    v = verdict or k.verdict_line("dated", n=4, hh_mm="14:02")
    return g.adm(
        name,
        content=content or [k.section_heading("e27.shell.region.accounts")],
        route_band=False,
        primary=k.add_account(),
        banners=banners,
        notices=notices,
        verdict=v,
        overlays=overlays,
        footer=True,
        h=k.FRAME_H,
    )


def ordered(items: list[Any]) -> dict[str, Any]:
    """A numbered static list (type.ui.body), never boxes to tick."""
    return k.vbox(
        "ordered list",
        [
            k.hbox(
                f"item {i}",
                [
                    k.tglyph(str(i), k.TEXT_2),
                    (
                        it
                        if isinstance(it, dict)
                        else k.text("words", it, k.BODY, k.TEXT_1, w=DLG_IW - 20)
                    ),
                ],
                {"gap": k.INSET_SM, "align": "start"},
            )
            for i, it in enumerate(items, 1)
        ],
        {"gap": k.STACK_SM},
        w=DLG_IW,
    )


def cancel() -> dict[str, Any]:
    return k.button(k.copy("e27.shared.cancel"), "secondary")


def close(variant: str = "secondary") -> dict[str, Any]:
    return k.button(k.copy("e27.shared.close"), variant)


# --- Board 07's frames (hi-fi rows L1295-1303).
def stage2_fields(*, readonly: bool = False) -> list[Any]:
    """The two stacked CMP-040 fields on CMP-201's writeOnly variant (BQ-8): masked dots after the paste."""
    nk, ns = k.copies("e27.scr127.stage2.fields")
    hint = k.copies("e27.scr126.key.label")[1]
    return [
        g.field_(nk, hint=hint, w=DLG_IW, bullets=True, write_only=True, readonly=readonly),
        g.field_(
            ns,
            hint=k.copy("e27.scr127.secret.help"),
            w=DLG_IW,
            bullets=True,
            write_only=True,
            readonly=readonly,
        ),
    ]


def f33() -> dict[str, Any]:
    """Frame 33: stage 1 — create the new key at Bybit; no ask line, no marker; [Cancel] [Next]."""
    body = [
        ordered(
            [
                k.copy("e27.scr127.stage1.create", uid="1234569"),
                g.cp_text(k.copy("e27.scr127.stage1.allowlist", egress_ip=g.EGRESS), w=DLG_IW - 20),
                k.copy("e27.scr127.stage1.policy", n=90, age=78, date="2026-11-04"),
                k.copy("e27.scr127.stage1.no_wait"),
            ]
        )
    ]
    dlg = dialog127(
        ("current", "todo", "todo", "todo", "todo"),
        k.copy("e27.scr127.stage1.h2"),
        body,
        [cancel(), k.button(k.copy("e27.scr127.stage1.next"), "primary")],
    )
    return route(name=FR[0], overlays=[k.overlay(dlg)])


def stepup_inset() -> dict[str, Any]:
    """SCR-006 over the wizard (E09-D06's chassis, consumed, never redrawn): its label and title; the server's
    action_summary and the password and code fields as labelled placeholders (the summary's words are the server's).
    """
    iw = 400 - 48
    return k.vbox(
        "SCR-006 footprint",
        [
            k.text(
                "footprint label", k.say("SCR-006 code-only, E09-D06"), k.CAPTION, k.TEXT_2, w=iw
            ),
            k.text("title", k.copy("e27.scr126.stepup.title"), k.HEADING_MD, k.TEXT_1, w=iw),
            k.placeholder("the server's action_summary (names sub_002, LIVE, UID 1234569)", iw, 32),
            k.placeholder("E09-D06 password and code fields", iw, 96),
        ],
        {
            "fill": k.OVERLAY,
            "stroke": k.BORDER_DEFAULT,
            "strokeWidth": k.HAIRLINE,
            "radius": k.R_DIALOG,
            "shadow": k.E_DIALOG,
            "pad": k.DIALOG_PAD,
            "gap": k.STACK_MD,
        },
        w=400,
        note='role="alertdialog"; the held request re-sent once on success',
    )


def f34() -> dict[str, Any]:
    """Frame 34: stage 2 — the consequences first, the write-only fields, the ask line, the marker; the destructive
    confirm (rung 1); SCR-006 inset over it (the wizard drawn left of centre so the inset sits beside it).
    """
    back, vs = k.copies("e27.scr127.buttons")
    body = [
        k.text("lead", k.copy("e27.scr127.stage2.lead"), k.BODY, k.TEXT_1, w=DLG_IW),
        k.text(
            "no undo",
            k.copy("e27.scr127.stage2.no_undo", old="...e5f6"),
            k.BODY,
            k.TEXT_1,
            w=DLG_IW,
        ),
        *stage2_fields(),
        k.text("ask line", k.copy("e27.shared.ask"), k.BODY, k.TEXT_2, w=DLG_IW),
        k.text("CMP-093 marker", k.copy("e27.scr127.marker"), k.CAPTION, k.TEXT_3, w=DLG_IW),
    ]
    dlg = dialog127(
        ("done", "current", "todo", "todo", "todo"),
        k.copy("e27.scr127.stage2.h2"),
        body,
        [cancel(), k.button(back, "secondary"), k.button(vs, "destructive")],
    )
    return route(
        name=FR[1],
        overlays=[
            k.overlay(dlg, x=24),
            k.overlay(
                stepup_inset(), x=k.FRAME_W - 400 - 40, scrim=False, name="overlay · SCR-006"
            ),
        ],
    )


def f35() -> dict[str, Any]:
    """Frame 35: stage 3 verifying — the running meta, D18's line, the fields read-only; Verify and switch busy
    (label kept, never T2); Back gone, Cancel becomes Close."""
    vs = k.copies("e27.scr127.buttons")[1]
    body = [
        k.text("status", k.copy("e27.scr126.validating"), k.BODY, k.TEXT_2, w=DLG_IW),
        k.text(
            "status · after about 3 s",
            k.copy("e27.scr126.validating.long"),
            k.BODY,
            k.TEXT_2,
            w=DLG_IW,
        ),
        *stage2_fields(readonly=True),
    ]
    dlg = dialog127(
        ("done", "done", "current", "todo", "todo"),
        k.copy("e27.scr127.stage3.h2"),
        body,
        [close(), k.button(vs, "destructive", "busy")],
        metas={3: k.copy("e27.scr127.stage3.meta", n=2)},
    )
    return route(name=FR[2], overlays=[k.overlay(dlg)])


def refused_list() -> dict[str, Any]:
    """CMP-203 for sub_002's new key (the 422's verification): every row passed but the allowlist, failed with
    CD-3's rule form (its Copy live: the address is served) and the whitelist read."""
    rws = g.rows("LIVE", "1234569", hh="10:39")
    read = k.copy("e27.scr126.refused.ip_read", ips="203.0.113.10 and 198.51.100.7")
    nodes = []
    for i, (c, o, wds) in enumerate(rws):
        if i == 6:
            nodes.append(k.check_row(c, "failed", read, w=DLG_IW))
            nodes.append(
                k.hbox(
                    "CD-3 rule form",
                    [
                        g.cp_text(
                            k.copy("e27.scr126.refused.ip_rule", egress_ip=g.EGRESS), w=DLG_IW - 40
                        )
                    ],
                    {"padL": k.INSET_XL},
                )
            )
        else:
            nodes.append(k.check_row(c, o, wds, w=DLG_IW))
    return k.vbox(
        "CMP-203 RequirementChecklist",
        nodes,
        {"gap": k.STACK_XS},
        w=DLG_IW,
        note="a list, no control, no live region of its own",
    )


def f36() -> dict[str, Any]:
    """Frame 36: stage 3 refused — the error status, CMP-027 (assertive once), the list, the new key still works."""
    body = [
        g.alert([k.copy("e27.scr127.stage3.refused", key_id_masked="...e5f6")], w=DLG_IW),
        refused_list(),
        k.text(
            "new key lives", k.copy("e27.scr127.stage3.new_key_lives"), k.BODY, k.TEXT_2, w=DLG_IW
        ),
    ]
    dlg = dialog127(
        ("done", "done", "error", "todo", "todo"),
        k.copy("e27.scr127.stage3.refused_h2"),
        body,
        [cancel(), k.button(k.copy("e27.scr127.stage3.back"), "secondary")],
    )
    return route(name=FR[3], overlays=[k.overlay(dlg)])


def f37() -> dict[str, Any]:
    """Frame 37: stage 3 no verdict — 3 stays current; CMP-027 once; no check list."""
    body = [g.alert([k.copy("e27.scr127.stage3.no_verdict", n=5)], w=DLG_IW)]
    dlg = dialog127(
        ("done", "done", "current", "todo", "todo"),
        k.copy("e27.scr127.stage3.no_verdict_h2"),
        body,
        [cancel(), k.button(k.copy("e27.scr127.stage3.back"), "secondary")],
    )
    return route(name=FR[4], overlays=[k.overlay(dlg)])


def stage4_body() -> list[Any]:
    """Stage 4's sentence with CMP-035 in place of its two times (the served overlap_until first, mm:ss second)."""
    full = k.copy(
        "e27.scr127.stage4.switched", hh_mm_ss="10:55:01", mm_ss=MM_SS, new="...d9e0", old="...e5f6"
    )
    head = k.say(
        "Switched at 10:40:01 UTC. New requests use ...d9e0. The old key ...e5f6 keeps working here"
    )
    cd = k.hbox(
        "CMP-035 Countdown",
        [
            k.text("absolute", g.piece(full, "until 10:55:01 UTC"), k.NUM_BASE, k.TEXT_1),
            k.tglyph("—", k.TEXT_2),
            k.text("relative", g.piece(full, f"{MM_SS} left"), k.NUM_BASE, k.TEXT_2),
        ],
        {"gap": k.INSET_SM},
        note='aria-live="off"; polite at 60 s, 10 s and the end; no colour change',
    )
    tail = g.piece(full, "— while requests in flight finish. Open orders stay open.")
    return [
        k.text("switched", head, k.BODY, k.TEXT_1, w=DLG_IW),
        cd,
        k.text("switched · tail", tail, k.BODY, k.TEXT_1, w=DLG_IW),
        k.text("no undo", k.copy("e27.scr127.stage4.no_undo"), k.BODY, k.TEXT_1, w=DLG_IW),
    ]


def f38(name: str | None = None) -> dict[str, Any]:
    """Frame 38: stage 4, switched — the fields cleared by the 200; the 900 s overlap; [Close] only."""
    dlg = dialog127(
        ("done", "done", "done", "current", "todo"),
        k.copy("e27.scr127.stage4.h2"),
        stage4_body(),
        [close()],
        metas={3: k.copy("e27.scr127.stage3.meta", n=2.4)},
    )
    return route(name=name or FR[5], overlays=[k.overlay(dlg)])


def checkbox(label: str) -> dict[str, Any]:
    """CMP-005, unchecked at mount: a 16 px color.surface.raised box with a 1 px color.text.tertiary outline."""
    bx = k.rect(
        "box",
        16,
        16,
        k.RAISED,
        o={"stroke": k.TEXT_3, "strokeWidth": k.HAIRLINE, "radius": k.R_CONTROL},
    )
    return k.hbox(
        "CMP-005 Checkbox · unchecked",
        [bx, k.text("label", label, k.BODY, k.TEXT_1, w=DLG_IW - 24)],
        {"gap": k.INSET_SM, "align": "start"},
        note="never required; gates and records nothing",
    )


def f39() -> dict[str, Any]:
    """Frame 39: stage 5 — CP-4 with CD-8, the CMP-005 note; [Close] primary."""
    body = [
        k.text("revoked", k.copy("e27.scr127.stage5.revoked"), k.BODY, k.TEXT_1, w=DLG_IW),
        checkbox(k.copy("e27.shared.bybit_note", key_id_masked="...e5f6")),
    ]
    dlg = dialog127(("done",) * 5, k.copy("e27.scr127.stage5.h2"), body, [close("primary")])
    return route(name=FR[6], overlays=[k.overlay(dlg)])


def f40() -> dict[str, Any]:
    """Frame 40: frame 38's stage 4 exactly; the G-4 strip is on the annotation layer (no control stands in)."""
    return f38(FR[7])


def f41() -> dict[str, Any]:
    """Frame 41: SCR-125 under CMP-092's row and the one CMP-028 notice, sub_002's row menu open: Add a key…, Rotate
    key… (focused) and Test key… T2 with keys.kek_unavailable; the rest enabled (D17)."""
    items = k.copies("e27.scr125.menu.items")
    gated = {1, 2, 3}
    mn = k.menu(
        [
            k.menu_item(
                it, reason_key="keys.kek_unavailable" if i in gated else None, focused=(i == 2)
            )
            for i, it in enumerate(items)
        ]
    )
    mn["note"] = (
        'CMP-041, aria-label "Actions for sub_002 · LIVE"; Enter / Space on a T2 item re-shows its reason'
    )
    row = k.hbox(
        "CMP-176 row · sub_002",
        [
            k.text("label", k.fixture("sub_002"), k.BODY_STRONG, k.TEXT_1),
            k.env_pill("LIVE"),
            k.masked_id("...e5f6"),
            k.focus_ring(
                k.hbox(
                    "CMP-002 more",
                    [k.glyph("more", k.TEXT_2)],
                    {"justify": "center", "radius": k.R_CONTROL},
                    w=32,
                    h=32,
                )
            ),
        ],
        {"gap": k.INSET_MD, "fill": k.RAISED, "padX": k.INSET_MD, "radius": k.R_CARD},
        w=k.INNER_W,
        h=48,
    )
    return route(
        name=FR[8],
        banners=[k.banner("e27.shell.banner.kek")],
        notices=[k.kek_notice()],
        verdict=k.verdict_line("unavailable"),
        content=[k.section_heading("e27.shell.region.accounts"), row],
        overlays=[
            k.overlay(mn, x=k.NAV_W + 16 + 16 + 360, y=420, scrim=False, name="overlay · row menu")
        ],
    )


SPEC = {  # frame index -> (build, strips, notes, proposed)
    0: (
        f33,
        [("D03-G1, #896", "the address and its Copy before any check")],
        [
            "The 48 h line is PROPOSED (OQ-5; RA-7). No ask line, no marker: nothing is sent at stage 1. No Back."
        ],
        ["HD9", "HD14", "D03-G1"],
    ),
    1: (
        f34,
        [],
        [
            (
                "Rung 1 with the keys step-up: SCR-006 opens over the wizard on the press (T1); the wizard is drawn "
                "left of centre so the inset sits beside it. The action_summary is the server's (a placeholder). "
                "Not saved / re-send unconfirmed legs are text-binding (e27.scr126.stepup.dropped, "
                "e27.shared.resend_unconfirmed)."
            )
        ],
        ["HD8", "HD9", "HD11"],
    ),
    2: (
        f35,
        [],
        [
            "The checks never appear one by one (D18); meta is the real request time in whole seconds."
        ],
        ["HD9"],
    ),
    3: (
        f36,
        [],
        [
            (
                "The failed row's Copy is live (the 422's verification serves egress_ip, 22:2745-2749). The "
                "fields keep their masked values for the resend (not shown at this stage)."
            )
        ],
        ["HD9", "D03-C15"],
    ),
    4: (
        f37,
        [],
        ["5 s is the server's Retry-After, written once, never a ticking count."],
        ["HD9"],
    ),
    5: (
        f38,
        [],
        [
            (
                "Announcements at 60 s and 10 s (e27.scr127.overlap.at60 / at10), polite, nothing per tick; closing "
                "leaves the overlap running and the rows read e27.scr125.busy.overlap (busy, not T2)."
            )
        ],
        ["HD7", "HD9"],
    ),
    6: (f39, [], ["Its arrival is the countdown's end, announced politely once."], ["HD9"]),
    7: (
        f40,
        [
            (
                "G-4, #897",
                (
                    "no drain read, no rollback, no early revoke, state: failed undefined, no schedule "
                    "control"
                ),
            )
        ],
        ["Nothing on the frame is T2 and no control stands in (D20)."],
        ["HD7", "HD9"],
    ),
    8: (
        f41,
        [],
        [
            (
                "The wizard never opens. Revoke key…, Suspected compromise…, Disable… and Delete (keeps history)… "
                "stay enabled (D17). Edit… is enabled too (the hi-fi row names no reason for it)."
            )
        ],
        ["HD6"],
    ),
}


def main() -> int:
    k.reset_notes()
    cs = [
        k.frame(nm, SPEC[i][0], strips=SPEC[i][1], notes=SPEC[i][2], proposed=SPEC[i][3])
        for i, nm in enumerate(FR)
    ]
    bd = k.board(
        NN,
        cs,
        source="E27-D03 §5 L1228-1304 (anatomy L1240-1268; hi-fi rows L1295-1303); §0 L224",
        cols=4,
        notes=[
            *g.LOCAL_NOTES[1:],
            (
                "Local helpers in gen_07.py: stepper127, dialog127, route, "
                "ordered, checkbox, cancel, close (see its docstring); gen_06's helpers imported."
            ),
        ],
        not_drawn=[
            "SCR-006's own fields and the server's action_summary words (E09-D06's; frame 34)",
            'the 200 % collapsed stepper "Stage {n} of 5 — {stage}" (board 10\'s specimens)',
        ],
    )
    path = k.KIT_DIR / f"{k.stem(NN)}.json"
    summary = k.write_sheet(path, bd)
    rep = k.compact_sheet(path)
    k.write_board_md(
        NN,
        bd,
        summary=summary,
        checks=[
            "every frame text issued from the deck / pinned text / fixtures (write_sheet)",
            "no frame shows more of a key than its masked id; write-only wells show dots only (BQ-8)",
            "T2 only on frame 41 (E27-D02 §7 'shows T2'); the busy confirm is never T2",
        ],
        live=[
            "every dialog sits inside the viewport less 48 px; a body taller than that clips and is marked to scroll",
            "frame 34: the wizard left of centre and SCR-006's footprint beside it, neither overlapping",
        ],
    )
    print(summary)
    print(rep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

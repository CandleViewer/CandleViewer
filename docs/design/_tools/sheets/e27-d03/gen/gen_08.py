"""E27-D03 / 08 scr-129-confirm (dark): frames 49-61, the SCR-129 confirm dialogs over SCR-125 (§7 L1389-1480).

Run: python3 -I -B gen/gen_08.py  (writes 08-scr-129-confirm.json / .md and the compacted copy in v4/).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
KIT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT_DIR))
import e27d03kit as k

NN = 8
L, ENV, UID = "sub_002", "LIVE", "1234569"
KEY, OTHER = "...e5f6", "...d9e0"
USERS, RULES = "alex (trade), bea (read)", '"BTC breakout", "ETH fade"'
POS = (("BTCUSDT", "long", "0.250"), ("ETHUSDT", "short", "1.20"))
DLG_IW = k.DIALOG_W - 2 * k.PX[k.DIALOG_PAD]
HALF_W = 600  # two forms side by side in one 1280 frame (frames 56, 57): kit choice "dialog"


# --- Route pieces (SCR-125 behind the dialogs; consumed from board 04's anatomy, drawn small).
def acct_row(
    label: str,
    uid: str,
    key: str | None,
    *,
    state: str = "OK",
    focus: bool = False,
    extra: list[Any] | None = None,
) -> Any:
    """One SCR-125 record row: identity, the state slot, the masked key, the row's Actions trigger (⋮)."""
    ident = k.text(
        "identity",
        k.copy("e27.scr125.row.identity", label=label, uid=uid, ENV=ENV),
        k.BODY,
        k.TEXT_1,
        w=260,
    )
    act = k.hbox(
        f"CMP-002 {k.copy('e27.scr125.row.actions', label=label, ENV=ENV)}",
        [k.glyph("more", k.TEXT_2)],
        {"justify": "center", "radius": k.R_CONTROL},
        w=32,
        h=32,
    )
    if focus:
        act = k.focus_ring(act)
    top = k.hbox(
        "cells",
        [ident, k.state_badge(state), k.masked_id(key) if key else None, act],
        {"gap": k.INSET_LG},
        w=k.INNER_W,
        h=40,
    )
    kids = [top, *(extra or [])]
    return k.vbox(
        f"row · {label}",
        kids,
        {
            "gap": k.STACK_XS,
            "padX": k.INSET_SM,
            "stroke": k.BORDER_SUBTLE,
            "strokeWidth": k.HAIRLINE,
        },
        w=k.INNER_W,
    )


def route(rows: list[Any] | None = None) -> list[Any]:
    """The Accounts region: its h2 and the LIVE rows (Main, sub_001, then sub_002 as given)."""
    rows = rows if rows is not None else [acct_row(L, UID, KEY)]
    return [
        k.section_heading("e27.shell.region.accounts"),
        acct_row("Main", "1234567", "...a1b2"),
        acct_row("sub_001", "1234568", "...c3d4"),
        *rows,
    ]


def shell(**kw: Any) -> dict[str, Any]:
    """admin_frame kwargs: the dated verdict, the meta line, the route rows, then kw."""
    base: dict[str, Any] = {
        "verdict": k.verdict_line("dated", n=4, hh_mm="14:02"),
        "meta": k.copy("e27.shell.meta", hh_mm_ss="14:02:11"),
        "content": route(),
    }
    base.update(kw)
    return base


# --- Dialog pieces.
def pos_line(sym: str, side: str, qty: str, *, stop: bool = True) -> Any:
    """A position line (type.num.base); the no-stop line leads with the octagon (§9 step-refused)."""
    if stop:
        return k.text(
            f"position · {sym}",
            k.copy("e27.scr129.exposure.position", symbol=sym, side=side, qty=qty),
            k.NUM_BASE,
            k.TEXT_1,
        )
    s = k.copy("e27.scr129.exposure.position_no_stop", symbol=sym, side=side, qty=qty)
    return k.hbox(
        f"position · {sym} · no stop",
        [k.glyph("octagon", k.STATUS["danger.strong"]), k.text("words", s, k.NUM_BASE, k.TEXT_1)],
        {"gap": k.INSET_XS},
    )


def choices(verb_line: str, *, leave_t2: bool = False, w: int = DLG_IW) -> Any:
    """CD-6's two radios, none checked, under the group's lead (e27.scr129.choice.lead)."""
    lead = k.text("legend", k.copy("e27.scr129.choice.lead", label=L), k.LABEL, k.TEXT_1, w=w)
    leave = k.copy("e27.scr129.choice.leave")
    first = k.t2_radio(leave, "accounts.stop_missing", w=w) if leave_t2 else k.radio(leave, w=w)
    return k.vbox(
        "CMP-006 RadioGroup · two choices",
        [lead, first, k.radio(k.say(verb_line), w=w)],
        {"gap": k.STACK_SM},
        note="none checked at mount; arrows move, Space checks",
    )


def typed(*, value: str | None = None, w: int = DLG_IW) -> Any:
    """The typed label field (CMP-007 well, HD11)."""
    return k.field(k.copy("e27.scr129.typed", label=L), k.fixture(value) if value else None, w=w)


def confirm(label: str, look: str, hint_key: str | None = None) -> Any:
    """The footer's confirm: a button in its look, the validity hint under it (HD8)."""
    state = {"validity": "validity", "focus": "focus"}.get(look, "default")
    b = k.button(label, "destructive" if look in ("validity", "focus") else look, state)
    if hint_key is None:
        return b
    hint = k.text(
        "hint",
        k.copy(hint_key, **({"label": L} if "typed" in hint_key else {})),
        k.CAPTION,
        k.TEXT_2,
    )
    return k.vbox("confirm and hint", [b, hint], {"gap": k.STACK_XS, "align": "end"})


def alert(chars: str, *, w: int = DLG_IW, kids: list[Any] | None = None) -> Any:
    """CMP-027 (role="alert", once): the danger tone, the octagon, the words (§9 c175-danger-word, -glyph)."""
    body = k.vbox(
        "words",
        [k.text("line", chars, k.BODY, k.TEXT_1, w=w - 44), *(kids or [])],
        {"gap": k.STACK_XS},
    )
    return k.hbox(
        "CMP-027 alert · error",
        [k.glyph("octagon", k.STATUS["danger.strong"]), body],
        {
            "fill": k.STATUS["danger.subtle"],
            "stroke": k.STATUS["danger.strong"],
            "strokeWidth": k.HAIRLINE,
            "radius": k.R_CARD,
            "pad": k.INSET_MD,
            "gap": k.INSET_XS,
            "align": "start",
        },
        w=w,
        note='role="alert", announced once',
    )


def exposure_lines(*, no_stop: bool = False) -> list[Any]:
    """The count sentence (hi-fi's singular "1 running algo", quoted) and the two position lines."""
    return [
        k.say("sub_002 holds 2 positions, 3 working orders and 1 running algo."),
        pos_line(*POS[0], stop=not no_stop),
        pos_line(*POS[1]),
    ]


def ov(dlg: Any, **kw: Any) -> Any:
    k._choice("dialog")
    return k.overlay(dlg, **kw)


# --- Frames 49-61.
def revoke_title() -> str:
    return k.copy("e27.scr129.revoke.title", key_id_masked=KEY, label=L, ENV=ENV)


def f49() -> dict[str, Any]:
    dlg = k.rung_dialog(
        revoke_title(),
        [k.copy("e27.scr129.revoke.not_last", label=L, new=OTHER)],
        rung=1,
        confirm=k.button(k.copy("e27.scr129.revoke.confirm", key_id_masked=KEY), "destructive"),
        marker="e27.scr129.marker.revoke",
    )
    return shell(overlays=[ov(dlg)])


def revoke_last(no_stop: bool) -> dict[str, Any]:
    cons: list[Any] = [k.copy("e27.scr129.revoke.last", label=L), *exposure_lines(no_stop=no_stop)]
    if no_stop:
        cons.append(k.copy("e27.scr129.revoke.no_stop", symbol="BTCUSDT", side="long", qty="0.250"))
    cons.append(k.say("The key still works at Bybit until you delete it in Bybit's dashboard."))
    dlg = k.rung_dialog(
        revoke_title(),
        cons,
        rung=3,
        choices=choices(
            "Flatten first — cancel 3 orders, stop 1 algo and close 2 positions, then " "revoke.",
            leave_t2=no_stop,
        ),
        typed=typed(),
        marker="e27.scr129.marker.revoke",
        confirm=confirm(k.copy("e27.scr129.confirm.choose"), "validity", "e27.scr129.hint.choose"),
    )
    return shell(overlays=[ov(dlg)])


def f52() -> dict[str, Any]:
    det = k.vbox(
        "row details · revoked key",
        [
            k.hbox(
                "key line",
                [
                    k.masked_id(KEY),
                    k.text(
                        "outcome",
                        k.copy("e27.scr125.outcome.revoked", hh_mm="14:12"),
                        k.BODY,
                        k.TEXT_1,
                    ),
                ],
                {"gap": k.INSET_SM},
            ),
            k.text(
                "CP-4 and CD-8",
                k.copy("e27.scr129.revoked.row"),
                k.BODY,
                k.TEXT_2,
                w=k.INNER_W - 32,
            ),
        ],
        {"gap": k.STACK_XS, "padL": k.INSET_LG, "padB": k.INSET_SM},
    )
    row = acct_row(L, UID, OTHER, focus=True, extra=[det])
    return shell(content=route([row]))


def f53() -> dict[str, Any]:
    k._fallback("SKELETON")
    skel = k.vbox(
        "CMP-015 skeleton · loading (static)",
        [
            k.rect(f"line {i}", w, 12, k.HOVER, o={"radius": k.R_CONTROL})
            for i, w in ((1, 520), (2, 440), (3, 480))
        ],
        {"gap": k.STACK_SM},
        w=520,
        h=52,
        note='aria-busy="true" on the body; static under reduced motion',
    )
    dlg = k.rung_dialog(
        k.copy("e27.scr129.disable.title", label=L, ENV=ENV),
        [k.copy("e27.scr129.loading", label=L), skel],
        rung=3,
        confirm=None,
        ask=False,
        marker=None,
    )
    return shell(overlays=[ov(dlg)])


def disable_lines() -> list[str]:
    return [
        k.copy("e27.scr129.disable.users", users=USERS, label=L),
        k.copy("e27.scr129.disable.rules", rules=RULES),
        *k.copies("e27.scr129.disable.history"),
    ]


def disable_dialog(*, error: Any = None, value: str | None = None, w: int = k.DIALOG_W) -> Any:
    iw = w - 2 * k.PX[k.DIALOG_PAD]
    cf = (
        confirm(k.copy("e27.scr129.confirm.disable", label=L), "focus")
        if value
        else confirm(
            k.copy("e27.scr129.confirm.disable", label=L), "validity", "e27.scr129.hint.typed"
        )
    )
    return k.rung_dialog(
        k.copy("e27.scr129.disable.title", label=L, ENV=ENV),
        [k.copy("e27.scr129.disable.stops", label=L), *disable_lines()],
        rung=3,
        typed=typed(value=value, w=iw),
        error=error,
        confirm=cf,
        cancel_focused=not value,
        w=w,
    )


def f54() -> dict[str, Any]:
    return shell(overlays=[ov(disable_dialog())])


def f55() -> dict[str, Any]:
    dlg = k.rung_dialog(
        k.copy("e27.scr129.disable.title", label=L, ENV=ENV),
        [k.copy("e27.scr129.disable.stops", label=L), *exposure_lines(), *disable_lines()],
        rung=3,
        choices=choices(
            "Flatten first — cancel 3 orders, stop 1 algo and close 2 positions, then " "disable."
        ),
        typed=typed(),
        confirm=confirm(k.copy("e27.scr129.confirm.choose"), "validity", "e27.scr129.hint.choose"),
    )
    return shell(overlays=[ov(dlg)])


def f56() -> dict[str, Any]:
    iw = HALF_W - 2 * k.PX[k.DIALOG_PAD]
    dead = k.rung_dialog(
        k.copy("e27.scr129.disable.title", label=L, ENV=ENV),
        [alert(k.copy("e27.scr129.unknown.dead", label=L), w=iw)],
        rung=3,
        typed=typed(w=iw),
        confirm=k.button(k.copy("e27.scr129.confirm.disable_leave"), "destructive"),
        cancel_focused=False,
        w=HALF_W,
    )
    copy_btn = k.button(
        k.copy("e27.shared.copy"), "secondary", name="CMP-033 CopyButton · egress IP"
    )
    fix = alert(
        k.say("Bybit refuses sub_002's key from 203.0.113.10. Fix it in Bybit's dashboard"),
        w=iw,
        kids=[
            copy_btn,
            k.text(
                "line 2",
                k.say("then try again; until then nothing can be revoked, disabled " "or deleted."),
                k.BODY,
                k.TEXT_1,
                w=iw - 44,
            ),
        ],
    )
    fix = k.focus_ring(fix, name="summary · focused (tabindex -1)")
    close = k.button(k.copy("e27.shared.close"), "secondary")
    fixable = k.vbox(
        "CMP-044 ConfirmDialog · fixable",
        [
            k.text(
                "title",
                k.copy("e27.scr129.disable.title", label=L, ENV=ENV),
                k.HEADING_MD,
                k.TEXT_1,
                w=iw,
            ),
            fix,
            k.fit_row(k.hbox("footer", [close], {"justify": "end"}, w=iw)),
        ],
        {
            "fill": k.OVERLAY,
            "shadow": k.E_DIALOG,
            "radius": k.R_DIALOG,
            "pad": k.DIALOG_PAD,
            "gap": k.STACK_MD,
        },
        w=HALF_W,
        note="the answer replaces the dialog content; [Close] only",
    )
    return shell(
        overlays=[
            ov(dead, x=24, name="overlay · dead"),
            ov(fixable, x=HALF_W + 56, scrim=False, name="overlay · fixable"),
        ]
    )


def f57() -> dict[str, Any]:
    iw = HALF_W - 2 * k.PX[k.DIALOG_PAD]
    e503 = alert(k.copy("e27.scr129.error.timeout", label=L, n=5), w=iw)
    e502 = alert(k.copy("e27.scr129.error.code", ret_code=10006), w=iw)
    return shell(
        overlays=[
            ov(disable_dialog(error=e503, value=L, w=HALF_W), x=24, name="overlay · 503"),
            ov(
                disable_dialog(error=e502, value=L, w=HALF_W),
                x=HALF_W + 56,
                scrim=False,
                name="overlay · 502",
            ),
        ]
    )


def delete_tail() -> list[str]:
    return [
        k.copy("e27.scr129.delete.keys", label=L),
        k.copy("e27.scr129.delete.users", users=USERS, label=L),
        k.copy("e27.scr129.disable.rules", rules=RULES),
        k.copy("e27.scr129.delete.history"),
        k.copy("e27.scr129.delete.bybit"),
    ]


def f58() -> dict[str, Any]:
    dlg = k.rung_dialog(
        k.copy("e27.scr129.delete.title", label=L, ENV=ENV),
        [k.copy("e27.scr129.delete.flat", label=L), *delete_tail()],
        rung=3,
        typed=typed(),
        confirm=confirm(
            k.copy("e27.scr129.delete.confirm", label=L), "validity", "e27.scr129.hint.typed"
        ),
    )
    return shell(overlays=[ov(dlg)])


def f59() -> dict[str, Any]:
    lead = k.say(
        "sub_002 holds 2 positions, 3 working orders and 1 running algo. Delete never leaves them behind: it "
        "flattens first — cancels 3 orders, stops 1 algo, closes 2 positions reduce-only — then deletes. If "
        "anything is still open, nothing is deleted."
    )
    dlg = k.rung_dialog(
        k.copy("e27.scr129.delete.title", label=L, ENV=ENV),
        [lead, pos_line(*POS[0]), pos_line(*POS[1]), *delete_tail()],
        rung=3,
        typed=typed(),
        confirm=confirm(
            k.copy("e27.scr129.delete.confirm_flatten"), "validity", "e27.scr129.hint.typed"
        ),
    )
    return shell(overlays=[ov(dlg)])


def f60() -> dict[str, Any]:
    items = k.copies("e27.scr125.menu.items")
    m = k.menu(
        [
            k.menu_item(items[0]),
            k.menu_item(items[1]),
            k.menu_item(items[6], second=k.copy("e27.scr125.menu.ask.label")),
            k.menu_item(items[7], reason_key="accounts.never_keyed", focused=True),
        ],
        name=f"CMP-041 Menu · {k.copy('e27.scr125.row.actions', label=L, ENV=ENV)}",
    )
    row = acct_row(L, UID, None, state="No key — inactive", focus=True)
    return shell(
        content=route([row]),
        overlays=[
            ov(m, x=k.NAV_W + k.MAIN_W - 16 - 296, y=470, scrim=False, name="overlay · row menu")
        ],
    )


def f61() -> dict[str, Any]:
    enable = k.button(
        k.copy("e27.scr125.menu.enable"), "secondary", name="CMP-001 Enable… (in Disable…'s place)"
    )
    out = k.hbox(
        "outcome",
        [
            k.text("line", k.copy("e27.scr125.outcome.disabled", hh_mm="14:12"), k.BODY, k.TEXT_1),
            enable,
        ],
        {"gap": k.INSET_MD, "padL": k.INSET_LG, "padB": k.INSET_SM},
    )
    row = acct_row(L, UID, KEY, state="Disabled", extra=[out])
    deleted = k.notice(
        [k.copy("e27.shell.notice.deleted", label=L, ENV=ENV)], name="CMP-028 notice · deleted"
    )
    dlg = k.rung_dialog(
        k.copy("e27.scr129.enable.title", label=L, ENV=ENV),
        [k.copy("e27.scr129.enable.rules")],
        rung=1,
        confirm=k.button(k.copy("e27.scr129.enable.confirm", label=L), "primary"),
    )
    return shell(content=route([row]), notices=[deleted], overlays=[ov(dlg, x=600, y=540)])


ASK_G8 = ("G-8, #895 / #898", "the ask line")


def cells() -> list[Any]:
    """The 13 cells in §0's order."""
    t = k.BOARDS[NN].frames
    return [
        k.frame(
            t[0],
            f49,
            proposed=["HD8"],
            notes=[
                "focus: Cancel; Esc cancels; focus returns to Actions for sub_002 · LIVE",
                "not drawn: e27.shared.resend_unconfirmed after an unanswered re-send (the key list read back, §7 L1467)",
            ],
        ),
        k.frame(
            t[1],
            lambda: revoke_last(False),
            proposed=["HD8", "HD11"],
            notes=[
                (
                    "after a choice the confirm reads e27.scr129.revoke.confirm_leave / confirm_flatten; valid once "
                    "sub_002 is typed (e27.scr129.hint.typed)"
                )
            ],
        ),
        k.frame(
            t[2],
            lambda: revoke_last(True),
            proposed=["HD8"],
            notes=[
                (
                    "T2 per §10.1: an arrow focuses the option without checking it; Space re-shows the reason once; "
                    "a 409 open_exposure after a stale read shows the same refusal (T4)"
                )
            ],
        ),
        k.frame(
            t[3],
            f52,
            notes=[
                (
                    "outcome, never T2; the shell announcer reads it politely once; focus on Actions for "
                    "sub_002 · LIVE"
                )
            ],
        ),
        k.frame(
            t[4],
            f53,
            strips=[
                ("G-7, #898", "no side-effect-free read; the summary comes only with a 409 today")
            ],
            proposed=["HD8"],
            notes=[
                (
                    "no confirm in the DOM; at 1 s the line reads e27.scr129.loading.slow, in "
                    "place, not announced"
                )
            ],
        ),
        k.frame(t[5], f54, strips=[ASK_G8], proposed=["HD8", "HD11"]),
        k.frame(
            t[6],
            f55,
            strips=[ASK_G8],
            proposed=["HD8", "HD11"],
            notes=["after a choice: e27.scr129.confirm.disable_leave / disable_flatten"],
        ),
        k.frame(
            t[7],
            f56,
            strips=[ASK_G8, ("D03-G1, #896", "the address and its Copy (fixable form)")],
            proposed=["HD14"],
            notes=[
                (
                    "two forms side by side: dead (left, from Disable) and fixable (right, "
                    "[Close] only); focus moves to the summary"
                )
            ],
        ),
        k.frame(
            t[8],
            f57,
            strips=[ASK_G8],
            notes=[
                (
                    "two forms side by side: 503 (left) and 502 (right); focus stays "
                    "on the confirm; a failed read is never replayed"
                )
            ],
        ),
        k.frame(t[9], f58, strips=[ASK_G8], proposed=["HD8", "HD11"]),
        k.frame(
            t[10],
            f59,
            strips=[ASK_G8],
            proposed=["HD8", "HD11"],
            notes=["the one choice is the confirm's own label; no radio, no delete anyway"],
        ),
        k.frame(
            t[11],
            f60,
            notes=["Enter or Space on the T2 item opens nothing and re-shows the reason once"],
        ),
        k.frame(
            t[12],
            f61,
            strips=[("G-8, #895 / #898", "the Enable… dialog's ask line")],
            proposed=["D03-Q4"],
            notes=[
                (
                    "the frame draws both outcome forms of row 61: the Disabled row with [Enable…] and its rung-1 "
                    "dialog, and the Deleted notice under the h1 (focus moves to it after a delete)"
                )
            ],
        ),
    ]


def build() -> dict[str, Any]:
    return k.board(
        NN,
        cells(),
        source="E27-D03 §0 L225 (board 08); §7 L1389-1480 (hi-fi rows L1467-1479); §2.4 "
        "CMP-044 rungs; §10.1 T2; §12.1 deck",
        cols=4,
        notes=[
            (
                "SCR-125 behind each dialog is drawn small (Main, sub_001, sub_002 LIVE rows); board 04 "
                "owns its anatomy"
            ),
            (
                "counts quote the hi-fi rows' singular \"1 running algo\" (say()); the deck's {k} running "
                'algos would read "1 running algos"'
            ),
        ],
    )


def main() -> int:
    bd = build()
    path = k.KIT_DIR / f"{k.stem(NN)}.json"
    print(k.write_sheet(path, bd))
    print(k.compact_sheet(path))
    print(
        k.write_board_md(
            NN,
            bd,
            checks=[
                "13 frames, names as E27-D02 §7; T2 only on frames 51 and 60",
                (
                    "every frame string from the deck / §12.2 / pinned quotes; fixtures only (sub_002 1234569, ...e5f6, "
                    "...d9e0, alex, bea, 203.0.113.10); times UTC"
                ),
                "rung-3 confirms in the validity look until a choice and the typed label; frame 53 renders no confirm",
            ],
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

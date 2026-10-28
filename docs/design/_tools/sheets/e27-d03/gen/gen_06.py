#!/usr/bin/env python3
"""gen_06 — E27-D03 (#816) board 06 `E27-D03 / 06 scr-126-add-key` (offline; no Penpot, no network).

Builds §0's nineteen frames of board 06 (L223): SCR-126 frames 18-32 in CMP-087 at 1280 x 800, comfortable, and
SCR-016 step 3's four frames 72-75 as 800 px insets (BQ-1), from the hi-fi rows §4.3 L1185-1199 and §4.4 L1223-1226,
the anatomy §4.1 L1133-1161 and §4.4 L1201-1222; writes 06-scr-126-add-key.json / .md beside the kit, compacts it.
Run: python3 -I -B docs/design/_tools/sheets/e27-d03/gen/gen_06.py

LOCAL HELPERS (the kit is never edited; gen_07 imports them):
  card()          a CMP-050 card (color.surface.raised, radius.card, elevation.card, space.inset.lg).
  piece()         a run of an ISSUED deck string (split at its [Copy] slot or around a time), issued as a part of it.
  cp_text()       a deck sentence holding "[Copy]" drawn as its text runs with CMP-033 between them.
  copy_button()   CMP-033 (CMP-002 ghost, 32 px): the copy glyph and "Copy".
  well()/field_() CMP-007 / CMP-201 wells (HD11) with the masked bullets drawn as dots (no characters), the
                  invalid form (2 px color.status.danger.default, the octagon and the message under it).
  alert()         CMP-027 (error: danger.subtle + octagon; warning: warning.subtle + triangle; 1 px strong border).
  rows()          CMP-203 rows in the pipeline's order: passed before the failing row, then not checked (§2.5).
  stepper126()/stepper016()  CMP-066 nav (BQ-12): the done step's check and word, the current step primary text.
  loading_button() CMP-001 loading for SCR-126 (the spinner replaces the label, width locked; frame 20).
  adm()           k.admin_frame() at the height its content needs (> 800 only for §3.1's continuation) with the
                  add route's band "Admin area · Accounts · Add a Bybit account" (§4.1 A; D02:443).
"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
KIT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT_DIR))
import e27d03kit as k

NN = 6
CARD_W, CARD_IW = 640, 608  # §4.1 C: one CMP-050 card 640 px wide, 608 inside
EGRESS = "203.0.113.10"
DANGER_DEFAULT = "color.status.danger.default"
LOCAL_NOTES = [
    (
        "Local helpers in gen_06.py (kit unchanged): card, piece, cp_text, copy_button, well, field_, alert, rows, "
        "stepper126, stepper016, loading_button, adm (see the module docstring)."
    ),
    "Masked bullets are drawn as ten 6 px dots in color.text.primary (no characters: CMP-201 never shows a value).",
    (
        "A deck sentence holding [Copy] is drawn as its runs with CMP-033 between them; the runs are parts of the issued "
        "deck string (piece())."
    ),
]


def card(name: str, kids: list[Any], *, w: int = CARD_W, gap: str = k.STACK_MD) -> dict[str, Any]:
    """A CMP-050 card (§4.1 C)."""
    return k.vbox(
        name,
        kids,
        {"fill": k.RAISED, "radius": k.R_CARD, "shadow": k.E_CARD, "pad": k.INSET_LG, "gap": gap},
        w=w,
        note="CMP-050 Card",
    )


def piece(full: str, seg: str) -> str:
    """seg, a run of the issued string full, issued as its part (never new copy)."""
    seg = seg.strip()
    if full not in k._ISSUED or seg not in full:
        raise ValueError(f"piece({seg!r}) is not a run of an issued string")
    return k._issue(seg)


def copy_button(*, focused: bool = False) -> dict[str, Any]:
    """CMP-033 CopyButton: CMP-002 ghost, 32 px, the copy glyph and its word (color.text.secondary)."""
    b = k.hbox(
        "CMP-033 CopyButton · ghost",
        [k.glyph("copy", k.TEXT_2), k.text("label", k.copy("e27.shared.copy"), k.LABEL, k.TEXT_2)],
        {"padX": k.INSET_SM, "gap": k.INSET_XS, "radius": k.R_CONTROL},
        h=k.dens().control,
        note="the one copy control on the screen (§4.1 F)",
    )
    return k.focus_ring(b) if focused else b


def cp_text(
    full: str,
    *,
    w: int = CARD_IW,
    typo: str = k.BODY,
    color: str = k.TEXT_1,
    name: str = "sentence with Copy",
) -> dict[str, Any]:
    """full (issued, holding "[Copy]") as its runs: the text before, then a row of CMP-033 and the text after."""
    before, after = full.split("[Copy]", 1)
    return k.vbox(
        name,
        [
            k.text("run 1", piece(full, before), typo, color, w=w),
            k.hbox(
                "copy row",
                [copy_button(), k.text("run 2", piece(full, after), typo, color, w=w - 96)],
                {"gap": k.INSET_SM},
            ),
        ],
        {"gap": k.STACK_XS},
        w=w,
    )


def well(
    w: int = CARD_IW,
    *,
    bullets: bool = False,
    value: str | None = None,
    invalid: bool = False,
    focused: bool = False,
    readonly: bool = False,
    typo: str = k.BODY,
) -> dict[str, Any]:
    """A CMP-007 well (HD11): color.surface.app, 1 px color.text.tertiary (invalid: 2 px danger.default)."""
    kids: list[Any] = []
    if value:
        kids.append(k.text("value", value, typo, k.TEXT_1))
    if bullets:
        kids.append(
            k.hbox(
                "bullets",
                [k.ellipse("bullet", 6, 6, {"fill": k.TEXT_1}) for _ in range(10)],
                {"gap": k.INSET_XS},
                h=6,
                note="the masked value: dots, never characters",
            )
        )
    o = {
        "fill": k.APP,
        "stroke": DANGER_DEFAULT if invalid else k.TEXT_3,
        "strokeWidth": k.THICK if invalid else k.HAIRLINE,
        "radius": k.R_CONTROL,
        "padX": k.INSET_SM,
    }
    nm = "CMP-007 well" + (" · invalid" if invalid else "") + (" · readonly" if readonly else "")
    wl = k.hbox(nm, kids, o, w=w, h=k.dens().control)
    return k.focus_ring(wl) if focused else wl


def field_(
    label: str,
    *,
    hint: str | None = None,
    w: int = CARD_IW,
    value: str | None = None,
    bullets: bool = False,
    write_only: bool = False,
    error: str | None = None,
    readonly: bool = False,
    focused: bool = False,
    typo: str = k.BODY,
) -> dict[str, Any]:
    """CMP-040 + CMP-007 (or CMP-201 writeOnly): label type.ui.label color.text.secondary, the well, the help
    (type.ui.caption color.text.secondary), the invalid message (octagon + type.ui.caption color.text.primary).
    """
    msg = None
    if error:
        msg = k.hbox(
            "message",
            [
                k.glyph("octagon", k.STATUS["danger.strong"]),
                k.text("words", error, k.CAPTION, k.TEXT_1, w=w - 24),
            ],
            {"gap": k.INSET_XS, "align": "start"},
            w=w,
            note="aria-describedby; never colour alone",
        )
    kids = [
        k.text("label", label, k.LABEL, k.TEXT_2),
        well(
            w,
            bullets=bullets,
            value=value,
            invalid=bool(error),
            focused=focused,
            readonly=readonly,
            typo=typo,
        ),
        k.text("help", hint, k.CAPTION, k.TEXT_2, w=w) if hint else None,
        msg,
    ]
    nm = f"CMP-201 writeOnly · {label}" if write_only else f"CMP-040 field · {label}"
    return k.vbox(nm, kids, {"gap": k.STACK_XS}, w=w)


def alert(
    lines: list[Any], *, tone: str = "error", w: int = CARD_IW, name: str | None = None
) -> dict[str, Any]:
    """CMP-027 Alert: error = danger.subtle with the octagon, warning = warning.subtle with the triangle; words
    color.text.primary (type.ui.body), a 1 px strong border."""
    t = "danger" if tone == "error" else "warning"
    gl = k.glyph("octagon" if t == "danger" else "triangle", k.STATUS[f"{t}.strong"])
    tw = w - 2 * 12 - 24
    txt = k.vbox(
        "words",
        [
            s if isinstance(s, dict) else k.text(f"line {i}", s, k.BODY, k.TEXT_1, w=tw)
            for i, s in enumerate(lines, 1)
        ],
        {"gap": k.STACK_XS},
    )
    return k.hbox(
        name or f"CMP-027 Alert · {tone}",
        [gl, txt],
        {
            "fill": k.STATUS[f"{t}.subtle"],
            "stroke": k.STATUS[f"{t}.strong"],
            "strokeWidth": k.HAIRLINE,
            "radius": k.R_CARD,
            "pad": k.INSET_MD,
            "gap": k.INSET_SM,
            "align": "start",
        },
        w=w,
        note='role="alert", announced once' if t == "danger" else 'role="status"',
    )


# --- CMP-203 rows in the pipeline's order (§2.5 L909-932; frame 3).
CHECK_KEYS = ("env", "withdrawal", "rights", "trade", "uta", "uid", "allowlist", "expiry", "probe")


def _passed(i: int, env: str, uid: str, hh: str) -> str:
    key = CHECK_KEYS[i]
    fills: dict[str, Any] = {
        "env": {"ENV": env},
        "withdrawal": {"hh_mm": hh},
        "uid": {"uid": uid},
        "allowlist": {"egress_ip": EGRESS},
        "probe": {"n": 4},
    }.get(key, {})
    return k.copy(f"e27.checks.{key}.passed", **fills)


def _failed(i: int, env: str) -> str:
    key = CHECK_KEYS[i]
    if (
        key == "withdrawal"
    ):  # no e27.checks.withdrawal.failed row: CMP-175's critical word (kit choice, gap noted)
        return k.copy("e27.cmp175.withdrawal_detected")
    return k.copy(f"e27.checks.{key}.failed", **({"ENV": env} if key == "env" else {}))


def rows(
    env: str,
    uid: str,
    *,
    fail: int | None = None,
    fail_words: str | None = None,
    none: bool = False,
    hh: str = "14:02",
    upto: int = 9,
) -> list[tuple[str, str, str]]:
    """(check, outcome, words) for the first upto checks: all passed; or passed before fail, fail failed, the rest
    not checked; or none=True every row not checked (KeyVerificationNotRead)."""
    names = k.copies("e27.checks.names")
    out = []
    for i in range(upto):
        if none or (fail is not None and i > fail):
            out.append((names[i], "not checked", k.copy("e27.checks.not_checked")))
        elif fail is not None and i == fail:
            out.append((names[i], "failed", fail_words or _failed(i, env)))
        else:
            out.append((names[i], "passed", _passed(i, env, uid, hh)))
    return out


# --- CMP-066 nav steppers (BQ-12).
def _step(n: str, label: str, state: str) -> dict[str, Any]:
    ink = k.TEXT_1 if state in ("current", "done") else k.TEXT_2
    kids = [k.tglyph(n, ink, k.LABEL, name="numeral"), k.text("label", label, k.LABEL, ink)]
    if state == "done":
        kids.append(k.glyph("check", k.STATUS["success.strong"]))
    note = (
        'aria-current="step"'
        if state == "current"
        else ("a link back to its step" if state == "done" else None)
    )
    return k.hbox(f"step {n} · {state}", kids, {"gap": k.INSET_XS}, note=note)


def stepper126(states: tuple[str, str]) -> dict[str, Any]:
    """SCR-126's two steps (e27.scr126.stepper), "1 Register the account ✓ · 2 Add its API key (current)"."""
    labels = k.copies("e27.scr126.stepper")
    items: list[Any] = []
    for i, (lab, st) in enumerate(zip(labels, states)):
        if i:
            items.append(k.tglyph("·", k.TEXT_2, k.LABEL, name="separator"))
        items.append(_step(str(i + 1), lab, st))
    return k.hbox(
        "CMP-066 Stepper · nav", items, {"gap": k.INSET_SM}, h=32, note='nav, aria-label "Steps"'
    )


def stepper016(current: int = 3, *, w: int = 752) -> dict[str, Any]:
    """SCR-016's six steps (e27.scr016.stepper): steps before current done, current primary text, the rest secondary."""
    items: list[Any] = []
    for i, lab in enumerate(k.copies("e27.scr016.stepper"), 1):
        st = "done" if i < current else "current" if i == current else "todo"
        if i > 1:
            items.append(k.tglyph("·", k.TEXT_2, k.LABEL, name="separator"))
        items.append(_step(str(i), lab, st))
    return k.hbox(
        "CMP-066 Stepper · nav · six steps", items, {"gap": k.INSET_SM, "wrap": "wrap"}, w=w
    )


def loading_button(label: str, variant: str = "primary") -> dict[str, Any]:
    """CMP-001 loading (frame 20): the spinner replaces the label, the width locked, aria-busy, focusable, never
    gated (CMP-014 in color.text.on-action on the primary fill)."""
    w = round(k.est_width(k.button(label, variant)))
    spin = k.ellipse(
        "CMP-014 Spinner", 14, 14, {"stroke": k.TEXT_ON_ACTION, "strokeWidth": k.THICK}
    )
    return k.hbox(
        f"CMP-001 button · {variant} · loading",
        [spin],
        {"fill": k.ACTION[variant], "radius": k.R_CONTROL, "justify": "center"},
        w=w,
        h=k.dens().control,
        note=f'accessible name "{label}", aria-busy="true", focusable, activation suppressed',
    )


def buttons(kids: list[Any], *, w: int = CARD_IW, name: str = "buttons") -> dict[str, Any]:
    """A right-aligned footer row (space.3 = 12 px apart), checked to fit."""
    h = round(
        max(k.est_height(c) for c in kids)
    )  # a row of text-free controls (the loading button) needs its h
    return k.fit_row(k.hbox(name, kids, {"justify": "end", "gap": k.INSET_MD}, w=w, h=h))


# --- The admin frame at its content's height, with the add route's band.
ROUTE_BAND = "Admin area · Accounts · Add a Bybit account"


def adm(
    name: str,
    *,
    content: list[Any],
    route_band: bool = True,
    h1: str | None = None,
    primary: Any = None,
    banners: list[Any] | None = None,
    notices: list[Any] | None = None,
    overlays: list[Any] | None = None,
    verdict: Any = None,
    footer: bool = False,
    h: int | None = None,
    grace: str | None = None,
) -> dict[str, Any]:
    """k.admin_frame() for SCR-126 / SCR-127: §3.1 blocks A-C, the PageHeader, then content; h = 800 unless the
    content needs the page's continuation (drawn under the viewport line, §3.1)."""
    bn, nt = banners or [], notices or []
    need = (
        k.TOP_H
        + sum(k.est_height(b) for b in bn)
        + k.STATUS_H
        + 2 * 16
        + 32
        + 4
        + 32
        + 32
        + sum(k.est_height(n) for n in [*nt, *content, *([verdict] if verdict else [])])
        + 12 * (4 + len(nt) + len(content) + (1 if verdict else 0))
        + (28 if footer else 0)
        + 8
    )
    hh = h or max(k.FRAME_H, int(math.ceil(need / 16.0) * 16))
    fr = k.admin_frame(
        name,
        content=content,
        banners=bn,
        notices=nt,
        overlays=overlays or [],
        h1=h1,
        primary=primary,
        verdict=verdict,
        footer=footer,
        h=hh,
        grace=grace,
    )
    for _p, x in k.walk(fr):
        if x.get("name") == "end" and not x.get("kids"):
            x["h"] = 32  # the PageHeader's empty end slot (no meta, no primary on the edit route)
    if route_band:
        for _p, x in k.walk(fr):
            if x.get("name") == "CMP-087 band":
                x["kids"][0]["chars"] = k.say(ROUTE_BAND)
                x["kids"][0]["note"] = "the add route's band (§4.1 A; D02:443)"
    return fr


# --- SCR-126's cards (§4.1 C-K).
def h2_env(label: str, uid: str, env: str, *, w: int = CARD_IW) -> dict[str, Any]:
    """Block D: "API key for {label} · UID {uid} · {ENV} (this deployment)", the environment word as the pill."""
    full = k.copy("e27.scr126.key.h2", label=label, uid=uid, ENV=env)
    a, b, _c = full.split(" · ")
    return k.hbox(
        "h2 · key step",
        [
            k.text("h2 run 1", a, k.HEADING_SM, k.TEXT_1),
            k.tglyph("·", k.TEXT_2),
            k.text("h2 run 2", b, k.HEADING_SM, k.TEXT_1),
            k.tglyph("·", k.TEXT_2),
            k.env_pill(env),
            k.text("h2 run 3", k.say("(this deployment)"), k.HEADING_SM, k.TEXT_1),
        ],
        {"gap": k.INSET_XS, "wrap": "wrap"},
        w=w,
        note=f'one h2: "{full}"',
    )


def instructions(*, w: int = CARD_IW) -> dict[str, Any]:
    """Block E: the lead and three static items (never boxes the owner ticks)."""
    lead, *items = k.copies("e27.scr126.key.instructions")
    return k.vbox(
        "instruction list",
        [k.text("lead", lead, k.BODY, k.TEXT_1, w=w)]
        + [
            k.hbox(
                f"item {i}",
                [k.tglyph("•", k.TEXT_2), k.text("words", s, k.BODY, k.TEXT_1, w=w - 16)],
                {"gap": k.INSET_XS, "align": "start"},
            )
            for i, s in enumerate(items, 1)
        ],
        {"gap": k.STACK_XS},
        w=w,
    )


def allowlist_row(*, w: int = CARD_IW, key: str = "e27.scr126.allowlist.help") -> dict[str, Any]:
    """Block F: CMP-036 dt "IP allowlist", dd CP-3 with CMP-033 (a target state before any check: D03-G1)."""
    dd = cp_text(k.copy(key, egress_ip=EGRESS), w=w, name="dd · CP-3")
    return k.vbox(
        "CMP-036 row · IP allowlist",
        [k.text("dt", k.copy("e27.scr126.allowlist.label"), k.LABEL, k.TEXT_2), dd],
        {"gap": k.STACK_XS},
        w=w,
    )


def key_fields(
    *,
    bullets: bool = False,
    readonly: bool = False,
    errors: tuple[str | None, str | None] = (None, None),
    w: int = CARD_IW,
) -> list[dict[str, Any]]:
    """Blocks G-H: API key and API secret on CMP-201's writeOnly variant (BQ-8, HD11)."""
    kl, kh = k.copies("e27.scr126.key.label")
    return [
        field_(
            kl, hint=kh, w=w, bullets=bullets, readonly=readonly, write_only=True, error=errors[0]
        ),
        field_(
            k.copy("e27.scr126.secret.label"),
            hint=k.copy("e27.scr126.secret.help"),
            w=w,
            bullets=bullets,
            readonly=readonly,
            write_only=True,
            error=errors[1],
        ),
    ]


def ask_marker(*, grace: str | None = None, w: int = CARD_IW) -> list[dict[str, Any]]:
    """Block I: the ask line (or the keys grace line) and CMP-093's marker, last before the buttons."""
    ask = k.copy("e27.shell.grace.keys", m_ss=grace) if grace else k.copy("e27.shared.ask")
    return [
        k.text("ask line", ask, k.CAPTION, k.TEXT_2, w=w),
        k.text("CMP-093 marker", k.copy("e27.scr126.marker"), k.CAPTION, k.TEXT_3, w=w),
    ]


def verify(state: str = "default") -> dict[str, Any]:
    """[Verify and save] (CMP-001 primary): default, loading (frame 20) or T2 (frame 29: no inline reason, its
    aria-describedby on the KEK notice)."""
    lab = k.copy("e27.scr126.buttons")
    if state == "loading":
        return loading_button(lab)
    if state == "t2":
        return k.hbox(
            "T2 · CMP-079 RbacGate · Verify and save",
            [k.button(lab, "primary", "t2")],
            {},
            note='aria-disabled="true"; aria-describedby the KEK notice (one notice, many pointers; 2a)',
        )
    return k.button(lab, "primary", state)


def key_step(
    env: str = "DEMO",
    label: str = "demo-1",
    uid: str = "9000001",
    *,
    bullets: bool = False,
    readonly: bool = False,
    v_state: str = "default",
    allowlist: bool = True,
    grace: str | None = None,
    errors: tuple[str | None, str | None] = (None, None),
    gap: str = k.STACK_MD,
) -> dict[str, Any]:
    """Block C: the form card holding D-J (frame 19's key step)."""
    kids = [
        h2_env(label, uid, env),
        instructions(),
        allowlist_row() if allowlist else None,
        *key_fields(bullets=bullets, readonly=readonly, errors=errors),
        *ask_marker(grace=grace),
        buttons([k.button(k.copy("e27.shared.cancel"), "secondary"), verify(v_state)]),
    ]
    return card("CMP-050 form card · key step", kids, gap=gap)


def result_card(kids: list[Any]) -> dict[str, Any]:
    """Block K: the result card (from y 180, above the form card): the h3 then the outcome."""
    return card(
        "CMP-050 result card",
        [k.text("h3", k.copy("e27.scr126.result.h3"), k.HEADING_SM, k.TEXT_1), *kids],
    )


def h1_126(states: tuple[str, str] = ("done", "current")) -> dict[str, Any]:
    """Block B's kwargs: the h1 "Add a Bybit account" and the stepper at its right."""
    return {"h1": k.copy("e27.scr126.h1"), "primary": stepper126(states)}


def checklist(rws: list[tuple[str, str, str]], w: int = CARD_IW) -> dict[str, Any]:
    """CMP-203 on the card (frame 3's rows)."""
    return k.check_list(rws, w=w)


# --- Board 06's frames (§0 L223; hi-fi rows L1185-1199, L1223-1226).
FR = list(k.BOARDS[NN].frames)
G1 = ("D03-G1, #896", "the egress address and its Copy before any check")


def env_line(env: str) -> dict[str, Any]:
    """A CMP-036 environment row: the CMP-075 pill and "(this deployment)" (e27.scr126.register.env, no control)."""
    k.copy("e27.scr126.register.env", ENV=env)
    return k.hbox(
        "CMP-036 row · environment",
        [k.env_pill(env), k.text("words", k.say("(this deployment)"), k.BODY, k.TEXT_1)],
        {"gap": k.INSET_XS},
        note=f'"{env} (this deployment)"; no control (OQ-4)',
    )


def f18() -> dict[str, Any]:
    """Frame 18: register the account shell, filled for demo-1 (Main account)."""
    lab, uid, kind, main_, sub, _parent = k.copies("e27.scr126.register.fields")
    kinds = k.vbox(
        "CMP-006 RadioGroup · Kind",
        [
            k.text("label", kind, k.LABEL, k.TEXT_2),
            k.hbox(
                "options",
                [k.radio(main_, checked=True, w=200), k.radio(sub, w=200)],
                {"gap": k.INSET_LG},
            ),
        ],
        {"gap": k.STACK_XS},
        note="horizontal; the arrows move and select",
    )
    c = card(
        "CMP-050 form card · register",
        [
            field_(lab, value=k.fixture("demo-1")),
            field_(uid, value=k.fixture("9000001"), typo=k.NUM_BASE),
            kinds,
            env_line("DEMO"),
            buttons(
                [
                    k.button(k.copy("e27.shared.cancel"), "secondary"),
                    k.button(k.copy("e27.scr126.register.buttons"), "primary"),
                ]
            ),
        ],
    )
    return adm(FR[0], content=[c], **h1_126(("current", "todo")))


def f19() -> dict[str, Any]:
    """Frame 19: §4.1 exactly, before any answer."""
    return adm(FR[1], content=[key_step()], **h1_126())


def f20() -> dict[str, Any]:
    """Frame 20: validating — the result card's status line only, the wells readonly, Verify and save loading."""
    st = card(
        "CMP-050 result card · status line",
        [
            k.text("status", k.copy("e27.scr126.validating"), k.BODY, k.TEXT_2, w=CARD_IW),
            k.text(
                "status · after about 3 s",
                k.copy("e27.scr126.validating.long"),
                k.BODY,
                k.TEXT_2,
                w=CARD_IW,
            ),
        ],
    )
    st["note"] = 'role="status"; each sentence polite once; no staged reveal, no progress bar (D18)'
    return adm(
        FR[2], content=[st, key_step(bullets=True, readonly=True, v_state="loading")], **h1_126()
    )


def f21() -> dict[str, Any]:
    """Frame 21: verified and stored — the result card alone, both steps done."""
    full = k.copy("e27.scr126.saved", key_id_masked="...a7b8", label="demo-1")
    pas = k.hbox(
        "pass line",
        [
            k.glyph("check", k.STATUS["success.strong"]),
            k.text("words", full, k.BODY, k.TEXT_1, w=CARD_IW - 24),
        ],
        {"gap": k.INSET_XS, "align": "start"},
        note="polite once",
    )
    rc = result_card(
        [
            pas,
            checklist(rows("DEMO", "9000001")),
            buttons([k.button(k.copy("e27.scr126.saved.done"), "primary")]),
        ]
    )
    return adm(FR[3], content=[rc], **h1_126(("done", "done")))


def _variant(name: str, kids: list[Any], w: int = 466) -> dict[str, Any]:
    return card(f"variant {name}", kids, w=w)


def f22() -> dict[str, Any]:
    """Frame 22: a LIVE registration in four nested variants (a)-(d)."""
    iw = 434
    _lab, uid, _kind, _m, _s, parent = k.copies("e27.scr126.register.fields")
    a = _variant(
        "(a) key format",
        [
            h2_env("sub_002", "1234569", "LIVE", w=iw),
            *key_fields(
                bullets=True,
                w=iw,
                errors=(
                    k.copy("e27.scr126.invalid.key_format"),
                    k.copy("e27.scr126.invalid.secret_format"),
                ),
            ),
        ],
    )
    b = _variant(
        "(b) UID digits",
        [env_line("LIVE"), field_(uid, w=iw, error=k.copy("e27.scr126.invalid.uid"))],
    )
    c = _variant(
        "(c) duplicate UID",
        [
            env_line("LIVE"),
            field_(uid, w=iw, value=k.fixture("1234568"), typo=k.NUM_BASE),
            alert([k.copy("e27.scr126.invalid.duplicate_uid", label="sub_001")], w=iw),
        ],
    )
    d = _variant(
        "(d) sixth sub and parent",
        [
            env_line("LIVE"),
            alert([k.copy("e27.scr126.invalid.sixth_sub", cap=5, used=5)], w=iw),
            field_(
                parent,
                w=iw,
                value=k.fixture("demo-1"),
                error=k.copy(
                    "e27.scr126.invalid.parent_env", parent="demo-1", parent_env="DEMO", ENV="LIVE"
                ),
            ),
        ],
    )
    grid = k.hbox(
        "four variants",
        [a, b, c, d],
        {"wrap": "wrap", "gap": k.INSET_MD, "align": "start"},
        w=k.INNER_W,
    )
    return adm(FR[4], content=[grid], **h1_126())


def f23() -> dict[str, Any]:
    """Frame 23: refused, withdrawal or transfer right (CP-5) — both fields cleared at once."""
    rc = result_card(
        [
            alert([k.copy("e27.scr126.refused.withdrawal")]),
            checklist(rows("DEMO", "9000001", fail=1)),
        ]
    )
    return adm(FR[5], content=[rc, key_step()], **h1_126())


def f24() -> dict[str, Any]:
    """Frame 24: Bybit refused the egress IP — every check not checked; the fields stay."""
    full = k.copy("e27.scr126.refused.ip_bybit", egress_ip=EGRESS)
    rc = result_card(
        [
            alert([k.copy("e27.scr126.refused.lead"), cp_text(full, w=CARD_IW - 48)]),
            checklist(rows("DEMO", "9000001", none=True)),
        ]
    )
    return adm(FR[6], content=[rc, key_step(bullets=True)], **h1_126())


def f25() -> dict[str, Any]:
    """Frame 25: CandleViewer's rule — the allowlist row failed with the whitelist it read."""
    full = k.copy("e27.scr126.refused.ip_rule", egress_ip=EGRESS)
    read = k.copy("e27.scr126.refused.ip_read", ips="203.0.113.10 and 198.51.100.7")
    rc = result_card(
        [
            alert([k.copy("e27.scr126.refused.lead"), cp_text(full, w=CARD_IW - 48)]),
            checklist(rows("DEMO", "9000001", fail=6, fail_words=read)),
        ]
    )
    return adm(FR[7], content=[rc, key_step(bullets=True)], **h1_126())


FAILS26 = (
    (0, "environment", "clears both fields"),
    (2, "other rights", "keeps them"),
    (3, "trade access", "keeps them"),
    (4, "unified account", "keeps them"),
    (5, "UID", "clears both fields"),
    (7, "expiry", "clears both fields"),
    (8, "probe", "keeps them"),
)


def f26() -> dict[str, Any]:
    """Frame 26: the other checks, seven nested variants: "Nothing was stored." over the list up to its failed row."""
    iw = 466
    vs = [
        _variant(
            f"({i}) {what} · {keep}",
            [
                alert([k.copy("e27.scr126.refused.lead")], w=iw - 32),
                checklist(rows("DEMO", "9000001", fail=fi, upto=fi + 1), w=iw - 32),
            ],
            w=iw,
        )
        for i, (fi, what, keep) in enumerate(FAILS26, 1)
    ]
    grid = k.hbox(
        "seven variants", vs, {"wrap": "wrap", "gap": k.INSET_MD, "align": "start"}, w=k.INNER_W
    )
    return adm(FR[8], content=[grid], **h1_126())


def f27() -> dict[str, Any]:
    """Frame 27: no verdict, two nested variants (503 and 502); no check list; the fields stay for the retry."""
    rc = result_card(
        [
            alert(
                [k.copy("e27.scr126.no_verdict.timeout", n=5)],
                tone="warning",
                name="variant 503 · CMP-027 Alert · warning",
            ),
            alert(
                [k.copy("e27.scr126.no_verdict.error", ret_code=10016)],
                tone="warning",
                name="variant 502 · CMP-027 Alert · warning",
            ),
        ]
    )
    return adm(FR[9], content=[rc, key_step(bullets=True)], **h1_126())


def f28() -> dict[str, Any]:
    """Frame 28: activation failed after a pass — the list all passed, then the danger band; the fields stay."""
    rc = result_card(
        [checklist(rows("DEMO", "9000001")), alert([k.copy("e27.scr126.activation_failed")])]
    )
    return adm(FR[10], content=[rc, key_step(bullets=True)], **h1_126())


def f29() -> dict[str, Any]:
    """Frame 29: frame 19 under the KEK condition: CMP-092's row, the one CMP-028 notice, Verify and save T2."""
    return adm(
        FR[11],
        content=[key_step(v_state="t2")],
        banners=[k.banner("e27.shell.banner.kek")],
        notices=[k.kek_notice(w=CARD_W)],
        **h1_126(),
    )


def stepup_footprint() -> dict[str, Any]:
    """SCR-006's footprint (E09-D06, consumed, never redrawn): its label, its title and the server's action_summary;
    the password and code fields are E09-D06's (a labelled placeholder)."""
    iw = 440 - 48
    return k.vbox(
        "SCR-006 footprint",
        [
            k.text(
                "footprint label", k.say("SCR-006 code-only, E09-D06"), k.CAPTION, k.TEXT_2, w=iw
            ),
            k.text("title", k.copy("e27.scr126.stepup.title"), k.HEADING_MD, k.TEXT_1, w=iw),
            k.text(
                "description",
                k.say("Import API key for account 'demo-1' (demo, UID 9000001)"),
                k.BODY,
                k.TEXT_1,
                w=iw,
            ),
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
        w=440,
        note='role="alertdialog"; focus on the password field (D06:47)',
    )


def f30() -> dict[str, Any]:
    """Frame 30: SCR-006 over frame 19 under a flat 60 % scrim (opacity.scrim, no blur)."""
    return adm(
        FR[12],
        content=[key_step(bullets=True)],
        overlays=[k.overlay(stepup_footprint())],
        **h1_126(),
    )


def edit_card(*, label_err: str | None = None, label_val: str = "sub_002") -> dict[str, Any]:
    """Frame 31's card: Label, the facts (CMP-036), the key as an outcome row with Rotate, Disable / Delete, Save."""
    lab, uid, *_r = k.copies("e27.scr126.register.fields")
    items = k.copies("e27.scr125.menu.items")
    fact = k.vbox(
        "CMP-036 facts",
        [
            k.hbox(
                "row · UID",
                [
                    k.text("dt", uid, k.LABEL, k.TEXT_2),
                    k.text("dd", k.fixture("1234569"), k.NUM_BASE, k.TEXT_1),
                ],
                {"gap": k.INSET_SM},
            ),
            k.text("row · kind", k.say("sub-account of Main"), k.BODY, k.TEXT_1),
            env_line("LIVE"),
        ],
        {"gap": k.STACK_SM},
    )
    keyrow = k.vbox(
        "key outcome row",
        [
            k.text(
                "key row",
                k.copy(
                    "e27.scr126.edit.key_row",
                    key_id_masked="...e5f6",
                    status="active",
                    hh_mm="14:02",
                    date="2026-11-04",
                ),
                k.BODY,
                k.TEXT_1,
                w=CARD_IW,
            ),
            k.button(items[2], "secondary"),
            k.text(
                "write-only", k.copy("e27.scr126.edit.write_only"), k.CAPTION, k.TEXT_2, w=CARD_IW
            ),
        ],
        {"gap": k.STACK_SM},
        w=CARD_IW,
        note="CMP-034 ...e5f6; Rotate key… opens SCR-127",
    )
    acts = k.hbox(
        "account actions",
        [k.button(items[6], "secondary"), k.button(items[7], "secondary")],
        {"gap": k.INSET_MD},
        note="open SCR-129",
    )
    return card(
        "CMP-050 form card · edit",
        [
            field_(lab, value=k.fixture(label_val), error=label_err),
            fact,
            keyrow,
            acts,
            buttons(
                [
                    k.button(k.copy("e27.shared.cancel"), "secondary"),
                    k.button(k.copy("e27.scr126.edit.buttons"), "primary"),
                ]
            ),
        ],
    )


def f31() -> dict[str, Any]:
    """Frame 31: edit mode for sub_002 (no key field; the key row with Rotate)."""
    return adm(
        FR[13],
        content=[edit_card()],
        route_band=False,
        h1=k.copy("e27.scr126.edit.h1", label="sub_002", ENV="LIVE"),
    )


def f32() -> dict[str, Any]:
    """Frame 32: three nested variants on frame 31's card: the 412, the label taken, nothing changed."""
    v1 = _variant(
        "(1) 412 conflict",
        [
            alert([k.copy("e27.scr126.edit.conflict", label="sub_002")], w=CARD_IW),
            k.button(k.copy("e27.scr126.edit.reload"), "secondary"),
        ],
        w=CARD_W,
    )
    lab = k.copies("e27.scr126.register.fields")[0]
    v2 = _variant(
        "(2) label taken",
        [
            field_(
                lab,
                value=k.fixture("sub_001"),
                error=k.copy("e27.scr126.edit.label_taken", label="sub_001", ENV="LIVE"),
            )
        ],
        w=CARD_W,
    )
    v3 = _variant(
        "(3) nothing changed",
        [alert([k.copy("e27.scr126.edit.unchanged")], tone="warning", w=CARD_IW)],
        w=CARD_W,
    )
    return adm(
        FR[14],
        content=[v1, v2, v3],
        route_band=False,
        h1=k.copy("e27.scr126.edit.h1", label="sub_002", ENV="LIVE"),
    )


# --- SCR-016 step 3 as 800 px insets (§4.4 L1201-1222; BQ-1).
INSET_IW = k.INSET_CARD_W - 48  # 752


def step_card(
    *,
    bullets: bool = False,
    readonly: bool = False,
    v_state: str = "default",
    extra_top: list[Any] | None = None,
    extra: list[Any] | None = None,
) -> dict[str, Any]:
    """Block C: §4.1's form card at 640 px in E27-D02 §5.7's order: Label, Bybit UID and "Main account" as text; the
    instruction list; API key and API secret; the allowlist row; [Verify and save] with the ask line.
    """
    lab, uid, _kind, main_, _s, _p = k.copies("e27.scr126.register.fields")
    kids = [
        *(extra_top or []),
        field_(lab, value=k.fixture("demo-1")),
        field_(uid, value=k.fixture("9000001"), typo=k.NUM_BASE),
        k.text("kind", main_, k.BODY, k.TEXT_1),
        instructions(),
        *key_fields(bullets=bullets, readonly=readonly),
        allowlist_row(),
        k.text("ask line", k.copy("e27.shared.ask"), k.CAPTION, k.TEXT_2, w=CARD_IW),
        buttons([verify(v_state)]),
        *(extra or []),
    ]
    return card("CMP-050 step card", kids)


def wizard(card_: Any, *, early: bool = False) -> list[Any]:
    """Blocks A, B, C and E: the six-step stepper, the h1 and lead, the step card, the wizard footer (Back ghost,
    Skip for now secondary, Continue primary); early= Continue's answer under the footer (D02:869-870).
    """
    back, skip, cont = k.copies("e27.scr016.buttons")
    foot = buttons(
        [k.button(back, "ghost"), k.button(skip, "secondary"), k.button(cont, "primary")],
        w=INSET_IW,
        name="wizard footer",
    )
    return [
        stepper016(3, w=INSET_IW),
        k.text("h1", k.copy("e27.scr016.h1"), k.HEADING_MD, k.TEXT_1, w=INSET_IW),
        k.text("lead", k.copy("e27.scr016.lead"), k.BODY, k.TEXT_2, w=INSET_IW),
        card_,
        foot,
        (
            k.text(
                "Continue's answer",
                k.copy("e27.scr016.continue_early"),
                k.CAPTION,
                k.TEXT_1,
                w=INSET_IW,
            )
            if early
            else None
        ),
    ]


def f72() -> dict[str, Any]:
    """Frame 72: step 3 loading — wells readonly, Verify and save loading, the status line; Continue answers."""
    status = [
        k.text("status", k.copy("e27.scr126.validating"), k.BODY, k.TEXT_2, w=CARD_IW),
        k.text(
            "status · after about 3 s",
            k.copy("e27.scr126.validating.long"),
            k.BODY,
            k.TEXT_2,
            w=CARD_IW,
        ),
    ]
    return {
        "kids": wizard(
            step_card(bullets=True, readonly=True, v_state="loading", extra=status), early=True
        )
    }


def f73() -> dict[str, Any]:
    """Frame 73: step 3 valid — block D's result row with demo-1's list under it; both wells cleared."""
    res = k.vbox(
        "result row",
        [
            k.hbox(
                "D · result",
                [
                    k.glyph("check", k.STATUS["success.strong"]),
                    k.text(
                        "words", k.copy("e27.scr016.result", hh_mm="14:02"), k.BODY_STRONG, k.TEXT_1
                    ),
                ],
                {"gap": k.INSET_XS},
                h=32,
            ),
            checklist(rows("DEMO", "9000001")),
        ],
        {"gap": k.STACK_SM},
        note="a row the server fills after a pass, never a box (F-19)",
    )
    return {"kids": wizard(step_card(extra=[res]))}


def f74() -> dict[str, Any]:
    """Frame 74: step 3 invalid — CP-5 on the danger band, the withdrawal row failed; wells cleared; Continue
    answers as in frame 72; Skip for now stays."""
    top = [
        alert([k.copy("e27.scr126.refused.withdrawal")]),
        checklist(rows("DEMO", "9000001", fail=1)),
    ]
    return {"kids": wizard(step_card(extra_top=top), early=True)}


def f75() -> dict[str, Any]:
    """Frame 75: skipped — the card gives way to the skipped line."""
    sk = card(
        "CMP-050 step card · skipped",
        [k.text("skipped", k.copy("e27.scr016.skipped"), k.BODY, k.TEXT_1, w=CARD_IW)],
    )
    return {"kids": wizard(sk)}


# --- Cells, board, sheet.
WD = (
    "The withdrawal row's failed words are CMP-175's critical word (e27.cmp175.withdrawal_detected): §12.1 has no "
    "e27.checks.withdrawal.failed row (CP-5's summary carries the refusal)."
)
SPEC = {  # frame index -> (build, strips, notes, proposed)
    0: (
        f18,
        [],
        [
            (
                'Once registered the account lists as "No key — inactive" and step 2 opens (11:320): behaviour, '
                "not drawn. Parent shows only for a sub (demo-1 is a Main account)."
            )
        ],
        [],
    ),
    1: (
        f19,
        [G1],
        ["§4.1's anatomy (A-J) before any answer; the card at 640 px, left-aligned (PROPOSED)."],
        ["HD11", "HD14", "D03-G1"],
    ),
    2: (
        f20,
        [G1],
        [
            "Verify and save loading: the spinner replaces the label, width locked, never gated (D18)."
        ],
        ["HD11", "HD14"],
    ),
    3: (
        f21,
        [],
        ["The LIVE line e27.scr126.saved.live is a deck string no frame draws (D02:486-490)."],
        ["D03-C15"],
    ),
    4: (
        f22,
        [],
        [
            (
                "Variants (a)-(d) are named in the layers: (a) sub_002's key step with both format errors, (b) the "
                "UID digits error, (c) the duplicate UID, (d) the sixth sub (no acknowledgement control) and a "
                "parent in the other environment."
            )
        ],
        [],
    ),
    5: (
        f23,
        [],
        [
            WD,
            (
                "CMP-027's details disclosure (the server's detail) is not drawn: its label is not written. "
                "Both fields cleared (CP-5; KV-I10)."
            ),
        ],
        [],
    ),
    6: (
        f24,
        [],
        [
            "The address and its Copy are served by this refusal's egress_ip (22:15263-15276): no strip."
        ],
        [],
    ),
    7: (
        f25,
        [],
        ["Rows before the allowlist pass; expiry and the probe stay not checked; the fields stay."],
        [],
    ),
    8: (
        f26,
        [],
        [
            (
                'Each variant draws its list up to the failed row; the later rows read "not checked" as in frame '
                "25 (not drawn). Environment, UID and expiry clear both fields; the other four keep them (C-2.11)."
            )
        ],
        [],
    ),
    9: (
        f27,
        [G1],
        [
            (
                "No check list: nothing reached a verdict (PROPOSED). The 5 s is Retry-After; 502 shows ret_code "
                "only (D12)."
            )
        ],
        ["HD14"],
    ),
    10: (
        f28,
        [],
        ['Never "nothing was stored" (MEMO:447); the fields stay for "import it again".'],
        [],
    ),
    11: (
        f29,
        [G1],
        [
            (
                "Verify and save is T2: lock leading, label color.text.tertiary, the stripped shape; its "
                "aria-describedby is the notice's id (one notice, many pointers)."
            )
        ],
        ["HD6", "HD14"],
    ),
    12: (
        f30,
        [G1],
        [
            (
                "SCR-006 is E09-D06's (consumed, never redrawn): the cancel / expiry / third-failure leg (\"Not "
                'saved — nothing was sent."), the unconfirmed re-send and the in-grace ask line are text-binding.'
            )
        ],
        ["HD14"],
    ),
    13: (
        f31,
        [],
        [
            (
                "The h1 with its environment and Save are new (PROPOSED, D02:262-270); a keyless account shows "
                '"Add a key…" in the key row\'s place (not drawn).'
            )
        ],
        [],
    ),
    14: (
        f32,
        [],
        [
            (
                "Variants (1) the 412 with Reload, the draft kept; (2) the label already used, under the Label field; "
                "(3) nothing changed (warning)."
            )
        ],
        [],
    ),
    15: (
        f72,
        [G1],
        ["Continue stays enabled; pressed, it answers under the footer (D02:869-870)."],
        ["HD14"],
    ),
    16: (
        f73,
        [],
        ["Continue moves on to step 4; SCR-019's account tasks read done (§8)."],
        ["D03-C15"],
    ),
    17: (f74, [], [WD, "Both wells cleared at once (D02:511-514); Skip for now stays."], []),
    18: (
        f75,
        [],
        ["A skip skips the step, never the check (IM-17); SCR-019's tasks stay pending (§8)."],
        [],
    ),
}


def cells() -> list[Any]:
    out = []
    for i, name in enumerate(FR):
        build, strips, notes, prop = SPEC[i]
        out.append(k.frame(name, build, strips=strips, notes=notes, proposed=prop))
    return out


def main() -> int:
    k.reset_notes()
    cs = cells()
    k.gap(
        "frames 23 and 74: no e27.checks.withdrawal.failed deck row; the failed row reads CMP-175's "
        "e27.cmp175.withdrawal_detected word"
    )
    bd = k.board(
        NN,
        cs,
        source="E27-D03 §4 L1125-1227 (§4.1 L1133-1161; §4.3 L1178-1200; §4.4 L1201-1227); "
        "§0 L223",
        cols=4,
        notes=LOCAL_NOTES,
        not_drawn=[
            "SCR-006's own fields and its dropped / re-send / grace legs (E09-D06's; frame 30's text binds)",
            "SCR-126's LIVE save line (e27.scr126.saved.live: no frame draws a LIVE save)",
            "CMP-027's details disclosure on frame 23 (its label is not written)",
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
            "write-only wells show dots, never characters; no reveal control (BQ-8)",
            "T2 only on frame 29 (E27-D02 §7 'shows T2'); never color.text.disabled / opacity.disabled",
        ],
        live=[
            (
                "frames 18, 19, 21, 30 and 31 (800 high): the form card's buttons sit above the StatusBar (about 20 px spare "
                "by the estimate); frames taller than 800 draw §3.1's continuation under the viewport line"
            ),
            "the masked dots and the loading spinner render (no characters in a write-only well)",
        ],
    )
    print(summary)
    print(rep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

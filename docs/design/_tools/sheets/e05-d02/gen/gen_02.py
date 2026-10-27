"""gen_02: E05-D02 / 02 selection-and-primitives (CMP-005 Checkbox, CMP-006 RadioGroup, CMP-010 Slider, CMP-014 Spinner,
CMP-019 Icon, CMP-031 ColorSwatch, CMP-039 FocusRing).

Slice 1 (spec/E05-D02@966f9edcd.md §8 L909-1372), conventions 2 matrix rule at compact density, T2 per E09-D09 §2.2.
Run: python3 -I -B gen/gen_02.py   (writes 02-selection-and-primitives.json + .md, validates, packs into ../E05-D02-v4/)
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import s1parts as p

import e05d02kit as k

NN = 2
STATES5 = ("default", "hover", "focus-visible", "disabled", "disabled-with-reason")
T2NOTE = {"disabled-with-reason": "T2 2a"}


def gated(n: k.Node, cid: str) -> k.Node:
    """A gated specimen with its 2a reason under it (the slice's rbac string)."""
    return p.t2(k.t2_inline(n, k.say(p.READ_ONLY, "CMP-003"), w=220))


# --- CMP-005 Checkbox.
def checkbox(state: str, checked: str) -> k.Node:
    label = k.say("Label", "CMP-005")
    n = p.labelled(p.box16(checked, state), label, state, name=f"CMP-005 checkbox · {checked}")
    return gated(n, "CMP-005") if state == "disabled-with-reason" else n


def cmp005() -> k.Node:
    k.gap(
        "CMP-005 / CMP-006: the spec gives no sample label; the boards draw the anatomy part names ('Label', "
        "'option-1' … 'option-3') and 'Risk-based' (CMP-006 option-4 as built)"
    )
    rows = [
        k.state_row(
            f"Checked={c}", [k.cell(s, checkbox(s, c), note=T2NOTE.get(s)) for s in STATES5]
        )
        for c in ("false", "true", "indeterminate")
    ]
    return k.block(
        "CMP-005",
        rows,
        states=list(STATES5),
        proposed=["C6", "A3", "D13", "D17"],
        note=(
            "Box 16 px (size.icon), radius.control; unchecked 1 px color.text.tertiary outline, checked / "
            "indeterminate color.action.primary.default with an on-action ✓ / − (text glyphs); hover keeps "
            "the fill, outline color.text.secondary."
        ),
        not_drawn=["comfortable density (row 32 px; the box stays 16)", "a hidden-label consumer"],
    )


# --- CMP-006 RadioGroup.
OPTIONS = ("option-1", "option-2", "option-3", "Risk-based")


def radio_group(state: str, orient: str) -> k.Node:
    """Four options, option-1 checked; hover = option-2's outline; focus = the ring on the checked option; T2 = the
    whole group gated (every option's lock leads its label)."""
    rows = []
    for i, nm in enumerate(OPTIONS):
        st = (
            state
            if state in ("disabled-with-reason",)
            else (
                "hover"
                if state == "hover" and i == 1
                else "focus-visible" if state == "focus-visible" and i == 0 else "default"
            )
        )
        rows.append(
            p.labelled(
                p.box16("true" if i == 0 else "false", st, radio=True),
                k.say(nm, "CMP-006"),
                st,
                name=f"option-{i + 1}",
                ring_radius=k.R_BADGE,
            )
        )
    o = {"gap": k.STACK_SM} if orient == "vertical" else {"gap": k.INSET_LG}
    n = (k.vbox if orient == "vertical" else k.hbox)(f"CMP-006 radiogroup · {orient}", rows, o)
    if state == "disabled":
        n = p.dim(n)
    return gated(n, "CMP-006") if state == "disabled-with-reason" else n


def cmp006() -> k.Node:
    rows = [
        k.state_row(
            "vertical", [k.cell(s, radio_group(s, "vertical"), note=T2NOTE.get(s)) for s in STATES5]
        ),
        k.state_row("horizontal", [k.cell("default", radio_group("default", "horizontal"))]),
    ]
    return k.block(
        "CMP-006",
        rows,
        states=list(STATES5),
        proposed=["C5", "C7", "D7", "D13"],
        note=(
            "Ring 16 px radius.badge; checked = color.action.primary.default fill with an on-action dot. "
            "Options space.stack.sm apart (vertical) or space.inset.lg (horizontal), C7."
        ),
        not_drawn=[
            "the option-level lock sample (D7, a documentation sample)",
            "horizontal x every non-default State (derivable)",
            "a group with no selection",
            "comfortable density",
        ],
    )


# --- CMP-010 Slider.
def slider_cell(state: str, marks: bool = False) -> k.Node:
    n = p.slider(state, marks=marks)
    if state == "disabled":
        n = p.dim(n)
    if state == "disabled-with-reason":
        n = gated(
            k.hbox("slider · T2", [k.lock(), n], {"gap": k.FIELD_GAP}, h=k.CONTROL_PX), "CMP-010"
        )
    return k.cell(state, n, note=T2NOTE.get(state))


def cmp010() -> k.Node:
    rows = [
        k.state_row("Marks=false", [slider_cell(s) for s in STATES5]),
        k.state_row("Marks=true", [slider_cell("default", marks=True)]),
    ]
    return k.block(
        "CMP-010",
        rows,
        states=list(STATES5),
        proposed=["B4", "C5", "C8", "D13", "D17"],
        note=(
            "Sample value 40 of 0-100 on a 216 px rail: 8 px track (B4), filled color.action.primary."
            "default, rest color.text.tertiary (hover color.text.secondary), 16 px thumb; T2 strips the "
            "track (raised + 1 px border) and the lock leads the rail."
        ),
        not_drawn=[
            "Marks=true x every non-default State",
            "a vertical slider (not catalogued)",
            "comfortable density",
        ],
    )


# --- CMP-014 Spinner.
def cmp014() -> k.Node:
    lp = k.say("Loading positions", "CMP-014")
    slow = k.say("Still loading positions…", "CMP-014")
    cancel = k.say("Cancel", "CMP-014")
    submit = k.say("Checking with the exchange…", "CMP-014")
    standalone = k.hbox(
        "standalone", [k.spinner(24), k.text("label", lp, k.BODY, k.TEXT_2)], {"gap": k.INSET_SM}
    )
    load = k.hbox(
        "slow path · load",
        [k.spinner(16), k.text("status", slow, k.BODY, k.TEXT_2), k.button(cancel, "secondary")],
        {"gap": k.INSET_SM},
    )
    order = k.hbox(
        "slow path · order submit",
        [k.spinner(16), k.text("status", submit, k.BODY, k.TEXT_2)],
        {"gap": k.INSET_SM},
    )
    rows = [
        k.state_row(
            "Size",
            [
                k.cell("sm (size.icon 16)", k.spinner(16)),
                k.cell("md (size.control.height 24)", k.spinner(24)),
            ],
        ),
        k.state_row(
            "in use",
            [
                k.cell("standalone · label", standalone, note="role=status"),
                k.cell("slow path · cancellable load", load, note="after 5 s (D15)"),
                k.cell("slow path · order submit", order, note="no Cancel (D15, C-2.10)"),
            ],
        ),
    ]
    return k.block(
        "CMP-014",
        rows,
        states=["default"],
        proposed=["D15", "C9", "A8"],
        note=(
            "A static frame of the spin: the track ring in color.border.default with a short arc in "
            "color.action.primary.default (FALLBACKS SPINNER); on a filled host the arc takes the host's "
            "label ink (CMP-001)."
        ),
        not_drawn=[
            "the motion (rotation; reduced-motion colour fade, D15)",
            "the surfaces row (app, canvas, raised, overlay, hover)",
            "comfortable md (32 px)",
        ],
    )


# --- CMP-019 Icon.
def cmp019() -> k.Node:
    sizes = [
        k.cell(f"{s} · {px}", k.icon(f"CMP-019 locked · {s}", "locked", k.TEXT_1, size=t))
        for s, t, px in (
            ("sm", k.ICON_SM, "12 px"),
            ("md", k.ICON, "16 px"),
            ("lg", k.ICON_LG, "20 px"),
        )
    ]
    glyphs = [k.cell(g, k.icon(f"CMP-019 {g}", g, k.TEXT_1)) for g in sorted(k.ICONS)]
    buy = k.say("Buy / Long", "CMP-001")
    pair = [
        k.cell(
            "decorative (aria-hidden)",
            k.hbox(
                "beside text",
                [
                    k.icon("CMP-019 arrow-up", "arrow-up", k.TEXT_1),
                    k.text("label", buy, k.BODY, k.TEXT_1),
                ],
                {"gap": k.INSET_XS},
            ),
        ),
        k.cell(
            "meaningful (role=img, aria-label)",
            k.icon("CMP-019 locked · meaningful", "locked", k.TEXT_2),
            note="lock: 'Not available' (T2)",
        ),
    ]
    rows = [
        k.state_row("Size", sizes),
        k.state_row("local glyphs", glyphs),
        k.state_row("decorative", pair),
    ]
    return k.block(
        "CMP-019",
        rows,
        states=["Size sm / md / lg"],
        proposed=["A10", "B6", "C11"],
        note=(
            "The per-set file holds five local icons; every other glyph on these boards is a text glyph "
            "(FALLBACKS ICONS). Icons are currentColor (color.text.*)."
        ),
        not_drawn=[
            "the 47-glyph base set (CMP-019 · Icon — base set; the per-set file holds five icons)",
            "the A10 16 / 20 / 24 optical scale (proposed)",
        ],
    )


# --- CMP-031 ColorSwatch.
def swatch_cell(state: str, selected: bool) -> k.Node:
    sw = p.swatch(selected, state)
    if state == "focus-visible":
        sw = k.focus_ring(sw)
    if state == "disabled":
        sw = p.dim(sw)
    if state == "disabled-with-reason":
        echo = k.tooltip(k.say(p.READ_ONLY, "CMP-003"), w=180, name="CMP-016 reason echo")
        sw = p.t2(
            k.vbox("2b", [k.lock_badge(dict(sw, name="swatch · T2")), echo], {"gap": k.STACK_XS})
        )
        return k.cell(state, sw, note="T2 2b: true colour kept")
    return k.cell(state, sw)


def cmp031() -> k.Node:
    cyan, amber = k.say("Cyan", "CMP-031"), k.say("Amber", "CMP-031")
    picker = k.vbox(
        "picker · Line colour",
        [
            k.tooltip(cyan, name="CMP-016 name tooltip"),
            k.hbox(
                "swatches",
                [p.swatch(True, "default"), p.swatch(False, "default", "color.drawing.selected")],
                {"gap": k.INSET_XS},
                h=24,
            ),
        ],
        {"gap": k.STACK_XS},
    )
    rows = [
        k.state_row(f"Selected={s}", [swatch_cell(st, s == "true") for st in STATES5])
        for s in ("false", "true")
    ]
    rows.append(
        k.state_row(
            "picker", [k.cell("Cyan selected · name tooltip", picker, note=f"{amber} beside (D14)")]
        )
    )
    return k.block(
        "CMP-031",
        rows,
        states=list(STATES5),
        proposed=["A5", "B5", "C12", "D14", "D13"],
        note=(
            "24 px swatch, radius.control, its true colour (color.drawing.default 'Cyan', "
            "color.drawing.selected 'Amber'); ✓ color.text.inverse; hover a 1 px color.text.secondary "
            "outline (drawn inside: the renderer has no outer stroke on a board)."
        ),
        not_drawn=[
            "a user-pickable palette (A5: no tokens)",
            "ThemeChip (C12)",
            "a StaticSwatch",
            "Selected=true x disabled (derivable)",
        ],
    )


# --- CMP-039 FocusRing (spec only).
def surrogate() -> k.Node:
    """RingOnCustomSurrogate: a 240 x 120 chart surrogate on color.surface.canvas with candles (color.candle.up /
    .down) and the 12 x 36 surrogate box ringed in color.focus.ring (border.focus)."""
    kids = [k.place(k.rect("grid line", 240, 1, "color.grid.line"), 0, 60)]
    for i, (y, h, up) in enumerate(
        (
            (50, 30, True),
            (40, 36, False),
            (30, 40, True),
            (44, 28, False),
            (36, 30, True),
            (28, 36, True),
            (40, 24, False),
            (34, 32, True),
            (30, 28, False),
        )
    ):
        kids.append(
            k.place(
                k.rect(f"candle {i + 1}", 8, h, "color.candle.up" if up else "color.candle.down"),
                16 + i * 24,
                y,
            )
        )
    kids.append(
        k.place(
            k.rect(
                "surrogate ring",
                16,
                40,
                o={"stroke": k.FOCUS_RING, "strokeWidth": k.FOCUS_W, "radius": k.R_RING},
            ),
            110,
            26,
        )
    )
    k._fallback("RING")
    return k.box(
        "RingOnCustomSurrogate", kids, {"fill": k.CANVAS, "radius": k.R_CONTROL}, w=240, h=120
    )


def cmp039() -> k.Node:
    on_btn = k.focus_ring(k.button(k.say("Save", "CMP-001"), "primary"))
    rows = [
        k.state_row(
            "reference",
            [
                k.cell("RingOnButton", on_btn, note="2 px, 2 px offset, radius + 2"),
                k.cell("RingOnCustomSurrogate", surrogate(), note="chart DOM-mirror surrogate"),
            ],
        )
    ]
    return k.block(
        "CMP-039",
        rows,
        states=["RingOnButton", "RingOnCustomSurrogate"],
        proposed=["A9", "B2", "D11"],
        ruled=["#3925"],
        note=(
            "Spec only: 2 px color.focus.ring (border.focus) at a 2 px offset, radius + 2 (radius.md, "
            "FALLBACKS RING), :focus-visible only. Every focus-visible cell on boards 01-02 uses it."
        ),
        not_drawn=[
            "the D11 halo proposal (canvas gap + halo strokes)",
            "the A9 thick ring (no token)",
        ],
    )


def main() -> int:
    blocks = [cmp005(), cmp006(), cmp010(), cmp014(), cmp019(), cmp031(), cmp039()]
    bd = k.board(
        NN,
        blocks,
        source="slice 1 §3 conventions 2-4, §6 decisions, §8 CMP-005 to CMP-039 L909-1372",
        notes=[
            (
                "T2 (E09-D09 §2.2) replaces slice 1 §3's trailing lock and D13's dimmed plate in every gated "
                "cell; the reason is the slice's rbac string (CMP-003 accessible-name table)."
            ),
            "Swatches keep their true colour when gated (CMP-031 open question); 2b badge + echo.",
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
            "CMP-005 Checked false / true / indeterminate x five States",
            "CMP-006 vertical x five States, horizontal",
            "CMP-010 Marks=false x five States, Marks=true",
            "CMP-014 sm / md, standalone, cancellable load, order submit",
            "CMP-019 sizes, the five local glyphs, decorative / meaningful",
            "CMP-031 Selected x five States + picker",
            "CMP-039 the two reference frames",
        ],
    )
    print(summary)
    print(rep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

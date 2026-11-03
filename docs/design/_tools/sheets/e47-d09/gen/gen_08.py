"""E47-D09 / 08 hotkey-editor: SCR-113 redlines RL-1 … RL-5 over the as-built editor (§10): the conflict at capture,
the reserved refusal, Reset all with its count, capture mode, the safety group first."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402
from common import k  # noqa: E402

NN = 8
S10 = k.L("## 10. SCR-113 hotkey editor")
CW = c.CONTENT_W - 48  # 728: the content column inside 24 px padding
ROW_H = 32
LABEL_W, FIELD_W = 232, 168
ACTIVE = "positions.close_all"  # the row every frame works on (§9's AC4 command)
CONFLICT_KEY = "Ctrl+Shift+A"  # held by global.account_picker: Global meets every context (`05` §3.3 rule 2)
RESERVED_KEY = "Ctrl+Shift+I"  # RES: browser/Electron devtools
RX = k.FRAME_W - k.RIGHT_W + 6
RW = k.RIGHT_W - 12


def holder(key: str) -> k.Cmd:
    return next(cm for cm in k.COMMANDS if k.binding(cm.id) == key)


def key_field(chars: str, *, focused: bool = False, invalid: bool = False, capture: bool = False) -> c.Node:
    kids = [k.text("value", chars, k.CAPTION if capture else k.NUM_XS, k.TEXT_1 if not capture else k.TEXT_1)]
    w_ = FIELD_W - (12 if focused else 0)
    f = k.hbox("key field", kids, {"padX": k.INSET_SM, "fill": k.CANVAS, "radius": k.R_CONTROL,
                                   "stroke": k.DANGER_STRONG if invalid else k.BORDER_STRONG,
                                   "strokeWidth": k.THICK if invalid else k.HAIR, "strokeAlign": "inner"},
               w=w_, h=k.CONTROL_H,
               note=('aria-invalid="true"; aria-describedby -> the row message node (present at mount)' if invalid
                     else "the key field (typed / select capture as built)"))
    return k.focus_ring(f) if focused else f


def row(cm: k.Cmd, i: int, *, field: c.Node | None = None, save_note: str | None = None) -> c.Node:
    b = k.binding(cm.id)
    fld = field or key_field(b or k.w("W-7"))
    btns = [k.button("Save", "secondary", name=f"Save {cm.label}".replace("/", k.SLASH)), k.button("Reset", "ghost"),
            k.button("Unbind", "ghost")]
    if save_note:
        btns[0] = dict(btns[0], note=save_note)
    lab: c.Node = k.text("label", cm.label, k.BODY, k.TEXT_1, w=LABEL_W)
    if cm.safety:  # the safety group mixes contexts: each row names its own (two arm rows share a label)
        lab = k.vbox("label", [k.text("action", cm.label, k.BODY, k.TEXT_1, w=LABEL_W),
                               k.text("context", cm.context, k.CAPTION, k.TEXT_2)], None, w=LABEL_W)
    return k.hbox(f"CMP-064 row · {cm.id}", [lab, fld,
                                            k.hbox("actions", btns, {"gap": k.INSET_XS}, h=k.CONTROL_H)],
                  {"gap": k.INSET_MD, "padX": k.INSET_SM, "fill": k.CANVAS if i % 2 else k.RAISED},
                  w=CW, h=(40 if cm.safety else ROW_H) + (12 if field is not None and "ring" in field["name"] else 0))


def message(name: str, chars: str, *, glyph: str = "warning", tone: str = k.WARN_STRONG,
            actions: list[c.Node] | None = None) -> c.Node:
    kids = [k.icon("glyph", glyph, tone), k.text("text", chars, k.BODY, k.TEXT_1, w=CW - 200)]
    return k.hbox(f"message · {name}", [k.hbox("lead", kids, {"gap": k.INSET_XS, "align": "start"}),
                                        k.hbox("actions", actions or [], {"gap": k.INSET_XS}, h=k.CONTROL_H)],
                  {"padX": k.INSET_SM, "padY": k.INSET_XS, "justify": "space-between", "fill": k.SUNKEN}, w=CW,
                  note='role="status" (polite), never alert; the node is in the DOM at mount, its text swapped in place')


def safety_cmds() -> list[k.Cmd]:
    return [cm for cm in k.COMMANDS if cm.safety]


def group(title: str, rows: list[c.Node], note_kids: list[c.Node] | None = None) -> c.Node:
    head = [k.text("h2", title, k.HEADING_SM, k.TEXT_1)] + (note_kids or [])
    return k.vbox(f"group · {title}", [*head, *rows], {"gap": k.STACK_XS}, w=CW)


def caution() -> list[c.Node]:
    k.copy_gap("RL-5's caution note: §10 asks for it in text, not colour; no W-row gives its words, so it is "
               "drawn as a warning glyph and placeholder lines (`14` SCR-113's checklist: \"trading actions are "
               "visually grouped and carry a caution note\")")
    return [k.hbox("caution note", [k.icon("glyph", "warning", k.WARN_STRONG),
                                    k.vbox("words", [k.placeholder("caution line 1", 420), k.placeholder(
                                        "caution line 2", 300)], {"gap": k.STACK_XS}, h=28)],
                   {"gap": k.INSET_SM, "align": "start", "padY": k.INSET_XS}, w=CW, h=36,
                   note="the caution note, in text (RL-5); its words are not in the deck (copy gap)")]


def page(rows_override: dict[str, list[c.Node]], *, top_message: c.Node | None = None) -> c.Node:
    """SCR-113 as built + the redlines: h1, search + context, the Safety group first (RL-5), then Global …"""
    k.copy_gap('SCR-113 words "Hotkeys", "Safety", "Save", "Reset", "Unbind", "Swap", "Reset all", "Import", "Export", '
               '"Require a modifier for destructive commands" and the group titles: `14` SCR-113\'s wireframe and as-built '
               "line (`14`:2414-2436), not this spec's")
    head = k.hbox("toolbar", [k.text("h1", "Hotkeys", k.HEADING_LG, k.TEXT_1),
                              k.hbox("filters", [k.hbox("CMP-054 search", [k.icon("glyph", "search", k.TEXT_2),
                                                                           k.text("value", "Filter", k.BODY, k.TEXT_2)],
                                                        {"gap": k.INSET_XS, "padX": k.INSET_SM, "fill": k.CANVAS,
                                                         "radius": k.R_CONTROL, "stroke": k.BORDER,
                                                         "strokeWidth": k.HAIR, "strokeAlign": "inner"},
                                                        w=200, h=k.CONTROL_H)], {"gap": k.INSET_SM}, h=k.CONTROL_H)],
                  {"justify": "space-between"}, w=CW, h=36)
    srows: list[c.Node] = []
    for i, cm in enumerate(safety_cmds()):
        srows += rows_override.get(cm.id) or [row(cm, i)]
    glob = [cm for cm in k.COMMANDS if cm.context == "Global" and not cm.safety]
    grows = [row(cm, i) for i, cm in enumerate(glob[:4])]
    foot = k.hbox("footer", [k.button("Reset all", "secondary"), k.button("Import", "ghost"),
                             k.button("Export", "ghost"),
                             k.hbox("safety option", [k.hbox("checkbox", [k.icon("check", "check", k.TEXT_ON_ACTION,
                                                                                 k.ICON_SM)],
                                                             {"justify": "center", "fill": k.ACTION_PRIMARY,
                                                              "radius": k.R_CONTROL}, w=16, h=16),
                                                      k.text("label", "Require a modifier for destructive commands",
                                                             k.CAPTION, k.TEXT_1)], {"gap": k.INSET_XS}, h=20)],
                  {"gap": k.INSET_SM}, w=CW, h=k.CONTROL_H + 8)
    kids = [head, foot, top_message, group("Safety", srows, caution()), group("Global", grows)]
    return k.vbox("SCR-113 hotkey editor", kids, {"gap": k.STACK_MD, "pad": k.INSET_XL}, w=c.CONTENT_W,
                  h=k.BODY_H)


def window(state: str, content: c.Node, ov: list[c.Node], note: str) -> c.Node:
    return c.settings_window(k.frame_for(NN, state), "Hotkeys", content, overlays=ov, note=note)


def act() -> k.Cmd:
    return k.CMD[ACTIVE]


def frame_conflict() -> tuple[c.Node, tuple[str, list[str]]]:
    h = holder(CONFLICT_KEY)
    msg = k.w("W-13", CONFLICT_KEY, h.label, h.context)
    rows = {ACTIVE: [row(act(), 1, field=key_field(CONFLICT_KEY, focused=True, invalid=True),
                         save_note="held by form validity (aria-describedby -> the message); no lock, never T2"),
                     message("conflict", msg, actions=[k.button("Swap", "secondary")])]}
    ov = [k.callout("RL-1", ["At capture, before Save (polite status):", f"“{msg}”",
                             "Save is held until Swap, another key or Cancel: form validity, not E09-D09's grammar"],
                    RX, 120, RW)]
    fr = window("hotkeys/conflict-at-capture", page(rows), ov, f"{CONFLICT_KEY} captured for {act().label}")
    c_, ln = k.RL["RL-1"]
    blk = [f"{k.rl('RL-1')}: a conflict is shown at capture, before Save, naming both actions (W-13); the key field "
           "carries aria-invalid=\"true\"; the field and Save point at a message node present at mount; never an alert",
           f"As built: {c_[2]} ({k.crow('D09-C16')}); `11`:5089-5091",
           f"Drawn: {CONFLICT_KEY} is {h.label}'s ({h.context}; KMAP:{k.kmap_line(h.id)}), and Global meets every "
           "context (`05` §3.3 rule 2): a conflict for the Positions row",
           f"{k.wcite('W-13')}; §12 L{k.L('Form validity is never T2')}: form validity is never T2"]
    return fr, k.frame_block(k.frame_for(NN, "hotkeys/conflict-at-capture"), blk,
                             keyboard="capture a key; Tab to Swap; Enter swaps; or capture another key")


def frame_reserved() -> tuple[c.Node, tuple[str, list[str]]]:
    msg = k.w("W-12", RESERVED_KEY)
    rows = {ACTIVE: [row(act(), 1, field=key_field(k.binding(ACTIVE), focused=True)),
                     message("reserved", msg)]}
    asb = f"{RESERVED_KEY} is reserved by {k.RESERVED[RESERVED_KEY]}"
    ov = [k.callout("RL-2", [f"{RESERVED_KEY} pressed in capture (polite):", f"“{msg}”",
                             f"As built: \"{asb}\" names the internals (VAL:187; RES)"], RX, 120, RW)]
    fr = window("hotkeys/reserved", page(rows), ov, f"{RESERVED_KEY} refused; the binding stays")
    blk = [f"{k.rl('RL-2')}: a reserved key is refused with W-12, naming no browser, shell or devtools internals",
           f"Drawn: {RESERVED_KEY} (RES: \"{k.RESERVED[RESERVED_KEY]}\"); the row keeps {k.binding(ACTIVE)}",
           f"{k.wcite('W-12')}; D09-A15 (the reserved refusal, E47-S08); T Sec"]
    return fr, k.frame_block(k.frame_for(NN, "hotkeys/reserved"), blk, keyboard="capture; the refusal is spoken once")


def frame_reset_all() -> tuple[c.Node, tuple[str, list[str]]]:
    n = k.changed_count()
    msg = k.w("W-17", n)
    saved = dict(k.PROFILE)
    k.PROFILE.clear()  # after Reset all every binding is its default
    try:
        content = page({}, top_message=message("reset all", msg, glyph="check", tone="color.status.success.strong"))
    finally:
        k.PROFILE.update(saved)
    ov = [k.callout("RL-3", ["After Reset all (polite):", f"“{msg}”",
                             f"As built: \"{k.w('W-14')}\" without a count (HKE:374); D09-A17"], RX, 120, RW)]
    fr = window("hotkeys/reset-all", content, ov, f"Reset all put {n} bindings back")
    blk = [f"{k.rl('RL-3')}: Reset per row is kept; Reset all keeps its stated result and names the count it changed",
           f"Drawn: the synthetic profile changed {n} bindings ({', '.join(saved)}); after Reset all "
           f"{act().label} reads {act().default} again",
           f"{k.wcite('W-14')} (as built); {k.wcite('W-17')} (its replacement, D09-A17)"]
    return fr, k.frame_block(k.frame_for(NN, "hotkeys/reset-all"), blk, keyboard="Reset all; the result is spoken "
                                                                                 "once; focus stays on the button")


def frame_capture() -> tuple[c.Node, tuple[str, list[str]]]:
    say = k.w("W-24", act().label)
    rows = {ACTIVE: [row(act(), 1, field=key_field("Press keys…", focused=True, capture=True)),
                     message("capture", say, glyph="info", tone=k.INFO_STRONG)]}
    k.copy_gap('"Press keys…" in the capturing field: the field\'s placeholder while it listens (RL-4 gives the '
               "spoken W-24 only)")
    ov = [c.say("W-24", "W-24", act().label, x=RX, y=120, wd=RW, head="Capture mode (polite):",
                extra=["Esc leaves capture without binding (Esc stays reserved); Tab / Shift+Tab are never captured "
                       "and leave as Esc does; a chord ends capture and is announced; focus stays on the row"])]
    fr = window("hotkeys/capture", page(rows), ov, f"Record on {act().label}: capture mode")
    blk = [f"{k.rl('RL-4')}: capture mode says W-24; Esc, Tab and Shift+Tab leave it without binding",
           f"{k.wcite('W-24')}; §13 2.1.2: no keyboard trap"]
    return fr, k.frame_block(k.frame_for(NN, "hotkeys/capture"), blk, keyboard="Enter on the key field starts "
                                                                              "capture; Esc / Tab leave it")


def frame_safety() -> tuple[c.Node, tuple[str, list[str]]]:
    sc = safety_cmds()
    ov = [k.callout("RL-5", ["The safety group leads (destructive and arm commands):",
                             *[f"{cm.label} ({cm.context})" for cm in sc]], RX, 120, RW)]
    fr = window("hotkeys/safety-group", page({}), ov, "the list as it opens: the Safety group first")
    blk = [f"{k.rl('RL-5')}: the safety group (destructive and arm commands) leads, with its caution note in text, "
           "not colour",
           f"Drawn: {len(sc)} registry commands with destructive true or an arm id ({', '.join(cm.id for cm in sc)}), "
           "then Global (the as-built grouping by context follows)",
           "`14` SCR-113 sign-off: \"trading actions are visually grouped and carry a caution note\" (`14`:2435)"]
    return fr, k.frame_block(k.frame_for(NN, "hotkeys/safety-group"), blk, keyboard="Tab through the rows; each "
                                                                                    "row's Save, Reset, Unbind")


def build() -> None:
    fr = [frame_conflict(), frame_reserved(), frame_reset_all(), frame_capture(), frame_safety()]
    k.reading("every SCR-113 frame works on positions.close_all (§9's AC4 command, in the Safety group); the "
              f"conflict key {CONFLICT_KEY} is Global's account picker, the reserved key {RESERVED_KEY} a RES entry")
    k.reading("RL-1's held Save is drawn as an ordinary secondary button (form validity, never T2: no lock, no "
              "raised fill); the key field shows aria-invalid as a 2 px color.status.danger.strong edge plus the "
              "message's words")
    k.build_all(NN, [f for f, _b in fr], k.annotations(NN, [b for _f, b in fr]))


if __name__ == "__main__":
    build()

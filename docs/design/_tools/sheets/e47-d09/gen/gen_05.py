"""E47-D09 / 05 palette (dark) and, through build("light" / "hc"), 06 palette-light and 10 palette-hc: the SCR-012
deltas on E10-D03's chassis — the binding column with "unbound", an invalid-here row, a T2 row, no match (§8, §12)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common as c  # noqa: E402
from common import k  # noqa: E402

S8 = k.L("## 8. SCR-012 command palette")
S12 = k.L("## 12. RBAC and the T2 paragraph")
PAL_W = 640  # E10-D03 §6.1 (D03E10:281): 640 px, centred under the TopBar
PAD = 12
IW = PAL_W - 2 * PAD
ROW_H = 32  # D03E10:281: 32 px compact
ROW2_H = 48  # a row with its second line (the reason)
VIEWER = "lee"  # E10-D03's sample Viewer (D03E10:67), synthetic
VERB = "change positions"  # E10-D03 §6.1's rbac.permission verb for the positions commands (D03E10:281)
RX = k.FRAME_W - k.RIGHT_W + 6
RW = k.RIGHT_W - 12
PY = k.TOP_H + 16


def field(q: str) -> c.Node:
    f = k.hbox("combobox field", [k.icon("glyph", "search", k.TEXT_2), k.text("value", q, k.BODY, k.TEXT_1)],
               {"gap": k.INSET_XS, "padX": k.INSET_SM, "fill": k.CANVAS, "radius": k.R_CONTROL, "stroke": k.BORDER,
                "strokeWidth": k.HAIR, "strokeAlign": "inner"}, w=IW - 12, h=k.CONTROL_H + 8)
    return k.focus_ring(f)


def row(cmd: k.Cmd, *, active: bool = False, reason: str | None = None, where: str | None = None) -> c.Node:
    """One CMP-059 option: [lock] label (+ the reason line) · [where] · binding · [warning + "confirms"]."""
    t2 = reason is not None
    label = k.text("label", cmd.label, k.BODY, k.TEXT_3 if t2 else k.TEXT_1)
    left_kids: list[c.Node] = []
    if t2:
        left_kids.append(k.icon("lock", "locked", k.TEXT_3, note='CMP-019 lock, decorative=false, name "Not available"'))
    lines = [label] + ([k.text("reason", reason, k.CAPTION, k.TEXT_2, note="aria-describedby; present at mount")]
                       if t2 else [])
    left_kids.append(k.vbox("text", lines, {"gap": k.STACK_XS}))
    right: list[c.Node] = []
    if where:
        right.append(k.text("context", where, k.CAPTION, k.TEXT_2, note="the registry's context label (KMAP:5-15)"))
    right += c.binding_cell(cmd.id, color=k.TEXT_3 if t2 else k.TEXT_1)
    if cmd.destructive:
        right += [k.icon("destructive", "warning", k.WARN_STRONG), k.text("confirms", "confirms", k.CAPTION, k.TEXT_2)]
    h = ROW2_H if t2 else ROW_H
    o = {"padX": k.INSET_SM, "justify": "space-between", **({"fill": k.SELECTED} if active else {})}
    note = ('aria-selected (the active descendant)' if active else 'role="option"')
    if t2:
        note += '; aria-disabled="true" (never disabled); CMP-079 RbacGate'
    return k.hbox(f"option · {cmd.label}", [k.hbox("left", left_kids, {"gap": k.INSET_SM}),
                                            k.hbox("right", right, {"gap": k.INSET_SM})], o, w=IW, h=h, note=note)


def palette(q: str, rows: list[c.Node], *, empty: list[c.Node] | None = None) -> c.Node:
    hint = k.hbox("footer hint", [c.kbd("Ctrl+Enter"), k.text("hint", "runs for every account in the group",
                                                               k.CAPTION, k.TEXT_2)], {"gap": k.INSET_XS}, h=20)
    body: list[c.Node] = [field(q)]
    if rows:
        body.append(k.text("group · Action", "Action", k.CAPTION, k.TEXT_3))
        body.append(k.vbox("listbox", rows, None, w=IW, h=round(sum(k.est_height(r) for r in rows))))
    body += empty or []
    body.append(hint)
    return k.vbox("CMP-059 command palette", body,
                  {"gap": k.STACK_SM, "pad": k.INSET_MD, "fill": k.OVERLAY, "radius": k.R_DIALOG, "stroke": k.BORDER,
                   "strokeWidth": k.HAIR, "strokeAlign": "inner"}, w=PAL_W,
                  note='CMP-043 dialog; role="combobox" + aria-activedescendant; the results role="listbox"')


def window(fid: str, pal: c.Node, extra: list[c.Node], note: str) -> c.Node:
    ovl, _r = k.modal(pal, y=PY)
    return k.workspace_window(fid, {}, overlays=[ovl, *extra], note=note)


def common_lines() -> list[str]:
    return [f"§8 L{S8 + 2}: E10-D03's chassis stands (D03E10:281): CMP-043 + CMP-059, 640 px, rows 32 px, the "
            "destructive mark (warning glyph + \"confirms\"); deltas only",
            "Focus: the field keeps DOM focus (ring), the active option is aria-activedescendant on "
            "color.surface.selected (E47-D04 board 06; not redrawn)"]


def frame_unbound(theme: str) -> tuple[c.Node, tuple[str, list[str]]]:
    fid = k.frame_for(5, "palette/unbound", theme)
    q = "centre"
    hits = k.search(q)
    assert [h.id for h in hits] == ["dom.centre_mark", "dom.recentre"], hits
    pal = palette(q, [row(h, active=i == 0) for i, h in enumerate(hits)])
    ov = [k.callout("run", ["Enter on \"Centre on mark\" runs it from the palette (K-8): unbound is not unreachable",
                            "palette.ran with the PROPOSED bound flag false (§15; D09-A12)"], RX, 120, RW)]
    fr = window(fid, pal, ov, "Ctrl+K, \"centre\": an unbound command is listed and runs")
    blk = [*common_lines(),
           f"§8 L{k.L('- **The binding column.**', start=S8)}: each row shows its current binding as CMP-022 Kbds; "
           f"an unbound row reads W-7 \"{k.w('W-7')}\" in color.text.secondary",
           f"Drawn: the synthetic profile unbinds dom.centre_mark (KMAP:{k.kmap_line('dom.centre_mark')}; default "
           f"{k.CMD['dom.centre_mark'].default}); \"Re-centre and resume auto-follow\" keeps "
           f"{k.binding('dom.recentre')}",
           f"{k.krule('K-8')}; {k.crow('D09-C14')}: #5280 drops an unbound row's key (PSRC:133), A-rows to E10-S05"]
    return fr, k.frame_block(fid, blk, keyboard="Ctrl+K; type; ↑ / ↓ move the active option; Enter runs; Esc "
                                                "closes and restores", waits=["D09-G5"])


def frame_invalid(theme: str) -> tuple[c.Node, tuple[str, list[str]]]:
    fid = k.frame_for(5, "palette/invalid-here", theme)
    q = "jump"
    hits = k.search(q)
    assert hits and all(not k.valid_here(h.id) for h in hits), hits
    reason = k.w("W-8")
    pal = palette(q, [row(h, active=i == 0, reason=reason, where=h.context) for i, h in enumerate(hits)])
    ov = [c.say("W-8", "W-8", x=RX, y=120, wd=RW, head="Enter on an invalid-here row (polite, once):",
                extra=["Nothing runs, focus does not move; the context caption names where it works (Replay)"])]
    fr = window(fid, pal, ov, "Ctrl+K, \"jump\" in the trading workspace: the Replay commands are invalid here")
    blk = [*common_lines(),
           f"§8 L{k.L('- **Invalid here.**', start=S8)}: a row whose validWhen fails in the current view stays "
           "listed as T2: its reason W-8 is the second line, its context caption the registry's label",
           f"Drawn: {len(hits)} Replay rows ({', '.join(h.id for h in hits)}) in SCR-020's trading workspace (the "
           "view's contexts: Global, Workspace, Chart, DOM, Ticket, Positions; kit reading)",
           f"{k.wcite('W-8')}: the PROPOSED state key keymap.not_here (vocabulary owner E47-S08; D09-A18)",
           f"The T2 paragraph (§12 L{S12 + 2}): lock + full label in color.text.tertiary, the reason in "
           "color.text.secondary, aria-disabled, never opacity.disabled"]
    return fr, k.frame_block(fid, blk, keyboard="↑ / ↓ land on a T2 row; Enter changes nothing and speaks W-8 once",
                             waits=["D09-G5"])


def frame_t2(theme: str) -> tuple[c.Node, tuple[str, list[str]]]:
    fid = k.frame_for(5, "palette/t2", theme)
    q = "close"
    hits = k.search(q)
    assert [h.id for h in hits] == ["positions.close", "positions.close_all"], hits
    reason = f"Your role can't {VERB}."
    k.copy_gap(f'"{reason}": E09-D09 §3.1 rbac.permission "Your role can\'t {{verb}}." (D09E09:89) with E10-D03 '
               f"§6.1's verb for the positions commands (D03E10:281); §16 has no row for it")
    pal = palette(q, [row(h, active=i == 0, reason=reason) for i, h in enumerate(hits)])
    # x 620, the empty TopBar gap: at 980 the tag covered FLATTEN ALL and FREEZE (live check)
    ov = [k.tag(f"session: {VIEWER} · Viewer (synthetic)", 620, 14, name="tag · the session"),
          k.callout("T2", ["Enter, Space or a bound hotkey on a T2 row (polite, once):", f"“{reason}”",
                           "Nothing runs, no focus move; the row keeps its keys, its role and its full label (K-11)"],
                    RX, 120, RW)]
    fr = window(fid, pal, ov, "a Viewer's palette: the positions writes are listed as T2 with their reason")
    blk = [*common_lines(),
           f"§8 L{k.L('- **RBAC.**', start=S8)}: E09-D09 governs ({k.crow('D09-C9')}): a write the session cannot make "
           "is T2 with the §3.1 key of its first missing leg; admin.* is absent without admin:read (T3)",
           f"§12 L{S12 + 2}: CMP-079 RbacGate; aria-disabled=\"true\", never the disabled attribute; the CMP-019 lock "
           "(name \"Not available\") leads the full label in color.text.tertiary; the reason in color.text.secondary "
           "via aria-describedby, present at mount; never color.text.disabled or opacity.disabled",
           "Both rows are destructive (warning glyph + \"confirms\"); Close all in view shows the profile's "
           f"{k.binding('positions.close_all')} · remapped (§9's AC4 remap)",
           f"{k.krule('K-11')}"]
    return fr, k.frame_block(fid, blk, keyboard="↑ / ↓ land on T2 rows without activating them; Enter re-shows the "
                                                "reason")


def frame_no_match(theme: str) -> tuple[c.Node, tuple[str, list[str]]]:
    fid = k.frame_for(5, "palette/no-match", theme)
    q = "flatten"
    assert not k.search(q)
    w9 = k.w("W-9")
    sugg = "Try fewer letters, or use the nav rail."
    k.copy_gap(f'the no-match suggestion "{sugg}": the shipped palette copy (PCOPY:40, read at 73bfdb08a); §8 says '
               '"W-9 and a suggestion" (D03E10:281) without its words')
    k.reading(f"W-9 is drawn in PCOPY:39's shipped form with the query in curly quotes (\"{w9} “{q}”\"), the "
              "verbatim fragment §16 checks")
    empty = [k.vbox("no results", [k.text("W-9", f"{w9} “{q}”", k.BODY, k.TEXT_1),
                                   k.text("suggestion", sugg, k.CAPTION, k.TEXT_2)],
                    {"gap": k.STACK_XS, "padX": k.INSET_SM, "padY": k.INSET_MD}, w=IW,
                    note="no group headers (D03E10:281); said once")]
    pal = palette(q, [], empty=empty)
    ov = [k.callout("flatten", [f"\"{q}\" finds nothing: the registry has no flatten-all command",
                                f"{k.crow('D09-C2')}; D09-G1"], RX, 120, RW)]
    fr = window(fid, pal, ov, "Ctrl+K, \"flatten\": no command or symbol matches")
    blk = [*common_lines(),
           f"§8 L{k.L('- **No match.**', start=S8)}: W-9 and a suggestion, no group headers",
           f"{k.wcite('W-9')}; the query \"{q}\" shows {k.crow('D09-C2')}: no flatten-all command is registered"]
    return fr, k.frame_block(fid, blk, keyboard="type; Esc closes and restores", waits=["D09-G1"])


def build(theme: str = "dark") -> None:
    nn = {"dark": 5, "light": 6, "hc": 10}[theme]
    fr = [f(theme) for f in (frame_unbound, frame_invalid, frame_t2, frame_no_match)]
    k.reading("every registry command sits under E10-D03's \"Action\" group (the five groups Navigate · Panel · "
              "Symbol · Action · Setting; the registry carries no group field)")
    k.reading("valid here = the command's context is active in SCR-020's trading workspace (Global, Workspace, "
              "Chart, DOM, Ticket, Positions) and its validWhen holds; Replay rows are the invalid-here example")
    k.reading("the synthetic keymap profile: positions.close_all → Ctrl+Shift+F, ticket.reduce_only → Alt+R, "
              "replay.bookmark → Ctrl+B (QA-3's three remaps), dom.centre_mark unbound (no default is unbound)")
    if theme == "hc":
        k.reading("board 10 is token-bound to the E47-D03 high-contrast set at its merge commit (73fefc62b); the theme "
                  "is switched at export")
    k.build_all(nn, [f for f, _b in fr], k.annotations(nn, [b for _f, b in fr]))


if __name__ == "__main__":
    build()

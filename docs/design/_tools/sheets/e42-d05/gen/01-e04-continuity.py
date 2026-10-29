"""E42-D05 board 01 `e04-continuity` (dark, 1280×800): HL-2, HL-5, HL-14, IL-2 beside E04-D01's four frames (AC-6).

The E04 frames are E04-D01's own boards and are not redrawn here (kit gap): each D05 frame is tagged with its E04
counterpart and §5.2's continuity anchors ride as a block in the annotation column. Offline; writes only
01-e04-continuity.{json,md} (+ packed copy).

Review r1 fixes (gen-local; the kit is not edited): anchors() bounded to §5.2's table (11 rows); frame titles carry
the state id only, the E04 twin rides in the frame note and the annotation; a second row of four empty, labelled
slots holds E04-D01's frames for the live Penpot step; HL-14 draws the spec's lone [Retry] (no health.report_failed,
which is HL-11 / HL-12's); HL-14's drop time stays a bar (no source gives it), stated in the annotation.
"""

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # the kit folder
import e42d05kit as d

NN = 1
K143 = (
    "Tab: incidents link → Re-read → Export → tiles in DOM order (heading link, Runbook link, Retry, history "
    "disclosure; no roving grid) → Table view → build line; Alt+T toggles Table view. Focus starts on the h1 "
    "(SCR-143 Keys, L324)."
)
BLOCKS = {
    "HL-2": {
        "decisions": "D1, D2, D3, D4, D5, D10, D13 (E04 scr-143-all-green: vocabulary, anatomy, last good, "
        "independence anchors)",
        "keyboard": K143
        + " Nothing announced: no component changes state; 'as of' and ages never.",
    },
    "HL-5": {
        "decisions": "D2, D4, D9, D11, D49 (ruling Q11: health.safe only where the component cannot affect "
        "exchange stops) (E04 scr-143-degraded-outage: degraded / outage and reassurance anchors)",
        "keyboard": K143
        + " The down tile is announced assertive once (D02:690); the CMP-092 banner is a "
        "static role=status, never re-announced; focus is not moved.",
    },
    "HL-14": {
        "decisions": "D6, D7, D8, D10, D48 (ruling Q10) (E04 scr-143-unreachable-backend: the unreachable-"
        "backend anchor — session memory and UTC supersede the cache and relative time)",
        "keyboard": K143
        + " [Retry] (after the overall line) and Re-read stay reachable, each one re-read "
        "(no timer); E17's banner announces once; tiles keep numbers marked stale (CMP-239), "
        "focus stays where it was.",
        "Drawn choices and gaps": [
            (
                "[Retry] enabled (L316) is drawn as a lone button under the overall line: the row gives no sentence "
                "for it and lists no health.report_failed (that line is HL-11 / HL-12's; its 'Showing live states "
                "only' would contradict tiles kept stale)."
            ),
            (
                "'stale since {drop time}': §1's worked example gives no drop time, so every tile's CMP-239 chip "
                "draws it as one bar (the kit's values rule: a bar, never an invented time); the drop follows the "
                "last health frame (as of 14:02:11). Private WS's 210 ms and 'last good 14:01:40' are §1's values; "
                "probes §1 does not give are bars."
            ),
            (
                "E17's banner is E17-D01:154's Disconnected copy verbatim, title 'Disconnected — reconnecting (3)' "
                "and its relative 'Last data 00:12 ago'; the UTC rule (D7, D8) binds D05's own stamps, not E17's "
                "copy. 'Cannot reach server' is E17-D01:197's order-entry reason (Disconnected, REST unreachable), "
                "which Export's T2 admin.server_unreachable follows; it is not the banner title."
            ),
        ],
    },
    "IL-2": {
        "decisions": "D15, D16, D17, D18, D51 (ruling Q13) (E04 scr-144-incident-log: incidents / export "
        "anchor)",
        "keyboard": "Segmented control (radio group, arrows move and select) → filter row (each T2 control by "
        "Tab; Enter re-shows the reason) → table (APG grid, one tab stop; arrows, Home/End, "
        "PgUp/PgDn; Space/Enter expands; Enter on 'Acknowledge: {title}' acts once) → Load more; "
        "focus stays on the acknowledged cell, which then holds the outcome line (SCR-144 Keys, "
        "L375).",
    },
}

E04_TWIN = {
    "HL-2": "scr-143-all-green",
    "HL-5": "scr-143-degraded-outage",
    "HL-14": "scr-143-unreachable-backend",
    "IL-2": "scr-144-incident-log",
}
_frame_name, _at = d.frame_name, d.at


def frame_name(f: d.F) -> str:
    """Board 01: the frame title is the state id, size and old board only; the E04 twin is not in the title."""
    if f.sid in E04_TWIN:
        return f"{f.sid} · {d.SIZE_NAME[f.px]} [{f.old}]"
    return _frame_name(f)


def at(fr: d.Node, f: d.F) -> d.Node:
    out = dict(fr, name=frame_name(f))
    if f.sid in E04_TWIN:
        out["note"] = (
            f"D05 twin of E04-D01 {E04_TWIN[f.sid]} (AC-6; §5.2): the E04 frame sits in the slot below "
            "(live Penpot step)"
        )
    return out


d.frame_name, d.at = frame_name, at

# HL-14: the spec row (L316) names [Retry] enabled and the copy keys tile.stale + admin.server_unreachable only;
# health.report_failed ("… Showing live states only") is HL-11 / HL-12's and contradicts tiles kept stale, so the
# overall line carries the lone [Retry] here.
_overall_line, _preset = d.overall_line, d._scr143_preset


def overall_line_hl14(px: int, word_state: str | None, **kw: object) -> d.Node:
    kw.pop("failed", None)
    ln = _overall_line(px, word_state, **kw)  # type: ignore[arg-type]
    return dict(
        ln,
        kids=list(ln["kids"]) + [d.button("Retry", "secondary")],
        note="overall = the worst state (Y:10061); [Retry] enabled (HL-14, L316): one re-read of the health "
        "report, no timer",
    )


def scr143_preset(px: int, sid: str, insets: tuple[str, ...]) -> d.Node:
    if sid != "HL-14":
        return _preset(px, sid, insets)
    d.overall_line = overall_line_hl14
    try:
        return d.scr143(
            px,
            sid,
            comps=d.health_set(example=True),
            numbers="stale",
            e17=True,
            export_t2=True,
            failed=True,
        )
    finally:
        d.overall_line = _overall_line


d._scr143_preset = scr143_preset


def anchors() -> list[str]:
    """§5.2's anchor rows only: from the header row to the first non-table line (the kit's anchors() scans 20 lines
    and swallowed §5.3's header)."""
    out: list[str] = []
    started = False
    for i in range(d.L_ANCHORS + 1, d.L_ANCHORS + 40):
        row = d.L(i)
        if not row.startswith("|"):
            if started:
                break
            continue
        started = True
        if row.startswith(("| Anchor", "| ---")):
            continue
        c = [x.strip() for x in row.strip().strip("|").split(" | ")]
        out.append(f"{c[0]}: E04 {c[1]} → D05 {c[2]} — {c[3]} (L{i})")
    assert len(out) == 11, out
    return out


def slot(sid: str, twin: str) -> d.Node:
    """An empty, labelled 1280×800 slot for E04-D01's frame (duplicated live, never redrawn from the spec)."""
    cap = d.vbox(
        "words",
        [
            d.text("title", f"E04-D01 · {twin}", d.HEADING_SM, d.TEXT_2),
            d.text(
                "body",
                f"Slot for E04-D01's own frame {twin}, duplicated in the live Penpot step beside its D05 twin "
                f"{sid} above (AC-6). Not a D05 frame; empty in this offline sheet.",
                d.BODY,
                d.TEXT_3,
                w=640,
            ),
        ],
        {"gap": d.STACK_SM},
    )
    return d.box(
        f"slot · E04 {twin} · 1280×800 (empty)",
        [cap],
        {
            "dir": "column",
            "align": "center",
            "justify": "center",
            "fill": d.SUNKEN,
            "stroke": d.BORDER_DEFAULT,
            "strokeWidth": d.HAIRLINE,
            "strokeAlign": "inner",
        },
        w=1280,
        h=800,
        note="placeholder for the live step; not a frame of this design",
    )


rows, groups = d.board_parts(NN, BLOCKS)
rows = [list(r) for r in rows] + [
    [slot(sid, E04_TWIN[sid]) for sid in ("HL-2", "HL-5", "HL-14", "IL-2")]
]
continuity = d.ann_block(
    "Continuity anchors · E04-D01 → E42-D05 (§5.2, AC-6)", anchors(), name="anchors"
)
e04 = d.ann_block(
    "E04-D01 frames (row 2: empty slots, live step pending)",
    [
        (
            "Twins: HL-2 ↔ scr-143-all-green · HL-5 ↔ scr-143-degraded-outage · HL-14 ↔ scr-143-unreachable-backend · "
            "IL-2 ↔ scr-144-incident-log. E04's four frames are E04-D01's own boards and are not redrawn from the spec; "
            "row 2 holds a 1280×800 slot under each D05 twin, filled by duplicating E04-D01's frame in the live Penpot "
            "step. Until then this board is not complete for AC-6: the pairwise comparison needs that step (deferral to "
            "be accepted by the orchestrator)."
        ),
        "§22 item 5: the owner compares each pair against the anchors (kept / superseded and why).",
    ],
    name="e04 frames",
)
ann = d.ann_column(NN, groups, [continuity, e04])
r = d.write_board(
    NN,
    rows,
    ann,
    md_extra=[
        "## E04 twins (row 2) — live step pending",
        "",
        (
            "Row 2's four `slot · E04 …` boards are empty, labelled placeholders, not D05 frames: the live Penpot step "
            "duplicates E04-D01's scr-143-all-green, scr-143-degraded-outage, scr-143-unreachable-backend and "
            "scr-144-incident-log into them, under HL-2, HL-5, HL-14 and IL-2. AC-6's pairwise comparison is not complete "
            "until then; the deferral needs the orchestrator's acceptance."
        ),
    ],
)
print(r["valid"], r["nodes"], r["sections"])

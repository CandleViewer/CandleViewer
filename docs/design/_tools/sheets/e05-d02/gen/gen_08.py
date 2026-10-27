"""gen_08: E05-D02 / 08 feedback-states (slice 4 §7: CMP-015, 023, 026, 027, 028, 029, 038, 045, 089, 090, 091).

Run: python3 -I -B gen/gen_08.py  -> 08-feedback-states.json (validated), its compacted twin in ../E05-D02-v4/
(compactOf sha guard) and 08-feedback-states.md. Every specimen string is k.say()'d from the frozen slice 4 spec (or
slice 1 / 3 where a nested component's own words are needed); a string the spec does not give is never invented: it
is left out and recorded with k.gap().
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))
from s4common import (
    Node,
    col,
    disclosure,
    edge,
    floating,
    glyph,
    hatched_edge,
    ibtn,
    k,
    link,
    nd,
    row,
    say,
    skel_rows,
    spread,
    t,
    tone_glyph,
)

NN = 8
PANEL_W = 480  # build-notes §4 board 08: CMP-089 / 090 / 091 full-panel states at 480 px (author choice, deviation)
NARROW = 360  # CMP-026 / 027 cells: within the 480 px column maximum (§5.1 "at most")
CALLOUT_W = 420


def S(chars: str, cid: str, doc: str | None = None) -> str:
    return say(chars, cid, doc)


# --- CMP-015 Skeleton -------------------------------------------------------------------------------------------
LINE_H = 18  # type.ui.body's line box (13 px x 1.4)


def _lines(widths: tuple[int, ...], fill: str, name: str, band: bool = False) -> Node:
    kids: list[Node] = [
        k.rect(f"line {i + 1}", w, LINE_H, fill, o={"radius": k.R_CONTROL})
        for i, w in enumerate(widths)
    ]
    h = len(widths) * LINE_H + (len(widths) - 1) * 4
    if band:
        kids.append(k.place(k.rect("shimmer band", 48, h, k.RAISED), max(widths) // 2 - 24, 0))
    return k.vbox(name, kids, {"gap": k.STACK_XS}, w=max(widths), h=h)


def cmp015() -> Node:
    cid = "CMP-015"
    two_tone = k.hbox(
        "CMP-015 row static",
        [
            k.rect("cell 1", 96, 16, k.HOVER, o={"radius": k.R_CONTROL}),
            k.rect("cell 2", 60, 16, k.RAISED, o={"radius": k.R_CONTROL}),
            k.rect("cell 3", 40, 16, k.HOVER, o={"radius": k.R_CONTROL}),
        ],
        {"gap": k.INSET_SM, "padX": k.INSET_SM},
        w=240,
        h=24,
    )
    card = k.vbox(
        "CMP-015 card",
        [_lines((120,), k.HOVER, "heading line"), _lines((208, 160), k.HOVER, "lines")],
        {
            "stroke": k.BORDER_SUBTLE,
            "strokeWidth": k.HAIRLINE,
            "radius": k.R_CARD,
            "pad": k.INSET_MD,
            "gap": k.STACK_SM,
        },
        w=240,
        h=18 + 8 + 40 + 24,
    )
    chart = k.hbox(
        "CMP-015 chart slot",
        [k.rect("block", 216, 96, k.HOVER, o={"radius": k.R_CARD})],
        {
            "stroke": k.BORDER_SUBTLE,
            "strokeWidth": k.HAIRLINE,
            "radius": k.R_CARD,
            "pad": k.INSET_MD,
        },
        w=240,
        h=120,
    )
    over = floating(
        "CMP-017 host (overlay)", [skel_rows(2, 216, on_overlay=True)], w=240, h=2 * 24 + 4 + 16
    )
    rows = [
        k.state_row(
            "Shape",
            [
                k.cell(
                    "default",
                    _lines((240, 240, 144), k.HOVER, "CMP-015 text", band=True),
                    note="text, count 3, the sweep's middle frame",
                ),
                k.cell("row", skel_rows(1, 240), note="a size.row.height row, three cell blocks"),
                k.cell("card", card, note="radius.card, a heading line and two text lines"),
                k.cell("chart", chart, note="one plain block in a chart-sized slot (§6 H9)"),
            ],
        ),
        k.state_row(
            "Motion · Surface",
            [
                k.cell(
                    "Motion=static",
                    two_tone,
                    note="the static two-tone: reduce, and after the 5 s stop",
                ),
                k.cell(
                    "Surface=overlay",
                    over,
                    note="color.surface.selected blocks on color.surface.overlay (§6 H3)",
                ),
            ],
        ),
    ]
    return k.block(
        cid,
        rows,
        states=["default", "row", "card", "chart", "Motion=static", "Surface=overlay"],
        not_drawn=nd(cid),
        proposed=["H3", "H9"],
    )


# --- CMP-023 ProgressBar ----------------------------------------------------------------------------------------
FILL = {
    "default": k.ACTION["primary"],
    "success": k.STATUS["success.default"],
    "warning": k.STATUS["warning.strong"],
    "danger": k.STATUS["danger.default"],
}  # §6 H4
BAR_W = 240


def pbar(
    label: str | None,
    value: str | None,
    frac: float,
    tone: str = "default",
    *,
    w: int = BAR_W,
    name: str = "CMP-023 bar",
) -> Node:
    """CMP-023: label row (type.ui.label left, type.num.sm value right, a warning / danger glyph before the value),
    then the 8 px color.surface.hover track (radius.badge) and its fill."""
    cid = "CMP-023"
    kids: list[Node] = []
    if value:
        vt = [
            tone_glyph(tone, k.NUM_SM) if tone in ("warning", "danger") else None,
            t("value", S(value, cid), k.NUM_SM, k.TEXT_2),
        ]
        vr = row("value", vt, gap=k.INSET_XS)
        lt = t("label", S(label, cid), k.LABEL, k.TEXT_2) if label else None
        kids.append(
            spread("label row", lt, vr, w)
            if lt
            else k.hbox("label row", [vr], {"justify": "end"}, w=w)
        )
    fw = round(w * frac)
    tk = [k.rect("fill", fw, 8, FILL[tone], o={"radius": k.R_BADGE})] if fw else []
    kids.append(k.hbox("track", tk, {"fill": k.HOVER, "radius": k.R_BADGE}, w=w, h=8))
    return k.vbox(name, kids, {"gap": k.STACK_XS}, w=w, h=None if value else 8)


def cmp023() -> Node:
    cid = "CMP-023"
    rows = [
        k.state_row(
            "Value · Label",
            [
                k.cell(
                    "default",
                    pbar("Loading history", "page 3 of ~9", 1 / 3),
                    note="progress, a third of the track",
                ),
                k.cell("empty", pbar("Loading history", "0 %", 0), note="the track alone"),
                k.cell("complete", pbar("Loading history", "100 %", 1)),
                k.cell(
                    "unlabelled",
                    pbar(None, "page 3 of ~9", 1 / 3),
                    note="named by the host's heading",
                ),
            ],
        ),
        k.state_row(
            "Kind · Tone",
            [
                k.cell(
                    "meter",
                    pbar(None, "31 %", 0.31),
                    note="a share of the recording budget (CMP-177)",
                ),
                k.cell("success", pbar(None, "100 %", 1, "success"), note="a finished export"),
                k.cell(
                    "warning",
                    pbar(None, "85 %", 0.85, "warning"),
                    note="meter: the warning glyph + figure",
                ),
                k.cell(
                    "danger",
                    pbar(None, "97 %", 0.97, "danger"),
                    note="meter: the danger glyph + figure",
                ),
            ],
        ),
    ]
    k.gap(
        "CMP-023 meter / success / warning / danger cells: the spec gives no label string (CMP-177's and the export's "
        "names are the hosts'); drawn unlabelled, named by the host (Label=hidden's form)"
    )
    return k.block(
        cid,
        rows,
        states=[
            "default",
            "empty",
            "complete",
            "unlabelled",
            "meter",
            "success",
            "warning",
            "danger",
        ],
        not_drawn=nd(cid),
        proposed=["H4", "H12"],
    )


# --- CMP-026 EmptyState / CMP-027 ErrorState --------------------------------------------------------------------
def es_block(
    name: str,
    glyph_node: Node | None,
    heading: str | None,
    desc: str | None,
    actions: list[Node],
    *,
    w: int = NARROW,
    extra: Node | None = None,
    htypo: str = k.HEADING_SM,
    fill: str | None = None,
    msg_color: str = k.TEXT_2,
) -> Node:
    """CMP-026's block: a centred column (padding space.inset.xl, gap space.stack.sm, space.stack.md before the
    actions): the decorative lg glyph, the heading (type.ui.heading-sm), the description (type.ui.body secondary).
    """
    inner = w - 2 * k.PX[k.INSET_XL]
    kids = [
        glyph_node,
        t("heading", heading, htypo, k.TEXT_1, w=inner) if heading else None,
        t("description", desc, k.BODY, msg_color, w=inner) if desc else None,
        extra,
    ]
    body = k.vbox("text", [x for x in kids if x], {"gap": k.STACK_SM, "align": "center"}, w=inner)
    parts = [body] + ([row("actions", actions)] if actions else [])
    o = {"gap": k.STACK_MD, "align": "center", "pad": k.INSET_XL}
    if fill:
        o["fill"] = fill
    return k.vbox(name, parts, o, w=w)


def deco(ch: str, name: str, color: str = k.TEXT_3) -> Node:
    """A decorative lg glyph (size.icon.lg stand-in: type.ui.heading-md)."""
    return k.tglyph(ch, color, k.HEADING_MD, name=f"CMP-019 {name} lg (text glyph, decorative)")


def cmp026() -> Node:
    cid = "CMP-026"
    rec = S("History starts {ts} — recording began then", cid)
    rows = [
        k.state_row(
            "Variant",
            [
                k.cell(
                    "default",
                    es_block(
                        "CMP-026 no-data",
                        deco("○", "no-data"),
                        S("No rules yet — start from a template", cid),
                        None,
                        [k.button(S("Browse templates", cid), "primary")],
                    ),
                    note="no-data, cta",
                ),
                k.cell(
                    "recording",
                    es_block(
                        "CMP-026 recording",
                        deco("●", "recording"),
                        rec,
                        None,
                        [link(S("Show coverage", cid))],
                    ),
                    note="the link? once; the owner's recorder CTA not drawn (wording under review)",
                ),
                k.cell(
                    "backfill",
                    es_block(
                        "CMP-026 backfill",
                        None,
                        S("Loading history — page 3 of ~9", cid),
                        None,
                        [],
                        extra=pbar(None, None, 1 / 3, w=NARROW - 48),
                    ),
                    note="a determinate CMP-023; never danger",
                ),
                k.cell(
                    "filtered-empty",
                    es_block(
                        "CMP-026 filtered",
                        glyph("search", k.TEXT_3, k.HEADING_MD),
                        S("No rows match: Bid-stacked, Delta negative", cid),
                        None,
                        [k.button(S("Clear filters", cid), "primary")],
                    ),
                ),
            ],
        ),
        k.state_row(
            "Variant · Action",
            [
                k.cell(
                    "error",
                    es_block(
                        "CMP-026 error",
                        deco("⊘", "danger", k.STATUS["danger.strong"]),
                        None,
                        S("Couldn't load users — store unavailable.", cid),
                        [k.button(S("Retry", cid), "secondary")],
                        msg_color=k.TEXT_1,
                    ),
                    note="CMP-027's panel form, polite (§6 H13)",
                ),
                k.cell(
                    "sentence",
                    es_block(
                        "CMP-026 sentence",
                        deco("○", "no-data"),
                        S("No rules yet.", cid),
                        S("Your role can't change rules.", cid),
                        [],
                    ),
                    note="T2's sentence form: the reason alone, no lock, no button",
                ),
                k.cell(
                    "sentence · recording",
                    es_block(
                        "CMP-026 sentence recording",
                        deco("●", "recording"),
                        rec,
                        S("Only the owner can start recording.", cid),
                        [],
                    ),
                    note="for a manager or viewer",
                ),
            ],
        ),
    ]
    k.gap(
        "CMP-026 recording: the owner's CTA to the recorder has no string (`14:83`, wording under review in E16-D01 "
        "§4): not drawn; the link `Show coverage` is"
    )
    return k.block(
        cid,
        rows,
        states=[
            "default",
            "recording",
            "backfill",
            "filtered-empty",
            "error",
            "sentence",
            "sentence · recording",
        ],
        not_drawn=nd(
            cid, "the recording cell's owner CTA to the recorder (wording under review, E16-D01 §4)"
        ),
        proposed=["H13"],
    )


def details_box(lines: list[str], cid: str, w: int) -> Node:
    """CMP-027's details: type.num.sm color.text.secondary on color.surface.raised, radius.control, inset.sm; a CMP-033
    copy button (text glyph)."""
    txt = k.vbox(
        "lines",
        [t(f"line {i + 1}", S(x, cid), k.NUM_SM, k.TEXT_2) for i, x in enumerate(lines)],
        {"gap": k.STACK_XS},
    )
    return k.hbox(
        "details",
        [txt, ibtn("copy", name="CMP-033 copy (text glyph)")],
        {
            "fill": k.RAISED,
            "radius": k.R_CONTROL,
            "pad": k.INSET_SM,
            "justify": "space-between",
            "align": "start",
        },
        w=w,
    )


def banner_box(tone: str, kids: list[Node], w: int, name: str) -> Node:
    """CMP-028's inline box in a tone: .subtle fill, 2 px .strong start edge, radius.card, inset.sm x inset.md."""
    key = {"error": "danger", "warning": "warning"}.get(tone, tone)
    body = k.hbox(
        name,
        kids,
        {
            "fill": k.STATUS[f"{key}.subtle"],
            "radius": k.R_CARD,
            "padY": k.INSET_SM,
            "padX": k.INSET_MD,
            "gap": k.INSET_SM,
            "align": "start",
        },
        w=w,
    )
    h = round(k.est_height(body))
    body["kids"] = [edge("edge", k.STATUS[f"{key}.strong"], h)] + body["kids"]
    return body


def cmp027() -> Node:
    cid = "CMP-027"
    msg = S("Couldn't load users — store unavailable.", cid)
    retry = k.button(S("Retry", cid), "secondary")
    dis = S("Technical details", cid)
    panel = es_block(
        "CMP-027 panel",
        deco("⊘", "danger", k.STATUS["danger.strong"]),
        None,
        msg,
        [retry, disclosure(dis)],
        msg_color=k.TEXT_1,
    )
    warn = es_block(
        "CMP-027 panel warning",
        deco("⚠", "warning", k.STATUS["warning.strong"]),
        None,
        S("Sensitivity high may produce many false positives", cid),
        [],
        msg_color=k.TEXT_1,
    )
    inline = row(
        "CMP-027 inline",
        [
            tone_glyph("danger"),
            t("message", S("Not sent — your access changed.", cid), k.BODY, k.TEXT_1),
            t(
                "reason",
                S("Owner only: your role can't use this action.", "CMP-001"),
                k.BODY,
                k.TEXT_1,
            ),
        ],
        gap=k.INSET_XS,
    )
    banner = banner_box(
        "error",
        [
            tone_glyph("danger"),
            t("message", S("Not sent — the price is off-tick", cid), k.BODY_STRONG, k.TEXT_1),
        ],
        NARROW,
        "CMP-027 banner",
    )
    det = es_block(
        "CMP-027 details",
        deco("⊘", "danger", k.STATUS["danger.strong"]),
        None,
        msg,
        [retry, disclosure(dis, True)],
        msg_color=k.TEXT_1,
        extra=None,
    )
    det["kids"].append(details_box(["code", "correlation id"], cid, NARROW - 48))
    summ = banner_box(
        "error",
        [
            tone_glyph("danger"),
            col(
                "summary",
                [
                    t("title", S("Can't submit — 2 problems", cid), k.HEADING_SM, k.TEXT_1),
                    link(S("Username", cid, "s3")),
                    link(S("Account", cid, "s3")),
                ],
                gap=k.STACK_XS,
            ),
        ],
        NARROW,
        "CMP-027 summary",
    )
    rows = [
        k.state_row(
            "Form · Severity",
            [
                k.cell("default", panel, note="panel, error, Retry shown; live=polite (§6 H14)"),
                k.cell(
                    "warning",
                    warn,
                    note="the warning glyph + the host's sentence (S59-3), role=status",
                ),
                k.cell(
                    "inline",
                    inline,
                    note="the refusal at the point of action, assertive once; the reason a D09 key",
                ),
                k.cell("banner", banner, note="a rejected order's class line, role=alert once"),
            ],
        ),
        k.state_row(
            "Details · sample",
            [
                k.cell(
                    "details",
                    det,
                    note="Technical details open: code + correlation id, CMP-033 copy",
                ),
                k.cell("summary", summ, note="E30-D02 D16's error summary: one link per field"),
            ],
        ),
    ]
    k.gap(
        "CMP-027 details: the code and correlation id values are host data; drawn as their names ('code', "
        "'correlation id') in type.num.sm"
    )
    k.gap(
        "CMP-027 summary: the field names are the host form's; slice 3's 'Username' and 'Account' stand in"
    )
    k.gap(
        "CMP-027 inline: the spec's '{reason}' is drawn with slice 1's D09 key 'Owner only: your role can't use this "
        "action.'"
    )
    return k.block(
        cid,
        rows,
        states=["default", "warning", "inline", "banner", "details", "summary"],
        not_drawn=nd(cid),
        proposed=["H14"],
    )


# --- CMP-028 Callout / Banner -----------------------------------------------------------------------------------
def callout(
    tone: str,
    title: str | None,
    body: str | None = None,
    *,
    details: str | None = None,
    actions: list[Node] | None = None,
    dismiss: bool = False,
    hatched: bool = False,
    band: bool = False,
    extra: Node | None = None,
    w: int = CALLOUT_W,
    name: str = "CMP-028 callout",
) -> Node:
    """CMP-028: color.status.{tone}.subtle fill (connection tones on danger, §6 H5), a 2 px .strong start edge
    (hatched: 4 px), the tone glyph in .strong, title body-strong primary, body body secondary, actions; inline
    radius.card, band square and full width."""
    cid = "CMP-028"
    key = "danger" if tone.startswith("connection") else tone
    inner = w - 2 * k.PX[k.INSET_MD] - 16 - k.PX[k.INSET_SM] - (32 if dismiss else 0)
    text_kids = [
        t("title", S(title, cid), k.BODY_STRONG, k.TEXT_1, w=inner) if title else None,
        t("body", S(body, cid), k.BODY, k.TEXT_2, w=inner) if body else None,
        t("details", S(details, cid), k.BODY, k.TEXT_2, w=inner) if details else None,
        extra,
        row("actions", actions) if actions else None,
    ]
    kids: list[Node] = [tone_glyph(tone), col("text", text_kids, gap=k.STACK_XS, w=inner)]
    if dismiss:
        kids.append(ibtn("close", name="CMP-002 close · Dismiss {title}"))
    o = {
        "fill": k.STATUS[f"{key}.subtle"],
        "padY": k.INSET_SM,
        "padX": k.INSET_MD,
        "gap": k.INSET_SM,
        "align": "start",
    }
    if not band:
        o["radius"] = k.R_CARD
    n = k.hbox(name, kids, o, w=w)
    h = round(k.est_height(n))
    n["kids"] = [hatched_edge(h) if hatched else edge("edge", k.STATUS[f"{key}.strong"], h)] + n[
        "kids"
    ]
    return n


def cmp028() -> Node:
    cid = "CMP-028"
    sec = lambda s: k.button(S(s, cid), "secondary")
    rows = [
        k.state_row(
            "Tone",
            [
                k.cell(
                    "default",
                    callout(
                        "info",
                        "Reconnected — backfilling history",
                        "Recorded coverage catching up: 00:41 remaining.",
                        extra=pbar(None, None, 0.6, w=200),
                    ),
                    note="info, inline, with a CMP-023",
                ),
                k.cell(
                    "warning",
                    callout(
                        "warning",
                        "Degraded — some data feeds are stale",
                        "Book and tape are live; 1 of 4 topics stale 6s. Recent trades may lag.",
                    ),
                    note="live=polite (§6 H15)",
                ),
                k.cell(
                    "danger",
                    callout(
                        "danger", "Trading locked: daily loss limit −2 % reached at 13:41 UTC."
                    ),
                    note="role=alert once; not dismissible while it holds",
                ),
                k.cell(
                    "success",
                    callout(
                        "success",
                        "Accepted — stop 63,900.0 held by the exchange · exchange id ends …5f60",
                    ),
                ),
            ],
        ),
        k.state_row(
            "Connection",
            [
                k.cell(
                    "reconnecting",
                    callout("connection-reconnecting", "Connection unstable — last data Ns ago"),
                    note="on danger.subtle (§6 H5); one polite 'Connection unstable'",
                ),
                k.cell(
                    "disconnected",
                    callout(
                        "connection-disconnected",
                        "Disconnected — reconnecting (attempt 3, next in 4 s)",
                        "Last data 00:12 ago. Trading is disabled while offline.",
                        details="Your exchange-side stop-losses are unaffected.",
                        actions=[sec("Retry now"), disclosure(S("Details", cid))],
                    ),
                    note="Action=retry; Details an APG disclosure",
                ),
            ],
        ),
        k.state_row(
            "Placement · Dismiss · Edge",
            [
                k.cell(
                    "band",
                    callout(
                        "info", "Your access changed just now.", dismiss=True, band=True, w=560
                    ),
                    note="the band slot: full width, square; live=off, dismissible once read",
                ),
                k.cell(
                    "dismissible",
                    callout(
                        "info",
                        "Reconnected",
                        "While you were offline: 1 order filled, 1 stop moved by a rule.",
                        dismiss=True,
                    ),
                    note="the trailing CMP-002 ghost close",
                ),
                k.cell(
                    "unprotected",
                    callout(
                        "danger",
                        "Order live · protective stop pending — attaching the exchange stop "
                        "(attempt 1 of 3)",
                        actions=[sec("Flatten now"), sec("Set stop by hand")],
                        hatched=True,
                    ),
                    note="Edge=hatched, the danger glyph for shield-off; sustained alert, not dismissible",
                ),
            ],
        ),
    ]
    return k.block(
        cid,
        rows,
        states=[
            "default",
            "warning",
            "danger",
            "success",
            "reconnecting",
            "disconnected",
            "band",
            "dismissible",
            "unprotected",
        ],
        not_drawn=nd(cid),
        proposed=["H5", "H15"],
    )


# --- CMP-029 Skeleton-Chart placeholder / CMP-038 InlineSpinnerText ---------------------------------------------
PANE_W, PANE_H = 320, 160


def candles(w: int, h: int, top: int = 0, n: int = 12) -> list[Node]:
    """Illustrative candle bodies and wicks in color.surface.hover (§5.1), plus the axis label blocks."""
    out: list[Node] = []
    seq = (40, 56, 36, 64, 48, 72, 52, 44, 68, 58, 76, 50)
    step = (w - 48) // n
    for i in range(n):
        bh = seq[i % len(seq)] * (h - 24) // 100
        y = top + (h - 24 - bh) // 2 + (i % 3) * 4
        out.append(k.place(k.rect(f"wick {i + 1}", 1, bh + 12, k.HOVER), 8 + i * step + 4, y - 6))
        out.append(k.place(k.rect(f"body {i + 1}", 8, bh, k.HOVER), 8 + i * step, y))
    out.append(
        k.place(
            k.rect("price axis", 28, h - 32, k.HOVER, o={"radius": k.R_CONTROL}), w - 36, top + 8
        )
    )
    out.append(
        k.place(k.rect("time axis", w - 56, 8, k.HOVER, o={"radius": k.R_CONTROL}), 8, top + h - 14)
    )
    return out


def ist(label: str, cid: str = "CMP-038", cancel: bool = False) -> Node:
    """CMP-038: CMP-014 sm (size.icon) then the text (type.ui.body secondary), gap inset.xs; Cancel ghost sm."""
    kids = [k.spinner(16), t("text", S(label, cid), k.BODY, k.TEXT_2)]
    r = row("CMP-038 inline spinner text", kids, gap=k.INSET_XS)
    if cancel:
        return row("CMP-038 with Cancel", [r, k.button(S("Cancel", "CMP-038"), "ghost", size="sm")])
    return r


def pane(name: str, band: bool, text_over: bool) -> Node:
    kids = candles(PANE_W, PANE_H)
    if band:
        kids.append(k.place(k.rect("shimmer band", 48, PANE_H, k.RAISED), PANE_W // 2 - 24, 0))
    if text_over:
        kids.append(ist("Loading 5,000 bars…", "CMP-029"))
    return k.hbox(
        name,
        kids,
        {
            "fill": k.CANVAS,
            "stroke": k.BORDER_SUBTLE,
            "strokeWidth": k.HAIRLINE,
            "justify": "center",
        },
        w=PANE_W,
        h=PANE_H,
    )


def cmp029() -> Node:
    cid = "CMP-029"
    sub_h = 48
    three = k.box(
        "CMP-029 panes 3",
        [
            *candles(PANE_W, PANE_H - 2 * sub_h),
            k.place(k.rect("pane rule 1", PANE_W, 1, k.BORDER_DEFAULT), 0, PANE_H - 2 * sub_h),
            k.place(
                k.rect("sub-pane 1", PANE_W - 56, 24, k.HOVER, o={"radius": k.R_CONTROL}),
                8,
                PANE_H - 2 * sub_h + 12,
            ),
            k.place(k.rect("pane rule 2", PANE_W, 1, k.BORDER_DEFAULT), 0, PANE_H - sub_h),
            k.place(
                k.rect("sub-pane 2", PANE_W - 56, 24, k.HOVER, o={"radius": k.R_CONTROL}),
                8,
                PANE_H - sub_h + 12,
            ),
        ],
        {"fill": k.CANVAS, "stroke": k.BORDER_SUBTLE, "strokeWidth": k.HAIRLINE},
        w=PANE_W,
        h=PANE_H,
    )
    rows = [
        k.state_row(
            "Panes · Motion",
            [
                k.cell(
                    "default",
                    pane("CMP-029 pane", True, True),
                    note="Panes=1, shimmer; the host's CMP-038 words over it, outside the hidden node",
                ),
                k.cell(
                    "Panes=3", three, note="a price pane over two sub-panes, the host's pane rules"
                ),
                k.cell(
                    "Motion=static",
                    pane("CMP-029 pane static", False, False),
                    note="reduce, and after the 5 s stop",
                ),
            ],
        )
    ]
    return k.block(
        cid,
        rows,
        states=["default", "Panes=3", "Motion=static"],
        not_drawn=nd(cid),
        proposed=["H3"],
    )


def cmp038() -> Node:
    cid = "CMP-038"
    rows = [
        k.state_row(
            "Phase · Cancel",
            [
                k.cell("default", ist("Loading positions"), note="Phase=waiting"),
                k.cell(
                    "slow",
                    ist("Still loading… the server is slow to answer"),
                    note="SCR-150's slow boot at 5 s, no Cancel",
                ),
                k.cell(
                    "cancellable",
                    ist("Still loading positions…", cancel=True),
                    note="a load at 5 s, Cancel offered",
                ),
            ],
        )
    ]
    return k.block(
        cid, rows, states=["default", "slow", "cancellable"], not_drawn=nd(cid), proposed=["H29"]
    )


# --- CMP-045 Toast ----------------------------------------------------------------------------------------------
TOAST_INNER = 360 - 2 * 12 - 16 - 8 - 32


def toast(
    tone: str,
    title: str,
    *,
    body: str | None = None,
    kicker: str | None = None,
    meta: str | None = None,
    actions: list[Node] | None = None,
    reason: str | None = None,
    name: str = "CMP-045 toast",
) -> Node:
    """CMP-045 (E40-D02 §4.2): conventions 30's surface, 360 px, inset.md, rows stack.sm; a 2 px start edge in
    color.status.{tone}.default (§6 H6); glyph in .strong; kicker caption secondary; title body-strong; body body
    secondary; meta num.sm tertiary; actions; dismiss CMP-002 ghost close. reason= the one T2 notice line.
    """
    cid = "CMP-045"
    txt = col(
        "text",
        [
            t("kicker", S(kicker, cid), k.CAPTION, k.TEXT_2) if kicker else None,
            t("title", S(title, cid), k.BODY_STRONG, k.TEXT_1, w=TOAST_INNER),
            t("body", S(body, cid), k.BODY, k.TEXT_2, w=TOAST_INNER) if body else None,
            t("meta", S(meta, cid), k.NUM_SM, k.TEXT_3) if meta else None,
        ],
        gap=k.STACK_XS,
        w=TOAST_INNER,
    )
    head = row(
        "head",
        [tone_glyph(tone), txt, ibtn("close", name="CMP-002 close · Dismiss {title}")],
        align="start",
    )
    kids: list[Node] = [head]
    if actions:
        kids.append(row("actions", actions, wrap="wrap"))
    if reason:
        kids.append(k.t2_reason(S(reason, cid), w=360 - 24, name="T2 reason · notice"))
    n = floating(name, kids, w=360, pad=k.INSET_MD)
    h = round(k.est_height(n))
    n["kids"] = [edge("edge", k.STATUS[f"{'info' if tone == 'info' else tone}.default"], h)] + n[
        "kids"
    ]
    return n


def cmp045() -> Node:
    cid = "CMP-045"
    ghost = lambda s, st="default": k.button(S(s, cid), "ghost", st)
    sec = lambda s, st="default": k.button(S(s, cid), "secondary", st)
    alert = {
        "kicker": "Warning · Alert",
        "body": "Last price 65,012.5 crossed above 65,000",
        "meta": "BTCUSDT · 5m",
    }
    undo_live = toast("info", "EMA 21 removed.", actions=[ghost("Undo")], name="CMP-045 undo")
    undo_out = toast("info", "EMA 21 removed.", name="CMP-045 undo outcome")
    rows = [
        k.state_row(
            "Tone",
            [
                k.cell(
                    "default",
                    toast(
                        "info", "Session extended.", body="Idle timer reset. Next warning in 14:00."
                    ),
                    note="info, timed, no action",
                ),
                k.cell(
                    "success", toast("success", "Accepted — stop 63,900.0 held by the exchange")
                ),
                k.cell(
                    "warning",
                    toast(
                        "warning",
                        "BTC above 65k",
                        **alert,
                        actions=[
                            sec("Open chart"),
                            ghost("Snooze ▾"),
                            ghost("Disable"),
                            ghost("Details"),
                        ],
                    ),
                    note="a fired alert: closes after 20 s, paused on hover and focus (§6 H26)",
                ),
                k.cell(
                    "danger",
                    toast(
                        "danger",
                        S("Not sent — the price is off-tick", cid),
                        actions=[sec("Details")],
                    ),
                    note="an order rejection, persistent; Details opens SCR-077",
                ),
            ],
        ),
        k.state_row(
            "State · Action",
            [
                k.cell(
                    "focused",
                    toast(
                        "info",
                        S("Template removed.", cid),
                        actions=[ghost("Undo", "focus-visible")],
                    ),
                    note="an action holding focus: its ring; every timer in the stack paused",
                ),
                k.cell(
                    "T2 action",
                    toast(
                        "warning",
                        "BTC above 65k",
                        **alert,
                        actions=[
                            sec("Open chart"),
                            ghost("Snooze", "disabled-with-reason"),
                            ghost("Disable", "disabled-with-reason"),
                        ],
                        reason="Your role can't change alerts.",
                    ),
                    note="CMP-079 form=notice: the lock leads each full label; one reason line both point at",
                ),
                k.cell(
                    "undo",
                    k.vbox("undo pair", [undo_live, undo_out], {"gap": k.STACK_SM}),
                    note="a local undo, then its outcome line once the window closes (§6 H27)",
                ),
            ],
        ),
    ]
    k.gap(
        "CMP-045 danger: the spec names 'an order rejection' without a title; CMP-027's banner line 'Not sent — the "
        "price is off-tick' (slice 4) stands in"
    )
    k.gap(
        "CMP-045 focused: the cell names no toast; E14-D04's 'Template removed. Undo' (slice 4 §6) is drawn"
    )
    return k.block(
        cid,
        rows,
        states=["default", "success", "warning", "danger", "focused", "T2 action", "undo"],
        not_drawn=nd(cid),
        proposed=["H6", "H26", "H27"],
    )


# --- CMP-089 / 090 / 091 route and panel outcomes (480 px, build-notes §4 board 08) --------------------------------
def page(name: str, kids: list[Node | None], *, fill: str = k.APP, w: int = PANEL_W) -> Node:
    """A full-panel stand-in: CMP-026's centred block on the route's surface, with a 1 px subtle edge."""
    return k.vbox(
        name,
        [x for x in kids if x],
        {
            "fill": fill,
            "stroke": k.BORDER_SUBTLE,
            "strokeWidth": k.HAIRLINE,
            "pad": k.INSET_XL,
            "gap": k.STACK_SM,
            "align": "center",
        },
        w=w,
    )


INNER = PANEL_W - 48


def cmp089() -> Node:
    cid = "CMP-089"
    lk = lambda: k.lock(k.ICON_LG, k.TEXT_3, name="CMP-019 lock lg (decorative)")
    h1 = lambda s: t("h1", S(s, cid), k.HEADING_LG, k.TEXT_1, w=INNER)
    sent = lambda s: t("sentence", S(s, cid), k.BODY, k.TEXT_2, w=INNER)
    acts = lambda: row(
        "actions",
        [
            link(S("Back to your workspace", cid)),
            k.button(S("Copy details", cid), "secondary"),
        ],
    )
    ref = t("ref", S("Ref {instance}", cid), k.NUM_SM, k.TEXT_2)
    never = "Your role can't see the journal. Ask the owner if you need it."
    rows = [
        k.state_row(
            "Variant · Ref",
            [
                k.cell(
                    "default",
                    page(
                        "CMP-089 default",
                        [lk(), h1("You don't have access to this"), sent(never), acts(), ref],
                    ),
                    note="never-had, Ref shown, permission",
                ),
                k.cell(
                    "no Ref",
                    page(
                        "CMP-089 no ref",
                        [lk(), h1("You don't have access to this"), sent(never), acts()],
                    ),
                    note="the step-3 pre-check landing: no request sent, no Ref, no audit",
                ),
            ],
        ),
        k.state_row(
            "Variant · Scope",
            [
                k.cell(
                    "withdrawn",
                    page(
                        "CMP-089 withdrawn",
                        [
                            lk(),
                            h1("Your access changed"),
                            sent(
                                "Your role can't see the journal any more — this changed just now. Anything you already sent "
                                "was decided by the server: check Orders. Ask the owner if this is unexpected."
                            ),
                            acts(),
                        ],
                    ),
                    note="Ref=none",
                ),
                k.cell(
                    "account",
                    page(
                        "CMP-089 account",
                        [
                            lk(),
                            h1("You don't have access to this"),
                            sent("This account isn't assigned to you."),
                            t("account echo", S("sub_001", cid), k.NUM_BASE, k.TEXT_1),
                            acts(),
                            ref,
                        ],
                    ),
                    note="the account id the client asked for, in mono",
                ),
            ],
        ),
    ]
    k.gap(
        "CMP-089 account: the echoed id is host data; slice 4's account 'sub_001' (CMP-044) stands in"
    )
    return k.block(
        cid,
        rows,
        states=["default", "no Ref", "withdrawn", "account"],
        not_drawn=nd(cid),
        proposed=["H18"],
    )


def cmp090() -> Node:
    cid = "CMP-090"

    def nf(name: str, route: str | None, sentence: str | None) -> Node:
        if route:
            line = row(
                "sentence",
                [
                    t("lead", S("There's nothing at", cid), k.BODY, k.TEXT_2),
                    t("route", S(route, cid), k.NUM_SM, k.TEXT_2),
                ],
                gap=k.INSET_XS,
            )
        else:
            line = t("sentence", S(sentence or "", cid), k.BODY, k.TEXT_2, w=INNER)
        tries = row(
            "try",
            [
                t("try", S("Try:", cid), k.BODY, k.TEXT_2),
                link(S("Workspace", cid)),
                k.tglyph("·", k.TEXT_3),
                link(S("Journal", cid)),
                k.tglyph("·", k.TEXT_3),
                link(S("Settings", cid)),
            ],
            gap=k.INSET_XS,
        )
        return page(
            name,
            [
                glyph("search", k.TEXT_3, k.HEADING_MD),
                t("h1", S("Page not found", cid), k.HEADING_LG, k.TEXT_1),
                line,
                tries,
            ],
        )

    rows = [
        k.state_row(
            "Variant",
            [
                k.cell(
                    "default",
                    nf("CMP-090 unknown", "/nowhere.", None),
                    note="Variant=unknown at /nowhere",
                ),
                k.cell(
                    "admin",
                    nf("CMP-090 admin", "/admin/users", None),
                    note="no admin:read: the same copy, title and analytics (D09 T3 hard-404)",
                ),
                k.cell(
                    "deleted",
                    nf("CMP-090 deleted", None, "this workspace was deleted"),
                    note="Variant=deleted",
                ),
            ],
        )
    ]
    return k.block(
        cid, rows, states=["default", "admin", "deleted"], not_drawn=nd(cid), proposed=["H19"]
    )


def cmp091() -> Node:
    cid = "CMP-091"
    dg = lambda: deco("⊘", "danger", k.STATUS["danger.strong"])
    btn = lambda s, v="secondary": k.button(S(s, cid), v)
    head = lambda: t(
        "heading", S("This panel stopped working", cid), k.HEADING_SM, k.TEXT_1, w=INNER
    )
    stack = k.vbox(
        "details",
        [
            k.rect(f"stack line {i + 1}", w, 8, k.BORDER_DEFAULT, o={"radius": k.R_CONTROL})
            for i, w in enumerate((360, 300, 332))
        ],
        {"fill": k.RAISED, "radius": k.R_CONTROL, "pad": k.INSET_SM, "gap": k.STACK_XS},
        w=INNER,
        h=3 * 8 + 2 * 4 + 16,
    )
    chrome = k.rect("chrome stand-in (TopBar)", PANEL_W - 2, 24, k.CANVAS)
    rows = [
        k.state_row(
            "Scope",
            [
                k.cell(
                    "default",
                    page(
                        "CMP-091 panel",
                        [
                            dg(),
                            head(),
                            row(
                                "actions",
                                [
                                    btn("Reload panel", "primary"),
                                    btn("Remove panel"),
                                    btn("Copy diagnostics"),
                                ],
                            ),
                        ],
                        fill=k.CANVAS,
                    ),
                    note="Scope=panel on color.surface.canvas; the workspace alive around it",
                ),
                k.cell(
                    "route",
                    page(
                        "CMP-091 route",
                        [
                            chrome,
                            dg(),
                            row(
                                "actions",
                                [
                                    btn("Reload page", "primary"),
                                    btn("Reload app"),
                                    btn("Start in safe mode"),
                                ],
                            ),
                        ],
                    ),
                    note="Scope=route on color.surface.app, the chrome intact",
                ),
                k.cell(
                    "app",
                    page(
                        "CMP-091 app",
                        [
                            dg(),
                            row(
                                "actions",
                                [
                                    btn("Reload app", "primary"),
                                    btn("Start in safe mode"),
                                    btn("Copy diagnostics"),
                                ],
                            ),
                        ],
                    ),
                    note="Scope=app: the root boundary, no chrome, role=alert",
                ),
            ],
        ),
        k.state_row(
            "Details · Repeated",
            [
                k.cell(
                    "details",
                    page(
                        "CMP-091 details",
                        [dg(), head(), disclosure(S("Technical detail", cid), True), stack],
                        fill=k.CANVAS,
                    ),
                    note="Details=open: the stack behind 'Technical detail' (CMP-027's disclosure)",
                ),
                k.cell(
                    "repeated",
                    page(
                        "CMP-091 repeated",
                        [
                            dg(),
                            head(),
                            row("actions", [btn("Remove panel"), btn("Copy diagnostics")]),
                        ],
                        fill=k.CANVAS,
                    ),
                    note="three crashes in two minutes stop the automatic reload (E10-D03 §9.4, PROPOSED)",
                ),
            ],
        ),
    ]
    k.gap(
        "CMP-091: the route / app h1, the error id, the host's protection sentence and the repeated-crash sentence "
        "are E10-D03's strings, not in slice 4: not drawn (the id and the stack lines are drawn as num-line stand-ins "
        "only in the details box)"
    )
    return k.block(
        cid,
        rows,
        states=["default", "route", "app", "details", "repeated"],
        not_drawn=nd(
            cid,
            "the route / app h1, the error id line and the protection and repeated-crash sentences (E10-D03's strings)",
        ),
        proposed=["H20"],
    )


def main() -> int:
    blocks = [
        cmp015(),
        cmp023(),
        cmp026(),
        cmp027(),
        cmp028(),
        cmp029(),
        cmp038(),
        cmp045(),
        cmp089(),
        cmp090(),
        cmp091(),
    ]
    notes = [
        "Tone carriers are never colour alone: every status cell pairs the CMP-019 glyph (text glyph) with words.",
        (
            "CMP-045's T2 action cell goes through CMP-079 form=notice: lock-led full labels in color.text.tertiary, the "
            "raised fill + hairline, one reason line in color.text.secondary (E09-D09 §2.2; conventions 36)."
        ),
        (
            "CMP-089 / 090 / 091 are full-panel states: drawn at 480 px wide (the spec names no panel size beyond CMP-026's "
            "480 px column; author choice, a deviation in the board .md)."
        ),
        (
            "Glyph stand-ins: info ⓘ, check ✓, warning ⚠, danger ⊘, disconnected ✕, search ⌕, no-data ○, recording ●, "
            "copy ⧉, chevrons ▾ ▴; the lock and close are the file's local icons."
        ),
    ]
    k.LOG.add(
        "deviations",
        "author choice (board 08): CMP-089 / 090 / 091 drawn at 480 px wide full-panel stand-ins "
        "(build-notes §4 board 08)",
    )
    k.LOG.add(
        "deviations",
        "author choice (board 08): CMP-026 / 027 cells at 360 px (within §5.1's 480 px maximum) "
        "and CMP-028 inline cells at 420 px, the band cell at 560 px",
    )
    bd = k.board(
        NN,
        blocks,
        source="slice 4 §3 conventions 30-39, §6 decisions H, §7 L1000-1056, L1184-1517, "
        "L1779-1860, L1931-2086",
        notes=notes,
    )
    path = k.KIT_DIR / f"{k.stem(NN)}.json"
    print(k.write_sheet(path, bd))
    rep = k.compact_sheet(path)
    print(rep)
    k.write_board_md(
        NN,
        bd,
        summary="Board 08: slice 4's feedback states, eleven blocks, the spec's named cells.",
        checks=[
            "every block draws the spec's named cells (Variants x States table or paragraph)",
            "every specimen string k.say()'d from the frozen slice 4 spec (slice 1 / 3 where nested)",
            "tone = glyph + word in every status cell (never colour alone)",
            "CMP-045 T2 action: lock leads each full label, tertiary label, one reason line (2a notice)",
            "no inst node; only the local icons locked and close",
        ],
        live=[
            "CMP-028 hatched edge: the 1 px ticks read at 1x on danger.subtle",
            "every toast / callout start edge reads at 1x (2 px abs rect at x 0)",
        ],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

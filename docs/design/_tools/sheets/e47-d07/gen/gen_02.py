"""Board 02 `E47-D07 / 02 shell-pair-writers` (dark): §2 — the shell's one pair in the DOM and the writers that write
into it; the local regions R-1 names, each pre-rendered empty at its control."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k  # noqa: E402

NN = 2
PAD = 24
P_PAIR, P_WRITERS, P_LOCAL = k.L("**The pair.**"), k.L("**Writers.**"), k.L("**Local regions")
WRITERS = (  # (the surface as §2's Writers paragraph names it, what it writes there): each checked against the text
    ("CMP-212 ToastHost and CMP-045 Toast", "write the toast's sentence into the pair"),
    ("CMP-077 ReconnectOverlay", "writes the connection rows"),
    ("CMP-117 RiskLockoutBanner", "writes the safety rows"),
    ("the ambient writer", "writes the fields"),
)


def _check_writers() -> None:
    para = k.plain(k.SPEC_LINES[P_WRITERS - 1])
    for who, what in WRITERS:
        if f"{who} {what}" not in para:
            raise SystemExit(f"board 02: §2 L{P_WRITERS} no longer says {who!r} {what!r}")


def sample(sid: str, channel: str) -> str:
    return next(x["text"] for x in k.SCRIPTS[sid]["expected"] if x["channel"] == channel)


def container(politeness: str, msg: str, wd: int) -> dict:
    child = k.vbox("p · the current message", [k.text("tag", "<p> (a new child per message)", k.CAPTION, k.TEXT_2),
                                                k.text("words", msg, k.BODY, k.TEXT_1, w=wd - 48)],
                   {"gap": k.STACK_XS, "pad": k.INSET_SM, "fill": k.RAISED, "radius": k.R_CONTROL}, w=wd - 32)
    head = k.text("tag", f'<div aria-live="{politeness}" aria-atomic="true">', k.NUM_SM, k.TEXT_1)
    return k.vbox(f"container · {politeness}", [head, child], {"gap": k.STACK_SM, "pad": k.INSET_SM,
                                                                "stroke": k.BORDER_STRONG, "strokeWidth": k.HAIR,
                                                                "strokeAlign": "inner", "radius": k.R_CARD},
                  w=wd - 16, note="the region is the container, not the child (`05`:154; D07-A3)")


def frame_pair(fid: str) -> dict:
    _check_writers()
    wcol, gap = 300, 120
    writers = [k.vbox(f"writer · {who}", [k.text("who", who, k.BODY_STRONG, k.TEXT_1, w=wcol - 24),
                                          k.text("what", what, k.CAPTION, k.TEXT_2, w=wcol - 24)],
                      {"gap": k.STACK_XS, "pad": k.INSET_SM, "fill": k.RAISED, "radius": k.R_CARD}, w=wcol)
               for who, what in WRITERS]
    y, placed = 72, []
    for wr in writers:
        placed.append(dict(wr, x=PAD, y=y))
        y += round(k.est_height(wr)) + 24
    tx = PAD + wcol + gap
    tw = 560
    pol = container("polite", sample("fast", "polite"), tw)
    ass = container("assertive", sample("fast", "assertive"), tw)
    tree = k.vbox("DOM · ShellLayout", [
        k.text("tag", "ShellLayout", k.NUM_SM, k.TEXT_2),
        k.vbox("ShellAnnouncer", [k.text("tag", "ShellAnnouncer (ANN:4) · rendered once · visually hidden", k.NUM_SM,
                                          k.TEXT_2), pol, ass],
               {"gap": k.STACK_SM, "pad": k.INSET_SM, "stroke": k.BORDER, "strokeWidth": k.HAIR, "strokeAlign": "inner",
                "radius": k.R_CARD}, w=tw)],
        {"gap": k.STACK_SM, "pad": k.INSET_MD, "fill": k.RAISED, "radius": k.R_CARD}, w=tw + 24, x=tx, y=72,
        note="the pair: pre-rendered empty at first paint, live for the session, never re-mounted (R-2)")
    arrows = [k.arrow(f"writes · {i}", PAD + wcol + 8, int(p["y"]) + 16, gap - 16) for i, p in enumerate(placed, 1)]
    rx = tx + tw + 24 + 32
    rw = k.FRAME_W - rx - PAD
    facts = [
        ("Pre-rendered empty", f"in the DOM from the first paint, both aria-atomic (§2 L{P_PAIR})"),
        ("Text swapped (R-2)", "a message is a child inside its stable container; a later message replaces it"),
        ("Exempt from modal inertness", "they speak under a CMP-043 dialog (ANN:86–91)"),
        ("No second region", "no component owns a region for a pair event (R-1; `05`:154; D17:249)"),
        ("Assertive region", f"{k.CLASSES['significant-assertive']['schedule']}"),
        ("Polite region", "status-polite rows and the ambient composite (§3.1)"),
    ]
    fcards = [k.vbox(f"fact · {a}", [k.text("a", a, k.LABEL, k.TEXT_1, w=rw - 16),
                                     k.text("b", b_, k.CAPTION, k.TEXT_2, w=rw - 16)],
                     {"gap": k.STACK_XS, "padX": k.INSET_SM, "padY": k.INSET_XS}, w=rw) for a, b_ in facts]
    facts_col = k.vbox("facts", fcards, {"gap": k.STACK_SM}, w=rw, x=rx, y=72)
    heads = [k.heading("h · writers", "Writers (§2)", PAD, PAD, wcol, sub="through announce or the ambient writer"),
             k.heading("h · pair", "The shell's one pair (§2, R-1, R-2)", tx, PAD, tw),
             k.heading("h · facts", "Hygiene", rx, PAD, rw)]
    return k.specimen(fid, [*heads, *placed, *arrows, tree, facts_col, k.synthetic_tag(PAD, k.FRAME_H - 28)])


def local_kinds() -> list[tuple[str, str]]:
    """§2's four local kinds, '(1) … (4)', as (number, words)."""
    para = k.plain(k.SPEC_LINES[P_LOCAL - 1])
    body = para.split("Four kinds stay local,", 1)[1]
    parts = re.split(r"\((\d)\) ", body)
    out = [(parts[i], parts[i + 1].rstrip("; ").split(". CMP-092")[0]) for i in range(1, len(parts) - 1, 2)]
    if [n for n, _ in out] != ["1", "2", "3", "4"]:
        raise SystemExit(f"board 02: §2 L{P_LOCAL}'s four kinds unreadable")
    return out


def frame_local(fid: str) -> dict:
    tw = 420
    reason = k.REASONS["maintenance"]
    msg = k.w("W-27").replace("{reason}", reason)
    k.fallback("chrome")
    ticket = k.vbox("order ticket (placeholders)", [
        k.text("h", "Order ticket", k.HEADING_SM, k.TEXT_1),
        *[k.placeholder(f"control {i}", tw - 32, 28) for i in range(1, 5)],
        k.placeholder("submit button", 120, 28),
        k.hbox("local alert · role=alert", [k.icon("glyph", "danger", k.DANGER_STRONG),
                                            k.text("words", msg, k.BODY, k.TEXT_1, w=tw - 64)],
               {"gap": k.INSET_SM, "pad": k.INSET_SM, "stroke": k.DANGER_STRONG, "strokeWidth": k.HAIR,
                "strokeAlign": "inner", "radius": k.R_CONTROL}, w=tw - 32,
               note='role="alert", pre-rendered empty with the ticket; its text swapped once (D07E11:634, A-09)'),
    ], {"gap": k.STACK_SM, "pad": k.INSET_LG, "fill": k.RAISED, "radius": k.R_CARD}, w=tw, x=PAD, y=72)
    k.copy_gap('"Order ticket": the ticket\'s heading on this diagram (the ticket is E11\'s; its controls are '
               "placeholders here)")
    tk = round(k.est_height(ticket))
    tags = [k.tag("T-9 / T-10: the reply at the control that took the action", PAD, 72 + tk + 12),
            k.tag("CMP-060 row written; stays until the next submit (R-8)", PAD, 72 + tk + 32)]
    rx = PAD + tw + 48
    rw = k.FRAME_W - rx - PAD
    cards = []
    for n, words in local_kinds():
        rows = re.findall(r"T-\d+", words)
        cls = k.TAX[rows[0]].cls if rows else "status-polite"
        cards.append(k.tagged_card(f"local kind {n}", cls, [
            k.text("n", f"({n}) {k.TAX[rows[0]].cls if rows else ''}", k.LABEL, k.TEXT_1, w=rw - 20),
            k.text("words", words, k.CAPTION, k.TEXT_1, w=rw - 20)], rw))
    d17 = k.tagged_card("T-17 · the dialog speaks", "significant-assertive", [
        k.text("n", "T-17 · rank 1", k.LABEL, k.TEXT_1, w=rw - 20),
        k.text("words", "its alertdialog speaks it on focus; the pair does not repeat it (R-1, §9; board 05)",
               k.CAPTION, k.TEXT_1, w=rw - 20)], rw)
    col = k.vbox("the local kinds", [*cards, d17], {"gap": k.STACK_SM}, w=rw, x=rx, y=72)
    heads = [k.heading("h · ticket", "A local reply (§2 kind 1)", PAD, PAD, tw),
             k.heading("h · kinds", f"The local regions (§2 L{P_LOCAL}; R-1)", rx, PAD, rw,
                       sub="each pre-rendered empty with its control; only its text is swapped")]
    return k.specimen(fid, [*heads, ticket, *tags, col, k.synthetic_tag(PAD, k.FRAME_H - 28)])


def main() -> None:
    b = k.BOARDS[NN]
    frames = [frame_pair(b.frames[0]), frame_local(b.frames[1])]
    blocks = [
        (b.frames[0], [
            f"§2 L{P_PAIR}: ShellLayout renders ShellAnnouncer once; two visually hidden containers, polite and "
            "assertive, aria-atomic, pre-rendered empty, live for the session (R-2)",
            f"§2 L{P_WRITERS}: the writers, each through announce or the ambient writer; none renders a region of its "
            "own for a taxonomy event (CMP-212's own regions are D07-C10 / D07-G4)",
            f"The sample messages are the fast script's first polite composite and first assertive line (§10.2): "
            f"\"{sample('fast', 'polite')}\" and \"{sample('fast', 'assertive')}\"",
            "The arrows are annotation: every writer writes into the pair"]),
        (b.frames[1], [
            f"§2 L{P_LOCAL}: four local kinds, each pre-rendered empty with its control (R-1's named exceptions)",
            f"The reply drawn: W-27 with the gate's maintenance refusal, its words from §7.3 (L{k.REASONS_LINE}): "
            f"\"{k.w('W-27').replace('{reason}', k.REASONS['maintenance'])}\"",
            "CMP-092's blocking row writes into the pair, not its own role=\"alert\" (D17:268; D07-C20)",
            "A local region never carries a taxonomy event the pair already speaks (R-6)"]),
    ]
    k.ambiguity("Board 02: §0 says the board draws \"the local own-action regions\"; the frame draws §2's four local "
                "kinds plus T-17's dialog, the other exception R-1 names, pointing to board 05 for it")
    p, md, pk = k.build(NN, frames, blocks, per_row=2)
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()

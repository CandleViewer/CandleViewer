"""Board 01 `E47-D07 / 01 taxonomy-map` (dark): §3 and §4 — the five classes, the four ranks and every T-row, grouped
by its SCR-117 panel class (§8.1); the local replies and the silent rows in their own groups."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import columns, k  # noqa: E402

NN = 1
PAD, COLS, GAP = 24, 4, 8
INNER = k.FRAME_W - 2 * PAD
LOCAL, NONE = "— (local reply)", "—"


def legend() -> list[dict]:
    cw = (INNER - 4 * 8) // 5
    cards = []
    for i, (c, d) in enumerate(k.CLASSES.items()):
        n = sum(t.cls == c for t in k.TAX.values())
        cards.append(dict(k.tagged_card(f"class · {c}", c, [
            k.text("name", f"{c} · {n} rows", k.BODY_STRONG, k.TEXT_1, w=cw - 20),
            k.text("schedule", d["schedule"], k.CAPTION, k.TEXT_2, w=cw - 20)], cw,
            note=f"§3.1 L{d['line']}: region {d['region']}", grow=False), x=PAD + i * (cw + 8), y=PAD))
    hmax = max(round(k.est_height(c)) for c in cards)
    return [dict(c, h=hmax, kids=[dict(c["kids"][0], h=hmax), dict(c["kids"][1], h=hmax)]) for c in cards]


# the group cards whose 'content' stack the drawing lane grew live (fix line: 57 -> 59 four times, 53 -> 54, 40 -> 41
# four times, 83 -> 85); every other card's live wrap left it slack, so it keeps the estimate
GROWN = frozenset(("Order fills", "Order problems", "Rule actions", "Your keys", "Trade groups", "Alerts", "Recorder",
                   "Rule fires", "Trading environment", "Countdowns"))


def group_card(title: str, cls: str, rows: list[k.Tax], wd: int, sub: str) -> dict:
    ranks = sorted({t.rank for t in rows} - {"—"})
    mixed = len(ranks) > 1
    if len(ranks) == 1:
        title += f" · rank {ranks[0]}"
    lines = [k.trow_line(t, wd - 20, rank=mixed) for t in rows]
    head = k.text("title", title, k.LABEL, k.TEXT_1, w=wd - 20)
    base = title.split(" · ")[0]
    return k.tagged_card(f"group · {base}", cls, [head, *lines], wd, note=sub, grow=base in GROWN)


def build_frame() -> tuple[dict, list[dict]]:
    b = k.BOARDS[NN]
    colw = (INNER - (COLS - 1) * GAP) // COLS
    leg = legend()
    y_rank = PAD + round(k.est_height(leg[0])) + 8
    rank_words = " · ".join(f"rank {n}: {w}" for n, w in sorted(k.RANKS.items()))
    rank_t = k.text("ranks", f"§5.1 L{k.RANK_LINE}, spoken first to last — {rank_words}; local: a reply at its "
                             "control (§2)", k.CAPTION, k.TEXT_1, w=INNER, x=PAD, y=y_rank)
    groups = []
    for p in k.PANEL:
        rows = [k.TAX[r.strip()] for r in p["rows"].split(",")]
        cls = {t.cls for t in rows}
        if len(cls) != 1:
            raise SystemExit(f"board 01: panel class {p['cls']} mixes classes {cls}")
        groups.append(group_card(f"{p['cls']} · {p['default']}", cls.pop(), rows, colw,
                                 f"default {p['default']} · {p['choice']} (§8.1 L{p['line']})"))
    local = [t for t in k.TAX.values() if t.panel == LOCAL]
    groups.append(group_card("Local replies (no panel class)", local[0].cls, local, colw,
                             "the ticket's own role=\"alert\"; the CMP-060 row only (§2, R-8)"))
    silent = [t for t in k.TAX.values() if t.panel == NONE]
    if {t.cls for t in silent} != {"silent"}:
        raise SystemExit("board 01: a row without a panel class is not silent")
    groups.append(group_card("Silent (never narrated)", "silent", silent, colw, "read where §4's last column says"))
    y0 = y_rank + round(k.est_height(rank_t)) + 12
    placed = columns(groups, PAD, y0, COLS, colw, GAP, k.FRAME_H - 32)
    drawn = sorted(t for g in groups for t in [n["name"].split(" · ")[1] for n in g["kids"][1]["kids"]
                                                  if n["name"].startswith("row · ")])
    if drawn != sorted(k.TAX):
        raise SystemExit("board 01: not every T-row is drawn exactly once")
    fr = k.specimen(b.frames[0], [*leg, rank_t, *placed, k.synthetic_tag(PAD, k.FRAME_H - 28)])
    return fr, groups


def main() -> None:
    b = k.BOARDS[NN]
    fr, groups = build_frame()
    n_as = sum(t.cls == "significant-assertive" for t in k.TAX.values())
    blocks = [(b.frames[0], [
        f"Every T-row of §4 (L{k.TAX_LINE}) appears once: {len(k.TAX)} rows, {n_as} significant-assertive, "
        f"{sum(t.cls == 'silent' for t in k.TAX.values())} silent, the rest polite; one class per row (BQ-2, T AC1)",
        f"Grouped by the SCR-117 panel class of §8.1 (L{k.PANEL_LINE}): {len(k.PANEL)} classes, then the local "
        "replies T-9 / T-10 (no panel class, R-1) and the silent rows",
        f"The five classes and their schedules are §3.1's table (L{k.CLASSES_LINE}); ranks are §5.1's (L{k.RANK_LINE})",
        f"The assertive set (§3.2, {len(k.ASSERTIVE_SET)} entries): `05`:152's six verbatim, the fixed safety group "
        "(the Risk and safety card) and the other PROPOSED rows (D07-C16)",
        "Each line: T-id · §4's event words without their source cite; the rank is in the card title, or on each line where a card mixes ranks (Risk and safety: 1 and 2)",
    ])]
    k.ambiguity("Board 01: §4's event cells carry a trailing source cite in parentheses; the map drops it (the cite "
                "is in each line's note) so a line fits a column")
    p, md, pk = k.build(NN, [fr], blocks, per_row=1)
    print(p.name, md.name, pk.name, len(groups))


if __name__ == "__main__":
    main()

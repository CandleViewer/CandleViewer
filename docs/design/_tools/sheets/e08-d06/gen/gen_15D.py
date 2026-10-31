"""Board 15D: CMP-126/funding-countdown-states (§7 states; the sign variants and no rate). r2's cmp126 table."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from b_helpers import R2_CREDIT, cl, k, run  # noqa: E402

COLS = (("story", 208), ("shown", 456), ("cond", 264))  # 928 = 960 - 2 x 16
COND_OF = {"≥ 1 h": "ge1h", "< 1 h": "lt1h", "< 5 min": "lt5m", "elapsed, no fresh ticker": "elapsed",
           "clock alarm on, or offset unknown": "clock", "next funding time unknown": "unknown",
           "not trading": "suppressed", "stale or disconnected, time ahead": "ge1h"}


def rate_of(label: str) -> str:
    """The sign variants from the fixture's fundingRate (F6): as recorded, sign flipped (illustrative), zero."""
    fr = str(k.TICKER["fundingRate"])
    return k.funding_pct({"Positive": fr, "Negative": fr[1:] if fr.startswith("-") else "-" + fr.lstrip("+"),
                          "Zero": "0"}[label])


def shown(r: dict) -> k.Node:
    lab = r["label"]
    if lab in ("Positive", "Negative", "Zero"):
        v = rate_of(lab)
        assert v == r["rate"], (lab, v, r["rate"])
        return k.hbox(f"shown · {lab}", [k.text("rate", v, k.NUM, k.TEXT_1), k.countdown("ge1h")], {"gap": k.INSET_LG})
    if lab == "Settlement":
        return k.text("desc", r["desc"], k.CAPTION, k.TEXT_2, w=COLS[1][1] - 16)
    cond = COND_OF.get(r.get("cond", ""), "ge1h")
    cd = k.countdown(cond, stale=r.get("_band") == "stale")
    first, second = k.countdown_text(cond)
    assert first == r["v"] and (second or None) == r.get("v2"), (lab, first, r["v"])
    return cd


def row(i: int, r: dict) -> k.Node:
    stale = r.get("_band") == "stale"
    cond = r.get("cond") or r.get("illus") or ""
    sh = shown(r)
    cells = [k.cell("story", r["label"], COLS[0][1], h=1, typo=k.NUM, color=k.TEXT_1),
             k.cell("shown", sh, COLS[1][1], h=1),
             k.cell("cond", cond or None, COLS[2][1], h=1, typo=k.CAPTION, color=k.TEXT_2)]
    h = max(k._row_h(cells, "comfortable"), int(k.est_height(sh)) + 12)
    o = {"fill": f"{k.DC}.stale.surface"} if stale else None
    note = "inside the band's stale treatment: keeps counting, the target is a fixed time (§7)" if stale else None
    return k.vbox(f"row {i:02d} · {r['label']}", [k.hbox("cells", [dict(c, h=h) for c in cells], o, w=928, h=h),
                                                  k.rect("row rule", 928, 1, k.BORDER_SUBTLE)], None, w=928, h=h + 1,
                  note=note)


def build(theme: str = "dark"):
    key = f"15{'D' if theme == 'dark' else 'L'}"
    fr = k.frames_of(key)[0]
    t = k.R2_BOARDS[15]["cmp126"]
    head = k.hbox("header row", [k.cell(f"h{j}", hd, w, h=32, typo=k.LABEL, color=k.TEXT_2)
                                 for j, (hd, (_c, w)) in enumerate(zip(t["head"], COLS), 1)], None, w=928, h=32)
    rows = [row(i, r) for i, r in enumerate(t["rows"], 1)]
    table = k.vbox("CMP-126 states table", [head, k.rect("header rule", 928, 1, k.BORDER), *rows], None, w=928)
    need = k.est_height(table)
    frame = k.free_frame(fr, theme, [table], {"dir": "column", "align": "start", "pad": k.INSET_LG})
    k.live(f"frame 15: the table needs about {need:.0f} px of {fr.h - 32}; read back the last row (Zero) inside")
    k.live("the < 5 min row leads with the warning glyph in color.status.warning.strong; the InBandState row sits "
           "on color.data-confidence.stale.surface with digits in color.data-confidence.stale.text")
    lv = k.live_values()
    k.derived(f"≥ 1 h: {lv['cd']} = next_funding_time_ms - ts_ms floored to seconds ({k.to_go_s()} s) from the "
              f"recorded ticker; < 1 h / < 5 min use §7's {k.COUNTDOWN_S} s (L{k.L('next in 00:59:59')}, "
              f"L{k.L('settles in 00:04:12')})")
    k.derived(f"rates F6: fundingRate {k.TICKER['fundingRate']} -> {rate_of('Positive')}; Negative = the same with "
              f"the sign flipped ({rate_of('Negative')}, illustrative); Zero -> {rate_of('Zero')} (L{k.L('0.0000 %')})")
    k.derived(f"clock row: skew {k.CLOCK_SKEW_MS} ms is §7's example (L{k.L('Clock skew 612 ms')})")
    blk = k.frame_block(fr, lines=[
        "Columns " + ", ".join(cl(h) for h in t["head"][:2]) + f", {t['head'][2]} (§7 L{k.L('| Condition')})",
        "Story names from the hand-off CMP-126 table: " + ", ".join(
            f"{r['label']} ({k.cite(r['label'])})" for r in t["rows"] if k.cite(r["label"])),
        cl("The digits update at most once a second"),
        cl("never negative, never a frozen 00:00:00"),
    ])
    ann = k.annotations(key, [blk, *[k.marker_block(m) for m in k.R2_BOARDS[15]["markers"]]], board_lines=[R2_CREDIT])
    illus = (f"the Negative row's {rate_of('Negative')} is the recorded rate with its sign flipped; the < 1 h and "
             f"< 5 min times are §7's examples (L{k.L('next in 00:59:59')}, L{k.L('settles in 00:04:12')})")
    return [frame], ann, illus


if __name__ == "__main__":
    th = sys.argv[1] if len(sys.argv) > 1 else "dark"
    frames, ann, illus = build(th)
    run(f"15{'D' if th == 'dark' else 'L'}", frames, ann, illustrative=illus,
        frames_info=["One table: story name | shown (CMP-126 drawn by the kit) | condition; 12 rows (r2 cmp126)"])

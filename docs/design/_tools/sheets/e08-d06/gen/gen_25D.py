"""Board 25D: SCR-103/not-recorded-non-owner-view-as (§15): SOLUSDT, two 480 × 1220 drawers — A: Manager or Viewer
(T2 rbac.owner_only, then the T3 sentence), B: the Owner viewing as alex (T2 rbac.view_as). Dark; its high-contrast
twin is gen_25H.py (same nodes). Run: python3 -I -B gen/gen_25D.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import c_helpers as c  # noqa: E402

k = c.k
KEY = "25D"
SYM = "SOLUSDT"
RULE_ROWS = {"Status": "status", "Tick size": "tick", "Quantity step": "step", "Minimum quantity": "minQty",
             "Maximum quantity, limit orders": "maxQty", "Minimum order value": "minNotional",
             "Maximum leverage": "maxLev", "Funding interval": "funding"}


def derivations() -> dict[str, str]:
    """Every number on the drawers, re-derived from instruments_after.json's SOLUSDT entry by the kit's §5 formatters;
    asserts r2's rows and examples equal them."""
    i, ru = k.INSTR[SYM], k.rules(SYM)
    f3 = f"§5 L{k.L('- **F3 Rule values')}"
    out: dict[str, str] = {}
    for it in k.D["bands"]["contract3"]["items"]:
        if it["_k"] == "row" and it["l"] in RULE_ROWS:
            want = ru[RULE_ROWS[it["l"]]]
            if it["v"] != want:
                raise ValueError(f"{it['l']}: r2 {it['v']!r} != derived {want!r}")
            if it["l"] != "Status":
                src = i[{"maxLev": "maxLev", "funding": "funding"}.get(RULE_ROWS[it["l"]], RULE_ROWS[it["l"]])]
                out.setdefault(want, f"{SYM} {RULE_ROWS[it['l']]} {src!r} in instruments_after.json -> {want} ({f3})")
    for unit, src in ((i["quote"], "quote"), (i["base"], "base")):
        out.setdefault(unit, f"{SYM} {src} coin {unit!r} (the unit column, §3)")
    near, down = c.round_to("148.1234", i["tick"], "nearest"), c.round_to("0.0019", i["step"], "down")
    ex = {"tick": f"Price must be a multiple of {ru['tick']} · 148.1234 → {near} (nearest)",
          "step": f"Quantity must be a multiple of {ru['step']} · 0.0019 → {down} (always down)",
          "notional": f"Order notional must be at least {ru['minNotional']} · 1.0 × {ru['step']} = "
                      f"{c.k.minimal(str(c.Decimal('1.0') * c.Decimal(i['step'])))} → refused",
          "lev": f"Leverage is set in steps of {ru['levStep']}"}
    drawn = [it["t"] for it in k.D["bands"]["contract3"]["items"] if it["_k"] == "ex"]
    if drawn != [ex["tick"], ex["step"], ex["notional"], ex["lev"]]:
        raise ValueError(f"examples {drawn} != derived {list(ex.values())}")
    if k.D["drawers"]["d25"]["identity"] != ru["identity"] or k.D["drawers"]["d25B"]["identity"] != ru["identity"]:
        raise ValueError("identity line != rules()['identity']")
    k.derived(f"examples re-derived with Decimal: 148.1234 to tick {i['tick']} nearest = {near} (§5 L"
              f"{k.L('148.1234 → 148.125')}); 0.0019 to step {i['step']} down = {down}; min notional "
              f"{ru['minNotional']}; leverage step {ru['levStep']}")
    k.derived(f"identity {ru['identity']!r}: base / quote, contract {i['contract']} -> "
              f"{k.CONTRACT_WORDS[i['contract']]!r} (§4.1), settle, launchTime {i['launch']} -> listed date (UTC)")
    return out


def build_parts(theme: str = "dark", key: str = KEY) -> tuple[list[k.Node], list[tuple[str, list[str]]]]:
    fa, fb = k.frames_of(key)
    frames = [k.drawer_frame(fa, theme, "d25"), k.drawer_frame(fb, theme, "d25B")]
    dv = derivations()
    ms = k.R2_BOARDS[25]["markers"]
    ma = [k.marker_block(m) for m in ms if not m["_at"].startswith("B:")]
    mb = [k.marker_block(m) for m in ms if m["_at"].startswith("B:")]
    t2, t3, va = k.T2_OWNER_ONLY, k.T3_SENTENCE, k.T2_VIEW_AS
    la = [f"§8 T2 sentence form: \"{t2}\" ({k.cite(t2)}), then the T3 sentence \"{t3}\" ({k.cite(t3)}) in place of "
          f"the hidden SCR-140 link; no lock glyph, no button, no aria-disabled (§8)",
          f"Recording \"○ Not recorded\" ({k.cite('○ Not recorded')}); live band = labelled placeholder rows (SOLUSDT "
          f"has no recorded ticker; nothing invented)",
          "Footer: Open in new chart, Open DOM ladder (both open a new panel, never the focused one)"]
    lb = [f"Owner viewing as alex: rbac.view_as \"{va}\" ({k.cite(va)}) in place of the owner-only sentence; then "
          f"\"{t3}\"; every other row follows the target's column (marker B:say:t2)",
          "Same values as frame A (the view-as read answers as the target)"]
    blocks = [k.frame_block(fa, lines=la), *ma, k.frame_block(fb, lines=lb), *mb,
              c.copy_block(frames, dv, max_line=300)]
    if any(n.get("color") == k.TEXT_LINK for f in frames for _p, n in k.walk(f)):
        raise ValueError("board 25 draws no link (T3 hides the SCR-140 link)")
    k.live("frame A: the recording band reads, in order, '○ Not recorded', 'Recorded data from' not available yet, "
           f"'Streams, last 90 days', \"{t2}\", \"{t3}\"; neither sentence is a button, link or aria-disabled control")
    k.live(f"frame B: the same band reads \"{va}\" where frame A reads \"{t2}\"; every other text equals frame A's")
    k.NOTES.add("sources", c.R2_CREDIT)
    return frames, blocks


def build(theme: str = "dark") -> tuple[list[k.Node], k.Node]:
    frames, blocks = build_parts(theme)
    k.live(c.CVD_LIVE)
    return frames, k.annotations(KEY, blocks, board_lines=[c.R2_CREDIT])


def main() -> None:
    frames, ann = build()
    p = k.write_sheet(KEY, frames, ann)
    md = k.write_md(KEY, p, frames_info=["A: r2 drawer d25 (Manager or Viewer); B: d25B (Owner viewing as alex)"])
    c.finish(KEY, p, md)


if __name__ == "__main__":
    main()

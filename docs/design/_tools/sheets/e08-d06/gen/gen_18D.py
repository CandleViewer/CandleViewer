"""Board 18D: SCR-103/precision-rules-examples (§5; minimal vs as delivered; one stacked 14-char qty; after
CR-8 / CR-11). r2's precision block; every number re-derived by the kit's §5 formatters."""
from __future__ import annotations

import sys
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from b_helpers import R2_CREDIT, cl, k, run, section, table  # noqa: E402

LW, RW = 560, 592  # 16 + 560 + 16 + 592 + 16 = 1200
P = k.R2_BOARDS[18]["precision"]
FIELDS = (("Tick size", "tick", "quote"), ("Quantity step", "step", "base"), ("Minimum quantity", "minQty", "base"),
          ("Maximum quantity, limit orders", "maxQty", "base"), ("Minimum order value", "minNotional", "quote"),
          ("Maximum leverage", "maxLev", None))


def nearest(price: str, tick: str) -> str:
    """Case 0: the nearest tick (none of these is a half-tick tie), shown at the tick's decimals, grouped (F4, F8)."""
    t = Decimal(tick)
    q = (Decimal(price) / t).quantize(Decimal(1), ROUND_HALF_EVEN) * t
    return k.group(k._plain(q.quantize(Decimal(1).scaleb(-k.decimals(tick)))))


def minimal_rows() -> list[list[str | None]]:
    i, ru, out = k.INSTR["BTCUSDT"], k.rules("BTCUSDT"), []
    for (lab, f, unit), r2 in zip(FIELDS, P["minimal"]["rows"]):
        row = [lab, ru[f], i[f], i[unit] if unit else None]
        assert row == r2, (row, r2)
        out.append(row)
    k.derived("minimal = F3 rule_value() of instruments_after.json's BTCUSDT strings; as delivered = those strings "
              f"(tick {i['tick']}, max qty {i['maxQty']}, leverage {i['maxLev']})")
    return out


def after_rows() -> list[list[str | None]]:
    lv = k.live_values()
    na = P["after"]["rows"][0][1]
    rows = [["24 h high", na, lv["high"], "USDT"], ["24 h low", na, lv["low"], "USDT"],
            ["Recorded data from", na, k.REC["started_at"], None]]
    assert rows == P["after"]["rows"], rows
    k.derived(f"after CR-8 / CR-11: high {lv['high']} / low {lv['low']} = F4 at_precision of the recorded "
              f"highPrice24h / lowPrice24h at tick {k.INSTR['BTCUSDT']['tick']}; {k.REC['started_at']} is 22's "
              "recording_started_at example")
    return rows


def tick_rows() -> list[list[str]]:
    out = []
    for r2 in P["ticks"]["rows"]:
        sym = r2[0].split(" ")[0]
        tick = k.minimal(k.INSTR[sym]["tick"]) if sym in k.INSTR else r2[1]
        pin, _arrow, _shown = r2[2].split(" ")
        shown = nearest(pin.replace(",", ""), tick)
        row = [r2[0], tick, f"{pin} → {shown}", str(len(shown))]
        assert row == r2, (row, r2)
        out.append(row)
    k.derived("tick cases: shown = the nearest multiple of the tick at the tick's decimals, grouped; Characters = "
              "len(shown); BTCUSDT / SOLUSDT / LUNAUSDT ticks from instruments_after.json, the others as §5 gives them")
    return out


def rule_rows() -> list[list[str]]:
    ru = k.rules("BTCUSDT")
    for r2, f in zip(P["rules"]["rows"], ("tick", "step", "minQty", "maxQty", "minNotional")):
        assert f" {ru[f]}." in r2[1], (r2[1], ru[f])
    assert nearest("50000.04", k.minimal(k.INSTR["BTCUSDT"]["tick"])) == "50,000.0"
    return [list(r) for r in P["rules"]["rows"]]


def f_list() -> dict:
    lv, ex = k.live_values(), {s for r in P["f"] for s in r[1:]}
    for v in (lv["last"], lv["index"], k.disk(k.REC["disk_bytes"]), lv["chg"].split(" ", 1)[1]):
        assert v in ex or any(v in s for s in ex), v
    k.derived(f"F4 {lv['last']} / {lv['index']}, F5 {lv['oi']}, F6 {lv['chg']}, F7 {k.disk(k.REC['disk_bytes'])}: "
              "the kit's formatters on the recorded snapshot and 22's disk example equal r2's F examples")
    rows = []
    for i, r in enumerate(P["f"], 1):
        exs = k.vbox("examples", [k.fit_text(f"ex {j}", s, k.NUM, k.TEXT_1, RW - 232 - 16) for j, s in
                                  enumerate(r[1:], 1) if s != "→"], {"gap": k.STACK_XS})
        rows.append([r[0], exs])
    return table("F1-F10", None, rows, [232, RW - 232], typos=[k.BODY_STRONG, k.NUM])


def stacked() -> dict:
    s = P["stacked"]
    v = k.group("50000000000")
    assert v == s["v"] and len(v) == 14
    box = k.vbox("CMP-036 Stacked", [k.cell("dt", s["label"], 432, h=24, color=k.TEXT_2),
                                     k.cell("dd", v, 432, h=24, end=True, typo=k.NUM)],
                 {"fill": k.OVERLAY}, w=432, note="CMP-036 Stacked: the value stacks under its label; digits are "
                 "never cut or ellipsised (§5 F8)")
    return section("stacked", s["title"], [box], LW)


def build(theme: str = "dark"):
    key = f"18{'D' if theme == 'dark' else 'L'}"
    fr = k.frames_of(key)[0]
    mh, ah = P["minimal"]["head"], P["after"]["head"]
    left = k.vbox("left column", [
        section("minimal", "minimal vs as delivered", [table("minimal vs as delivered", [*mh, ""], minimal_rows(),
                [264, 104, 112, 80], typos=[k.BODY, k.NUM, k.NUM, k.CAPTION], ends=[False, True, True, False],
                colors=[k.TEXT_2, k.TEXT_1, k.TEXT_1, k.TEXT_3])], LW),
        section("after", ah[1], [table("after CR-8 and CR-11", ["", *ah, ""], after_rows(), [168, 144, 168, 80],
                typos=[k.BODY, k.BODY, k.NUM, k.CAPTION], ends=[False, False, True, False],
                colors=[k.TEXT_2, k.TEXT_3, k.TEXT_1, k.TEXT_3]),
                k.text("illustrative", P["after"]["illus"], k.CAPTION, k.TEXT_2)], LW),
        stacked()], {"gap": k.STACK_LG}, w=LW)
    right = k.vbox("right column", [
        section("ticks", P["ticks"]["title"], [table("tick width cases", P["ticks"]["head"], tick_rows(),
                [248, 96, 168, 80], typos=[k.BODY, k.NUM, k.NUM, k.NUM], ends=[False, True, False, True])], RW),
        section("rules", P["rules"]["title"], [table("rule examples", P["rules"]["head"], rule_rows(),
                [136, 208, 248], typos=[k.BODY, k.BODY, k.CAPTION], colors=[k.TEXT_2, k.TEXT_1, k.TEXT_2])], RW),
        section("formatting", "Number formatting and precision rules", [f_list()], RW)], {"gap": k.STACK_LG}, w=RW)
    frame = k.free_frame(fr, theme, [left, right])
    need = max(k.est_height(left), k.est_height(right)) + 32
    k.live(f"frame 18: the taller column needs about {need:.0f} of {fr.h} px; read back that F10 ends inside")
    k.live("the Stacked value 50,000,000,000 reads whole (14 characters), end-aligned under its label")
    blk = k.frame_block(fr, lines=[
        "Sections: " + ", ".join(f"{t} ({k.cite(t) or '§5'})" for t in (
            P["ticks"]["title"], P["rules"]["title"], P["stacked"]["title"], P["after"]["head"][1])),
        *[f"Rule sentence {cl(r[1].split(chr(34))[1])}" for r in P["rules"]["rows"]],
        "Every frame string is verbatim in §5 or the hand-off (the generator refuses an uncited one)",
    ])
    ann = k.annotations(key, [blk, *[k.marker_block(m) for m in k.R2_BOARDS[18]["markers"]]], board_lines=[R2_CREDIT])
    illus = (f"the after CR-8 / CR-11 column (L{k.L('after CR-8 / CR-11')}) and the two computed tick rows "
             "(not recorded instruments)")
    return [frame], ann, illus


if __name__ == "__main__":
    frames, ann, illus = build("dark")
    run("18D", frames, ann, illustrative=illus,
        frames_info=["Left: minimal vs as delivered, after CR-8 / CR-11, Stacked; right: tick cases, rule examples, "
                     "F1-F10"])

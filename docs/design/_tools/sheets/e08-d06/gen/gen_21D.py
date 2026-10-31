"""Board 21D: SCR-103/keyboard-focus-order (§10.1). Board 1's drawer (d01) with the ring on the first Tab stop beside
§10.1's key table and the Tab order the drawer has in this state."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from b_helpers import R2_CREDIT, cl, k, lean_cell, run, section, size_rings, table  # noqa: E402

RW = 472  # 16 + 480 + 16 + 472 + 16 = 1000
B = k.R2_BOARDS[21]
HEAD = ["Key", "Where", "Action", k.D["copy"]["focusAfter"]]


def order_names() -> list[str]:
    """r2's _order mapped to the controls' visible names (D copy), then the trap back to Close."""
    c = k.D["copy"]
    names = {"close": "Close", "link": c["settings"]}
    out = [names.get(o) or o.split(":", 1)[1] for o in B["_order"]]
    return out + ["Close (trapped)"]


def build(theme: str = "dark"):
    key = f"21{'D' if theme == 'dark' else 'L'}"
    fr = k.frames_of(key)[0]
    drawer = size_rings(k.drawer("d01", h=1360, focused="close"))
    keys = table("§10.1 keys", HEAD, [list(r) for r in B["keys"]], [104, 112, 152, 104],
                 typos=[k.NUM, k.CAPTION, k.CAPTION, k.CAPTION], colors=[k.TEXT_1, k.TEXT_2, k.TEXT_1, k.TEXT_2],
                 rules=False)
    steps = []
    for i, nm in enumerate(order_names(), 1):
        steps.append(lean_cell(f"step {i}", [k.text("n", str(i), k.NUM, k.TEXT_2), k.text("control", nm)], RW, h=24))
    order = section("tab order", "Tab, Shift+Tab", [k.vbox("steps", steps, {"gap": k.STACK_XS}, w=RW)], RW)
    right = k.vbox("right column", [keys, order], {"gap": k.STACK_LG}, w=RW)
    frame = k.free_frame(fr, theme, [drawer, right])
    need = k.est_height(right) + 32
    k.live(f"frame 21: the right column needs about {need:.0f} of {fr.h} px; the drawer is 1360 tall at y 16")
    k.live("the focus ring sits on Close only")
    k.derived(f"Tab stops in this state: {len(order_names()) - 1} controls (r2's _order) "
              "then the trap back to Close")
    blk = k.frame_block(fr, lines=[
        f"Drawer: board 1's d01 at 480 × 1360; the ring is on \"Close\" (L{k.L('Close → band actions')}), "
        "the first Tab stop after the title",
        "Table: §10.1 rows verbatim, backticks dropped (L" + str(k.L("### 10.1 Keys")) + ")",
        f"Order: §10.1's Tab row (L{k.L('Close → band actions')}), quoted in full in the block at close",
        cl("Recorder settings nor Record in the Tab order"),
    ])
    ann = k.annotations(key, [blk, *[k.marker_block(m) for m in B["markers"]]], board_lines=[R2_CREDIT])
    return [frame], ann


if __name__ == "__main__":
    frames, ann = build("dark")
    run("21D", frames, ann, allow_uncited=["Close"],
        frames_info=["Left: d01 with the ring on Close; right: §10.1 keys table + the Tab order"])

"""Board 09 `E47-D07 / 09 transcript-preview` (dark): §10 — the three transcripts as the content of E47-D05's board-07
announcement tile (its DoD), not a second tile: SCR-117 scrolled to Announcements, E47-D05's rows as placeholders,
the tile's list holding each script's expected lines."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k  # noqa: E402

NN = 9
S10 = k.L("## 10. Transcripts")
HEADS = {"quiet": "### 10.1 ", "fast": "### 10.2 ", "incident": "### 10.3 "}
TILE_IN = k.TILE_W - 32


def title_of(sid: str) -> tuple[str, int]:
    ln = k.L(HEADS[sid])
    t = k.plain(k.SPEC_LINES[ln - 1])[len(HEADS[sid]):]
    return re.sub(r"\)(:.*)?$", ")", t), ln


def tile(sid: str) -> dict:
    t, _ln = title_of(sid)
    btn = k.button(k.PLAY_LABEL, name=f"button · {k.PLAY_LABEL}")
    items = []
    for j, x in enumerate(k.SCRIPTS[sid]["expected"], 1):
        items.append(k.vbox(f"li {j}", [
            k.text("meta", f"{k.secs(x['t'])} s · {x['channel']} · {x['rows']}", k.NUM_SM, k.TEXT_2),
            k.text("line", x["text"], k.CAPTION, k.TEXT_1, w=TILE_IN)], {"gap": k.STACK_XS},
            w=TILE_IN))
    ul = k.vbox("ul · transcript", items, {"gap": k.STACK_SM}, w=TILE_IN,
                note="a plain list, never a live region; played to the end (E47-D05 §6.3)")
    return k.vbox("CMP-228 tile · announcements (E47-D05's)", [
        k.text("script", t, k.LABEL, k.TEXT_1, w=TILE_IN), btn, ul],
        {"gap": k.STACK_SM, "pad": k.INSET_LG, "fill": k.RAISED, "radius": k.R_CARD, "stroke": k.BORDER,
         "strokeWidth": k.HAIR, "strokeAlign": "inner"}, w=k.TILE_W,
        note=f"E47-D05's board-07 tile with E47-D07's content: the {sid} script's expected lines (§10)")


def build_frame(fid: str, sid: str) -> dict:
    k.fallback("chrome")
    rows = k.vbox("E47-D05's announcement rows (placeholders)", [
        k.text("h2", k.SECTION_NAME, k.HEADING_SM, k.TEXT_1),
        *[k.placeholder(f"row {i}", k.ROWS_W - 40 * (i % 2), 40) for i in range(1, 6)]],
        {"gap": k.STACK_LG}, w=k.ROWS_W)
    tl = tile(sid)
    h = k.est_height(tl)
    if h > k.BODY_H - 48:
        raise SystemExit(f"board 09: the {sid} tile ({h:.0f} px) outruns the viewport")
    content = k.hbox("SCR-117 content", [rows, tl], {"gap": k.INSET_XL, "align": "start", "pad": k.INSET_XL,
                                                    "fill": k.APP}, w=k.CONTENT_W)
    return k.window(k.frame_name(fid), content, overlays=[k.synthetic_tag(k.SHELL_TAG_X, k.FRAME_H - 40)],
                    note="SCR-117 scrolled to Announcements; the tile played to the end")


def main() -> None:
    b = k.BOARDS[NN]
    sids = [k.frame_state(f).split("/")[1] for f in b.frames]
    if sids != list(HEADS):
        raise SystemExit(f"board 09: §H's frames {sids} != the three scripts")
    frames = [build_frame(f, s) for f, s in zip(b.frames, sids)]
    blocks = []
    for f, s in zip(b.frames, sids):
        t, ln = title_of(s)
        n = len(k.SCRIPTS[s]["expected"])
        blocks.append((f, [f"§10 L{ln}: {t}; {n} lines, the transcripts' expected lines verbatim (the tool's replay "
                           f"equals them), seed {k.SEED}",
                           "channel words: polite / assertive / focus (the auto-flatten dialog's focus speech, §9)"]))
    blocks[0][1].insert(0, f"§10 L{S10}: the transcripts replace E47-D05 board 07's bracketed class names (D05:218); "
                           "this board is content for that tile, not a second tile (BQ-14 rider)")
    k.ambiguity("Board 09: the tile's line layout (time · channel · rows over the words) is the kit's; E47-D05's "
                "tile (its §6.3) owns the frame, the button and the list semantics")
    p, md, pk = k.build(NN, frames, blocks, per_row=3)
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()

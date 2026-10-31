"""Board 25 high contrast (key 25H): the second twin under the cap (ruling 2026-10-31: 1L + this one).
Same frames, same nodes and values as 25D (gen_25D.build_parts), token-bound; the token theme `high-contrast` is
switched at export (nothing painted). Theme word "hc"; root "… · high contrast"; export §15's pattern with "-hc".
Run: python3 -I -B gen/gen_25H.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import c_helpers as c  # noqa: E402
import gen_25D as base  # noqa: E402

k = c.k


def hc_lines() -> list[str]:
    bar = k.L("High contrast holds body text to 7:1")
    rows = [("`text.primary` on `surface.overlay`", "values"), ("`text.secondary` on `surface.overlay`", "labels"),
            ("`text.tertiary` on `surface.overlay`", "units, examples")]
    out = [f"§13 hc column, as computed in the spec: " + "; ".join(
        f"{r.replace('`', '')} ({use}) {k._cells(k.SPEC_LINES[k.L(r) - 1])[3]} (L{k.L(r)})" for r, use in rows)
        + f"; hc holds body text to 7:1 (L{bar})",
        f"H-8 (L{k.L('**H-8 E47-D03')}): text.link on surface.overlay is 6.15 in hc; this board draws no link (T3 hides "
        f"the SCR-140 link), so no pair here misses the 7:1 bar",
        f"Spec line 3 (L{k.L('high contrast by table')}): high contrast by table; this board is the one drawn hc twin "
        f"(ruling 2026-10-31)"]
    return out


def main() -> None:
    with c.hc_registered(25) as hb:
        frames, blocks = base.build_parts(c.HC_THEME, key=hb.key)
        ann = c.hc_annotations(hb, blocks, board_lines=[c.R2_CREDIT, *hc_lines()])
        k.live(f"export with the {c.HC_TOKEN_THEME} theme, then read back color.text.secondary on "
               f"color.surface.overlay in the PNG at about the §13 hc ratio (>= 7:1); restore the dark theme after")
        k.deviate(f"no hc twin is listed in §15 (twins are 1-17 light); the root and the export follow §15's pattern "
                  f"with \"high contrast\" / \"-hc\" (ruling 2026-10-31); grid slot is the twin rows' "
                  f"({k.grid_xy(hb.key)[0]}, {k.grid_xy(hb.key)[1]})")
        p = k.write_sheet(hb.key, frames, ann)
        sh = c.json.loads(p.read_text(encoding="utf-8"))["board"]
        x, y = k.grid_xy(hb.key)
        summary = (f"Board 25 high contrast (§15 L{hb.line}: {hb.content}). Grid ({x}, {y}); {sh['w']} x {sh['h']} "
                   f"px; footer \"page {k.PAGE} · board 25 high contrast · {k.REV}\".")
        md = k.write_md(hb.key, p, summary=summary,
                        frames_info=["same frames and values as 25D; hc theme at export"])
    c.finish(hb.key, p, md)


if __name__ == "__main__":
    main()

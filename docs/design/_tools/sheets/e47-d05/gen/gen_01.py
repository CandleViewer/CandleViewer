"""Board 01 `E47-D05 / 01 scr117-default` (dark): §2, §3, §4 — every row with its label, description and (tri-states)
Effective line, the sources in words, the four tiles, the links. build_frame(theme) is reused by board 02 (light)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import full_window, k  # noqa: E402

NN = 1


def build_frame(theme: str) -> tuple[dict, int]:
    fid = k.BOARDS[NN].frames[0].replace("dark", theme)
    return full_window(fid, k.PS(theme=theme), note=f"SCR-117/default · {theme}: every row at its default")


def blocks(fid: str, need: int, theme: str) -> list[tuple[str, list[str]]]:
    st = k.STATES["SCR-117/default"]
    lines = [
        f"§10 L{st['line']} SCR-117/default: {st['shows']}",
        f"§2 L{k._S2 + 2}: one h1 \"{k.H1}\" (the shipped h2 is D05-G3), W-1, the scope line W-2, the settings search, "
        f"then {', '.join(k.SECTION_ORDER)} and {k.HELP_SECTION}; one column, max-width 60 rem",
        f"§4 L{k.L('## 4. Option rows')}: each row's label (W-3 … W-10 where shipped) and its PROPOSED description "
        "(D05-G1), the description the row's aria-describedby target (R-1)",
        f"§5.1 L{k._S51}: the two tri-states read \"{k.effective(k.PS(theme=theme), 'reduced_motion')[1]}\" — the OS "
        "reports no preference, so no OS signal: the product default (W-14); the source in words, never colour (R-3)",
        f"§3 L{k.L('## 3. The preference key list')}: 11 keys, 3 PROPOSED (always_show_focus_ring, larger_hit_targets, "
        "announce_throttle_s); the cadence row is hidden until Always is chosen (§7.1)",
        f"§6: the tiles sit to the right of their group at 1280 px, idle on arrival (no loop until focus or the "
        f"pointer enters the group, §13.2 L{k.L('### 13.2 Performance')})",
        f"§9 L{k.L('## 9. Link-outs')}: W-21 and W-23 are real links underlined in color.text.link; W-22 a button "
        "(aria-haspopup=\"dialog\") opening SCR-013",
        f"The page is about {need} px: drawn at its full scroll length, the 800 px fold marked (FALLBACKS full-length)",
    ]
    return [(fid, lines)]


def main() -> None:
    k.section_reading_note()
    fr, need = build_frame("dark")
    p, md, pk = k.build(NN, [fr], blocks(k.BOARDS[NN].frames[0], need, "dark"), per_row=1,
                        full_length=k.BOARDS[NN].frames)
    print(p.name, md.name, pk.name, need)


if __name__ == "__main__":
    main()

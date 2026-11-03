"""Board 10 `E47-D05 / 10 keyboard-order-150` (dark): §12 — the Tab and reading order numbered on the page at 150 %
text scale (the tiles stacked under their groups, §11), drawn at its full scroll length."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import full_window, k  # noqa: E402

NN = 10
# §12's order at the defaults: nav, the search, each section's controls top to bottom with the tile's button, then
# the Help links and the cheatsheet button (Reset / Reset this section appear only when modified, so not here)
STOPS = ["nav", "search", "reduced_motion", "disable_canvas_animation", "tile:Motion", "increased_contrast",
         "thick_focus_ring", "always_show_focus_ring", "always_show_tables", "announce_prices", "verbosity",
         "tile:Announcements", "keyboard_only", "larger_hit_targets", "link:statement", "link:shortcuts", "cheatsheet"]


def stop_words(s: str) -> str:
    if s == "nav":
        return f"SettingsNav \"{k.H1}\""
    if s == "search":
        return f"\"{k.SEARCH_LABEL_GAP}\""
    if s.startswith("tile:"):
        return "Pause (motion tile)" if s == "tile:Motion" else "Play sample (announcement tile)"
    if s.startswith("link:"):
        return k.w("W-21") if s == "link:statement" else k.w("W-23")
    if s == "cheatsheet":
        return k.w("W-22")
    return k.ROWS[s]["label"]


def main() -> None:
    k.section_reading_note()
    b = k.BOARDS[NN]
    ps = k.PS(sc=k.Scale(1.5), motion_running=True, markers=tuple((s, i + 1) for i, s in enumerate(STOPS) if s != "nav"))
    nav_mark = k.marker(1, k.NAV_W + k.SET_NAV_W - 36, k.TOP_H + 8 + 2 * 32 + 8, name="stop 1 · SettingsNav")
    fr, need = full_window(b.frames[0], ps, overlays=[nav_mark],
                           note="150 % text scale; the page at its full scroll length")
    s12 = k.L("## 12. Keyboard model")
    order = "; ".join(f"{i + 1} {stop_words(s)}" for i, s in enumerate(STOPS))
    lines = [
        f"§12 L{s12}: Tab order — {order}",
        "Initial focus: from a SettingsNav click it stays on the entry (stop 1); from a deep link or reload it goes to "
        "the h1 (tabindex=\"-1\", out of the Tab order)",
        "A RadioGroup is one stop (arrows move a roving tabindex, `15`:108); a Toggle is role=\"switch\", Enter / Space "
        "toggles (`15`:87); Enter in the search does nothing beyond the field",
        "The motion tile's Pause shows because the loop runs while focus is in its group (§13.2); the cadence row is a "
        "stop only when Always is chosen; each Reset and Reset this section slot in after their control when shown",
        f"Reading order = DOM order: h1, W-1, W-2, the search, each section (h2, rows, tile), Help and statement",
        f"§11 L{k.L('## 11. Themes, text scale')}: at 150 % labels and descriptions wrap and each tile stacks under its "
        f"group; the page is about {need} px, drawn at full length with the 800 px fold marked",
        "Shell stops (TopBar, NavRail) precede stop 1 and are the shell's; numbered markers are annotation",
    ]
    p, md, pk = k.build(NN, [fr], [(b.frames[0], lines)], per_row=1, full_length=b.frames)
    print(p.name, md.name, pk.name, need)


if __name__ == "__main__":
    main()

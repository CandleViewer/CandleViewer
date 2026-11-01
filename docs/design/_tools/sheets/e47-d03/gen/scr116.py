"""Shared SCR-116 frame builders for boards 01-05 (E47-D03 §8)."""
from __future__ import annotations

import sys
from pathlib import Path

GEN_DIR = Path(__file__).resolve().parent
for _p in (GEN_DIR, GEN_DIR.parent):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import e47d03kit as k  # noqa: E402

S31 = "### 3.1 Chrome"
S34 = "### 3.4 The proposed"


def default_frame(fid: str, theme: str, *, preset: str = "Blue", warning: bool = False, focus: str | None = "Theme",
                  selected_row: bool = False) -> dict:
    ch = k.Choice(theme=theme, preset=preset, warning=warning, focus=focus, selected_row=selected_row)
    page = k.scr116_page(ch)
    need = k.est_height(page)
    if need > k.BODY_H:
        raise ValueError(f"{fid}: the page is about {need:.0f} px for {k.BODY_H}")
    return k.window(k.frame_name(fid), theme, page,
                    note=f"SCR-116 · {theme}; preview {k.preview_name(theme, preset)}")


def common_lines(theme: str) -> list[str]:
    tw = (theme,)
    return [
        k.keys_line(),
        f"Structure (§8.1 L{k.L('Structure: one `h1`')}): one h1, each FormSection a labelled group under its own "
        f"heading, the PreviewTile after the controls in DOM order",
        k.cr_line("body text on the app", S31, tw),
        k.cr_line("tertiary text on a panel", S31, tw),
        k.cr_line("focus colour on the app", S31, tw),
        k.cr_line("control boundary on the app (F-9)", S31, tw)
        + "; drawn with color.border.strong as it resolves today: D03-D3 / D03-D4 raise it (§3.4)",
        f"Accent {k.PRESETS[0]} ({theme}): {k.acc(theme, 'Blue')}:1 lowest over app, canvas, panel, drawer and "
        f"selected row (§8.2 L{k.PRESET_ROWS['Blue'][1]}); warning in this theme: "
        f"{'yes' if k.acc_warns(theme, 'Blue') else 'no'}",
        f"PreviewTile name (W-19 pattern): \"{k.preview_name(theme, 'Blue')}\"; caption W-20 \"{k.w('W-20')}\"",
        f"Analytics (§12 L{k.L('## 12. Analytics')}): nothing on load (J16)",
    ]

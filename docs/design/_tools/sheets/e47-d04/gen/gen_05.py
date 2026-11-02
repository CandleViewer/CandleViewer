"""E47-D04 / 05 dialog-flatten: the flatten-all ConfirmDialog: the trap, Cancel initial, and the restore to the
TopBar's FLATTEN ALL on Esc and on completion (§9)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k, bodies  # noqa: E402

NN = 5
F_OPEN, F_RESTORE = k.frames_of(NN)
L91, L92 = k.L("### 9.1 Initial focus per dialog type"), k.L("### 9.2 Lifetime, dismissal and restore")
L_FLAT = k.L("- **Flatten all (T AC5).**")
TITLE = "Flatten all positions — all accounts"  # E39-D03 S1, the control's accessible name (copy gap: see notes)


def frame_open() -> tuple[k.Node, tuple[str, list[str]]]:
    k.copy_gap(f'dialog title "{TITLE}": E39-D03 §10 S1 (the FLATTEN ALL control\'s accessible name); E47-D04 '
               "names the dialog only as \"the flatten-all ConfirmDialog\" (§0) and E39-D01 owns its copy")
    body = [k.placeholder(f"consequence line {i}", 380 if i < 3 else 240, 12) for i in (1, 2, 3)]
    cancel = k.button("Cancel", "secondary", focused="normal", name="Cancel (initial focus)")
    confirm = k.button("Confirm", "destructive", name="Confirm (destructive)")
    dlg = k.dialog(TITLE, [k.vbox("description", body, {"gap": k.STACK_SM}, h=52)], [cancel, confirm],
                   name="CMP-044 alertdialog · flatten all")
    ovl, (dx, dy, dw, dh) = k.modal(dlg)
    by = dy + dh - 24 - 26  # the actions row (estimate; the live check re-centres)
    cx = dx + dw - 24 - confirm["w"] - 8 - cancel["w"]
    ov = [ovl, k.marker(1, cx + 4, by - 26, name="trap 1 · Cancel"),
          k.marker(2, dx + dw - 24 - confirm["w"] + 4, by - 26, name="trap 2 · Confirm"),
          k.tag("Tab from 2 wraps to 1; Shift+Tab from 1 wraps to 2 (trap)", dx, dy + dh + 8),
          k.tag("page inert behind the scrim; ring keys inert", dx, dy - 24),
          k.tag("invoker · FLATTEN ALL", k.flatten_x(), 50)]
    fr = k.workspace_window(F_OPEN, bodies(), overlays=ov,
                            note="the flatten-all confirm open over the workspace; focus on Cancel")
    lines = [f"§9.1 L{L91}: destructive confirm (alertdialog: flatten all, ...): initial target Cancel (`15`:525); "
             "never Confirm (R-6)",
             f"§9.2 L{L92} Trap: while open Tab and Shift+Tab cycle inside; the page is inert; ring keys are inert",
             f"§9.2 L{L_FLAT}: opened from the TopBar's FLATTEN ALL control (`14`:302) or its hotkey: CMP-044 "
             "alertdialog, Cancel initial, trapped for its whole lifetime",
             "A blocking dialog: a scrim click does nothing and focus stays inside (A11Y-F-0013)",
             k.arch("Announcements", "dialog"),
             "The body's consequence copy is E39-D01's (drawn as placeholders); the LIVE typed confirm (E39-D03) is "
             "not this board's subject",
             "QA-2 (hand-off §G): 20 Tab presses stay inside; the first focused is Cancel"]
    return fr, k.frame_block(F_OPEN, lines, keyboard="Tab / Shift+Tab cycle Cancel ↔ Confirm; Esc or Cancel closes")


def frame_restore() -> tuple[k.Node, tuple[str, list[str]]]:
    flat = k.button(k.FLATTEN, "destructive", focused="normal", name="FLATTEN ALL (restored)")
    ov = [k.callout("restore", ["Esc or Cancel: the dialog closes, focus returns to FLATTEN ALL.",
                                "On completion: the dialog closes, focus returns to FLATTEN ALL and the outcome is "
                                "announced in the assertive region."], 760, 70, 360)]
    fr = k.workspace_window(F_RESTORE, bodies(), flatten=flat, overlays=ov,
                            note="after Esc, Cancel or completion: focus on the TopBar's FLATTEN ALL")
    lines = [f"§9.2 L{L_FLAT}: Esc or Cancel closes it and focus returns to FLATTEN ALL; on completion the dialog "
             "closes, focus returns to FLATTEN ALL and the outcome is announced in the assertive region",
             f"Opened by its hotkey from a panel, it restores to the element that held focus (§9.2 L{L_FLAT})",
             f"{k.rule('R-7')}; the fallback when the invoker is gone is chosen by R-4",
             k.arch("Announcements", "dialog"),
             "QA-2 (hand-off §G): after Esc and after completion focus is FLATTEN ALL"]
    return fr, k.frame_block(F_RESTORE, lines, keyboard="Esc / Cancel / completion → FLATTEN ALL")


def build(theme: str = "dark") -> None:
    del theme
    fr = [frame_open(), frame_restore()]
    k.build_all(NN, [f for f, _b in fr], k.annotations(NN, [b for _f, b in fr]))


if __name__ == "__main__":
    build()

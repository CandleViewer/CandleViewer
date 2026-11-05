"""Board 08 scr033-validation-source-unavailable: SCR-033/no-row-selected, -threshold-invalid,
-source-unavailable (T2 2a), -view-as (T2 2a), -apply-no-write (T2 2a) (§6.5, §1.4)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import ui  # noqa: E402
from ui import k  # noqa: E402

NN = 8
MW = 248
OI = "OI Δ"


def rows(enabled: tuple[str, ...] = ui.DEFAULT, **per: dict) -> list[ui.R]:
    return [ui.R(lab, on=lab in enabled, **per.get(lab, {})) for lab in ui.list_order(enabled)]


def no_row() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-033/no-row-selected"
    w12 = k.W("W-12")
    rs = [ui.R(lab, on=False) for lab in ui.list_order()]
    return ui.dialog(fid, rs, apply="invalid", message=w12, markers=[
        ui.announce(w12, how='polite, once, on the last uncheck (role="status")', w=MW)]), k.frame_block(fid, [
        "Every checkbox cleared: Apply is disabled as form validity, not T2 (§1.4; 14:870 \"at least one row "
        "selected\"): no lock and no reason key; it stays focusable with aria-disabled=\"true\" and W-12 as its "
        "aria-describedby; a press changes nothing and re-announces W-12",
        "W-12 names \"Hide Deep Stats\", the explicit action (MEMO C10, A5)"])


def invalid() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-033/threshold-invalid"
    bad_pct, bad_unit = "140", k.ui("4o0", "a synthetic mistyped entry (not a number)")
    rs = rows(**{"Delta": {"expanded": (k.S("abs >"), bad_unit), "invalid": k.W("W-29", row="Delta", unit="BTC"),
                           "focus": "field"},
                 "Delta %": {"expanded": (k.S("abs >"), bad_pct), "invalid": k.W("W-13", row="Delta %")}})
    return ui.dialog(fid, rs), k.frame_block(fid, [
        f"A percent bound outside 0–100 ({bad_pct}) shows W-13; a unit-row bound that is not a number or is outside "
        f"E20-S03's bounds shows W-29; each under its field, naming its row (§6.5)",
        "The field gets aria-invalid and is described by its message, shown on blur and on Apply; Apply stays "
        "enabled and focus moves to the first invalid field on press (Delta's, drawn focused)"])


def unavailable() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-033/source-unavailable"
    w14 = k.W("W-14")
    rs = rows(**{OI: {"t2": w14, "focus": "t2"}})
    k.decide(f"{OI}'s source is absent for the synthetic {k.SYM} session on this frame (the state is the source's "
             f"absence; no real symbol is claimed to lack open interest)")
    return ui.dialog(fid, rs, scroll_to_end=True, markers=[
        ui.acc_name("the checkbox, as heard", f"{OI}, checkbox, not checked, unavailable, {w14}", w=MW),
        ui.announce(w14, how="polite, once, when Space re-shows it", w=MW)]), k.frame_block(fid, [
        f"On a symbol without open interest the {OI} row stays in the list, T2 rendering 2a inline (§1.4; MEMO G8); "
        f"never silently hidden (E20.json:394)",
        f"Its checkbox keeps its native role and full label \"{OI}\" (G-T2.1a), aria-disabled=\"true\", never "
        f"disabled, in the roving row (G-T2.1b); the W-14 node is in the DOM at mount, linked by aria-describedby "
        f"(G-T2.1c); CMP-079 RbacGate wraps it, CMP-019 lock (\"Not available\") leads the label (G-T2.1d)",
        "Look (E09-D09 §2.1): color.surface.raised + a color.border.default hairline, label and lock "
        "color.text.tertiary, the reason its own line in color.text.secondary; never color.text.disabled or "
        "opacity.disabled, in every theme (forced colours: R2)",
        f"The reason key {k.S('deepstats.source_unavailable')} is PROPOSED, E17-D01 the vocabulary owner; W-14 is "
        f"that owner's to word", k.source_line(OI)])


def view_as() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-033/view-as"
    w17 = k.W("W-17", user=k.VIEW_AS_USER)
    return ui.dialog(fid, rows(**{"Delta": {"focus": "row"}}), apply="t2", view_as=w17, markers=[
        ui.acc_name("Apply, as heard", f"{k.S('Apply')}, button, unavailable, {w17}", w=MW)]), k.frame_block(fid, [
        "View-as is checked first (§1.4): one notice in the dialog header (R32:57) carries W-17 (rbac.view_as, "
        "E09-D09:95), Apply's aria-describedby target; Apply is T2 2a with the CMP-019 lock",
        "Every row control stays operable as a preview; nothing is saved",
        "Without workspaces:write the same rendering takes rbac.permission or rbac.owner_only (PROPOSED, D02-OQ2): "
        "SCR-033/apply-no-write"])


def apply_no_write() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-033/apply-no-write"
    why = k.ui("Your role can't save workspaces.", "E09-D09 rbac.permission with its verb \"save workspaces\" "
               "(E09-D09:89, :114); rbac.owner_only by the chooser if no non-owner role holds workspaces:write; "
               "PROPOSED, D02-OQ2")
    return ui.dialog(fid, rows(**{"Delta": {"focus": "row"}}), apply="t2", apply_reason=why, markers=[
        ui.acc_name("Apply, as heard", f"{k.S('Apply')}, button, unavailable, {why}", w=MW)]), k.frame_block(fid, [
        "Without workspaces:write (22:10588) Apply is T2 rendering 2a (§1.4): CMP-079 RbacGate, the CMP-019 lock "
        "leading the full label, the reason under Apply as its aria-describedby target, in the DOM at mount",
        "The reason key is rbac.permission or rbac.owner_only by E09-D09 §3.1's chooser, verb \"save workspaces\" "
        "(E09-D09:114); PROPOSED, D02-OQ2 (is Apply a template save?)",
        "Every row control stays operable as a preview; Enter or Space on Apply changes nothing and re-shows the "
        "reason with one polite announcement"])


if __name__ == "__main__":
    ui.run(NN, [no_row(), invalid(), unavailable(), view_as(), apply_no_write()], 2)

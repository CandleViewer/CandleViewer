"""Board 09 `E47-D08 / 09 safety-static` (dark + hc): §11 under reduce — every safety signal identifiable by its icon
and its word, none animated: the env banner (CMP-074) and badge (CMP-075), the freeze banner (CMP-117), the arm toggle
read-only as T2 (CMP-229; §12, E09-D09 rendering 2a), the kill-switch engaged pill (CMP-211) and the status-bar
kill-switch word and rule count (CMP-208). The hc twin is the same builder; the theme is the token set at export."""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import FOCUS_SYMBOL, chart_body, k  # noqa: E402

NN = 9
CAT = k._git_show(k.BASE_SHA, "docs/plan/15-component-catalogue.md")
E10 = k._git_show(k.BASE_SHA, "docs/design/E10/E10-D03.md")
KS_LN = k.find_line('| FREEZE… engaged pill', E10)
KS_PILL = re.search(r'"(Kill switch: engaged · \d+ account)"', E10[KS_LN - 1]).group(1)
OPEN_LN = k.find_line("open-ended (`until` NULL:", CAT)
OPEN_TXT = re.search(r'open-ended \(`until` NULL: "([^"]+)"\)', CAT[OPEN_LN - 1]).group(1)
ARM_LN = k.find_line('LOCKED (neutral pill, lock glyph, "LOCKED · {account}', CAT)
ARM_TPL = re.search(r'"(LOCKED · \{account\} · \{size\} \{coin\})"', CAT[ARM_LN - 1]).group(1)
ARM_NAME = re.search(r'\("(Chart trading: locked)";', CAT[k.find_line('"Chart trading: locked"', CAT) - 1]).group(1)
SAFE = {s["signal"]: s for s in k.SAFETY}
RULES_ARMED = 2  # synthetic count


def banner_env() -> k.Node:
    return k.hbox("CMP-074 EnvBanner · LIVE", [k.env_glyph("live"), k.text("word", "LIVE", k.BODY_STRONG, k.TEXT_1),
                                               k.text("what", "Trading environment: Live", k.CAPTION, k.TEXT_2)],
                  {"gap": k.INSET_SM, "padX": k.INSET_LG, "fill": k.RAISED, "stroke": k.ENV_LIVE,
                   "strokeWidth": k.THICK, "strokeAlign": "inner"}, w=k.MAIN_W, h=32,
                  note='role="status"; the word always rendered (`15` CMP-074); static in every tier (§11)')


def banner_freeze() -> k.Node:
    return k.hbox("CMP-117 RiskLockoutBanner · FROZEN", [
        k.icon("lock", "locked", k.TEXT_1, note='CMP-019 Icon lock'),
        k.text("word", "FROZEN", k.BODY_STRONG, k.TEXT_1),
        k.text("reason", OPEN_TXT, k.BODY, k.TEXT_1)],
        {"gap": k.INSET_SM, "padX": k.INSET_LG, "fill": k.DANGER_SUBTLE, "stroke": k.DANGER_STRONG,
         "strokeWidth": k.HAIR, "strokeAlign": "inner"}, w=k.MAIN_W, h=36,
        note='named role="region"; appears as a cut; never dismissible while it holds (`15` CMP-117)')


def arm_t2() -> k.Node:
    label = k.fill_slot(k.fill_slot(k.fill_slot(ARM_TPL, "{account}", "Main"), "{size}", "0.010"), "{coin}", "BTC")
    pill = k.hbox("CMP-229 ArmToggle · read-only (T2)", [
        k.icon("lock", "locked", k.TEXT_3, note='CMP-019 Icon lock, decorative=false, name "Not available"'),
        k.text("label", label, k.LABEL, k.TEXT_3)],
        {"gap": k.INSET_XS, "padX": k.INSET_SM, "radius": k.R_CONTROL, "fill": k.RAISED, "stroke": k.BORDER,
         "strokeWidth": k.HAIR, "strokeAlign": "inner"}, h=24,
        note=f'aria-pressed switch "{ARM_NAME}", aria-disabled="true" (never disabled), in the Tab order; CMP-079 '
             'RbacGate rendering 2a; never opacity.disabled (§12)')
    reason = k.text("reason · W-12", k.T2_VERB, k.CAPTION, k.TEXT_2,
                    note="the reason node in the DOM at mount, aria-describedby; color.text.secondary (§12)")
    return k.vbox("arm toggle + reason", [pill, reason], {"gap": k.STACK_XS})


def statusbar() -> k.Node:
    return k.statusbar([
        k.hbox("CMP-208 kill switch", [k.icon("kill-switch glyph", "danger", k.DANGER_STRONG),
                                       k.text("word", "Kill switch: engaged", k.CAPTION, k.TEXT_1)],
               {"gap": k.INSET_XS}, h=20, note="the kill-switch glyph and its word (§11)"),
        k.text("armed rules", f"Armed rules: {RULES_ARMED}", k.CAPTION, k.TEXT_1, note="the count as text (§11)"),
        k.placeholder("connection chip", 120)])


def safety_table() -> k.Node:
    cols = (k.Col("sig", "Signal", 200), k.Col("cmp", "Component", 152), k.Col("car", "Static carrier", 520),
            k.Col("red", "Reduce and hc", 184), k.Col("fl", "Flashes", 96))
    rows = [k.table_row(cols, {"sig": s["signal"], "cmp": s["component"], "car": s["carrier"], "red": s["reduce"],
                               "fl": s["flashes"]}, f"row {i}", i) for i, s in enumerate(k.SAFETY, 1)]
    return k.table("CMP-049 grid · §11", f"§11 (L{k.SAFETY[0]['line'] - 2}): every signal static in every tier and "
                   "theme", k.header_row(cols), rows, note="annotation table (the spec's §11), not product UI")


def build_frame(fid: str) -> tuple[k.Node, list[str]]:
    arm = arm_t2()
    tools_h = math.ceil(k.est_height(arm))  # 42: toggle 24 + gap 4 + the reason's 14 px line box (the first sheets: 40)
    body, _sc = chart_body(1192, 228 - k.HEADER_H - 36, 100)  # the plot's scale as drawn; its content ends at 135
    body = dict(body, h=232 - k.HEADER_H - tools_h)  # 162: tools + plot keep the panel body's 204
    tools = k.hbox("chart tools", [arm], {"padX": k.INSET_SM, "fill": k.RAISED}, w=1192, h=tools_h)
    ch = k.panel(f"CMP-080 panel · chart {FOCUS_SYMBOL}", f"Chart · {FOCUS_SYMBOL}",
                 k.vbox("tools + plot", [tools, body], None, w=1192), 1192, 232)
    content = k.vbox("workspace", [banner_env(), banner_freeze(), k.box("pad", [dict(ch, x=16, y=0)], None,
                                                                          w=k.MAIN_W, h=232),
                                   k.box("table pad", [dict(safety_table(), x=16, y=0)], None, w=k.MAIN_W, h=330)],
                     {"gap": k.STACK_MD}, w=k.MAIN_W, h=k.BODY_H)
    pill = k.chip(KS_PILL, fill_=k.DANGER_SUBTLE, stroke=k.DANGER_STRONG, name="CMP-211 status · engaged",
                  lead=k.icon("glyph", "danger", k.DANGER_STRONG),
                  note='role="status"; KillSwitchEngaged (`15`:2754); static')
    top = k.topbar(badge=k.env_badge("live"), right=[pill])
    fr = k.window(fid, content, top=top, status=statusbar(), note="§11 under reduce")
    th = k.frame_theme(fid)
    lines = [f"Reduced motion effective; theme {k.THEME_WORD[th]}: every signal reads by icon and word, nothing moves "
             f"(R-7; §11 L{k.SAFETY[0]['line'] - 2})",
             f"T2 (§12 L{k.T2_LINE}): lock + the full label in color.text.tertiary on a raised fill, reason "
             f"\"{k.T2_VERB}\" (W-12 with its {{verb}}) in color.text.secondary; aria-disabled, never opacity.disabled",
             f"Words: \"{KS_PILL}\" E10-D03 L{KS_LN}; FROZEN reason `15` L{OPEN_LN}; the pill template `15` L{ARM_LN} "
             f"filled Main / 0.010 / BTC (synthetic)"]
    k.copy_gap(f"CMP-208's words \"Kill switch: engaged\" and \"Armed rules: {RULES_ARMED}\" are kit labels: §11 names "
               "\"the kill-switch glyph and its word; the count as text\" without the words")
    k.copy_gap(f"CMP-117's banner reads FROZEN + `15` L{OPEN_LN}'s open-ended line as its reason (§11 gives no reason "
               "text)")
    return fr, lines


def main() -> None:
    frames, blocks = [], []
    for fid in k.BOARDS[NN].frames:
        fr, lines = build_frame(fid)
        frames.append(fr)
        if k.frame_theme(fid) != "dark":
            lines = [f"High-contrast twin: the same nodes and words; evidence in the second export "
                     f"{k.BOARDS[NN].twin_export}; drawn in D03's high-contrast theme (forced colours are board 10's)",
                     lines[0]]
        blocks.append((fid, lines))
    p, md, pk = k.build(NN, frames, blocks, per_row=2, board_lines=[
        "The replay frame and chip (§11's last row) are drawn on board 07"])
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()

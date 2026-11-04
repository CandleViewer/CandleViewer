"""E47-D13 / 07 feedback-copy (dark): "Report an accessibility problem": the template and the CMP-033 default,
copied and failed (§9)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k, stop, tag_right  # noqa: E402

NN = 7
F_DEF, F_COPIED, F_FAILED = k.frames_of(NN)
L9 = k.L("## 9. The feedback path")


TAG_X = 1024


def _frame(fid: str, state: str) -> tuple[k.Node, k.Page, int]:
    page = k.statement_page(k.State(copy=state, focus="copy"))
    sc = page.height - k.BODY_H
    fy = lambda key: page.frame_xy(key, sc)[1]  # noqa: E731
    ov = [stop(5, fy("copy") + 4, "Tab stop 5 · copy"), stop(6, fy("footer"), "Tab stop 6 · footer"),
          tag_right(f"h2 · {k.wcite('W-12')}", fy("feedback.h2") + 2),
          # x 1024 (live check): end-aligned at the estimates (974, 980) they covered the template box's right edge
          k.tag(f"{k.wcite('W-14')}: three lines, nothing personal", TAG_X, fy("template") + 8),
          k.tag(f"CMP-033 · {k.wcite('W-13')} · focus stays on it", TAG_X, fy("copy") - 18),
          tag_right("CMP-207 BuildFooter (synthetic values)", fy("footer"))]
    if state == "copied":
        ov.append(tag_right(f"polite region: {k.wcite('W-2')} once", fy("copy") + 4))
    if state == "failed":
        ov.append(tag_right(f"polite region: {k.wcite('W-17')} then {k.wcite('W-18')}, once", fy("copy") + 4))
    return k.window(fid, page.node, scroll=sc, overlays=ov, note=f"the feedback path · CopyButton {state}"), page, sc


def frame_default() -> tuple[k.Node, tuple[str, list[str]]]:
    fr, _p, _s = _frame(F_DEF, "default")
    lines = [f"§9 L{L9}: W-12 shows a three-line template (W-14) as selectable static text with real line breaks and a "
             "CMP-033 CopyButton (W-13); it asks for the screen, what was tried and the app version, nothing else: no "
             "name, no health or disability question, no screenshot; nothing is stored by the app",
             f"App version in the template: the running version ({k.SYNTH['running']}, synthetic)",
             "The copied text goes to the owner by the team's existing internal channel; copying works offline"]
    return fr, k.frame_block(F_DEF, lines, keyboard="Enter or Space on the button copies (a native button)",
                             waits=["D13-G1"])


def frame_copied() -> tuple[k.Node, tuple[str, list[str]]]:
    fr, _p, _s = _frame(F_COPIED, "copied")
    lines = ["CMP-033 copied: the check glyph in color.status.success.default (`15` CMP-033 States), and W-2 in "
             "text, said once by the polite region; the announcement never contains the copied value",
             "A repeat press announces at most once per state change (§9)",
             f"§7.9 L{k.L('### 7.9 Analytics')}: a11y.problem_report_copied {{}} on a successful copy (PROPOSED)"]
    return fr, k.frame_block(F_COPIED, lines, waits=["D13-G3"])


def frame_failed() -> tuple[k.Node, tuple[str, list[str]]]:
    fr, _p, _s = _frame(F_FAILED, "failed")
    lines = ["CMP-033 failed: the glyph in color.status.danger.default and W-17 then W-18 in text, once each; never "
             "the glyph colour alone (§9)",
             "Focus stays on the button; the template stays selectable so it can be copied by hand (W-18)"]
    return fr, k.frame_block(F_FAILED, lines)


def build() -> None:
    fr = [frame_default(), frame_copied(), frame_failed()]
    k.build_all(NN, [f for f, _b in fr], k.annotations(NN, [b for _f, b in fr]))


if __name__ == "__main__":
    build()

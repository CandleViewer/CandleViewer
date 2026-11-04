"""E47-D13 / 03 stale-notice (dark): the CMP-028 notice above the version line (W-7), the version-unknown variant
(W-8) and the offline frame (§8.2, §7.3)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k, stop, tag_right  # noqa: E402

NN = 3
F_STALE, F_UNKNOWN, F_OFF = k.frames_of(NN)
L73, L82 = k.L("### 7.3 States"), k.L("### 8.2 Staleness")


def _notice_frame(fid: str, st: k.State, wkey: str) -> tuple[k.Node, k.Page]:
    page = k.statement_page(st)
    fy = lambda key: page.frame_xy(key)[1]  # noqa: E731
    ov = [stop(1, fy("notice") + 6, "notice"), stop(2, fy("version") - 3, "version line"),
          tag_right(f"CMP-028 tone info · role status · {k.wcite(wkey)}", fy("notice") - 18),
          tag_right("in the DOM before the version line at first render", fy("notice") + page.h["notice"] + 2),
          tag_right(f"version line · {k.wcite('W-6')}", fy("version") + 16)]
    return k.window(fid, page.node, overlays=ov, note=f"{wkey} above the version line"), page


def frame_stale() -> tuple[k.Node, tuple[str, list[str]]]:
    st = k.State(stale=True)
    fr, _p = _notice_frame(F_STALE, st, "W-7")
    lines = [f"§8.2 L{L82}: stale when appliesTo ({k.SYNTH['appliesTo']}, synthetic) differs from the running "
             f"version CMP-207 shows ({st.running}, synthetic): any difference means \"not issued for this release\"",
             "The statement still renders, under the notice, never as current (T AC3); the glyph and the words carry "
             "it, the info.subtle fill is decoration (lost under forced colours, §7.6)",
             k.pair_line("P4", "dark"),
             f"§7.3 L{L73}: the notice is read in order; the spec does not rely on role=status announcing it"]
    return fr, k.frame_block(F_STALE, lines, waits=["D13-G2"])


def frame_unknown() -> tuple[k.Node, tuple[str, list[str]]]:
    fr, _p = _notice_frame(F_UNKNOWN, k.State(unknown=True), "W-8")
    lines = [f"§8.2 L{L82}: if the running version cannot be read, W-8 in the same CMP-028 notice, same place",
             "Same reading order: h1, status, target, scope, notice, version line"]
    return fr, k.frame_block(F_UNKNOWN, lines)


def frame_offline() -> tuple[k.Node, tuple[str, list[str]]]:
    page = k.statement_page(k.State())
    fy = lambda key: page.frame_xy(key)[1]  # noqa: E731
    ov = [k.tag("offline (synthetic): no network; the page renders from the cached chunk", k.MAIN_X + 300,
                k.FRAME_H - k.STATUS_H + 16, name="tag · offline"),
          tag_right("loaded state: identical to online (BQ-12)", fy("h1") + 6)]
    fr = k.window(F_OFF, page.node, overlays=ov, note="offline: the cached chunk; the page works")
    lines = [f"§7.3 L{L73}: offline, the chunk is cached with the app and the page works (BQ-12); copy works offline "
             f"(§9 L{k.L('## 9. The feedback path')})",
             f"§7.9 L{k.L('### 7.9 Analytics')}: the chunk loads on navigation only and is cached for offline use",
             "The offline signal itself is the shell's StatusBar (placeholder here); nothing on the page changes",
             f"Not drawn (§0 L{k.NOT_DRAWN_LINE}): the loading skeleton and the chunk-failed state"]
    return fr, k.frame_block(F_OFF, lines)


def build() -> None:
    fr = [frame_stale(), frame_unknown(), frame_offline()]
    k.build_all(NN, [f for f, _b in fr], k.annotations(NN, [b for _f, b in fr]))


if __name__ == "__main__":
    build()

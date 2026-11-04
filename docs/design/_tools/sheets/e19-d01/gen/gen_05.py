"""Board 05 developing-vs-final: memo §6.3 and PD-1 — the header and legend words "Developing · as of HH:MM UTC" with
an open-ended value-area bracket (no end cap), beside a final session reading "Final" with a closed bracket; never
dashed, hollow or hatched, never opacity or motion alone."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import rb  # noqa: E402
from rb import k  # noqa: E402

NN = 5


def side(fid: str, pr: k.Profile, framing: str, note: str) -> tuple[k.Node, tuple[str, list[str]]]:
    pane = rb.profile_pane(pr, row_px=10)
    pw = pane["w"] + 32
    words = k.developing_words(pr)
    head = [k.text("title", k.ui("Profile · BTCUSDT"), k.BODY_STRONG, k.TEXT_1), rb.menu_button(k.mode_words()[0]),
            k.text("state", words, k.LABEL, k.TEXT_1)]
    leg = rb.legend([(k.memo("Value area 70 %"), rb.glyph("bracket")), (words, None),
                     (k.ui(f"Row size {k.ROW_TICKS} ticks"), None)], pw - 16)
    p = rb.panel(head, [k.hbox("pane row", [pane], {"padX": k.INSET_LG}, w=pw, h=pane["h"]),
                        k.hbox("legend row", [leg], {"padX": k.INSET_SM}, w=pw)], pw)
    k.derive(f"{pr.label}: {'complete' if pr.complete else f'developing, as of {k.hhmm(pr.as_of)} UTC'}; "
             f"{len(k.periods(pr.first))} periods; POC {k.row_price(pr, pr.poc)}, VA "
             f"{k.row_price(pr, pr.va[0])}–{k.row_price(pr, pr.va[1])}")
    return (k.frame(fid, [p, rb.marker(note, pw)], pw + 2 * k.FRAME_PAD, framing),
            k.frame_block(fid, [k.f_line("F-1"), k.f_line("F-3")] if not pr.complete else
                          [k.f_line("F-2"), f"G-1: {k.GAPS[0][1][1]}", f"G-2: {k.GAPS[1][1][1]}"],
                          ["PD-1"] if not pr.complete else []))


def frames() -> tuple[list[k.Node], list[tuple[str, list[str]]]]:
    f1, f2 = k.BOARDS[NN].frames
    a = side(f1, k.DEVELOPING, "Research — the developing session (30 Oct, synthetic): the words in the header and the "
                               "legend, and the value-area bracket drawn open (no end cap)",
             k.memo("an open-ended value-area bracket (no end cap) while developing"))
    b = side(f2, k.FINAL, "Research — the final session beside it (29 Oct, synthetic): \"Final\" in the header and "
                          "the legend, the bracket closed with end caps",
             k.memo("at close the words become \"Final\" and the bracket closes"))
    return [a[0], b[0]], [a[1], b[1]]


if __name__ == "__main__":
    rb.run(NN, frames(), 2, board_lines=[
        "Never dashed, hollow or hatched (F-3), never opacity or motion alone (E19-D05 owns the transition) — memo §6.3",
        "AC 2 stays open: only sessions can show whether the words are noticed unaided (protocol T2, T4, T8)",
        f"OQ-5: {k.OQS[4][1][1]}"])

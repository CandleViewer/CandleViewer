"""Board 06 approximated-partial-strip: memo §6.4–§6.5, PD-4, PD-5 — the header status slot with CMP-011 (partial,
E16-D05's words) left of CMP-227 at section grade ("(estimated)", "approximated from bars"), the hatched approximated
rows, and delta drawn as absent over the bar-approximated portion with words."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import rb  # noqa: E402
from rb import k  # noqa: E402

NN = 6


def status_slot(partial: bool) -> k.Node:
    kids = [rb.chip_partial(len(k.RECORDED_DAYS), len(k.REQUESTED)) if partial else None, rb.est_badge()]
    return k.hbox("header status slot", kids, {"gap": k.INSET_XS}, h=24,
                  note="status slot: CMP-011 left of CMP-227, 4 px apart (space.inset.xs), each its own name")


def approx_words() -> str:
    return k.memo_tpl("Delta not available before 09:00 UTC", **{"09:00": k.hhmm(k.TICKS_FROM)})


def session(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    pr = k.APPROX_SESSION
    pane = rb.profile_pane(pr, row_px=12, hatch=True, delta=True)
    pw = pane["w"] + 32
    head = [k.text("title", k.ui("Profile · BTCUSDT"), k.BODY_STRONG, k.TEXT_1), rb.menu_button(k.mode_words()[0]),
            k.text("state", k.developing_words(pr), k.LABEL, k.TEXT_1), status_slot(False)]
    strip = k.hbox("delta absent words", [k.icon("glyph", "info", k.TEXT_1),
                                          k.text("words", approx_words(), k.LABEL, k.TEXT_1)],
                   {"gap": k.INSET_XS, "padX": k.INSET_LG}, w=pw, h=20)
    leg = rb.legend([(k.memo("Value area 70 %"), rb.glyph("bracket")),
                     (k.memo("approximated from bars"), rb.glyph("hatch")),
                     (k.ui(f"Row size {k.ROW_TICKS} ticks"), None)], pw - 16)
    p = rb.panel(head, [strip, k.hbox("pane row", [pane], {"padX": k.INSET_LG}, w=pw, h=pane["h"]),
                        k.hbox("legend row", [leg], {"padX": k.INSET_SM}, w=pw)], pw)
    hatched = sorted(pr.approx)
    k.derive(f"{pr.label}: periods before {k.hhmm(k.TICKS_FROM)} UTC are approximated from bars (the memo's uniform "
             f"rule); {len(hatched)} of {len(pr.rows)} rows carry approximated volume and are hatched; delta drawn "
             f"from the {sum(1 for p in k.periods(pr.first) if not p.approximated)} recorded periods only; POC "
             f"{k.row_price(pr, pr.poc)}")
    return (k.frame(fid, [p], pw + 2 * k.FRAME_PAD,
                    "Research — a session with a bar-approximated morning (28 Oct, synthetic): CMP-227 at section "
                    "grade in the header, the approximated rows hatched, delta absent before the recorded trades "
                    "begin, with words"),
            k.frame_block(fid, [k.f_line("F-4"), k.f_line("F-5"), k.f_line("F-6"),
                                "Hatch reading (kit): a row is hatched when any of its volume is bar-approximated "
                                "(G-3: no per-row flag exists yet)", "TPO over the approximated portion: not drawn "
                                "here (Volume input); PD-4 requires it absent too"], ["PD-4"]))


def composite(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    pr = k.COMPOSITE
    pane = rb.profile_pane(pr, row_px=8, hatch=True)
    pw = max(pane["w"] + 32, 840)
    cov = k.ui(f"Covered {k.day_word(k.COVERED_DAYS[0])}–{k.day_word(k.COVERED_DAYS[-1])} 2026 "
               f"({len(k.COVERED_DAYS)} of {len(k.REQUESTED)} requested sessions)",
               "the covered-range words; G-4 has no carrier yet")
    head = [k.text("title", k.ui("Profile · BTCUSDT"), k.BODY_STRONG, k.TEXT_1), rb.menu_button(k.mode_words()[4]),
            status_slot(True)]
    leg = rb.legend([(k.memo("Value area 70 %"), rb.glyph("bracket")),
                     (k.memo("approximated from bars"), rb.glyph("hatch")), (cov, None),
                     (k.ui(f"Row size {k.ROW_TICKS} ticks"), None)], pw - 16)
    p = rb.panel(head, [k.hbox("pane row", [pane], {"padX": k.INSET_LG}, w=pw, h=pane["h"]),
                        k.hbox("legend row", [leg], {"padX": k.INSET_SM}, w=pw)], pw)
    k.derive(f"composite: requested {', '.join(k.day_word(d) for d in k.REQUESTED)}; recorded trades on "
             f"{', '.join(k.day_word(d) for d in k.RECORDED_DAYS)} (28 Oct from {k.hhmm(k.TICKS_FROM)} UTC, its "
             f"morning approximated from bars); nothing kept for 25–27 Oct; POC {k.row_price(pr, pr.poc)}, VA "
             f"{k.row_price(pr, pr.va[0])}–{k.row_price(pr, pr.va[1])}")
    return (k.frame(fid, [p], pw + 2 * k.FRAME_PAD,
                    "Research — a composite short of history and partly approximated: E16-D05's partial chip left of "
                    "CMP-227 in the status slot, the covered range in the legend"),
            k.frame_block(fid, [k.f_line("F-15"), k.f_line("F-20"),
                                "Reading (kit): a day with any recorded trades counts as recorded in the chip's n; "
                                "no hatch for partial history (E16-D05 :285) — the hatch here is the approximated "
                                "morning"], ["PD-5"]))


def header_slot(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    w = 760
    slot = status_slot(True)
    meas = k.hbox("measurements", [rb.marker("CMP-011 info · left"), rb.marker("4 px (space.inset.xs)"),
                                   rb.marker("CMP-227 section · right")], {"gap": k.INSET_SM}, h=20)
    names = k.hbox("accessible names", [
        rb.hidden("CMP-011 accessible name", k.memo_tpl("Partial: {n} of {m} requested days recorded",
                                                        **{"{n}": str(len(k.RECORDED_DAYS)),
                                                           "{m}": str(len(k.REQUESTED))}), 340),
        rb.hidden("CMP-227 accessible name", k.ui("Estimated, approximated from bars",
                                                  "CMP-227's name pattern \"Estimated, <display name>\" (`15`) with "
                                                  "the memo's methodology words"), 340)], {"gap": k.INSET_LG,
                                                                                           "align": "start"}, w=w - 48)
    return (k.frame(fid, [k.text("label", "the header status slot, actual size", k.LABEL, k.TEXT_2), slot, meas,
                          names], w,
                    "Research — the status slot close up: two chips, never merged, at least 4 px apart, each with "
                    "its own accessible name"),
            k.frame_block(fid, [k.memo("at least 4 px apart, each with its own accessible name"),
                                f"A-5: {k.AMEND['A-5'][2]}", f"G-3: {k.GAPS[2][1][1]}"]))


def frames() -> tuple[list[k.Node], list[tuple[str, list[str]]]]:
    out = [f(fid) for f, fid in zip((session, composite, header_slot), k.BOARDS[NN].frames)]
    return [a for a, _b in out], [b for _a, b in out]


if __name__ == "__main__":
    rb.run(NN, frames(), 3, board_lines=["AC 3 stays open: no misread exists to quote; the protocol records one "
                                         "verbatim (T9) — memo §6.4"])

"""Board 02 centring-modes: auto-follow, free-scroll and centre lock as state strips (memo §6 centring row, AD-3, AD-4,
AD-8; F-1, F-2, F-3; K3). Each strip is a run of ladder snapshots on the seeded mark walk (one update per 50 ms); the
edge band is ILLUSTRATIVE (OQ-3: E21-D05 #505 owns the numbers)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import rb  # noqa: E402
from rb import k  # noqa: E402

NN = 2
FW = 1680
IW = FW - 2 * k.FRAME_PAD



def band_col(centre: int, on: bool) -> k.Node:
    """A 12 px column beside the ladder: the band rows filled (auto-follow), else empty."""
    cells = [k.rect(f"band · {j + 1:02d}", 12, rb.ROW_H, k.BORDER_STRONG if on and abs(off - centre) >= k.BAND_FROM
                    else None, {"stroke": k.BORDER_SUBTLE, "strokeWidth": k.HAIR})
             for j, off in enumerate(range(centre + k.HALF, centre - k.HALF - 1, -1))]
    return k.vbox("edge band", [k.rect("band head", 12, rb.HEAD_H, k.RAISED), *cells], {}, w=12,
                  h=rb.HEAD_H + len(cells) * rb.ROW_H)


def snap(label: str, state: str, centre: int, mark: int, *, band: bool, extra: list | None = None,
         pointer: int | None = None) -> k.Node:
    lad = rb.ladder("ladder", centre, rb.rel_book(mark), mark, pointer_row=pointer)
    w = 12 + lad["w"]
    state_kids: list[k.Node | None] = [rb.badge(state, strong=True)]
    if extra:
        state_kids.append(k.hbox("resume", [extra[0], k.text("words", extra[1], k.CAPTION, k.TEXT_1, w=w - 56)],
                                 {"gap": k.INSET_XS, "align": "start"}, w=w, h=32))
    return k.vbox(f"snapshot · {label}", [k.hbox("when", [k.text("words", label, k.NUM_SM, k.TEXT_2, w=w)],
                                                 {"align": "start"}, w=w, h=28),
                                          k.vbox("state", state_kids, {"gap": k.STACK_XS}, w=w, h=56),
                                          k.hbox("ladder + band", [band_col(centre, band), lad], {"align": "start"},
                                                 w=w, h=lad["h"])], {"gap": k.STACK_XS}, w=w)


def when(u: int) -> str:
    return f"update {u} · +{u * k.UPDATE_MS} ms"


def auto_follow(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    pick, far = [0], 0
    for u, m in enumerate(k.WALK):
        if abs(m) > far:
            pick.append(u)
            far = abs(m)
    last = len(k.WALK) - 1
    st = k.memo("auto-follow")
    snaps = [snap(when(u), st, 0, k.WALK[u], band=True) for u in pick]
    snaps.append(snap(f"{when(last)} · re-centred", st, k.WALK[last], k.WALK[last], band=True))
    k.derive(f"auto-follow snapshots: update 0 and each update that takes the mark to a new distance from the centre "
             f"({', '.join(str(u) for u in pick)}); the mark enters the band (|offset| ≥ {k.BAND_FROM} rows) at update "
             f"{last} (+{last * k.UPDATE_MS} ms) and the ladder re-centres once, on {k.price(k.px(k.WALK[last]))}")
    return (k.frame(fid, [k.hbox("strip", snaps, {"gap": k.INSET_MD, "align": "start"}, w=IW),
                          k.text("default", k.memo("auto-follow with an edge-band trigger; a manual scroll suspends it "
                                                   "visibly (free-scroll); Space resumes"), k.BODY, k.TEXT_1, w=IW)],
                    FW, "Default (memo §6, centring mode): the mark moves within a still ladder; one re-centre when it "
                        "reaches the band", proposed=True),
            k.frame_block(fid, [f"Band rows filled in the 12 px column: the outer {k.BAND} rows a side — ILLUSTRATIVE, "
                                "OQ-3 (E21-D05 #505) owns the edge band, target and minimum interval"],
                          ads=["AD-3"], fs=["F-1"]))


def free_scroll(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    down = k.HALF - k.BAND  # the user scrolls the view down by this many rows (kit illustration)
    last = len(k.WALK) - 1
    vis = [u for u in range(last + 1) if -down - k.HALF <= k.WALK[u] <= -down + k.HALF]
    gone = next(u for u in range(last + 1) if k.WALK[u] > -down + k.HALF)
    fs_ = k.memo("free-scroll")
    resume = [rb.key_cap("Space"), k.memo("Space = re-centre + resume auto-follow")]
    snaps = [snap(when(0), k.memo("auto-follow"), 0, k.WALK[0], band=True),
             snap(f"{when(0)} · scrolled down {down} rows", fs_, -down, k.WALK[0], band=False, extra=resume),
             snap(when(vis[-1]), fs_, -down, k.WALK[vis[-1]], band=False, extra=resume),
             snap(f"{when(last)} · mark above the view", fs_, -down, k.WALK[last], band=False, extra=resume),
             snap(f"{when(last)} · Space", k.memo("auto-follow"), k.WALK[last], k.WALK[last], band=True)]
    k.derive(f"free-scroll: a {down}-row scroll down puts the view centre on {k.price(k.px(-down))} (rows "
             f"{k.price(k.px(-down - k.HALF))}–{k.price(k.px(-down + k.HALF))}); the mark walks "
             f"{k.price(k.px(k.WALK[0]))} → {k.price(k.px(k.WALK[vis[-1]]))} (update {vis[-1]}, the last in view) and "
             f"leaves the view at update {gone}; no re-centre; Space centres on {k.price(k.px(k.WALK[last]))}")
    return (k.frame(fid, [k.hbox("strip", snaps, {"gap": k.INSET_MD, "align": "start"}, w=IW),
                          rb.card("F-3 (heuristic)", [k.FINDINGS["F-3"][0][1]], IW)],
                    FW, "Free-scroll is a visible state: a text indicator names the resume key; Space returns to "
                        "auto-follow (AD-4)", proposed=True),
            k.frame_block(fid, ["The state words and the resume key sit in the header area of every free-scroll "
                                "snapshot; the band column is empty while auto-follow is suspended",
                                "Indicator copy is the memo's quote of `14`:1214; E21-D02 #440 writes the header copy"],
                          ads=["AD-4"], fs=["F-3"]))


def centre_lock(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    us = [0] + [u for u in range(1, len(k.WALK)) if k.WALK[u] != k.WALK[u - 1]][:4]
    prow = k.HALF - 3  # the pointer rests on screen row 6 (three rows above the centre row)
    under = [k.price(k.px(k.WALK[u] + 3)) for u in us]
    cl = k.memo("centre lock")
    snaps = [snap(when(u), cl, k.WALK[u], k.WALK[u], band=False, pointer=prow) for u in us]
    k.derive(f"centre lock: updates {', '.join(str(u) for u in us)} (each moves the mark); the pointer stays on "
             f"screen row {prow + 1} and the price under it is {' → '.join(under)}")
    kc, _ln = k.KILLS["K3"]
    opts = []
    for m in ("auto-follow", "free-scroll", "centre lock"):
        on = m == "auto-follow"
        ro = {"stroke": k.BORDER_STRONG, "strokeWidth": k.THICK if on else k.HAIR, **({"fill": k.TEXT_1} if on else {})}
        opts.append(k.hbox(f"option · {m}", [k.ellipse("radio", 14, 14, ro),
                                             k.text("label", k.memo(m), k.BODY, k.TEXT_1),
                                             k.text("caveat", k.ui("moves every row on every update",
                                                                   "AD-8's every-update-motion caveat"),
                                                    k.CAPTION, k.TEXT_2) if m == "centre lock" else None],
                           {"gap": k.INSET_SM}, h=20))
    setting = k.vbox("SCR-051 Ladder tab · centring", [
        k.text("label", k.ui("Centring", "SCR-051 setting label (E21-D03 #503)"), k.LABEL, k.TEXT_2), *opts],
        {"pad": k.INSET_MD, "gap": k.STACK_SM, "fill": k.RAISED, "stroke": k.BORDER, "strokeWidth": k.HAIR,
         "strokeAlign": "inner", "radius": k.R_CARD}, w=520, note="SCR-051 Ladder tab, one three-option setting (AD-8)")
    return (k.frame(fid, [k.hbox("strip", snaps, {"gap": k.INSET_MD, "align": "start"}, w=IW),
                          k.text("pointer", f"pointer row (board marker): {' → '.join(under)}", k.NUM_SM, k.TEXT_1),
                          k.hbox("setting", [setting, rb.card("C4", [k.CONTRAS["C4"][0][1], k.CONTRAS["C4"][0][2]],
                                                              IW - 520 - 12)], {"gap": k.INSET_MD, "align": "start"},
                                 w=IW),
                          k.hbox("cards", [rb.card("F-2 (heuristic) · Blocker", [k.FINDINGS["F-2"][0][1]],
                                                   (IW - 12) // 2),
                                           rb.card(f"K3 · {kc[1]}", [kc[2], kc[3]], (IW - 12) // 2)],
                                 {"gap": k.INSET_MD, "align": "start"}, w=IW)],
                    FW, "Centre lock pins the mark to one row: every row moves on every update (recorded other "
                        "position; an opt-in SCR-051 setting, AD-8)", proposed=True),
            k.frame_block(fid, ["The hairline-edged row is the pointer's screen row (board marker); its price changes "
                                "between aiming and clicking (F-2)"], ads=["AD-8"], fs=["F-2"]))


if __name__ == "__main__":
    built = [f(fid) for f, fid in zip((auto_follow, free_scroll, centre_lock), k.BOARDS[NN].frames)]
    rb.run(NN, ([b[0] for b in built], [b[1] for b in built]), 1,
           board_lines=["Snapshots: the seeded mark walk, one update per 50 ms (book updates at up to 20 Hz, F-2)",
                        "Sizes: the t0 book shape carried with the mark (synthetic)"])

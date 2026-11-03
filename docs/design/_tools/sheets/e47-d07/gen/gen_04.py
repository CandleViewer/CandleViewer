"""Board 04 `E47-D07 / 04 incident-timeline` (dark): §5.1 and §10.3 — the queue by rank, the speech estimates, the log
row per event and the auto-flatten's persistent toast; every figure is the tool's replay of the incident script."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k  # noqa: E402

NN = 4
SID = "incident"
PAD, X0, PXS = 24, 150, 44
S51, S103 = k.L("### 5.1 The queue"), k.L("### 10.3 Incident")


def X(ms: int) -> float:
    return X0 + ms * PXS / 1000


def build_frame(fid: str) -> tuple[dict, dict]:
    k.fallback("timeline-scale")
    r = k.replay(SID)
    evs = [i for i in k.items(SID) if i.kind == "event"]
    lines = r.lines
    end = max(x.t + k.est_ms(x.text) for x in lines)
    if X(end) > k.FRAME_W - PAD:
        raise SystemExit("board 04: the axis runs past the frame")
    lanes = [("events in", 64), ("focus (dialog)", 128), ("assertive", 160), ("polite", 192)]
    kids: list[dict] = [k.text(f"lane · {n}", n, k.CAPTION, k.TEXT_2, x=PAD, y=y + 2) for n, y in lanes]
    for j, e in enumerate(evs, 1):
        kids.append(k.tag(f"{e.tid} · rank {k.TAX[e.tid].rank} · arrives {k.secs(e.t)} s", round(X(e.t)),
                          44 + 20 * j, name=f"tag · event {j}"))
    lane_y = {"focus": 128, "assertive": 160, "polite": 192}
    for j, x in enumerate(lines, 1):
        e = k.est_ms(x.text)
        cls = "ambient-polite" if x.channel == "polite" else "significant-assertive"
        kids.append(k.lane_bar(f"line {j}", X(x.t), X(x.t + e), lane_y[x.channel], 20, cls,
                               f"{x.rows} · {k.secs(e)} s"))
        if x.channel != "polite":
            kids.append(k.rect(f"drop {j}", 2, 20, k.MARK_FILL, x=round(X(x.t)), y=192))
    kids.append(k.tag("each assertive write drops the pending ambient values (PW:116–120)", round(X(lines[1].t)) + 6,
                      216, name="tag · drops"))
    kids.append(k.rect("axis", round(X(end) - X0), 1, k.AXIS, x=X0, y=244))
    for t in range(0, end // 1000 + 1, 2):
        kids.append(k.text(f"tick {t}", f"{t} s", k.NUM_SM, k.AXIS, x=round(X(t * 1000)) - 6, y=250))
    kids.append(k.text("scale", f"{PXS} px per second", k.CAPTION, k.TEXT_3, x=PAD, y=250))
    # the queue as it stands once the last event has arrived (before T-17's speech ends)
    t_q = max(e.t for e in evs)
    pend = sorted([e for e in evs], key=lambda e: (int(k.TAX[e.tid].rank), e.seq))
    qrows = []
    for j, e in enumerate(pend, 1):
        ln = next(x for x in lines if x.rows == e.tid)
        state = "speaking (dialog focus)" if ln.t <= t_q else f"waits; written at {k.secs(ln.t)} s"
        qrows.append(k.tagged_card(f"queue {j}", "significant-assertive", [
            k.text("head", f"{j}. {e.tid} · rank {k.TAX[e.tid].rank} · {state}", k.LABEL, k.TEXT_1, w=340),
            k.text("words", ln.text, k.CAPTION, k.TEXT_2, w=340)], 364))
    queue = k.vbox("the queue", [k.text("h", f"The queue at {k.secs(t_q)} s, by rank then arrival (§5.1)", k.LABEL,
                                        k.TEXT_1), *qrows], {"gap": k.STACK_SM}, w=364, x=PAD, y=288)
    ass_lines = [x for x in lines if x.channel != "polite"]
    lw = 400
    log = k.vbox("CMP-060 NotificationCenter · log", [
        k.text("h", f"CMP-060 entries: {len(ass_lines)}, one per assertive line (R-8)", k.LABEL, k.TEXT_1),
        *[k.log_row(f"{k.secs(x.t)} s", next(e.text for e in evs if e.tid == x.rows), lw, j)
          for j, x in enumerate(ass_lines, 1)]],
        {"gap": k.STACK_XS, "pad": k.INSET_SM, "fill": k.RAISED, "radius": k.R_CARD}, w=lw + 16, x=PAD + 364 + 24,
        y=288, note='role="log"; the fallback of record when a write overruns the reader (§5.1, R-8)')
    flat = next(e for e in evs if e.tid == "T-17")
    tst = dict(k.toast(flat.text, persistent=True, wd=360), x=k.FRAME_W - PAD - 360, y=288)
    tnote = k.tag("the attention set's persistent toast (R-8); T-17's dialog is its speaker", k.FRAME_W - PAD - 360,
                  288 + round(k.est_height(tst)) + 8)
    kids += [k.heading("h", f"Incident, Always · Normal · 2 s (§10.3 L{S103}): reject, auto-flatten and disconnect",
                       PAD, PAD, 900), queue, log, tst, tnote, k.synthetic_tag(PAD, k.FRAME_H - 28)]
    return k.specimen(fid, kids), dict(lines=lines, evs=evs)


def main() -> None:
    b = k.BOARDS[NN]
    fr, f = build_frame(b.frames[0])
    if len(f["lines"]) != int(k.val("SIM", "incident.lines")):
        raise SystemExit("board 04: line count != §10.3's figure")
    blocks = [(b.frames[0], [
        f"§5.1 L{S51}: one queue by rank (1 the auto-flatten, 2 safety, 3 execution, 4 connectivity), drained once per "
        "frame; the head written alone and in full; the next write waits for its speech estimate, max(1.5 s, "
        "characters / 15 per second) (PROPOSED, D07-Q3)",
        "Events: " + "; ".join(f"{e.tid} at {k.secs(e.t)} s" for e in f["evs"]) + "; lines: "
        + "; ".join(f"{x.rows} {x.channel} at {k.secs(x.t)} s" for x in f["lines"]),
        "T-17's write is its alertdialog taking focus (§9); the reader's focus speech is the queue's item, the pair "
        "does not also write W-5 (R-6)",
        "The disconnect is heard last, well after its event; the overlay and its toast are immediate (D07-Q4)",
        "Nothing is dropped from the queue; the drop counter stays 0 (§12); the shipped announcer's overwrite is "
        "D07-G1 (#304)"])]
    p, md, pk = k.build(NN, [fr], blocks, per_row=1)
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()

"""Board 03 `E47-D07 / 03 polite-timeline` (dark): §6.1 — the fast script's 10 Hz fields, the 2 s cadence, the speech
share, latest wins and the composite in fixed order; every bar and figure is the tool's replay of §10.2."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k  # noqa: E402

NN = 3
SID = "fast"
PAD, X0, PXS = 24, 150, 16  # the axis starts at X0; PXS px per second (FALLBACKS timeline-scale)
S61 = k.L("### 6.1 Ambient fields")


def X(ms: int) -> float:
    return X0 + ms * PXS / 1000


def build_frame(fid: str) -> tuple[dict, dict]:
    k.fallback("timeline-scale")
    s = k.SCRIPTS[SID]
    dur = int(s["duration_ms"])
    r = k.replay(SID)
    pol = [x for x in r.lines if x.channel == "polite"]
    ass = [x for x in r.lines if x.channel != "polite"]
    end = max(x.t + k.est_ms(x.text) for x in r.lines)
    if X(end) > k.FRAME_W - PAD:
        raise SystemExit("board 03: the axis runs past the frame")
    its = k.items(SID)
    fields = [i for i in its if i.kind == "field" and i.fld in ("quote", "mark")]
    cad = int(s["settings"]["cadence_ms"])
    lanes = [("10 Hz fields", 64), (f"cadence {cad // 1000} s", 104), ("polite: speech", 136),
             ("polite: share wait", 168), ("assertive", 200)]
    kids: list[dict] = [k.text(f"lane · {n}", n, k.CAPTION, k.TEXT_2, x=PAD, y=y + 2) for n, y in lanes]
    nq = sum(i.fld == "quote" for i in fields)
    nm = sum(i.fld == "mark" for i in fields)
    kids.append(k.lane_bar("10 Hz band", X(fields[0].t), X(max(i.t for i in fields)), 64, 20, "ambient-polite",
                           f"{nq} quote + {nm} mark values ({SID}: every "
                           f"{s['streams'][0]['every_ms']} ms), never queued"))
    for t in range(0, dur + 1, cad):
        kids.append(k.rect(f"cadence {t // 1000}", 1, 12, k.AXIS, x=round(X(t)), y=106))
    rows = []
    for i, x in enumerate(pol, 1):
        e = k.est_ms(x.text)
        kids.append(k.lane_bar(f"speech {i}", X(x.t), X(x.t + e), 136, 20, "ambient-polite", f"{i}"))
        nxt = pol[i].t - x.t if i < len(pol) else None
        if nxt is not None:  # the share wait gates the next composite (§6.1); after the flush there is none
            kids.append(k.lane_bar(f"wait {i}", X(x.t + e), X(x.t + 2 * e), 168, 20, "silent"))
        rows.append((i, x, e, nxt))
    for i, x in enumerate(ass, 1):
        e = k.est_ms(x.text)
        kids.append(k.lane_bar(f"assertive {i}", X(x.t), X(x.t + e), 200, 20, "significant-assertive", x.rows))
        kids.append(k.tag(f"{x.rows} drops the pending values", round(X(x.t)), 224, name=f"tag · drop {i}"))
    kids.append(k.rect("axis", round(X(end) - X0), 1, k.AXIS, x=X0, y=252))
    for t in range(0, end // 1000 + 1, 10):
        kids.append(k.text(f"tick {t}", f"{t} s", k.NUM_SM, k.AXIS, x=round(X(t * 1000)) - 6, y=258))
    kids.append(k.text("scale", f"{PXS} px per second", k.CAPTION, k.TEXT_3, x=PAD, y=258))
    kids.append(k.rect("stream end", 2, 200, k.MARK_FILL, x=round(X(dur)), y=56, abs=True))
    kids.append(k.tag(f"stream ends · {dur // 1000} s", round(X(dur)) - 60, 40))
    # the composite table
    cols = (("#", 40), ("t (s)", 80), ("rows", 100), ("composite (fixed order: quote, mark)", 340),
            ("estimate (s)", 110), ("next after (s)", 150))
    k.copy_gap("board 03's table headings (#, t (s), rows, composite, estimate, next after) are the kit's words over "
               "§10.2's columns and §5.1's estimate")
    hdr = k.hbox("header row", [k.hbox(f"h · {c}", [k.text("t", c, k.LABEL, k.TEXT_2)], {"padX": k.INSET_SM}, w=wd,
                                       h=22) for c, wd in cols], {"fill": k.RAISED}, h=22)
    trs = [hdr]
    for i, x, e, nxt in rows:
        vals = (str(i), k.secs(x.t), x.rows, x.text, k.secs(e), k.secs(nxt) if nxt else "flush (stream over)")
        trs.append(k.hbox(f"row {i}", [k.hbox(f"c · {c}", [k.text("t", v, k.NUM_SM if c != cols[3][0] else k.CAPTION,
                                                                  k.TEXT_1)], {"padX": k.INSET_SM}, w=wd, h=20)
                                       for (c, wd), v in zip(cols, vals)], {}, h=20))
    table = k.vbox("CMP-049 table · composites", trs, None, x=PAD, y=296,
                   note="§10.2's polite lines with §5.1's estimate; spacing = max(cadence, 2 x estimate) (§6.1)")
    # latest wins: the last values before composite 2
    c2 = pol[1]
    before = [i for i in fields if i.fld == "quote" and i.t <= c2.t][-6:]
    if not c2.text.startswith(before[-1].text):
        raise SystemExit("board 03: composite 2 does not open with the latest quote")
    lw = k.vbox("latest wins", [k.text("h", f"Latest wins (R-4): the last quote values before composite 2 at "
                                            f"{k.secs(c2.t)} s", k.LABEL, k.TEXT_1, w=300),
                                *[k.text(f"v {j}", f"{k.secs(i.t)} s  {i.text}" + ("  ← said" if j == len(before) else
                                                                                  "  (replaced)"),
                                         k.NUM_SM, k.TEXT_1 if j == len(before) else k.TEXT_3)
                                  for j, i in enumerate(before, 1)]],
                  {"gap": k.STACK_XS, "pad": k.INSET_SM, "fill": k.RAISED, "radius": k.R_CARD}, w=330,
                  x=k.FRAME_W - PAD - 330, y=296)
    kids += [k.heading("h", f"Fast market, Always · Normal · {cad // 1000} s (§10.2): the polite channel", PAD, PAD,
                       900), table, lw, k.synthetic_tag(PAD, k.FRAME_H - 28)]
    share = sum(k.est_ms(x.text) for x in pol[:-1]) / (pol[-2].t + k.est_ms(pol[-2].text) - pol[0].t)
    facts = dict(pol=pol, ass=ass, n_in=sum(x.t <= dur for x in pol), share=share, nq=nq, nm=nm)
    return k.specimen(fid, kids), facts


def main() -> None:
    b = k.BOARDS[NN]
    fr, f = build_frame(b.frames[0])
    sp = [f["pol"][i + 1].t - f["pol"][i].t for i in range(len(f["pol"]) - 1)]
    if f["n_in"] != int(k.val("SIM", "fast.composites")) or len(f["pol"]) != int(k.val("SIM", "fast.polite")):
        raise SystemExit("board 03: the replay's composite counts differ from §6.1's figures")
    blocks = [(b.frames[0], [
        f"§6.1 L{S61}: one composite per cadence in a fixed order, latest value per field, a value already said is "
        "skipped; nothing appended, nothing queued (R-4)",
        f"The replay (the tool's, §10.2): {len(f['pol'])} polite composites, {f['n_in']} inside the stream's minute "
        f"and 1 flush at {k.val('SIM', 'fast.flush-at')} s; {len(f['ass'])} assertive lines, each dropping the "
        "values pending for the cadence (PW:116–120)",
        f"Speech share (PROPOSED, D07-Q3): the next composite waits max(cadence, 2 x the previous estimate); spacings "
        f"{', '.join(k.secs(x) for x in sorted(set(sp)))} s, so the polite channel speaks at most half the time "
        f"(§6.1: {k.val('SIM', 'fast.polite-share')} %)",
        f"At these figures the share term, not the 2 s cadence, sets the pace: "
        f"{k.val('SIM', 'fast.spacing-1s')} / {k.val('SIM', 'fast.spacing-2s')} / {k.val('SIM', 'fast.spacing-5s')} s "
        "under 1 / 2 / 5 s (D07-Q3)",
        f"Fields: {f['nq']} quote and {f['nm']} mark values at 10 Hz; T-32 / T-33 have no stream in this script; "
        "prints and whale prints are silent here (BQ-7, not opted in)",
        "Lanes: speech = [write, write + §5.1's estimate]; share wait = the second estimate before the next composite"])]
    p, md, pk = k.build(NN, [fr], blocks, per_row=1)
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()

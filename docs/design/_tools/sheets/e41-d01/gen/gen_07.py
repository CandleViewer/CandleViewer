"""Board 07 scr095-states: SCR-095 insufficient-sample (n < 20, the `14` caveat verbatim, stats still shown),
low-bucket (n < 5 marked in text), empty, no-match, loading and error."""
from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import s095  # noqa: E402
import wf  # noqa: E402
from wf import k  # noqa: E402

NN = 7
SEP = (datetime(2026, 9, 1, tzinfo=k.UTC), datetime(2026, 9, 30, 23, 59, 59, tzinfo=k.UTC))


def small_tag() -> tuple[str, list[k.Trade]]:
    """The first tag, in TAGS order, whose LIVE count is >= 5 and < 20 (the protocol's 12-trade view if it exists)."""
    cands = [(n, k.trades(tag=n)) for n, _c, _a in k.TAGS]
    exact = [c for c in cands if len(c[1]) == 12]
    return (exact or [c for c in cands if 5 <= len(c[1]) < 20])[0]


def insufficient(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    tag, rs = small_tag()
    cav = wf.notice("info", k.deck("caveat.sample"), f"n = {len(rs)}", s095.INNER, name="caveat (CMP-028 inline)")
    coh = k.text("cohort", k.ui(f"Cohort: a LIVE subset — LIVE trades tagged '{tag}', {len(rs)} trades (not the DEMO "
                                f"set; board 08 shows DEMO)"), k.BODY, k.TEXT_1, w=s095.INNER)
    sm = s095.summaries(rs)
    cw = s095.HALF - 24
    row = k.hbox("charts row 1", [wf.chart_card(k.ui("Equity and drawdown"), wf.equity_chart(rs, cw), sm["equity"],
                                                s095.HALF),
                                  wf.chart_card(k.ui("R distribution"), wf.histogram(rs, cw), sm["hist"], s095.HALF)],
                 {"gap": k.INSET_LG, "align": "start"}, w=s095.INNER)
    k.derive(f"insufficient sample: tag '{tag}' holds {len(rs)} LIVE trades (< 20) in the range — the protocol's "
             "12-trade view")
    return (k.frame(fid, [s095.screen(body=[coh, cav, s095.stat_cards(rs, "LIVE"), row], filt={"tag": tag})],
                    wf.SCREEN_W, "SCR-095 insufficient-sample — fewer than 20 trades: the caveat is shown and every "
                                 "statistic stays, each with its n"),
            k.frame_block(fid, ["The checklist's '12 trades - not statistically meaningful' and `13`'s empty "
                                "treatment are superseded by `14`:2205's caveat (memo C-1, BQ-8)"],
                          wds=["WD-3", "WD-14"]))


def low_bucket(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    rs = k.trades()
    low = [(n, len(r)) for n, r in k.breakdown(rs, "tag") if len(r) < 5]
    k.derive(f"low buckets (n < 5) by tag: {', '.join(f'{n} {c}' for n, c in low)}")
    card = k.vbox("breakdown (full width)", [s095.breakdown_card(rs)], {}, w=s095.HALF)
    name0, rs0 = next((n, r) for n, r in k.breakdown(rs, "tag") if len(r) < 5)
    s0 = k.stats(rs0)
    said = (f"{name0}, {k.deck('caveat.bucket', n=s0.n)}, win rate {k.pct(s0.win_rate)}, expectancy "
            f"{k.rfmt(s0.expectancy)}, net P&L {k.usdt(s0.net)}")
    side = k.vbox("reading", [wf.hidden("row read by a screen reader", said, s095.HALF)], {"gap": k.STACK_SM},
                  w=s095.HALF)
    return (k.frame(fid, [s095.screen(body=[s095.stat_cards(rs, "LIVE"), k.hbox(
        "row", [card, side], {"gap": k.INSET_LG, "align": "start"}, w=s095.INNER)])], wf.SCREEN_W,
                    "SCR-095 low-bucket — a breakdown row with fewer than 5 trades carries the words and its count, "
                    "not a colour"),
            k.frame_block(fid, [], wds=["WD-4"]))


def empty(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    rs = k.trades(frm=SEP[0], to=SEP[1])
    assert not rs
    rng = k.day_range(*SEP)
    body = [wf.empty_state(k.deck("empty.range"), None, s095.INNER)]
    return (k.frame(fid, [s095.screen(body=body, filt={"range": rng})], wf.SCREEN_W,
                    "SCR-095 empty — no trades in the range: no statistic, no chart"),
            k.frame_block(fid, [f"Range {rng}: 0 trades (derived)", "`14` SCR-095 States: empty"]))


def no_match(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    sym, tag = k.no_match_filter()
    body = [wf.empty_state(k.deck("empty.filter"), None, s095.INNER, actions=[wf.btn(k.ui("Clear filters"))])]
    return (k.frame(fid, [s095.screen(body=body, filt={"symbol": sym, "tag": tag})], wf.SCREEN_W,
                    "SCR-095 no-match — the cohort matches no trade"),
            k.frame_block(fid, [f"{sym} + {tag}: 0 LIVE trades (derived)"]))


def loading(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    cw = (s095.INNER - 6 * 8) // 7
    body = [k.hbox("cards", [wf.skel_block(f"card {i + 1}", cw, 64) for i in range(7)], {"gap": k.INSET_SM}, h=64,
                   w=s095.INNER),
            k.hbox("charts", [wf.skel_block("chart 1", s095.HALF, 240), wf.skel_block("chart 2", s095.HALF, 240)],
                   {"gap": k.INSET_LG}, h=240, w=s095.INNER),
            wf.hidden("status (polite live region)", k.ui("Loading analytics"), 360)]
    return (k.frame(fid, [s095.screen(body=body)], wf.SCREEN_W, "SCR-095 loading — static skeletons, no partial "
                                                                "figures"),
            k.frame_block(fid, ["`14` SCR-095 States: loading"]))


def error(fid: str) -> tuple[k.Node, tuple[str, list[str]]]:
    body = [wf.notice("danger", k.ui("Analytics could not be loaded", "no error string in §7.1"), None, s095.INNER,
                      actions=[wf.btn(k.ui("Retry"), glyph="refresh")], name="CMP-028 notice")]
    return (k.frame(fid, [s095.screen(body=body)], wf.SCREEN_W, "SCR-095 error — the read failed; no stale figure"),
            k.frame_block(fid, ["memo §7 frame list: error"]))


def frames() -> tuple[list[k.Node], list[tuple[str, list[str]]]]:
    out = [f(fid) for f, fid in zip((insufficient, low_bucket, empty, no_match, loading, error), k.BOARDS[NN].frames)]
    return [a for a, _b in out], [b for _a, b in out]


if __name__ == "__main__":
    wf.run(NN, frames(), 2)

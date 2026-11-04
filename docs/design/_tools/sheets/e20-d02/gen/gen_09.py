"""Board 09 scr045-delta-export: SCR-045/deepstats-columns, -exporting, -export-cancelled (§7)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import ui  # noqa: E402
from ui import k  # noqa: E402

NN = 9
EXISTING = ("time", "open", "high", "low", "close", "vol", "delta", "cvd")  # 14:1097's sketch words (copy gap)
REPEATED = ("Delta", "Cumulative Delta")  # already existing columns: not repeated (§7.1, D02-OQ3)
EXPORT_N = 86_400  # kit: a 60-day 1m range, over the job threshold
EXPORT_P = 40  # kit: the job's progress when drawn


def deep_cols() -> list[str]:
    return [x for x in ui.DEFAULT if x not in REPEATED]


def table() -> k.Node:
    cols = [k.Col("time", k.ui(EXISTING[0], "SCR-045's existing column (14:1097 sketch)"), 104)]
    cols += [k.Col(c, k.ui(c, "SCR-045's existing column (14:1097 sketch)"), 96 if c in ("open", "high", "low",
                                                                                          "close", "cvd") else 80,
                   typo=k.NUM_XS, align="right") for c in EXISTING[1:]]
    for lab in deep_cols():
        u = {"pct": "%"}.get(k.UNIT[lab], k.unit_word(lab))
        head = f"{lab} ({u})" if u else lab
        cols.append(k.Col(k.safe(lab), head, max(96, round(k.text_w(head, k.CAPTION)) + 24), typo=k.NUM_XS,
                          align="right"))
    tick = k.INSTR[k.SYM][0]
    rows = []
    for b in k.window(16):
        r = {"time": f"{b.t} · {k.W('W-7')}" if b.forming else b.t, "open": f"{b.o.quantize(tick):,}",
             "high": f"{b.h.quantize(tick):,}", "low": f"{b.l.quantize(tick):,}", "close": f"{b.c.quantize(tick):,}",
             "vol": k.value("Total Volume", b), "delta": k.value("Delta", b), "cvd": k.value("Cumulative Delta", b)}
        for lab in deep_cols():
            r[k.safe(lab)] = k.value(lab, b)
        rows.append(r)
    return dict(k.grid_table("CMP-049 Table · SCR-045", cols, rows, row_h=28), x=16, y=104)


def header(state: str) -> list[k.Node]:
    title = k.ui(f"{k.SYM} 1m · table view (visible range)", "SCR-045's title (14:1093 sketch)")
    exp = k.S("Export CSV")
    if state == "exporting":
        btn = ui.hbox("CMP-099 Export CSV · busy", [ui.icon("pending", "pending", k.TEXT_2, k.ICON_SM),
                                                    ui.text("label", exp, k.BODY_STRONG, k.TEXT_1)],
                      {"gap": k.INSET_XS, "padX": k.BUTTON_PADX, "fill": k.RAISED, "stroke": k.BORDER,
                       "strokeWidth": k.HAIR, "strokeAlign": "inner", "radius": k.R_CONTROL}, w=128, h=32,
                      note="CMP-099 loading (15:1106); aria-busy; focus has moved to Cancel")
    else:
        btn = ui.button(exp, name="CMP-099 Export CSV", focused=state == "cancelled",
                        note="CMP-099 PrintExportBar's one button (14:1110)")
    out = [ui.box("SCR-045 header", [ui.text("title", title, k.HEADING_SM, k.TEXT_1, x=16, y=16),
                                     dict(btn, x=k.WIN_W - 16 - btn["w"], y=8 if state != "cancelled" else 4),
                                     ui.rect("rule", k.WIN_W, 1, k.BORDER, x=0, y=47)],
                  {"fill": k.RAISED}, w=k.WIN_W, h=48, x=0, y=0)]
    if state == "exporting":
        w19 = k.W("W-19", n=f"{EXPORT_N:,}", p=EXPORT_P)
        track = 320
        bar = ui.box("CMP-028 progress", [ui.rect("track", track, 8, k.SUNKEN, x=0, y=0),
                                          ui.rect("fill", round(track * EXPORT_P / 100), 8, k.TEXT_2, x=0, y=0)],
                     {}, w=track, h=8, x=16, y=64, note=f"progressbar, aria-valuenow {EXPORT_P}, aria-valuetext "
                                                         f"updated at most every 5 s or 10 % step")
        out += [bar, ui.text("progress words (W-19)", w19, k.CAPTION, k.TEXT_1, x=16 + track + 16, y=58),
                dict(ui.button(k.S("Cancel"), focused=True, name="Cancel (separate)"), x=k.WIN_W - 16 - 84, y=52)]
    if state == "cancelled":
        out.append(ui.text("status (W-20)", k.W("W-20"), k.BODY, k.TEXT_1, x=16, y=60,
                           note='role="status"; no file downloads'))
    return out


def frame(fid: str, state: str, markers: list[k.Node]) -> k.Node:
    return k.frame(fid, [*header(state), table(), *ui.stack(markers, 720, 640)])


def columns() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-045/deepstats-columns"
    k.spec_gap("§7.1 names only Delta and Cumulative Delta as not repeated, so Total Volume is added beside the existing "
               "vol column (the same number twice): for E20-S04 / D02-OQ3")
    return frame(fid, "idle", [ui.note_marker(k.ui(
        "added after cvd, in strip order: " + ", ".join(deep_cols()), "board-marker note"))]), k.frame_block(fid, [
        "The enabled rows become columns after CVD, in strip order, each headed by its §7 label and unit (MEMO AD-4, "
        "A8; E20-S04); the existing time, OHLC, volume, delta and CVD columns are untouched (14:1097)",
        "Delta and Cumulative Delta already show as existing columns and are not repeated (§7.1, D02-OQ3)",
        "CSV is CMP-099 PrintExportBar in the header (14:1110): one button, \"Export CSV\""])


def exporting() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-045/exporting"
    k.derive(f"the job: {EXPORT_N:,} bars (kit: a 60-day 1m range) > the {k.EXPORT_JOB:,}-bar job threshold; "
             f"{EXPORT_P} % done when drawn")
    return frame(fid, "exporting", [ui.announce(k.W("W-25", n=f"{EXPORT_N:,}"), how="polite, once, at start")]), \
        k.frame_block(fid, [
            "A range over the job threshold runs as a job (11:1961): a progress bar and a separate Cancel, in "
            "SCR-030's rebuild pattern (14:761); the visible text W-19",
            "When Export CSV is busy focus moves to Cancel (drawn); it returns to Export CSV on finish, cancel and "
            "failure; W-26 at the end, W-27 on failure (with Retry; named, not drawn)",
            "The job path is D02-G4 (no endpoint invented); CMP-099 has no progress or cancel (D02-G5)"])


def cancelled() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-045/export-cancelled"
    return frame(fid, "cancelled", [ui.announce(k.W("W-20"), how="polite, once")]), k.frame_block(fid, [
        "On cancel W-20; no file downloads: a cancelled job leaves no partial artefact reachable by the download URL "
        "(E20.json:448)", "Focus returns to Export CSV (drawn)",
        "Not drawn (§0): SCR-045/export-insufficient-role (E20-D03), SCR-045/export-failed (§7.2)",
        "Not drawn (§0 lists no finished frame): W-26, \"Export of {n} bars finished. Download started.\", the polite announcement at the end of a job (§7.2); the text is binding"])


if __name__ == "__main__":
    ui.run(NN, [columns(), exporting(), cancelled()], 2)

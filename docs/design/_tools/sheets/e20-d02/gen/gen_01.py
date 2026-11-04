"""Board 01 strip-default-allrows: SCR-030/strip-Default, -AllRows, -WithSparklines, -sparkline-guard (§3.2,
§3.3, §3.5)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I leaves this folder off sys.path
import ui  # noqa: E402
from ui import k  # noqa: E402

NN = 1
SPARK_ON = ("Delta", "Cumulative Delta")  # kit: the two rows whose sparkline switch is on (WithSparklines)
# kit: seven sparkline switches on (more than six), in the order they were enabled; the last three draw (`11`:1941)
GUARD_ORDER = ("Delta", "Delta %", "Total Volume", "# Trades", "Cumulative Delta", "Max Delta", "Min Delta")


def default() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-030/strip-Default"
    return ui.chart(fid, ui.P()), k.frame_block(fid, [
        "MEMO AD-1's five, in order, the top row nearest the bars: " + ", ".join(ui.DEFAULT) + " (§3.2)",
        "Thresholds on, the Global set named (W-1); the world's breached cells carry word, glyph slot and shade (§3.6)",
        *[k.source_line(x) for x in ui.DEFAULT]])


def allrows() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-030/strip-AllRows"
    return ui.chart(fid, ui.P(rows=ui.ALL12)), k.frame_block(fid, [
        f"{k.CEILING} rows, MEMO §5's ranks 1–12 in order (§3.3); the ceiling, not a cap: a 13th row renders (D02-C2, "
        f"D02-OQ1); E20-K01 measures at 5 and 13",
        "The other 8, enable-able in SCR-033: " + ", ".join(k.OTHER_8),
        *[k.source_line(x) for x in ui.ALL12[5:]]])


def sparklines() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-030/strip-WithSparklines"
    return ui.chart(fid, ui.P(spark=SPARK_ON)), k.frame_block(fid, [
        f"CMP-024 per row, right of the label: the last N = {k.SPARK_N} values (SCR-033's stepper default, "
        f"11:1934); its aria-label summarises the trend (15:294)",
        f"Sparkline switch on for {', '.join(SPARK_ON)} (kit choice); the per-row switch is PROPOSED (§6.2, D02-A4)"])


def guard() -> tuple[k.Node, tuple[str, list[str]]]:
    fid = "SCR-030/strip-sparkline-guard"
    drawn = GUARD_ORDER[-k.GUARD_DRAW:]
    words = k.W("W-18", rows=", ".join(drawn))
    p = ui.P(rows=ui.ALL12, spark=drawn, callout=words, markers=[ui.announce(words)])
    return ui.chart(fid, p), k.frame_block(fid, [
        f"{len(GUARD_ORDER)} rows' sparklines on (more than {k.GUARD_MAX}), enabled in this order: "
        f"{', '.join(GUARD_ORDER)}; only the {k.GUARD_DRAW} most recently enabled draw (11:1941)",
        "CMP-028 inline callout above the strip, announced once, politely, when it appears (§3.5)"])


if __name__ == "__main__":
    ui.run(NN, [default(), allrows(), sparklines(), guard()], 2)

"""Board 6D: Not trading, LUNAUSDT Closed, Owner, compact (AC 3): notice, delisted chip, live band replaced."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from a_helpers import R2_CREDIT, emit, k, strings_block  # noqa: E402

KEY = "6D"


def build(theme: str = "dark") -> tuple[list, dict]:
    key = f"6{'D' if theme == 'dark' else 'L'}"
    k.NOTES.reset()
    fr = k.frames_of(key)[0]
    frame = k.drawer_frame(fr, theme, "d06")
    ru = k.rules("LUNAUSDT")
    k.derived("LUNAUSDT rules by the §5 F3 formatter on instruments_after.json: "
              + ", ".join(f"{a} {b}" for a, b in ru.items()))
    blk = k.frame_block(fr, lines=[
        "Status row in words; the contract band stays fully legible; Open in new chart is the only action"])
    luna = k.FX["instruments"]["LUNAUSDT"]
    l_tick = k.L("Price must be a multiple of 0.1 · 50,000.04")
    l_row = k.L("| LUNAUSDT (fixture, Closed)")
    extra = {
        ru["identity"]: f"(L{k.L('| BTC / USDT · USDT perpetual')}'s identity line with the fixture's LUNAUSDT: "
                        f"base {luna['base']}, launch {luna['launch']} ms)",
        f"Price must be a multiple of {ru['tick']} · 0.123456 → 0.1235 (nearest)":
            f"(L{l_tick}'s example form with L{l_row}'s LUNAUSDT row: tick 0.0001, 0.123456 → 0.1235)",
        luna["base"]: "(the fixture's base coin, the quantity unit as BTC is at L66)",
    }
    ann = k.annotations(key, [blk, strings_block([frame], extra),
                              *[k.marker_block(m) for m in k.R2_BOARDS[6]["markers"]]], board_lines=[R2_CREDIT])
    return [frame], ann


if __name__ == "__main__":
    f, a = build("dark")
    emit(KEY, f, a, notes={"live_checks": [
        "board 6D: the footer holds one button (Open in new chart); no Open DOM ladder",
        "board 6D: the danger notice sits under the identity line inside the sticky header"]})

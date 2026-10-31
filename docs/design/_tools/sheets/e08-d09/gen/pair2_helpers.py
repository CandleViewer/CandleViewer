"""Pair B helpers (boards 05 clock and 09 clock-light): the summary strip and the §10 Clock section in each state.
Every string comes from E08-D09.md through the kit (k.w / k.state_word / k.L); nothing here edits the kit."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import e08d09kit as k  # noqa: E402

Node = dict[str, Any]


def cite(key: str) -> str:
    """'W-38 (§15 L454)': a copy key with its spec line."""
    return f"{key} (§15 L{k.COPY[key].line})"


def secs(ms: int) -> str:
    """W-38's size slot: the offset in seconds, two decimals (620 -> '0.62'); derived from the frame's ms."""
    return k.offset_s(ms)


def offset_sentence(ms: int, direction: str) -> str:
    """W-38: the size and a direction word, never a sign (§10 Fields)."""
    return k.w("W-38", 0 if direction == "behind" else 1, secs(ms))


# The illustrative clock world (one clock: k.AS_OF = 14:02:11; every time derived with k.at / k.ago)
MEASURED_S = 128  # last measurement 128 s before AS_OF: 14:00:03 "(2m ago)" (W-39's own sample); < 300 s, < 900 s
COOLDOWN_LEFT_S = 20  # W-36b's slot; the re-measure ran 10 s before AS_OF
REMEASURED_S = 10
OK_MS, OK_DIR = 12, "ahead"  # after the re-measure (W-29's sample size 12 ms)


def tiles(clock_sid: str | None, clock_number: str | None, clock_status: Node | None = None) -> Node:
    """The five CMP-178 tiles (§2.2 item 2). Only Clock varies on this board; the others are fixed across the frames:
    REST budget and Private streams in S-19 (D09-G1), Public market data served "Within budget" with W-52's
    connection count, IP hold served "Within budget" (D09-G13 assumed served)."""
    tw = k.tile_widths()
    h = k.TILE_HEADINGS
    return k.summary_strip([
        k.tile(h[0], None, None, w_=tw[0], gid="D09-G1"),
        k.tile(h[1], "S-01", k.w("W-52", 0, 3), w_=tw[1]),
        k.tile(h[2], None, None, w_=tw[2], gid="D09-G1"),
        k.tile(h[3], clock_sid, clock_number, w_=tw[3], status=clock_status),
        k.tile(h[4], "S-01", None, w_=tw[4]),
    ])


def remeasure(mode: str) -> Node:
    """The Re-measure now button (W-35; §10 L357): idle, busy (aria-busy, "Measuring…") or cooldown (T2-3, W-36b)."""
    if mode == "idle":
        return k.button(k.w("W-35", 0), "secondary", name="button · Re-measure now")
    if mode == "busy":
        return k.ring(k.busy_button(k.w("W-35", 1), "secondary", name="button · Re-measure now (busy)"))
    if mode == "cooldown":
        return k.t2_button(k.w("W-35", 0), k.w("W-36b", None, COOLDOWN_LEFT_S), focused=True,
                           name="T2 · Re-measure now + reason")
    raise ValueError(mode)


LABELS = k.CLOCK_LABELS


def clock_section(sid: str | None, *, ms: int | None, direction: str = "behind", measured_s: int | None = MEASURED_S,
                  lines: list[str] = (), button: str = "idle") -> Node:
    """§10 as a dl of CMP-036 rows (§17.1 L517): the state (word + glyph + origin), the offset (W-38, or W-23's
    sentence when unmeasured), the last measurement (W-39 second piece), next due (W-39 first piece); then the state's lines
    (W-37, W-22, W-27, W-23) and the Re-measure button. sid None = the ok state (W-29, no S-id)."""
    if sid is None:
        st = k.clock_ok_status(ms, direction)
    else:
        st = k.state_line(sid, name="state")
    rows = [k.kv_row("row · state", LABELS[0], st)]
    if ms is None:
        rows.append(k.kv_row("row · offset", LABELS[1], k.w("W-23", 1)))
    else:
        rows.append(k.kv_row("row · offset", LABELS[1], offset_sentence(ms, direction), numeric=True))
    if measured_s is not None:
        rows.append(k.kv_row("row · last measured", LABELS[2],
                             k.w("W-39", 1, k.at(-measured_s), k.ago(measured_s)), numeric=True))
    rows.append(k.kv_row("row · next due", LABELS[3], k.w("W-39", 0)))
    dl = k.vbox("CMP-036 dl · clock", rows, None, w=k.INNER_W, note="dl of CMP-036 rows (§17.1)")
    kids: list[Node | None] = [dl]
    if lines:
        kids.append(k.lines_block("clock lines", lines, w_=k.INNER_W - 16))
    kids.append(k.hbox("clock actions", [remeasure(button)], {"gap": k.INSET_SM}, w=k.INNER_W))
    k.copy_gap(f"clock dl labels {', '.join(repr(x) for x in LABELS)}: §10 Fields L{k.L('- **Fields (T:24):**')} names "
               f"the fields (offset, last measured, next due, the alarm state) but §15 gives no dt string")
    return k.section("Clock", kids, waits=["D09-G5", "D09-G6"])


def crop_note() -> None:
    k.deviate("board 05 / 09 windows draw the page's band, header, summary strip and the Clock section only (§2.2 "
              f"L{k.L('6. **Clock.**')}): Rate budgets, the simulator and the inspector, which sit between them, are "
              "left out so the clock is in the 672 px view (a focus crop; board 01 draws the whole page)")

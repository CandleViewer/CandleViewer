"""Board 04 ws-states (§0): S-06 disconnected, S-07 reconnecting (attempt count), S-08 resubscribe storm, S-20
dropping updates, and the Force reconnect dialog (§11). Run: python3 -I -B gen_04.py"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pair5_helpers as h  # noqa: E402
from pair5_helpers import cw, k  # noqa: E402

NN = 4
LAST_DATA_S = 12  # S-06: last data 12 s before as of
ATTEMPT = 3  # S-07: the attempt in progress
STORM_S, STORM_RECONN = 3, 4  # S-08: socket 1 resubscribed 3 s ago; 4 reconnects in the last hour
DROPPED = 12  # S-20: updates dropped in the last minute


def mmss(s: int) -> str:
    return f"{s // 60:02d}:{s % 60:02d}"


def frame(fid: str, theme: str, sections: list, *, overlays=()):  # noqa: ANN001, ANN202
    return k.window(fid, theme, sections, scroll=h.fit_scroll(sections), overlays=overlays)


def build(theme: str = "dark") -> tuple[list, dict]:
    fids = [f for f, _s in k.frames_of(NN)]
    frames, blocks = [], []
    kb_insp = "Tab to the inspector disclosure, Enter / Space opens it, arrows move in the grid (SCR-147-KB-6)"
    kb_rec = "Tab to Reconnect market data; Enter / Space opens the confirm (SCR-147-KB-1, PP-1)"

    # S-06: socket 1 disconnected; sockets 2 and 3 healthy
    h.start()
    s1 = h.conn_row(1, h.conn_state("S-06", cw("W-18", 1, mmss(LAST_DATA_S))), since=k.at(-h.SINCE_S), reconn=0,
                    ping=h.PING_MS[0], old="disconnected")
    secs = [h.tiles(public_sid="S-06"), h.inspector([s1, h.healthy_row(2), h.healthy_row(3)]),
            h.actions(h.reconnect_trigger())]
    frames.append(frame(fids[0], theme, secs))
    blocks.append(k.frame_block(fids[0], waits=["D09-G3", "D09-G7"], recovery=True, keyboard=f"{kb_insp}; {kb_rec}",
                                lines=[f"Last data {k.at(-LAST_DATA_S)} = as of {k.AS_OF} - {LAST_DATA_S} s, shown as "
                                       f'W-18\'s "{mmss(LAST_DATA_S)} ago" (derived)',
                                       "Socket 1's old values (topics, connected since, reconnects, ping) bind "
                                       "color.data-confidence.disconnected.text (§16)",
                                       f"Tile: the worst connection state (§5.2 precedence); {h.SOCKETS} sockets x "
                                       f"{h.TOPICS_PER_SOCKET} topics = {h.TOPICS} topics (W-44, W-52)",
                                       "Reconnect market data stays enabled: the origin's action line (W-12)",
                                       h.copy_line()]))

    # S-07: socket 1 reconnecting, attempt 3
    h.start()
    s1 = h.conn_row(1, h.conn_state("S-07", figures=(cw("W-19", 1, ATTEMPT),)), since=k.at(-h.SINCE_S), reconn=0,
                    ping=h.PING_MS[0], old="reconnecting")
    secs = [h.tiles(public_sid="S-07"), h.inspector([s1, h.healthy_row(2), h.healthy_row(3)]),
            h.actions(h.reconnect_trigger())]
    frames.append(frame(fids[1], theme, secs))
    blocks.append(k.frame_block(fids[1], waits=["D09-G3", "D09-G7"], recovery=True, keyboard=kb_insp,
                                lines=[f"Attempt {ATTEMPT} in progress; reconnects in the last hour count completed "
                                       "reconnects only (0)",
                                       "Socket 1's old values bind color.data-confidence.reconnecting.text (§16)",
                                       "Attempts re-announce nothing; re-entries within 5 s collapse into "
                                       '"Connection unstable" (SR-6)', h.copy_line()]))

    # S-08: socket 1 resubscribing more than once inside 5 s
    h.start()
    s1 = h.conn_row(1, h.conn_state("S-08"), since=k.at(-STORM_S), reconn=STORM_RECONN, ping=h.PING_MS[0])
    secs = [h.tiles(public_sid="S-08"), h.inspector([s1, h.healthy_row(2), h.healthy_row(3)],
                                                    waits=("D09-G3", "D09-G4")), h.actions(h.reconnect_trigger())]
    frames.append(frame(fids[2], theme, secs))
    blocks.append(k.frame_block(fids[2], waits=["D09-G3", "D09-G4", "D09-G7"], keyboard=kb_insp,
                                lines=[f"Connected since {k.at(-STORM_S)} = as of - {STORM_S} s: the last "
                                       f"resubscribe, inside D04's 5 s window; {STORM_RECONN} reconnects in the last "
                                       "hour (derived)",
                                       "The resubscribe counter is not in a read (D09-G4); trigger PROPOSED (D09-Q2)",
                                       h.copy_line()]))

    # S-20: our queue dropping updates (bus-level; every socket healthy)
    h.start()
    inner = h.strip_inner()
    sent = k.text("sentence (W-28)", cw("W-28", 1, DROPPED), k.CAPTION, k.TEXT_1, w=inner)
    secs = [h.tiles(public_sid="S-20", extra=[sent]), h.inspector([h.healthy_row(i) for i in (1, 2, 3)],
                                                                  waits=("D09-G3", "D09-G4")),
            h.actions(h.reconnect_trigger())]
    frames.append(frame(fids[3], theme, secs))
    blocks.append(k.frame_block(fids[3], waits=["D09-G4"], suppressed=["S-01"], keyboard=kb_insp,
                                lines=[f"{DROPPED} updates dropped in the last minute (illustrative; drop counters are "
                                       "Prometheus only, D09-G4)",
                                       "Every socket stays healthy: the drop is our backend's queue, not the "
                                       "network (origin Our backend)", h.copy_line()]))

    # Force reconnect dialog over a healthy page (inspector closed, Actions with the private placeholder)
    h.start()
    dlg = h.reconnect_dialog()
    secs = [h.tiles(), h.inspector([], open_=False), h.actions(h.reconnect_trigger(), [h.private_placeholder()])]
    frames.append(frame(fids[4], theme, secs, overlays=k.modal(dlg, measured_h=380)))  # h as drawn (live SHEET-FIX)
    blocks.append(k.frame_block(fids[4], waits=["D09-G7", "D09-G12", "D09-G17"],
                                keyboard="SCR-147-KB-1: focus on Cancel; Tab; Enter confirms; Esc = Cancel, focus back "
                                         "to the trigger",
                                lines=["Rung 2, no typed token (§11, RULED BQ-13); role alertdialog; contract-first: "
                                       "no route (D09-G7)",
                                       f"Blast radius {h.SOCKETS} connections, {h.TOPICS} topics: the same world as the "
                                       "inspector's disclosure (W-44)",
                                       f'After confirm, per connection: "{k.w("W-59", 0)} · '
                                       f'{k.w("W-59", 1, h.TOPICS_PER_SOCKET)}" (W-59); SCR-147-SR-12 polite: '
                                       f'"{k.w("W-58", None, h.TOPICS)}"',
                                       f'T2 (not drawn here): under S-04 / S-05 "{k.w("W-36")}"; connection budget '
                                       f'"{k.w("W-57", None, 40)}" (SCR-147-T2-1)',
                                       "Private stream row: W-53 placeholder in S-19 (§11)", h.copy_line()]))

    ann = k.annotations(NN, blocks, board_lines=[
        "Each frame draws the regions its state touches (summary strip, inspector, Actions) in §2.2's order; the "
        "other sections are off the frame (board 01 draws the whole page)",
        "Healthy connection rows read S-01 \"Within budget\" (§5.2 has no connected word; see spec gaps)"])
    k.deviate("board 04: frames draw the summary strip, the inspector (open on the state frames) and Actions only; "
              "the clock section between them is off the frame (§2.2 order kept)")
    k.spec_gap("connection rows: §5.2 gives no 'connected' word; healthy socket rows use S-01 \"Within budget\" (W-13), "
               "SR-9's \"Market data connected.\" is an announcement only")
    k.deviate("W-36 / W-57 T2 forms of Reconnect market data are named in the annotation only on board 04 (board 03 "
              "draws W-36; board 06 draws the view-as form)")
    return frames, ann


def main(theme: str = "dark", nn: int = NN) -> None:
    frames, ann = build(theme)
    k.live("S-06 frame: read back socket 1's word 'Disconnected — last data 00:12 ago' and its old values in "
           "color.data-confidence.disconnected.text")
    k.live("Force reconnect dialog: read back the focus ring on Cancel and the W-55 marker as the last line before "
           "the buttons")
    p = k.write_sheet(nn, frames, ann)
    md = k.write_md(nn, p)
    packed = k.pack_sheet(p)
    rc, msg = k.validate(p)
    print(p, md, packed, f"validator exit {rc}: {msg.splitlines()[-1] if msg else ''}", sep="\n")


if __name__ == "__main__":
    main()

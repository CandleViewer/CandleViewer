"""Board 05 `E47-D07 / 05 focus-kept` (dark): §9 — focus and the typed price kept in the order ticket when a reject is
announced; the auto-flatten's `alertdialog`, the one exception (`05`:96), focus on its safe button."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k  # noqa: E402

NN = 5
S9 = k.L("## 9. Focus and persistence") + 2
TYPED = re.search(r'"(\d+)" typed', k.SPEC_LINES[S9 - 1]).group(1)  # §9: "6400" typed
MAIN_W = k.FRAME_W - k.NAV_W
TICKET_W = 320


def event_text(tid: str) -> str:
    return next(i.text for i in k.items("incident") if i.kind == "event" and i.tid == tid)


def ticket(*, focused: bool) -> dict:
    k.fallback("chrome")
    k.copy_gap('"Order ticket" and "Price": the ticket\'s heading and its price field\'s label (§9 names "the order '
               'ticket\'s price field"; the ticket is E11\'s, its other controls are placeholders here)')
    return k.vbox("order ticket", [
        k.text("h", "Order ticket", k.HEADING_SM, k.TEXT_1),
        k.placeholder("side and type", TICKET_W - 32, 28),
        k.field("Price", TYPED, wd=TICKET_W - 32 - (12 if focused else 0), focused=focused, caret=focused),
        k.placeholder("quantity", TICKET_W - 32, 28),
        k.placeholder("submit button", 120, 28),
        k.box("local alert (empty)", [], None, w=TICKET_W - 32, h=8,
              note='the ticket\'s own role="alert", pre-rendered empty (§2 kind 1)')],
        {"gap": k.STACK_MD, "pad": k.INSET_LG, "fill": k.RAISED, "radius": k.R_CARD}, w=TICKET_W,
        note=f'the ticket stays open; the price field holds "{TYPED}"' + (" with focus and the caret in place"
                                                                       if focused else ""))


def workspace(extra: list[dict]) -> dict:
    focused = bool(extra)  # the reject frame passes its toast (focus in Price); the dialog frame passes none
    chart = k.box("chart panel (placeholder)", [k.placeholder("chart", MAIN_W - TICKET_W - 72, 640)], None,
                  w=MAIN_W - TICKET_W - 48, h=660, x=16, y=16)
    return k.box("workspace", [chart, dict(ticket(focused=focused), x=MAIN_W - TICKET_W - 16, y=16), *extra], None,
                 w=MAIN_W, h=k.BODY_H)


def frame_reject(fid: str) -> dict:
    t3 = event_text("T-3")
    tst = dict(k.toast(t3, persistent=False, wd=360), x=MAIN_W - TICKET_W - 16 - 360 - 16, y=16)
    content = workspace([tst])
    tx = k.NAV_W + MAIN_W - TICKET_W - 16
    tags = [k.tag(f'focus stays in Price; the value "{TYPED}" and the caret unchanged (R-7)', tx - 140,
                  k.TOP_H + 278, name="tag · focus kept"),  # 8 px below the ticket card's bottom (the render's call)
            k.tag("T-3 spoken once from the pair; the toast appears without focus", k.NAV_W + 300, k.TOP_H + 120,
                  name="tag · toast"),
            k.tag("CMP-060 entry written (R-8)", k.NAV_W + 300, k.TOP_H + 140, name="tag · log")]
    return k.window(k.frame_name(fid), content, settings=False, overlays=[*tags, k.synthetic_tag(k.SHELL_TAG_X, k.FRAME_H - 40)],
                    note="the order ticket open with focus in its price field; a reject arrives")


def frame_dialog(fid: str) -> dict:
    w5 = event_text("T-17")
    acts = [k.button(k.w("W-41", 1), name="button · View position"),
            k.button(k.w("W-41", 0), name="button · Dismiss", focused=True)]
    dlg = k.dialog(k.w("W-40"), [k.text("description · W-5", w5, k.BODY, k.TEXT_1, w=k.DIALOG_W - 48,
                                        note="aria-describedby: W-5 with the event's slots")],
                   acts, name="CMP-044 alertdialog · auto-flatten",
                   note='role="alertdialog" aria-modal="true", aria-labelledby the title (W-40), aria-describedby W-5; '
                        "focus on Dismiss, the safe button (§9)")
    tags = [k.tag("the one exception (`05`:96): focus moves to Dismiss; the focus speech is T-17's queue item",
                  k.NAV_W + 16, k.TOP_H + 16, name="tag · exception"),
            k.tag(f'behind the scrim the ticket keeps "{TYPED}"; on close focus returns to Price (D04:289)',
                  k.NAV_W + 16, k.TOP_H + 36, name="tag · return")]
    return k.window(k.frame_name(fid), workspace([]),
                    settings=False, overlays=[k.modal(dlg), *tags, k.synthetic_tag(k.SHELL_TAG_X, k.FRAME_H - 40)],
                    note="the auto-flatten's alertdialog over the workspace")


def main() -> None:
    b = k.BOARDS[NN]
    frames = [frame_reject(b.frames[0]), frame_dialog(b.frames[1])]
    blocks = [
        (b.frames[0], [
            f"§9 L{S9}: an announcement never moves focus, never changes a field's value and never closes or resets a "
            f"form: with \"{TYPED}\" typed in the price field, the reject (T-3) is spoken, its log entry written, the "
            "toast shown without focus (T AC5; D04:286)",
            f"The reject's words: \"{event_text('T-3')}\" (W-3, the incident script's event)",
            "The toast is not persistent: T-3 is not in the attention set (R-8; `15`:531)"]),
        (b.frames[1], [
            "T-17's role=\"alertdialog\" opens when the queue reaches it (rank 1) and takes focus at once on its safe "
            f"button; title W-40 \"{k.w('W-40')}\", description W-5, buttons W-41 with focus on \"{k.w('W-41', 0)}\"",
            "The reader's focus speech is the queue's item; the pair does not also write W-5 (R-6); later queued "
            "messages are spoken from the pair while it is open and never move focus",
            "Its persistent toast is on board 04 (R-8); the ticket underneath keeps its typed value"]),
    ]
    p, md, pk = k.build(NN, frames, blocks, per_row=2)
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()

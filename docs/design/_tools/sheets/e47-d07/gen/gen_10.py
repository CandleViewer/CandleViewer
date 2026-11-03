"""Board 10 `E47-D07 / 10 copy-anatomy` (dark): §7.1 — a sentence is the class word, the fact with the symbol, the
qualifiers, then the account when more than one is in scope; the closed slots. W-1, W-3 and W-5 (hand-off §E) taken
apart, each filled from a §10 script's event, and W-3 with an unmapped reason (W-36)."""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k  # noqa: E402

NN = 10
PAD = 24
QUAL = (" at {price}", ", average", " Reason:")
PARTS = ("class word", "fact with the symbol", "qualifiers", "account")
TONE = dict(zip(PARTS, ("significant-assertive", "status-polite", "ambient-polite", "echo-polite")))
ACCOUNT = re.search(r"for account (\w+)", k.w("W-43")).group(1)  # "Main", W-43's verbatim example (D17:259)
ACCOUNT_T = " Account {account}."
EXAMPLES = (("W-1", "quiet", "T-1"), ("W-3", "fast", "T-3"), ("W-5", "incident", "T-17"))


def segments(tpl: str) -> list[tuple[str, str]]:
    cw_end = tpl.index(". ") + 1
    si = tpl.index("{symbol}") + len("{symbol}")
    qs = [tpl.find(q, si) for q in QUAL if tpl.find(q, si) >= 0]
    q0 = min(qs) if qs else len(tpl)
    out = [("class word", tpl[:cw_end]), ("fact with the symbol", tpl[cw_end:q0])]
    if q0 < len(tpl):
        out.append(("qualifiers", tpl[q0:]))
    return out


def fill(seg: str, slots: dict[str, str]) -> str:
    if "{reason}" in seg:
        words = k.REASONS.get(slots.get("reason", ""), "(W-36)")
        if words.startswith("(W-36"):
            seg = seg.replace("Reason: {reason}.", k.w("W-36"))
        else:
            slots = dict(slots, reason=words)
    for a, v in slots.items():
        seg = seg.replace("{" + a + "}", v)
    return seg


def event(sid: str, tid: str) -> tuple[dict, str]:
    ev = next(e for e in k.SCRIPTS[sid]["events"] if e["taxonomy"] == tid)
    txt = next(i.text for i in k.items(sid) if i.kind == "event" and i.tid == tid)
    return {a: str(v) for a, v in ev["slots"].items()}, txt


def chip_row(name: str, segs: list[tuple[str, str]], *, labels: bool) -> dict:
    chips = []
    for part, s in segs:
        kids = [k.text("words", s.strip(), k.BODY, k.TEXT_1)]
        if labels:
            kids.append(k.text("part", part, k.CAPTION, k.TEXT_2))
        chips.append(k.tagged_card(f"{part}", TONE[part], kids, round(max(k.text_w(s.strip(), k.BODY),
                                                                             k.text_w(part, k.CAPTION))) + 28))
    return k.hbox(name, chips, {"gap": k.INSET_XS, "align": "start"})


def build_frame(fid: str) -> tuple[dict, list[str]]:
    kids: list[dict] = [k.heading("h", f"The words (§7.1 L{k.GRAMMAR_LINE}): class word, fact with the symbol, "
                                       "qualifiers, account", PAD, PAD, 1100)]
    y, notes = 64, []
    for wid, sid, tid in EXAMPLES:
        tpl = k.w(wid)
        segs = segments(tpl)
        if "".join(s for _p, s in segs) != tpl:
            raise SystemExit(f"board 10: {wid}'s segments do not rebuild it")
        slots, txt = event(sid, tid)
        filled = [(p, fill(s, slots)) for p, s in segs]
        if "".join(s for _p, s in filled) != txt:
            raise SystemExit(f"board 10: {wid} filled from {sid} != the tool's text")
        kids.append(k.text(f"label · {wid}", f"{wid} ({tid}, the {sid} script's event)", k.LABEL, k.TEXT_2, x=PAD,
                           y=y))
        t_row = chip_row(f"template · {wid}", segs, labels=True)
        f_row = chip_row(f"filled · {wid}", filled, labels=False)
        kids += [dict(t_row, x=PAD, y=y + 20), dict(f_row, x=PAD, y=y + 20 + round(k.est_height(t_row)) + 6)]
        y += 20 + round(k.est_height(t_row)) + 6 + round(k.est_height(f_row)) + 20
        notes.append(f"{wid}: \"{txt}\"")
    # the account (R-10) and the unknown reason (W-36)
    slots, txt = event("quiet", "T-1")
    acc = segments(k.w("W-1")) + [("account", ACCOUNT_T)]
    accf = [(p, fill(s, dict(slots, account=ACCOUNT))) for p, s in acc]
    kids.append(k.text("label · account", f"W-1 with more than one account in scope (R-10; the account is "
                                          f"\"{ACCOUNT}\", W-43's example)", k.LABEL, k.TEXT_2, x=PAD, y=y))
    kids.append(dict(chip_row("filled · account", accf, labels=True), x=PAD, y=y + 20))
    y += 20 + round(k.est_height(chip_row("m", accf, labels=True))) + 20
    slots3, _t = event("fast", "T-3")
    unk = [(p, fill(s, dict(slots3, reason="NOT_A_CODE"))) for p, s in segments(k.w("W-3"))]
    kids.append(k.text("label · W-36", "W-3 with a code outside §7.3's map: the reason becomes W-36, the upstream "
                                       "text is never spoken (R-9)", k.LABEL, k.TEXT_2, x=PAD, y=y))
    kids.append(dict(chip_row("filled · unknown reason", unk, labels=False), x=PAD, y=y + 20))
    y += 20 + 40 + 16
    chips = [k.hbox(f"slot · {s}", [k.text("t", s, k.NUM_SM, k.TEXT_1)], {"padX": k.INSET_XS, "radius": k.R_BADGE,
                                                                       "stroke": k.BORDER, "strokeWidth": k.HAIR,
                                                                       "strokeAlign": "inner"}, h=20)
             for s in k.SLOTS]
    kids.append(k.text("label · slots", f"The closed slots ({len(k.SLOTS)}; R-9): nothing else fills a template",
                       k.LABEL, k.TEXT_2, x=PAD, y=y))
    kids.append(k.hbox("slots", chips, {"gap": k.INSET_XS, "wrap": "wrap"}, w=k.FRAME_W - 2 * PAD, x=PAD, y=y + 20))
    if y + 20 + 48 > k.FRAME_H - 36:
        raise SystemExit(f"board 10: the content ({y + 68} px) passes the frame")
    kids.append(k.synthetic_tag(PAD, k.FRAME_H - 28))
    return k.specimen(fid, kids), notes


def main() -> None:
    b = k.BOARDS[NN]
    fr, notes = build_frame(b.frames[0])
    para = k.plain(k.SPEC_LINES[k.GRAMMAR_LINE - 1])
    rules = [s.strip() for s in re.split(r"(?<=\.) (?=[A-Z`])", para) if s.startswith(("Signs", "Prices"))]
    blocks = [(b.frames[0], [
        f"§7.1 L{k.GRAMMAR_LINE}: the class word, then the fact with the symbol, then the qualifiers (price, reason), "
        "then \" Account {account}.\" when more than one account is in scope (R-10); \"symbol first\" reads as symbol "
        "first within the fact (D07-C4)", *rules,
        "Each filled row is the tool's rendering of the named script's event; the chips rebuild it exactly",
        *notes,
        "Read W-1, W-3 and W-5 aloud: each should be clear by ear on first hearing (hand-off §E)"])]
    k.NOTES.add("fallbacks", "kit choice: board 10 reuses the four class tones as part tones (class word, fact, "
                             "qualifiers, account); each chip names its part, so colour is not the only signal")
    k.ambiguity("Board 10: §7.1 names the four parts but not where the fact ends; the kit ends it at the first "
                "qualifier after the symbol (\" at {price}\", \", average\", \" Reason:\") or at its sentence's end")
    p, md, pk = k.build(NN, [fr], blocks, per_row=1)
    print(p.name, md.name, pk.name)


if __name__ == "__main__":
    main()

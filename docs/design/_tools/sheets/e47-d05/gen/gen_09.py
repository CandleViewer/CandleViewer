"""Board 09 `E47-D05 / 09 modified-reset-search` (dark): §10 — modified with the per-option Reset, the section-reset
preview dialog, and the search results with their section paths."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k, view_window  # noqa: E402

NN = 9
DIALOG_MEASURED_H = 178  # the live check measured the section-reset dialog at 440 x 178 (re-centred: y 311)
CHANGED = (("reduced_motion", "on"), ("disable_canvas_animation", "true"))
TOP = ("Motion", "Contrast and focus")
TERM = "motion"  # kit choice: a §10 synonym


def value_words(key: str, v: str) -> str:
    """A value in the row's own words: the tri-state radios (§5.1) or On / Off for a switch."""
    if key in k.TRI:
        return dict(zip(k.KEYS[key]["values"], k.TRI_OPTIONS))[v]
    return {"true": "On", "false": "Off"}[v]


def main() -> None:
    k.section_reading_note()
    b = k.BOARDS[NN]
    ps_mod = k.PS(values=CHANGED, focus="reset:reduced_motion", sections=TOP)
    ps_dlg = k.PS(values=CHANGED, sections=TOP)
    ps_srch = k.PS(search=TERM, focus="search", sections=TOP)
    lines = [f"{k.ROWS[key]['label']}: {value_words(key, v)} → {value_words(key, k.KEYS[key]['default'])}"
             for key, v in CHANGED]
    k.copy_gap('"On" / "Off" for a switch\'s value in the preview lines, and the dialog title "Reset this section" '
               '(§10 gives the line form "Label: current → default" and names the invoking button, not a title)')
    cancel = k.button("Cancel", ps_dlg, focused="normal")
    cancel = dict(cancel, note="initial focus (D04:299's destructive-confirm row; PROPOSED for a reset preview)")
    confirm = k.button(k.w("W-24", 1), ps_dlg, name="button · Reset (confirm)")
    k.copy_gap('"Cancel": the dialog\'s initial-focus button (§10 names it)')
    dlg = k.dialog("Reset this section", [k.vbox("changes", [k.text(f"change {i + 1}", ln, k.BODY, k.TEXT_1, w=380)
                                                             for i, ln in enumerate(lines)], {"gap": k.STACK_XS})],
                   [cancel, confirm])
    frames = [view_window(b.frames[0], ps_mod, note=b.frames[0]),
              view_window(b.frames[1], ps_dlg, overlays=[k.modal(dlg, measured_h=DIALOG_MEASURED_H)], note=b.frames[1]),
              view_window(b.frames[2], ps_srch, note=b.frames[2])]
    n = len(CHANGED)
    w28 = k.fill(k._quoted(k.COPY["W-28"].s)[0], n=str(n))
    k.NOTES.add("copy_keys", f"W-28 (§15 L{k.COPY['W-28'].line}, {k.COPY['W-28'].status}): {w28}")
    ms = k.search_matches(TERM)
    st = k.STATES
    blocks = [
        (b.frames[0], [
            f"§10 L{st['SCR-117/modified']['line']}: {st['SCR-117/modified']['shows']}",
            f"Two rows changed in Motion: {'; '.join(lines)} (current → default); each shows \"{k.w('W-24', 0)}\" in "
            "text and its Reset; the Reset of Reduced motion holds focus (CMP-039 normal), named \"Reset Reduced motion\"",
            "Reduced motion On makes the effective motion reduced: the motion tile shows its still frames (R-6)",
            f"\"Reset this section\" appears under the group while anything in it is modified (§12 L{k.L('## 12.')})"]),
        (b.frames[1], [
            f"§10 L{st['SCR-117/section-reset-preview']['line']}: {st['SCR-117/section-reset-preview']['shows']}",
            f"The CMP-043 dialog lists each change as \"Label: current → default\" ({n} lines); Cancel holds the initial "
            f"focus; confirming speaks \"{w28}\" (W-28) once",
            "On close focus returns to \"Reset this section\"; if it is gone (nothing modified any more) to the "
            "section's h2 (tabindex=\"-1\", §12); at 200 % the dialog grows to the viewport, its body scrolling (D04:127)"]),
        (b.frames[2], [
            f"§10 L{st['SCR-117/search-results']['line']}: synonyms {', '.join(k.SYNONYMS)} (`11`:5067–5069)",
            f"The term \"{TERM}\" matches {len(ms)} rows by label or description: "
            + "; ".join(f"{k.ROWS[x]['label']} ({k.H1} › {k.section_of(x)})" for x in ms)
            + f"; one polite status \"{len(ms)} settings found\" (W-29)",
            "Activating a result moves focus to its control, scrolled clear of sticky chrome (2.4.11); the field keeps "
            "focus while typing (drawn focused)"]),
    ]
    k.ambiguity(f"Board 09 search: §10 gives the synonyms and the status, not the match rule: the kit matches the term "
                f"in a row's label or description (\"{TERM}\" finds {len(ms)}), each result naming its section path as "
                f"\"{k.H1} › <section>\"")
    p, md, pk = k.build(NN, frames, blocks, per_row=3)
    print(p.name, md.name, pk.name, ms)


if __name__ == "__main__":
    main()

"""e42d04kit: the sheet kit for the E42-D04 (#887, PR #4193) Penpot boards. Python 3.12+, standard library only, built
on E42-D03's e42kit (imported from its folder, never edited).

Every builder returns cvsheet v1 node dicts (schema: ../cvsheet-v1.js header). e42kit draws the CMP-087 admin shell
(TopBar, NavRail, band, rule, strip, PageHeader, footer marker, RightRail, StatusBar), the T2 control, buttons, fields,
dialogs, the scrim and the text metrics; this kit adds the D04 surfaces: SCR-135's audit table (columns, severity words
and glyphs with the high rule, CMP-174 filters, the "N new entries" pill, the keyset pager, the append-only page text,
the tamper footer, the export control and line), §7's integrity incident banner, §6's diff language, SCR-136's record
drawer, SCR-145's flag rows, groups and dialogs, SCR-148's page, dialogs and banners, SCR-006, §13's motion cards and
frames and the proof sheets (status sheet, diff sheet).
Sources: SPEC, the folded, capped and restated E42-D04.md of the boards PR (the boards branch, branch design/e42-d04-boards;
L-numbers read at SPEC_MD5_FOLD, re-pinned from 58f901df by repin/linemap-carries.json, unchanged at SPEC_MD5_CAP, the
board-cap restatement in place, re-pinned to SPEC_MD5_BRANCH, f4418e83b with the CMP-044 ruling R-2, by
gen10/tools/linemap.py's new_line(), then to SPEC_MD5, cbec19a92 with §0 / §17 / §21 restated for the ten confirmed
boards, by its restated_line()): §0 boards (the ten boards 01-10: NEW_BOARDS; the 74 earlier ids: BOARDS, ON), §1 worked example, §4-§11 screens, §12.1 T2, §13 motion, §14 copy
deck, §15 tokens; every other `path:line` at the spec's pin b7154f951 (DOCS); build-notes.md beside this file
(binding, "SPEC MOVED (boards PR carries)", "SPEC CAPPED (board cap, 2026-10-24)"); E42-D03 by reference (merged
58660d32f).

Use from a generator (python3 -I keeps the generator's folder off sys.path):
    import sys; sys.dont_write_bytecode = True
    sys.path.insert(0, "<this folder>")
    import e42d04kit as d
    frames = [d.audit_page(px) for px in (1280, 2560)]          # or audit_frame(px, [parts…]) for any AL-n
    ann = d.annotations(2, {"state": "AL-2 …", "decisions": "D2, D3, D4, D8", ...})   # build it after the frames
    b = d.board(2, frames, ann)
    d.write_sheet(2, b, d.sections_for_board(frames, ann))   # writes 02-scr135-populated.json, validates, raises
Copy: copy(key, **fills) returns a D04 §14 string (or an inherited E42-D03, D09, E30-D02 or D02 string) verbatim and
records its key; label(key) returns a string the spec gives outside §14 and records it as a copy gap with its line;
bar(field) draws a value no source gives as a neutral bar named by its field, never a number; rich() splits a keyed
string around its unknown fills (bars) and its [Actions] (controls). Notes: this kit records into NOTES, e42kit into
e42kit.LOG; annotations() and write_sheet() merge the two and re-qualify e42kit's E42-D03 line references.
CLI: python3 -I e42d04kit.py selftest   (writes 00-selftest.json: AL-2 at both sizes, validated)
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any, NamedTuple

sys.dont_write_bytecode = True  # importing e42kit must never refresh E42-D03's __pycache__ (read-only for this kit)
D03_DIR = Path(__file__).resolve().parent.parent / "e42-d03"  # E42-D03's kit folder (e42kit.py)
if str(D03_DIR) not in sys.path:
    sys.path.insert(0, str(D03_DIR))
import e42kit as k  # noqa: E402  (after the path insert)

Node = dict[str, Any]
KIT_DIR = Path(__file__).resolve().parent
SHEETS_DIR = KIT_DIR.parent
VALIDATOR = SHEETS_DIR / "tools" / "validate_sheet.py"
COMPONENTS = SHEETS_DIR / "tools" / "components.offline.json"
TOKENS_FILE = k.TOKENS_FILE
WT = Path(__file__).resolve().parents[5]  # the repository root: the boards PR's tree (design/e42-d04-boards, folds G-1..G-39)
SPEC = KIT_DIR / "gen10" / "pin" / "branch-cbec19a92.md"  # `git show cbec19a92:docs/design/E42/E42-D04.md` (md5
# SPEC_MD5): the spec of record for the cap10b boards, §0 / §17 / §21 restated for the ten confirmed boards. The kit
# reads the pinned branch text, never the moving worktree (Fix pass 3, 2026-10-28)
SPEC_MD5 = "04dda6e1247e38d231de80861fccddea"  # cbec19a92 (1,083 lines); every L-number below re-pinned from
# SPEC_MD5_BRANCH by gen10/tools/linemap.py's restated_line() (L1-54 kept; §0 L55-81 re-read by content; L82-870 +29,
# L871-930 +36, L931-959 +38, L960 on +44; Fix pass 3)
SPEC_MD5_BRANCH = "8168a3048305eb6692042b14ade96ceb"  # f4418e83b (1,039 lines): the extras lens + the CMP-044 ruling R-2,
# the kit's pin 10-28 (drift fix pass: re-pinned from SPEC_MD5_CAP, L1-689 kept, L694-856 +2, L857-937 +19, L939 on +21)
SPEC_MD5_CAP = "29360883820664eba06edd3d25dff0d9"  # 1ef40f20b, the board-cap restatement (the kit's pin until 10-28)
SPEC_MD5_FOLD = "818bd87704658faaf05a3738659b4348"  # fold commit 8a3bc3f2d (1,018 lines): every L-number in this kit
# was read here; the cap commits 9ccf2790c (§0) and 1ef40f20b (outside §0) re-word 69 lines in place, none moved
SPEC_MD5_MERGED = "a58b368b886d44a75afa2f6ea0f8bb53"  # origin/main (#4193): repin/linemap-carries.json's "old" side
PIN = "b7154f951"  # the spec's key: "Every `path:line` is at `main` b7154f951…" (L16-17; D03 merged L11-12)
PIN_DIR = KIT_DIR / "repin" / "pin-b7154f951"  # `git show b7154f951:<path>` copies of the files that moved since
DOC_PIN = KIT_DIR / "gen10" / "pin" / "docs"  # `git show b7154f951:<path>` of D02, D09 and E30, which the boards branch's
# rebase onto main moved (md5 06dc71c5, 20c5d5f4, a3c44ca5 on 2026-10-28); the pins keep DOCS_MD5
DOCS = {  # every other file this kit quotes (line numbers checked by the self-test), each as it reads at PIN
    "D02": DOC_PIN / "E42-D02.md", "D01": WT / "docs/design/research/e42-admin.md",  # = PIN (md5 checked)
    "D09": DOC_PIN / "E09-D09.md", "E30": DOC_PIN / "E30-D02.md",  # = PIN
    "E39": WT / "docs/design/E39/E39-D03.md", "E10": WT / "docs/design/E10/E10-D02.md",  # = PIN
    "E17": WT / "docs/design/E17/E17-D01.md",  # = PIN (MM-5's availability banner, E17-D01:148)
    "D03": WT / "docs/design/E42/E42-D03.md",  # merged 58660d32f (the key's D03; e42kit reads 9644f23f0: same lines)
    "CAT": PIN_DIR / "catalogue.py",  # svc/admin/flags/catalogue.py at PIN: 17 flags (main serves 18 since #4227)
    "SCOPES": PIN_DIR / "scopes.py",  # svc/auth/scopes.py at PIN
    "15": PIN_DIR / "15-component-catalogue.md",  # docs/plan/15-component-catalogue.md at PIN (`15:699` etc.)
}
CHROME_15 = {693: "`color.surface.app`", 702: "`color.surface.raised`", 711: "`color.surface.raised`",  # `15` at PIN:
             2475: "`color.surface.sunken`", 2485: "`color.surface.raised`",  # CMP-070-072, CMP-208, CMP-209,
             2500: "Flatten-all"}  # CMP-211's Purpose
DOCS_MD5 = {"D02": "55a8fa7d", "D01": "6b556c91", "D09": "dcc79485", "E30": "8f46498f", "E39": "999457d2",
             "E10": "39e478a4", "E17": "620b625c", "D03": "2e87d809", "CAT": "49b791cd", "SCOPES": "a72c7642",
             "15": "6daa7bea"}
PAGE, REV = "E42-D04", "r1"  # the page and the script revision in every footer (§0 L64-65)
SECTION_BUDGET = 14000  # build notes: "Keep each section under ~14 KB of JSON"; write_sheet() refuses more
ANN_W, ANN_TEXT_W, ANN_HEADROOM = k.ANN_W, k.ANN_TEXT_W, 64  # headroom: text-metric error under the column estimate
PITCH_X, PITCH_Y = k.PITCH_X, k.PITCH_Y  # 4600 x 1800 (build notes)
ROOT_PAD = k.ROOT_PAD
SIZES = k.SIZES  # 1280: NavRail 64, main 976 (944 inside); 2560: NavRail 240, main 2080 (2048 inside); RightRail 240
BOTH, ONLY_1280 = "1280×800+2560×1440", "1280×800"

# --- Tokens (exact Penpot names in token-sync.json; colour and typography from the semantic sets, §15 L721-732).
APP, RAISED, OVERLAY, SUNKEN, HOVER, SELECTED = k.APP, k.RAISED, k.OVERLAY, k.SUNKEN, k.HOVER, k.SELECTED
BORDER_SUBTLE, BORDER_DEFAULT = k.BORDER_SUBTLE, k.BORDER_DEFAULT
TEXT_1, TEXT_2, TEXT_3, TEXT_LINK, TEXT_ON = k.TEXT_1, k.TEXT_2, k.TEXT_3, k.TEXT_LINK, k.TEXT_ON_ACTION
ACTION_PRIMARY, FOCUS_RING = k.ACTION_PRIMARY, k.FOCUS_RING
OK_SUBTLE, OK_STRONG, WARN_SUBTLE, WARN_STRONG = k.OK_SUBTLE, k.OK_STRONG, k.WARN_SUBTLE, k.WARN_STRONG
DANGER_SUBTLE, DANGER_STRONG, INFO_SUBTLE, INFO_STRONG = k.DANGER_SUBTLE, k.DANGER_STRONG, k.INFO_SUBTLE, k.INFO_STRONG
NEUTRAL_SUBTLE = k.NEUTRAL_SUBTLE
CAPTION, BODY, BODY_STRONG, LABEL = k.CAPTION, k.BODY, k.BODY_STRONG, k.LABEL
HEADING_SM, HEADING_MD, NUM_SM, NUM_BASE = k.HEADING_SM, k.HEADING_MD, k.NUM_SM, k.NUM_BASE
INSET_XS, INSET_SM, INSET_MD, INSET_LG, INSET_XL = k.INSET_XS, k.INSET_SM, k.INSET_MD, k.INSET_LG, k.INSET_XL
STACK_XS, STACK_SM, STACK_MD, STACK_LG = k.STACK_XS, k.STACK_SM, k.STACK_MD, k.STACK_LG
FIELD_GAP, DIALOG_PAD = k.FIELD_GAP, k.DIALOG_PAD
R_CONTROL, R_CARD, R_BADGE, R_DIALOG = k.R_CONTROL, k.R_CARD, k.R_BADGE, k.R_DIALOG
HAIRLINE, THICK, FOCUS_W = k.HAIRLINE, k.THICK, k.FOCUS_W
E_POPOVER, OPACITY_SCRIM = k.E_POPOVER, k.OPACITY_SCRIM
PX = dict(k.PX)
CODE_SURFACE = SUNKEN  # §15 L726-727: the raw record's color.surface.code -> color.surface.sunken
TRACK = HOVER  # §15 L727-728: CMP-023's color.track -> color.surface.hover
CHIP_DEV = INFO_SUBTLE  # §15 L727-728: CMP-095's color.chip.dev -> color.status.info.subtle (D02 DS-4)
HIGH_TYPO = HEADING_SM  # D2 L166: the high word in font.weight.semibold; cvsheet v1 binds a typography (FALLBACKS)
HIGH_RULE_W = 2  # D2: a border.thick (2 px) left rule in color.status.danger.strong (§15 L763: a real border-left)
BAR_FILL, BAR_H = SELECTED, 10  # neutral value bars: E42-D03 boards' look (1.41:1 dark on raised; never a value)
ROW_H, CONTROL_H = k.ROW_H, k.CONTROL_H  # 32 px rows and controls (comfortable density, E42-D03 §4)
TONES = k.TONES  # tone -> (fill, glyph kind, glyph colour)

FALLBACKS = {  # this kit's fallback and token lines (printed under Tokens by annotations())
    "SEMIBOLD": ("fallback: font.weight.semibold (D2 L166, §15 L725) cannot bind on a cvsheet v1 text, which takes a "
                 "typography token only: the high severity word binds type.ui.heading-sm, the semantic typography "
                 "whose weight is font.weight.semibold (14 px beside the row's 13 px)"),
    "THICK": "token: border.thick (2 px, §15 L725) is a Tier-1 primitive the spec names (the high rule's width)",
    "CODE": ("fallback: color.surface.code does not exist (CG-24 L938): the raw record binds color.surface.sunken "
             "(§15 L726-727)"),
    "TRACK": "fallback: color.track does not exist (CG-24): CMP-023's track binds color.surface.hover (§15 L727-728)",
    "CHIP": ("fallback: color.chip.dev does not exist (CG-24): CMP-095 binds color.status.info.subtle (§15 L727-728, "
             "D02 DS-4)"),
    "MOTION": ("token: the motion.duration.* and motion.easing.* tokens are code-only in Penpot (§13 L645-648, "
               "`16:307`): frames name them as text, never bind them"),
    "SCRIM": ("fallback: the scrim is black at opacity.scrim in every theme, E09-D06 §7's #000000 until "
              "color.surface.scrim exists, never color.surface.sunken (§15 L731-732; E09-D08 D2; CG-24 L938). "
              "cvsheet v1 binds tokens only and validate_sheet.py refuses a primitive colour, so palette.black "
              "(#000000, E09-D08 A-2's PROPOSED value) cannot bind: the scrim binds color.surface.sunken, which is "
              "palette.black in dark only, so every dark D04 dialog board draws D2's pixels and scrim() refuses a "
              "light frame (no D04 light board holds a dialog: 29, 37, 53, 62 are page twins)"),
    "ICON_SM": ("token: size.icon.sm (12 px) is the Tier-1 primitive the expander cell's two glyphs take: the "
                "selected row's check and the chevron share one 24 px cell (D14 L178; E11-D04:296's convention; "
                "validator WARN)"),
}

# --- Notes. This kit records into NOTES; e42kit records into k.LOG. annotations() and write_sheet() merge both,
# re-qualifying e42kit's lines, whose "§n" and "L…" references are E42-D03's (requalify()).
NOTE_KINDS = (*k.NOTE_KINDS, "spec_gaps")


class _Notes:
    """Notes recorded while nodes are built, deduplicated in first-seen order."""

    def __init__(self) -> None:
        """Start empty."""
        self.notes: dict[str, list[str]] = {kd: [] for kd in NOTE_KINDS}

    def add(self, kind: str, line: str) -> str:
        """Record one line under kind and return it."""
        if line not in self.notes[kind]:
            self.notes[kind].append(line)
        return line


NOTES = _Notes()
EMITTED: set[str] = set()  # strings the decks returned (filled by the self-test's _instrument(); markers always)


def reset_notes() -> None:
    """Clear this kit's notes and e42kit's (write_sheet() does this after writing)."""
    NOTES.notes = {kd: [] for kd in NOTE_KINDS}
    k.reset_notes()


SRC = {  # the D04 spec sections a sheet draws from (headings checked by the self-test)
    "boards": "E42-D04 §0 L53-121 (the ten boards, the ids, names, exports, count)",
    "example": "E42-D04 §1 L123-159 (locked inputs, the worked example L136-149, the objects)",
    "decisions": "E42-D04 §2 L161-194 (D1-D30)",
    "audit": "E42-D04 §4 L216-316 (SCR-135: anatomy, columns, filters, AL-1..AL-29, keys, roles, events)",
    "drawer": "E42-D04 §5 L318-356 (SCR-136: anatomy, links, AD-1..AD-8, keys, events)",
    "diff": "E42-D04 §6 L358-405 (the diff language)",
    "incident": "E42-D04 §7 L407-445 (the integrity incident)",
    "export": "E42-D04 §8 L447-483 (the export job)",
    "flags": "E42-D04 §9 L485-555 (SCR-145)",
    "maint": "E42-D04 §10 L557-594 (SCR-148)",
    "rungs": "E42-D04 §11 L596-615 (dialogs and rungs)",
    "voice": "E42-D04 §12 L617-630 (live regions, key repeat)",
    "t2": "E42-D04 §12.1 L632-637 (T2)",
    "motion": "E42-D04 §13 L639-698 (the motion spec)",
    "copy": "E42-D04 §14 L700-713 (the copy deck)",
    "tokens": "E42-D04 §15 L715-767 (tokens, contrast, greyscale, colour vision)",
}
SRC_LINES = {"boards": 53, "example": 123, "decisions": 161, "audit": 216, "drawer": 318, "diff": 358, "incident": 407,
             "export": 447, "flags": 485, "maint": 557, "rungs": 596, "voice": 617, "t2": 632, "motion": 639,
             "copy": 700, "tokens": 715}  # the folded spec's headings (the self-test proves each)
DEVIATIONS = {
    "names": ("A per-id sheet's board name keeps the earlier per-id form in Penpot's normalised ' / ' form ('E42-D04 / "
              "13 SCR-135 / tamper-failed · …', the earlier §0's 'SCR-135/tamper-failed') so cvsheet's find-or-create "
              "root matches on every section call (E42-D03's convention); the drawn boards take §0 L61-62's "
              "'E42-D04 / NN <slug> · <sizes> · <theme>'."),
    "shell": ("Shell: CMP-087 under (b) (E42-D03 SH-6): the band carries its label only, and the strip reads "
              "strip.none, unless a board adds them: a live grace reads D03's 'Still trusted for {class} · {m:ss}' in "
              "the band and the dialog, its {class} 'flag changes' or 'audit exports' (D21 L185; §20 A-row (1) "
              "L882-884, PROPOSED to E42-D03: grace_line())."),
    "compose": ("Tables, rows, pagers, filters, pills, banners, drawers, dialogs and fields are token compositions "
                "named '<CMP id> <Name> (composition)': the library sets in components.offline.json stop at CMP-039 "
                "and cvsheet v1 cannot set an instance's glyph, fill or border."),
    "link": ("Links: a running-text CMP-021 link carries a drawn 1 px color.text.link underline as wide as its "
             "estimated text (cvsheet v1 texts take no textDecoration; E42-D03 board 22's pattern)."),
    "bars": ("Values the state rows show but §1's worked example (L136-149) does not give are neutral bars "
             "(color.surface.selected, radius.control) named by their field: never a number, never a loading state."),
    "chrome": ("Shell chrome (§0 L111-116; orchestrator ruling 2026-10-23, G-30): E10-D02 owns the shell chrome and "
               "binds the build (an 80 px TopBar with CMP-211's Safety cluster at its right, E10-D02:65-73); the "
               "boards keep the chrome D03 draws (TopBar and StatusBar 48 px, CMP-211 at the RightRail's top: D03 "
               "D1, §1, §4; `15:2500`), so D03's sheets and these match: two merged specs disagree, a C-row for the "
               "owner with E42-D03 (§20 L878-881), not an A-row. Its content other than the Admin entry, the env "
               "badges and the owner's name is neutral placeholders. `15` names color.surface.raised for CMP-071, "
               "CMP-072 and CMP-209 and color.surface.sunken for CMP-208 (15:702, :711, :2485, :2475 at b7154f951); "
               "the boards draw all four on color.surface.app, CMP-070's surface (15:693), as every E42-D03 board "
               "does."),
    "edge": ("The current Admin entry carries DS-2's edge (D02:1003): color.text.tertiary at border.thick, inner, "
             "beside e42kit's color.surface.selected fill (E42-D03 board 06 review finding 1, as its boards 21-41)."),
    "renames": ("e42kit compositions take the build notes' names: 'CMP-209 RightRail (composition)', 'primary action · "
                "CMP-001 Button (composition)', 'CMP-093 AuditActionTrigger (composition) · footer marker' (E42-D03 "
                "board 06 review finding 6)."),
    "dialog-w": ("CMP-043 'size' Large is drawn 640 px wide at both sizes (§11 L599; E42-D03's kit width: no source "
                 "gives the width)."),
    "counts": ("Counts in type.num.base (D02:120 'type.num.base for every count and clock'; D02:154 'counts in "
               "type.num'; G-45): a count is its own type.num.base text in a row whose space.inset.xs gap stands for "
               "the word spaces (count_text(); E42-D03's), the row's note carrying the keyed string."),
    "expander": ("SCR-135's expander column (§4 L239-240, CMP-173's button) stays 24 px at 2560, a fixed button cell "
                 "(E11-D04:189 'fixed'); the other nine columns scale to the grid's width (DJ)."),
    "modal-env": ("Dialogs: the ENV badge stays above the scrim and the card (§11 L599-602, C-2.11, E10-D02:264; "
                  "G-31): modal() draws the TopBar's CMP-074 and the StatusBar's CMP-075 badges again over the "
                  "scrim at their chrome positions (cvsheet v1 has no z-order across boards); at 200 % a dialog fills "
                  "only the area between the TopBar and the StatusBar (AL-28, FF-15)."),
    "focus": ("A focus ring is a 2 px color.focus.ring inner stroke on a wrapper with space.inset.xs padding, 2 px off "
              "the control (CMP-039; E42-D03's kit)."),
}
_D03_EXACT = {  # e42kit lines whose E42-D03 references would mislead on a D04 board -> this kit's wording
    k.FALLBACKS["DS-1"]: ("fallback: color.surface.admin-tint pending E42-D03 DS-1 (by reference, §15 L732): the band "
                          "binds color.surface.raised"),
    k.FALLBACKS["DS-2"]: ("fallback: color.border.admin pending E42-D03 DS-2 (by reference, §15 L732): the 4 px rule "
                          "and the current Admin entry's edge bind color.text.tertiary"),
    k.FALLBACKS["DS-3"]: ("fallback: color.border.input pending E42-D03 DS-3: field boundaries bind "
                          "color.text.tertiary"),
    k.FALLBACKS["SCRIM"]: FALLBACKS["SCRIM"],  # G-43: e42kit's SCRIM = SUNKEN, ruled out (E09-D08 D2): scrim()
    k.FALLBACKS["STEP"]: "token: E42-D03 §2 D1's space.3 gaps bind the semantic alias space.stack.md (12 px)",
    k.FALLBACKS["CONTROL"]: ("token: size.control.comfortable (32 px, §15 L726) is the Tier-1 primitive the spec "
                             "names (validator WARN)"),
    k.DEVIATIONS["chrome"]: DEVIATIONS["chrome"],
    k.DEVIATIONS["link"]: DEVIATIONS["link"],
    k.DEVIATIONS["compose"]: DEVIATIONS["compose"],
    k.DEVIATIONS["dialog-w"]: DEVIATIONS["dialog-w"],
    k.DEVIATIONS["focus"]: DEVIATIONS["focus"],
    "'Admin': an anatomy string, not a §14 key (spec L189)": ("'Admin': CMP-071 NavRail's Admin item (`15:699` at "
                                                              "b7154f951), not an E42-D04 §14 key"),  # G-48
}
D03_LINES = ("E42-D03 L-numbers in these notes are e42kit's, read at PR #4138's head 9644f23f0 (e42kit.SPEC_MD5 "
             "b4ef3ab8); merged 58660d32f (md5 2e87d809, the key's D03, L11-12) keeps them line for line: 22 lines "
             "re-worded, none moved, each cited fact still on its line (repin/linemap-d03.json)")


def requalify(line: str) -> str:
    """An e42kit note line with its E42-D03 references named as such ('§4 L176' -> 'E42-D03 §4 L176'); lines this
    kit rewrites wholesale come from _D03_EXACT."""
    if line in _D03_EXACT:
        return _D03_EXACT[line]
    if "E42-D03" in line or "E42-D04" in line:
        return line
    s = line.replace("pending DS-", "pending E42-D03 DS-")
    s = re.sub(r"(?<![\w-])(spec )?§(\d)", lambda m: f"E42-D03 {m.group(1) or ''}§{m.group(2)}", s)
    s = re.sub(r"(?<![\w-])spec L(\d)", r"E42-D03 spec L\1", s)
    return re.sub(r"\(L(\d)", r"(E42-D03 L\1", s)


def merged_notes(extra: dict[str, Any] | None = None) -> dict[str, list[str]]:
    """This kit's notes, then e42kit's (re-qualified), then extra (a generator's own lines), deduplicated."""
    out: dict[str, list[str]] = {kd: [] for kd in NOTE_KINDS}
    texty = ("sources", "copy_gaps", "deviations", "fallbacks")
    for src, fix in ((NOTES.notes, False), (k.LOG.notes, True), (extra or {}, False)):
        for kd, lines in src.items():
            if kd not in out:
                raise KeyError(f"notes kind {kd!r}; allowed {NOTE_KINDS}")
            for raw_ln in [lines] if isinstance(lines, str) else lines:
                ln = requalify(raw_ln) if fix and kd in texty else raw_ln
                if ln not in out[kd]:
                    out[kd].append(ln)
    if any(re.search(r"E42-D03 [^,;)]*L\d", ln) for kd in texty for ln in out[kd]) and D03_LINES not in out["sources"]:
        out["sources"].append(D03_LINES)  # G-48: e42kit's D03 lines hold at merged 58660d32f
    return out


def _src(key: str) -> None:
    """Record the D04 spec section SRC[key] as a source of the sheet being built."""
    NOTES.add("sources", SRC[key])


def _fallback(key: str) -> None:
    """Record this kit's fallback or token line FALLBACKS[key] (printed under Tokens)."""
    NOTES.add("fallbacks", FALLBACKS[key])


def _deviate(key: str, line: str | None = None) -> None:
    """Record a deviation: DEVIATIONS[key], or a one-off line."""
    NOTES.add("deviations", line or DEVIATIONS[key])


def spec_gap(line: str) -> None:
    """Record a spec gap the sheet hit (with its spec lines)."""
    NOTES.add("spec_gaps", line)


def live(line: str) -> None:
    """Record a check to make live, after rendering."""
    NOTES.add("live_checks", line)


# --- The board registry. The restated §0 (cbec19a92, L53-122) draws ten boards, 01-10 (its table, L78-89), and keeps
# the 74 earlier state-board ids as ids, written in brackets (L58-60): each hi-fi row's Board cell in §4 (L263-293), §5
# (L340-349), §9 (L526-544) and §10 (L575-588) names its id and slug and either the board that draws it or "not drawn".
# BOARDS stays keyed by the earlier id (each per-id generator draws one id): number, screen, state id and name, slug,
# ★ (Count L91-97's ★ ids), S (§18's line, L852-853), theme (light = a state row's "<id> in light" twin) and the board
# that draws it (ON) are read from the restated text. The ids' own frame sizes (an id's planned 1280 / 2560 frames, its
# "(1280, three frames)") and the motion and proof ids' descriptions are the earlier plan's: the restated §0 no longer
# tabulates them, so they are read from §0 L67-74 of IDS_PIN (f4418e83b, the text before the restatement) and kept
# as recorded; the restated rows' "(1280)" notes and the Not-drawn list (L98-104) are checked against them.
def _spec_lines() -> list[str]:
    """SPEC's lines (index 0 = L1)."""
    return SPEC.read_text(encoding="utf-8").split("\n")


LINES = _spec_lines()
IDS_PIN = KIT_DIR / "gen10" / "pin" / "branch-f4418e83b.md"  # `git show f4418e83b:docs/design/E42/E42-D04.md`
IDS_PIN_MD5 = "8168a3048305eb6692042b14ade96ceb"  # the earlier ids' frame sizes and motion / proof descriptions only


def _ids_lines() -> list[str]:
    """IDS_PIN's lines (the earlier plan's §0, f4418e83b)."""
    raw = IDS_PIN.read_bytes()
    if hashlib.md5(raw).hexdigest() != IDS_PIN_MD5:
        raise RuntimeError(f"{IDS_PIN.name} is not f4418e83b's text")
    return raw.decode("utf-8").split("\n")


class Bd(NamedTuple):
    """One earlier state-board id (§0 L58-60: the ids stay as ids), as the restated text gives it."""

    nn: int
    screen: str  # SCR-135 | SCR-136 | SCR-145 | SCR-148 | motion | proofs
    state_id: str  # AL-1 … MM-12; "" for motion and proofs
    state: str  # the state table's State cell (motion and proofs: the earlier §0's description, IDS_PIN)
    slug: str  # the Board cell's slug (id 65: the kit's)
    size: str  # the per-id sheet name's <size>: BOTH or ONLY_1280
    frames: tuple[int, ...]  # the id's frame widths at 1:1 (IDS_PIN §0; id 66: four 1000 × 1728 theme frames)
    theme: str  # dark | light | dark+light+hc+forced-colours
    star: bool  # ★: one of the earlier plan's ★ ids (Count, L91-97)
    sec: bool  # S: named for the security reviewer (§18, L852-853)
    twin: int | None  # a light id's dark twin
    line: int  # the spec line of its state row (motion and proofs: its first mention in §0)
    spec_name: str  # the per-id form: "E42-D04 / 13 SCR-135/tamper-failed · 1280×800+2560×1440 · dark"
    name: str  # Penpot's normalised form (DEVIATIONS["names"]): the per-id sheet's board.name
    export: str  # the per-id stem's path (the boards' exports are NEW_BOARDS', §0 L67-69)
    on: int | None = None  # the restated board (01-10) that draws it, or None: "not drawn — the text is binding"
    on_1280: bool = False  # drawn at 1280 only on that board ("· board NN (1280)", L98-104's list)

    @property
    def drawn(self) -> bool:
        """On one of the ten boards (§0 L78-89)."""
        return self.on is not None


class NewBoard(NamedTuple):
    """One drawn board, a row of the restated §0 table (L78-89)."""

    nn: int
    slug: str
    theme: str
    frames_cell: str  # "row 1: AL-2 [02] 1280 + 2560, AL-3 [03] 1280 · row 2: …"
    star: bool
    status: str  # PENDING until drawn
    evidence: str
    line: int
    ids: tuple[int, ...]  # the earlier ids it draws, in the cell's order
    frames: tuple[int, ...]  # frames per id, in the cell's order (board 08's [66]: four columns)

    @property
    def name(self) -> str:
        """§0 L61-62's board name: `E42-D04 / NN <slug> · <sizes> · <theme>`."""
        sizes = ("1000×1728" if self.slug == "status-sheet" else
                 BOTH if "2560" in self.frames_cell else ONLY_1280)
        return f"{PAGE} / {self.nn:02d} {self.slug} · {sizes} · {self.theme}"

    @property
    def export(self) -> str:
        """§0 L67's export path."""
        return f"docs/design/E42/img/{PAGE}-{self.nn:02d}-{self.slug}.png"


_STATE_ROW = re.compile(r"^\|\s*(AL|AD|FF|MM)-(\d+)\s*\|")
_BOARD_CELL = re.compile(r"\[?(\d{2})\]?\s+`([a-z0-9-]+)`(?:\s+\(([^)]*)\))?")
_ON_CELL = re.compile(r"\s+·\s+(?:board (\d{2})(?:\s+\((1280)\))?|(not drawn))$")
_NEW_ROW = re.compile(r"^\|\s*(\d{2})\s*\|\s*`([a-z0-9-]+)`\s*\|")
_SCREEN_OF = {"AL": "SCR-135", "AD": "SCR-136", "FF": "SCR-145", "MM": "SCR-148"}
_MARK_ITEM = re.compile(r"^(\d{2})((?:\s*[★S])*)\s*(?:\(([^)]*)\))?\s*(light)?$")
_RANGE_ITEM = re.compile(r"^(\d{2})–(\d{2})$")  # an unmarked run in a cap list, "05–09" (IDS_PIN §0 L69-72; en dash)
# IDS_PIN §0 L69-74 (the earlier plan under the board cap, 9ccf2790c): "drawn <ids>; not drawn — the text is binding;
# drawn on request: <ids>", or either list alone (L73: the not-drawn list only); _cap_lists() reads a row's lists
CAP_DRAWN, CAP_NOT_DRAWN = "drawn ", "not drawn — the text is binding; drawn on request: "
EARLIER_TEN = (2, 13, 14, 32, 34, 41, 55, 66, 67, 69)  # the earlier ten (IDS_PIN §0 L79), superseded by L78-89
FOLD_MARKS = {  # the fold 8a3bc3f2d's §0 marks (SPEC_MD5_FOLD): 18 ★, 6 S, 4 light ids (the restated text keeps them)
    "star": (2, 3, 4, 10, 11, 13, 14, 21, 22, 23, 32, 39, 41, 49, 57, 58, 66, 67), "sec": (4, 13, 14, 32, 34, 41),
    "light": (29, 37, 53, 62)}
_WORDS = {"two": 2, "three": 3, "four": 4}
_PREFIX = re.compile(r"^scr\d{3}-")
KIT_SLUGS = {65: "flash-vestibular"}  # §0 L102 gives id 65's slug `flash-vestibular` (G-28)
SHEET_FRAMES = {63: (1280,), 64: (1280,), 65: (1280,), 66: (1000,) * 4, 67: (1280,), 68: (1280,), 69: (1280, 2560)}
SHEET_FRAME_H = {66: 1728}  # §0 L87: board 08's [66], "four 1000 × 1728 columns"; 67, 68 1280 × 800
SHEET_SIZE = {66: "1000×1728"}  # id 66's <size> (gen_66's sheet name); every other id's follows its frames
SHEET_THEME = {66: "dark+light+hc+forced-colours"}  # §0 L87: "dark, light, hc and forced-colours columns"
SPEC_GAPS: list[str] = [  # gaps this kit hits while encoding the spec (each with its lines); generators add their own.
    # The three §0 gaps of 58f901df (id 65's slug, ids 66-68's sizes, 66's theme columns) stay closed (G-28): 65
    # `flash-vestibular` (L102), 66 four 1000 × 1728 columns (L87; the forced-colours one a construction, §15), 67
    # and 68 one 1280 × 800 frame each. The cap's dropped ★ on id 39 is closed: Count (L94) lists [39] among the ★ ids.
]


def _cells(row: str) -> list[str]:
    """A markdown table row's cells, stripped."""
    return [c.strip() for c in row.strip().strip("|").split("|")]


def _cap_lists(body: str, i: int) -> list[tuple[str, bool]]:
    """An IDS_PIN §0 row's id lists under the cap (9ccf2790c): "drawn <items>; not drawn — the text is binding; drawn
    on request: <items>", or either list alone → [(items, drawn)]; anything else raises."""
    if body.startswith(CAP_NOT_DRAWN):
        return [(body[len(CAP_NOT_DRAWN):], False)]
    if not body.startswith(CAP_DRAWN):
        raise ValueError(f"§0 L{i}: neither {CAP_DRAWN.strip()!r} nor {CAP_NOT_DRAWN[:9]!r} leads {body[:48]!r}")
    head, sep, tail = body[len(CAP_DRAWN):].partition("; " + CAP_NOT_DRAWN)
    return [(head, True), (tail, False)] if sep else [(head, True)]


def _earlier_ids(old: list[str]) -> tuple[dict[int, dict[str, Any]], dict[int, tuple[int, ...] | None]]:
    """IDS_PIN's §0 rows (L67-74): the motion and proof ids (screen, slug, description) and each id's frame sizes
    ((1280, three frames) etc.; None = §0's default, both sizes unless the state row notes (1280)). An id listed twice,
    a backward run or an unreadable item raises."""
    mp: dict[int, dict[str, Any]] = {}
    frames: dict[int, tuple[int, ...] | None] = {}

    def put(i: int, nn: int, fr_: tuple[int, ...] | None) -> None:
        if nn in frames:
            raise ValueError(f"{IDS_PIN.name} §0 L{i}: id {nn:02d} listed twice")
        frames[nn] = fr_

    sec0 = next(i for i, ln in enumerate(old, 1) if ln.startswith("## 0."))
    sec1 = next(i for i, ln in enumerate(old, 1) if ln.startswith("## 1."))
    for i in range(sec0, sec1):
        c = _cells(old[i - 1])
        if len(c) < 3 or c[1] not in ("SCR-135", "SCR-136", "SCR-145", "SCR-148", "motion", "proofs"):
            continue
        if c[1] in ("motion", "proofs"):
            for items, _drawn in _cap_lists(c[2], i):
                for part in re.split(r" · (?=\d{2} )", items):
                    pm = re.match(r"(\d{2})\s+(?:`([a-z-]+)`)?\s*(★)?\s*:?\s*(.*)$", part)
                    if not pm:
                        raise ValueError(f"{IDS_PIN.name} §0 L{i}: cannot read {part!r}")
                    nn = int(pm.group(1))
                    mp[nn] = {"screen": c[1], "slug": pm.group(2) or KIT_SLUGS[nn],
                              "state": re.sub(r"\s+—\s+one 1280 frame each$", "", pm.group(4))}
                    put(i, nn, SHEET_FRAMES[nn])
            continue
        for items, _drawn in _cap_lists(c[2].split("): ", 1)[1], i):
            for item in items.split(" · "):
                rm = _RANGE_ITEM.match(item.strip())
                if rm:
                    lo, hi = int(rm.group(1)), int(rm.group(2))
                    if lo >= hi:
                        raise ValueError(f"{IDS_PIN.name} §0 L{i}: run {item!r} does not ascend")
                    for nn in range(lo, hi + 1):
                        put(i, nn, None)
                    continue
                mm = _MARK_ITEM.match(item.strip())
                if not mm:
                    raise ValueError(f"{IDS_PIN.name} §0 L{i}: cannot read {item!r}")
                paren = (mm.group(3) or "").strip()
                fr_: tuple[int, ...] | None = None
                if paren:
                    pp = [p.strip() for p in paren.split(",")]
                    if pp[0] != "1280":
                        raise ValueError(f"{IDS_PIN.name} §0 L{i}: unexpected size note {paren!r}")
                    fr_ = (1280,) * (_WORDS[pp[1].split()[0]] if len(pp) > 1 else 1)
                put(i, int(mm.group(1)), fr_)
    return mp, frames


def _ids_in(text_: str) -> list[int]:
    """The bracketed ids of a restated text span, runs expanded ("[05]–[12]" → 05..12), in order."""
    out: list[int] = []
    for m in re.finditer(r"\[(\d{2})\](?:–\[(\d{2})\])?", text_):
        lo, hi = int(m.group(1)), int(m.group(2) or m.group(1))
        out += list(range(lo, hi + 1))
    return out


def _new_frames(cell: str) -> tuple[tuple[int, ...], tuple[int, ...]]:
    """A §0 table Frames cell (L80-89) → (ids, frames per id): "1280 + 2560" two, "its three 1280 frames" three,
    "four 1000 × 1728 columns" four, else one ("each 1280", "one 1280 frame each")."""
    ids, frs = [], []
    parts = re.split(r"(?=\[\d{2}\])", cell)
    for j, part in enumerate(parts[1:], 1):
        nn = int(part[1:3])
        tail = part[4:]
        n = 2 if "1280 + 2560" in tail else 3 if "its three 1280 frames" in tail else (
            4 if "four 1000 × 1728 columns" in tail else 1)
        ids.append(nn)
        frs.append(n)
    return tuple(ids), tuple(frs)


def _parse_new_boards(lines: list[str]) -> dict[int, NewBoard]:
    """The restated §0 table (L78-89): one row per drawn board."""
    sec0 = next(i for i, ln in enumerate(lines, 1) if ln.startswith("## 0."))
    sec1 = next(i for i, ln in enumerate(lines, 1) if ln.startswith("## 1."))
    out: dict[int, NewBoard] = {}
    for i in range(sec0, sec1):
        if not _NEW_ROW.match(lines[i - 1]):
            continue
        c = _cells(lines[i - 1])
        ids, frs = _new_frames(c[3])
        out[int(c[0])] = NewBoard(int(c[0]), c[1].strip("`"), c[2], c[3], c[4] == "★", c[5], c[6], i, ids, frs)
    return out


def _parse_boards(lines: list[str], new: dict[int, NewBoard]) -> dict[int, Bd]:
    """The 74 earlier ids: the four state tables give number, screen, state, slug, the (1280) size note and the board
    that draws it; the restated §0 gives the motion and proof ids' boards and lines, Count the ★ ids, §18 the S ids;
    IDS_PIN the frame sizes and the motion and proof descriptions (_earlier_ids)."""
    raw: dict[int, dict[str, Any]] = {}
    for i, row in enumerate(lines, 1):
        m = _STATE_ROW.match(row)
        if not m:
            continue
        c = _cells(row)
        if len(c) < 7:  # a state table row has 7 cells; §4's tamper-line table (L228-236, G-12) has 2
            continue
        om = _ON_CELL.search(c[2])
        if not om:
            raise ValueError(f"L{i}: the Board cell {c[2]!r} names neither a board nor 'not drawn'")
        on = None if om.group(3) else int(om.group(1))
        when = c[3]
        tw = re.fullmatch(r"((?:AL|AD|FF|MM)-\d+) in light", when.strip())
        cells = _BOARD_CELL.findall(c[2][:om.start()])
        for nn_s, slug, paren in cells:
            state = c[1].replace("**", "")
            if len(cells) > 1:  # one state row, several ids (FF-8: [45] order entry, 74 ingestion)
                extra = paren.strip() or slug.removeprefix(cells[0][1]).strip("-")
                state = f"{state} · {extra}" if extra else state
            raw[int(nn_s)] = {"screen": _SCREEN_OF[m.group(1)], "state_id": c[0], "state": state,
                              "slug": slug, "only1280": paren.strip() == "1280", "line": i,
                              "twin_sid": tw.group(1) if tw else None, "on": on, "on_1280": bool(om.group(2))}
    mp, frames = _earlier_ids(_ids_lines())
    sec0 = next(i for i, ln in enumerate(lines, 1) if ln.startswith("## 0."))
    sec1 = next(i for i, ln in enumerate(lines, 1) if ln.startswith("## 1."))
    on_new = {nn: nb.nn for nb in new.values() for nn in nb.ids}
    for nn, r in mp.items():  # motion and proofs: the board from §0's table, the line of the id's first mention
        line = next(i for i in range(sec0 + 7, sec1) if f"[{nn:02d}]" in lines[i - 1])
        raw[nn] = {**r, "state_id": "", "only1280": SHEET_FRAMES[nn] == (1280,) * len(SHEET_FRAMES[nn]),
                   "line": line, "twin_sid": None, "on": on_new.get(nn), "on_1280": False}
    # ★ ids: Count's (the earlier plan's other ★ ids, and those rendered as part of boards 01 and 02) and a ★ board's
    # one id (08's [66], 09's [67])
    stars = set(_ids_in(_s0_item(lines, "Count"))) | {nb.ids[0] for nb in new.values() if nb.star and len(nb.ids) == 1}
    sec_ids = set(_ids_in(_join(lines, *_s_line(lines))))
    out: dict[int, Bd] = {}
    sid_to_nn = {r["state_id"]: nn for nn, r in sorted(raw.items(), reverse=True) if r["state_id"]}
    for nn in sorted(raw):
        r = raw[nn]
        fr_ = frames.get(nn) or ((1280,) if r["only1280"] else (1280, 2560))
        if r["only1280"] and fr_[0] != 1280:
            raise ValueError(f"id {nn}: the state table's (1280) disagrees with the earlier §0")
        twin = sid_to_nn[r["twin_sid"]] if r["twin_sid"] else None
        theme = "light" if twin else SHEET_THEME.get(nn, "dark")
        size = SHEET_SIZE.get(nn) or (ONLY_1280 if all(f == 1280 for f in fr_) else BOTH)
        state = _PREFIX.sub("", r["slug"])
        spec_name = f"{PAGE} / {nn:02d} {r['screen']}/{state} · {size} · {theme}"
        out[nn] = Bd(nn, r["screen"], r["state_id"], r["state"], r["slug"], size, fr_, theme, nn in stars,
                     nn in sec_ids, twin, r["line"], spec_name, k.penpot_name(spec_name),
                     f"docs/design/E42/img/{PAGE}-{nn:02d}-{r['slug']}.png", r["on"], r["on_1280"])
    return out


def _s0_item(lines: list[str], head: str) -> str:
    """A restated §0 bullet's text ("- **<head>…**" to the next bullet or blank line), whitespace collapsed."""
    a = next(i for i, ln in enumerate(lines, 1) if ln.startswith(f"- **{head}"))
    b = next(i for i in range(a + 1, len(lines) + 1) if lines[i - 1].startswith("- **") or not lines[i - 1].strip())
    return _join(lines, a, b - 1)


def _join(lines: list[str], a: int, b: int) -> str:
    """Lines a..b (1-based) joined, whitespace collapsed (code ticks kept)."""
    return re.sub(r"\s+", " ", " ".join(lines[a - 1:b]))


def _s_line(lines: list[str]) -> tuple[int, int]:
    """§18's security-reviewer sentence's lines (L852-853)."""
    b = next(i for i, ln in enumerate(lines, 1) if "go to the security reviewer" in ln)
    return b - 1, b


NEW_BOARDS = _parse_new_boards(LINES)
BOARDS = _parse_boards(LINES, NEW_BOARDS)
if sorted(BOARDS) != list(range(1, 75)):
    raise RuntimeError(f"§0 keeps ids 01-74; the spec parse found {sorted(set(range(1, 75)) ^ set(BOARDS))} off")
LIGHT_TWINS = {nn: b.twin for nn, b in BOARDS.items() if b.twin}  # {29: 2, 37: 30, 53: 39, 62: 57}
DRAWN = tuple(nn for nn, b in BOARDS.items() if b.drawn)  # the ids the ten boards draw (§0 L78-89; the self-test)
ON = {nn: b.on for nn, b in BOARDS.items() if b.on}  # id -> the board (01-10) that draws it


def grid_xy(nn: int) -> tuple[int, int]:
    """Board nn's page position: x = ((NN − 1) mod 5) × 4600, y = floor((NN − 1) / 5) × 1800 (build notes)."""
    return ((nn - 1) % 5) * PITCH_X, ((nn - 1) // 5) * PITCH_Y


def board_name(nn: int) -> str:
    """Id nn's per-id sheet name (the earlier per-id form, normalised; DEVIATIONS["names"])."""
    return BOARDS[nn].name


def export_path(nn: int) -> str:
    """Id nn's per-id stem path, E42-D04-NN-<slug>.png (§0 L67-69's form; the boards' exports are NEW_BOARDS')."""
    return BOARDS[nn].export


def title(nn: int) -> str:
    """The default annotation title: "02 SCR-135 · AL-2 populated, page checked" (motion and proofs: the slug; a light
    board names its dark twin's state)."""
    b = BOARDS[nn]
    if b.twin:
        tw = BOARDS[b.twin]
        return f"{nn:02d} {b.screen} · {b.state_id}: {tw.state_id} {tw.state} in light (board {tw.nn:02d}'s construction)"
    tail = f"{b.state_id} {b.state}" if b.state_id else f"{b.slug}: {b.state}"
    return f"{nn:02d} {b.screen} · {tail}"


# --- The copy deck. COPY is generated from §14 L704-711 and L713 by script (repin/tools/gencopy_new.py, byte-exact;
# the self-test re-proves every string). Kit-named sub-keys, a key's later strings as §14 gives them: audit.new_n.one
# / .cap, audit.count.one, audit.end.filtered, export.running.no_pct, diff.unchanged_n.one, flags.scope.plus_n /
# .plus_one / .ignored, flags.count.one, dlg.positions.unavailable, admin.oldest.filtered (admin.oldest = audit.end,
# L711), dlg.flag.body.one / .yours (the pieces §14 gives in its own note; use flag_body()); "maintenance" is the
# PROPOSED E30-D02 state key §14's inherited row gives verbatim (L713; MM-5 L581). Gone with the folds:
# admin.export_running (G-1: a busy export is busy), admin.conflict_first (G-4: dlg.conflict_first, a validity hint).
COPY: dict[str, str] = {  # key -> the §14 string verbatim (L704-711, L713); "{…}" = a fill
    "audit.append_only": "Records can only be added, never edited or deleted. Kept indefinitely.",
    "audit.marker": "Viewing this log is recorded — Audit log viewed (admin.audit_read)",
    "audit.caption": "Audit log, newest first. All times UTC. Role at the time is not recorded yet.",
    "audit.slow": "Taking longer than usual…",
    "audit.no_match": "No records match these filters.",
    "audit.own_only": "Showing your actions only",
    "audit.own_no_match": "No actions by you match these filters.",
    "audit.own_filter": "That filter isn't available in your view.",
    "audit.env_page": "{ENV} (this page only)",
    "audit.new_n": "{n} new entries — show newest",
    "audit.new_n.one": "1 new entry — show newest",
    "audit.new_n.cap": "200+ new entries — show newest",
    "audit.new_loaded": "{n} new entries loaded",
    "audit.count": "{n} entries on this page",
    "audit.count.one": "1 entry on this page",
    "audit.result_started": "Started",
    "audit.result_intent": "Intent",
    "audit.end": "No older entries.",
    "audit.end.filtered": "No older entries match these filters.",
    "audit.cursor_lost": "This page can't be continued. Start again from the newest entries. [Newest]",
    "audit.error": ("Couldn't load the audit log — the query took too long or the store is unavailable. Try a "
                    "shorter time range, or try again at {hh:mm:ss} UTC. [Retry]"),
    "audit.limited": ("Too many requests — try again at {hh:mm:ss} UTC (in {s} s). Run tamper check and opening "
                      "records still work."),
    "audit.err_range": "From must be earlier than To.",
    "audit.err_ip": "Enter one IP address, not a range.",
    "tamper.page_passed": "Tamper check: this page checked — passed",
    "tamper.page_partial": "Tamper check: this page could not be fully checked — run a tamper check",
    "tamper.page_partial_own": "Tamper check: this page could not be fully checked.",
    "tamper.newest_partial": "The newest entries could not be fully checked — run a tamper check",
    "tamper.incidents_unavailable": "Tamper status: incident log unavailable",
    "tamper.checking": "Checking entries…",
    "tamper.range_passed": ("Tamper check: entries {from}–{to} checked at {hh:mm} UTC — passed. This covers that "
                            "range only."),
    "tamper.range_empty": "No entries in that range — nothing was checked.",
    "tamper.busy": "A tamper check is already running. Try again when it ends.",
    "tamper.limited": "Too many tamper checks this hour — try again at {hh:mm} UTC.",
    "tamper.stopped": "The check didn't finish — nothing was verified. Try again at {hh:mm:ss} UTC.",
    "tamper.stopped_entry": ("The check stopped at a record too large to check — nothing was verified. Checking "
                             "this range again stops there too; tell security."),
    "tamper.failed.title": "Tamper check FAILED at entry {n} — treat this as a security incident",
    "tamper.failed.facts": "Found at {hh:mm:ss} UTC on {yyyy-mm-dd} in a check of entries {from}–{to}.",
    "tamper.failed.meaning": ("Each record is linked to the one before it, so a change or gap shows here. The "
                              "links are not keyed: someone with database access could also have rewritten "
                              "earlier records consistently, so treat the whole log as unverified until security "
                              "has compared it with an independent copy."),
    "tamper.failed.safe": ("Native stop-losses are unaffected. A break does not stop order entry by itself: "
                           "decide now whether to engage the kill switch (FREEZE…)."),
    "tamper.failed.recheck": "A new check finds the same break until the chain is restored.",
    "tamper.failed.steps": ("Don't change or delete anything in the database. Snapshot it, find the first broken "
                            "link in the verifier log and escalate it as a security incident (SECURITY.md). Tell "
                            "the security reviewer now."),
    "tamper.failed.copy": "Copy details",
    "export.dlg.title": "Export the audit log",
    "export.dlg.body": ("A signed file (NDJSON and its signature) of every entry from {from} to {to} UTC, with "
                        "the neighbouring entries that link them — not just the rows on screen. Filters don't "
                        "apply."),
    "export.dlg.pii": "The file holds personal data (actor IP addresses).",
    "export.dlg.range": "Choose at most 31 days.",
    "export.dlg.starting": "Starting the export…",
    "export.not_built": "Export isn't built yet. Nothing was exported or recorded.",
    "export.running": "Preparing the export… {n} % · job {id8}",
    "export.running.no_pct": "Preparing the export… · job {id8}",
    "export.poll_failed": "Can't check the export right now — retrying.",
    "export.ready": ("Export ready — {rows} entries (the chain span for {from} to {to} UTC), {size} · sha256 "
                     "{hex8}… [Copy] · key {key_id} · deleted at {yyyy-mm-dd hh:mm} UTC [Download]"),
    "export.trust": ("Verify the signature only with the full key fingerprint you saved from the record of a key "
                     "rotation you performed, or of the first key's generation — never with the key id or a key "
                     "served next to the file."),
    "export.fail.export_too_large": "Too many entries for one file — choose a shorter window.",
    "export.fail.signing_key_rotated": "The signing key changed while the file was made — export again.",
    "export.fail.signing_unavailable": "Signing isn't available — nothing was exported.",
    "export.fail.audit_unavailable": "The export couldn't be recorded, so it wasn't made.",
    "export.fail.internal_error": "The export failed — export again.",
    "export.cancelled": "The export was cancelled.",
    "export.lost": "This export's status is no longer available — start a new export.",
    "export.expired": "The export expired at {yyyy-mm-dd hh:mm} UTC and its file was deleted.",
    "export.limited": "Too many downloads this hour — try again at {hh:mm} UTC.",
    "export.download_failed": "Couldn't start the download — nothing was sent. Try again.",
    "export.unknown": "We couldn't tell whether the export started. [Check again]",
    "export.refused.range": "That window is longer than {days} days.",
    "export.refused.busy": "An export or a signing-key change is already running.",
    "export.refused.rate": "Too many exports this hour — try again at {hh:mm} UTC.",
    "export.refused.signing": "Signing isn't available right now — nothing was started.",
    "export.refused.store": "The export couldn't be recorded, so nothing was started.",
    "export.not_sent": "Not sent.",
    "rec.immutable": "This record cannot be edited or deleted.",
    "rec.role": "Role at the time: not recorded",
    "rec.agent_none": "User agent: not recorded",
    "rec.chain": "Each record is linked to the one before it.",
    "rec.verified_to": "In entries {from}–{to}, checked at {hh:mm} UTC — passed (last tamper check).",
    "rec.not_checked": "No tamper check this session covers this record.",
    "rec.after_break": "Not verified — at or after the break at entry {n}.",
    "rec.correlation_none": "Linked records can't be listed yet.",
    "rec.related_actor": "This actor's entries",
    "rec.related_subject": "This subject's entries",
    "rec.related_time": "Entries around this time",
    "rec.reason_code": "Reason code",
    "rec.reason_given": "Reason given",
    "rec.raw_flagged": "This record holds a value under a secret-named field — report it to security (SR-069).",
    "rec.hidden": "not shown in your view",
    "rec.deleted_user": "deleted-user-{12 hex}",
    "rec.raw_show": "Show raw record",
    "diff.before": "Before",
    "diff.after": "After",
    "diff.requested": "Requested",
    "diff.added": "Added",
    "diff.removed": "Removed",
    "diff.changed": "Changed",
    "diff.created": "Created",
    "diff.no_before": "— (no earlier state recorded)",
    "diff.not_sent": "not sent",
    "diff.overrides_kept": "not sent — the existing overrides stay",
    "diff.head_failed": "Not applied — {reason}",
    "diff.head_intent": "Intent — the outcome is a separate record",
    "diff.result": "Recorded result",
    "diff.head_started": "Started — the result is a separate record",
    "diff.unchanged_n": "{n} unchanged fields",
    "diff.unchanged_n.one": "1 unchanged field",
    "diff.full": "Show full value",
    "diff.inline": "changed from {a} to {b}",
    "diff.inline_requested": "requested {b} (stored {a})",
    "diff.secret": "Secret — never recorded",
    "diff.secret_named": "Hidden — secret-named field",
    "diff.credential": "Redacted — it held a credential",
    "diff.personal": "Personal data, hashed · {hex8}…",
    "diff.oversize": "Too large to record — replaced when it was written",
    "diff.key_id_note": "finds the key; never pin it",
    "diff.none": "none",
    "diff.withheld": "Withheld — too large to show here",
    "diff.hidden": "Not shown in your view",
    "flags.affects": "Affects order entry",
    "flags.affects_desktop": "Affects the desktop app's connection",
    "flags.deployment": "Deployment: {VALUE}",
    "flags.your_override": "You: {VALUE} — your override",
    "flags.your_resolved": "You: {VALUE} — resolved for you",
    "flags.scope": "Deployment",
    "flags.scope.plus_n": "+ {n} user overrides",
    "flags.scope.plus_one": "+ 1 user override",
    "flags.scope.ignored": "overrides ignored",
    "flags.scope_account": "not available",
    "flags.changed_by": "Changed {yyyy-mm-dd hh:mm} UTC by {user}",
    "flags.no_match": "No flags match {q}.",
    "flags.search": "Search flags",
    "flags.count": "{n} flags",
    "flags.count.one": "1 flag",
    "flags.load_failed": "Flags unavailable — {detail}. Nothing can be changed until they load. [Retry]",
    "flags.saving": "Saving…",
    "flags.applied": ("{key}: the deployment value is {VALUE}. Every session gets it within 2 seconds; overrides "
                      "stay."),
    "flags.conflict": ("This flag changed while you were editing: it is now {VALUE}, changed by {user} at "
                       "{hh:mm:ss} UTC. Your reason is kept. [Use the current value]"),
    "flags.err_reason": "Enter a reason (up to 280 characters).",
    "flags.err_credential": "Remove the credential: reasons are recorded as written.",
    "flags.err_character": "Remove line breaks and hidden characters.",
    "flags.fail_closed_value": "fail-closed value",
    "flags.store_down": "Couldn't confirm the change — the flag store is unavailable.",
    "flags.audit_down": "The audit record could not be written; nothing was changed.",
    "flags.checking": "Checking whether the change was applied…",
    "flags.history_no_outcome": "Outcome not recorded",
    "flags.history_full": "Full history → Audit log",
    "maint.off": "Maintenance mode is off.",
    "maint.on": "Maintenance mode is on since {yyyy-mm-dd hh:mm} UTC — turned on by {user}.",
    "maint.on_system": "Maintenance mode is on since {yyyy-mm-dd hh:mm} UTC — turned on outside this console.",
    "maint.list": ("New orders that open or add to a position are refused for everyone. · Running algos are "
                   "cancelled; resting entry orders can still fill. · Recording continues, unless the recorder is "
                   "set to stop during maintenance. · Every session sees a maintenance notice."),
    "maint.stays": ("Still available: cancel, close and flatten (the kill switch's flatten too), reducing and "
                    "stop-tightening amends, attaching a missing stop-loss and re-arming a protective trigger. "
                    "Exchange-side stop-losses are never touched."),
    "maint.list_lead": "While it is on:",
    "maint.window_later": "Scheduled window and message to users",
    "maint.window_field": "Scheduled window",
    "maint.message_field": "Message to users",
    "maint.load_failed": ("Maintenance state unavailable — {detail}. Turning it on or off waits until it loads. "
                          "[Retry]"),
    "maint.turning_on": "Turning on…",
    "maint.turning_off": "Turning off…",
    "maint.conflict": "This changed while you were looking: maintenance mode is already {ON / OFF}.",
    "maint.fail_closed": ("Maintenance mode reads ON because the flag store is unreachable — a fail-closed value, "
                          "not a stored one. New orders are refused while it is unreachable; then the stored "
                          "value applies."),
    "maint.unreadable": ("Maintenance mode reads ON because its stored value can't be read. Turning it off "
                         "repairs it and needs a fresh code."),
    "banner.maintenance_fail_closed": ("Order entry is blocked: maintenance mode's stored value can't be read, so "
                                       "it counts as on. Native stops on the exchange are unaffected."),
    "banner.maintenance_unverified": ("Maintenance mode is on — new orders are refused. Native stops on the "
                                      "exchange are unaffected."),
    "tile.maintenance_fail_closed": "Maintenance: ON (fail-closed)",
    "dlg.flag.title": "Turn {on / off} '{description}' ({key})",
    "dlg.flag.body": "Deployment value from {A} to {B}. {n} user overrides stay; yours: {VALUE}.",
    "dlg.flag.body.one": "1 user override stays",
    "dlg.flag.body.yours": "; yours: {VALUE}",
    "dlg.flag.desktop": ("Turning this off cuts the desktop app off from the backend within about a minute, its "
                         "cancels and kill switch included. Use the web app to turn it back on."),
    "dlg.positions": "Open positions: {n}",
    "dlg.positions.unavailable": "Open positions: unavailable",
    "dlg.conflict_first": "Use the current value first.",
    "dlg.engage.order_entry.title": "Turn on 'Refuses order acceptance' (killswitch.order_entry)",
    "dlg.engage.order_entry.list": ("New orders that open or add to a position are refused for everyone until "
                                    "this is turned off. · Resting orders, positions and exchange-side "
                                    "stop-losses are not touched; cancel, close and flatten still work. · Running "
                                    "algos keep running, but their orders that open or add to a position are "
                                    "refused. · Traders see 'Order entry is paused for maintenance' on a refused "
                                    "order. · This is not the kill switch (FREEZE…), which stays as it is."),
    "dlg.engage.ingestion.title": "Turn on 'Stops market-data ingestion' (killswitch.ingestion)",
    "dlg.engage.ingestion.list": ("Its description says it stops market-data ingestion; nothing reads this switch "
                                  "yet, so ingestion keeps running. · Turning it off always needs a fresh code."),
    "dlg.release.order_entry": ("This switch stops refusing new orders. Maintenance mode and the kill switch "
                                "(FREEZE…; \"Kill switch: engaged\" while it is on) still refuse them while "
                                "either is on."),
    "dlg.maint_off.body": ("This stops refusing new orders for maintenance. The order-entry switch "
                           "(killswitch.order_entry) and the kill switch (FREEZE…; \"Kill switch: engaged\" while "
                           "it is on) still refuse them while either is on. Cancelled algos do not resume."),
    "dlg.release.ingestion": "Nothing reads this switch yet, so ingestion never stopped.",
    "dlg.maint_on.positions": ("Open positions: {n} — they stay open; maintenance doesn't touch their exchange "
                               "stop-losses."),
    "dlg.maint_on.algos": "Running algos are cancelled; if that fails, it is tried again within 5 seconds.",
    "admin.live_gate": "Blocked: live trading is set by the live gate.",
    "admin.flags_store": "Changes wait until the flag store is back.",
    "admin.export_not_built": "Export isn't built yet.",
    "admin.window_not_built": "Scheduling isn't built yet.",
    "admin.rate_limited": "Paused by a rate limit.",
    "admin.newest": "Already at the start of the list.",
    "admin.oldest": "No older entries.",
    "admin.oldest.filtered": "No older entries match these filters.",
    "admin.page_edge": "No more records in the loaded page.",
    "maintenance": "Order entry is paused for maintenance.",
}
COPY_SOURCE = {"flags.group.safety": ("D02", 717), "flags.fail_closed": ("D02", 717), "flags.unreadable": ("D02", 717)}
COPY.update({  # §14 L709 keys whose string D02:717 holds ("D02:717's heading", "D02:717 verbatim")
    "flags.group.safety": "Safety flags — these change what trading can do and need a fresh code to release",
    "flags.fail_closed": ("Flag store unreachable — every flag shows its fail-closed value; changes are refused until "
                          "it is back"),
    "flags.unreadable": "stored value unreadable — resolves to its fail-closed value; saving a valid value repairs it",
})
COPY_PIECES = ("dlg.flag.body.one", "dlg.flag.body.yours")  # never drawn alone: flag_body() splices them
# Inherited keys (§14 L713) outside E42-D03's deck (D03's own are e42kit.COPY): key -> (string, doc, line).
INHERITED: dict[str, tuple[str, str, int]] = {
    "rbac.permission": ("Your role can't {verb}.", "D09", 256),
    "rbac.owner_only": ("Only the owner can {verb}.", "D09", 257),
    "rbac.read_only": ("Read-only after three wrong codes.", "D09", 261),
    # rbac.view_as ("Read-only while viewing as {user}.", D09:262) is e42kit.COPY's, the same D09 string: copy()
    # delegates to it, so no D04 key shadows an E42-D03 key (the self-test's check; G-48).
    "glyph.name": ("Not available", "D09", 264),
    "banner.read_only.title": ("Read-only after three wrong codes.", "D09", 268),
    "banner.read_only.body": ("Changes are off for 5 minutes. Market data keeps streaming; exchange-side stop-losses "
                              "are unaffected.", "D09", 268),
    "inflight.read_only": ("Not sent — read-only after three wrong codes.", "D09", 273),
    "scr154.never_had.h1": ("You don't have access to this", "D09", 275),
    "scr154.never_had.body": ("{reason} Ask the owner if you need it.", "D09", 275),
    "scr154.link": ("Back to your workspace", "D09", 277),
    "scr155.h1": ("Page not found", "D09", 279),
    "scr155.body": ("There's nothing at {route}.", "D09", 279),
    "refusal.trading_disabled.maintenance": ("Order entry is paused for maintenance", "E30", 436),
}
OWNER_ONLY_VERBS = {  # rbac.owner_only's {verb} per control (AL-25 L289, AD-7 L348; D09 §3.2)
    "actor": "see other users' entries", "ip": "filter by IP address", "search": "search the audit log",
    "env": "filter by environment", "export": "export the audit log", "verify": "run a tamper check",
    "raw": "see raw records",
}
# Strings the spec writes in §1-§13 (anatomy, labels, the worked example's literals): key -> (string, first line, last
# line), re-read at SPEC_MD5 (each proved on its lines by the self-test). §14 L712 now keys the anatomy strings under
# `labels.*` (G-29, D30 L194; "each key the string in snake case"), and a few moved into other §14 keys: LABEL_KEYS
# names the key for those, and label() records it as a copy key; the rest stay copy gaps (spec text outside §14).
LABELS: dict[str, tuple[str, int, int]] = {
    "route.audit": ("Audit log", 220, 221), "signed_export": ("Signed export…", 221, 221),
    "run_tamper_check": ("Run tamper check", 226, 226), "newest": ("Newest", 168, 168),
    "newer": ("Newer", 168, 168), "older": ("Older", 168, 168),
    "col.time": ("Time", 240, 240), "col.actor": ("Actor", 240, 240), "col.role": ("Role", 240, 240),
    "col.action": ("Action", 240, 240), "col.target": ("Target", 240, 240), "col.env": ("Environment", 240, 240),
    "col.ip": ("IP", 240, 240), "col.severity": ("Severity", 240, 240), "col.result": ("Result", 241, 241),
    "role.dash": ("—", 249, 249), "role.not_recorded": ("not recorded", 249, 249), "env.none": ("—", 252, 252),
    "env.LIVE": ("LIVE", 252, 252), "env.DEMO": ("DEMO", 252, 252), "env.TESTNET": ("TESTNET", 252, 252),
    "filter.from": ("From", 256, 256), "filter.to": ("To", 256, 256), "filter.utc": ("UTC", 256, 256),
    "filter.actor": ("Actor", 257, 257), "filter.action": ("Action", 257, 257), "filter.subject": ("Subject", 257, 257),
    "filter.outcome": ("Outcome", 258, 258), "filter.severity": ("Severity", 258, 258), "filter.ip": ("IP", 258, 258),
    "filter.search": ("Search", 258, 258), "filter.env": ("Environment", 259, 259), "filters": ("Filters", 292, 292),
    "you": ("you", 289, 289), "my_activity": ("My activity", 289, 289), "clear_filters": ("Clear filters", 271, 271),
    "sev.critical": ("Critical", 166, 166), "sev.error": ("Error", 166, 166), "sev.warning": ("Warning", 166, 166),
    "sev.info": ("Info", 166, 166), "sev.debug": ("Debug", 166, 166), "out.success": ("Success", 167, 167),
    "out.failure": ("Failure", 167, 167), "out.denied": ("Denied", 167, 167),
    "record.h2": ("Record 1,204,118", 324, 324), "previous": ("Previous", 324, 324), "next": ("Next", 324, 324),
    "close": ("Close", 325, 325), "sec.who": ("Who", 325, 325), "sec.what": ("What", 328, 328),
    "sec.diff": ("Before / after", 329, 329), "sec.request": ("Request", 329, 329),
    "sec.related": ("Related", 329, 329),
    "sec.integrity": ("Integrity", 331, 331), "sec.raw": ("Raw record", 332, 332), "f.session": ("session", 327, 327),
    "f.ip": ("IP", 327, 327), "copy": ("Copy", 327, 327), "copied": ("Copied", 343, 343),
    "summary": ("Order submitted (orders.submit) · Success · Info · 2026-10-22 14:01:50.212 UTC · LIVE", 325, 325),
    "what_to_do": ("What to do now", 423, 424), "incident_log": ("Incident log", 424, 424),
    "security_centre": ("Security centre", 425, 425), "compress": ("Compress (gzip)", 457, 457),
    "export": ("Export", 459, 459), "cancel": ("Cancel", 459, 459), "download": ("Download", 286, 286),
    "export_marker": ("Recorded · needs your confirmation — Audit log exported (admin.audit_export)", 449, 450),
    "route.flags": ("Feature flags", 492, 492),
    "flags.meta": ("All times UTC · as of 14:02:09", 492, 492),  # G-14: meta.asof, never "Resolved from the store"
    "meta.utc_only": ("All times UTC", 149, 149),  # §1: the meta before a read's first answer and after a failed one
    "flags.marker": ("Changes here are recorded in the audit log · Flag changed (flags.change)", 495, 496),
    "group.gated": ("Gated", 510, 510), "group.rollouts": ("Rollouts", 511, 511), "group.other": ("Other", 512, 512),
    "scope.deployment": ("Deployment", 499, 499), "scope.plus_one": ("+ 1 user override", 529, 529),
    "scope.ignored": ("overrides ignored", 500, 500), "scope.na": ("not available", 709, 709),
    "change": ("Change…", 501, 501), "history": ("History", 502, 502), "revert_off": ("Revert to OFF", 534, 534),
    "to_maintenance": ("→ Maintenance", 509, 509), "reload_now": ("Reload now", 529, 529), "why": ("Why?", 532, 532),
    "open_positions": ("Open positions: 2", 535, 535), "unavailable": ("unavailable", 535, 535),
    "fc_value": ("fail-closed value", 709, 709), "ON": ("ON", 529, 529), "OFF": ("OFF", 529, 529),
    "turn_on": ("Turn on", 532, 532), "turn_off": ("Turn off", 582, 582),
    "route.maint": ("Maintenance mode", 563, 563), "turn_on_menu": ("Turn on…", 563, 563),
    "turn_off_menu": ("Turn off…", 563, 563), "maint.on_title": ("Turn on maintenance mode", 578, 578),
    "maint.off_title": ("Turn off maintenance mode", 582, 582),
    "fresh_code": ("This always needs a fresh code.", 582, 582),
    "nothing_changed": ("Nothing was changed.", 583, 583),
    "maint.marker": ("Recorded in the audit log · Maintenance on (maintenance.enabled) + Flag changed (flags.change)",
                     568, 568),
    "maint.marker_off": ("Maintenance off (maintenance.disabled) + Flag changed (flags.change)", 569, 570),
    "scr006.title": ("Confirm it's you", 134, 134),
    "action_summary": ("Set feature flag 'killswitch.order_entry' to true, user overrides 0", 517, 517),
    "f.request_id": ("request_id", 329, 329), "f.entry_hash": ("entry_hash", 331, 331),  # §5's field names, drawn
    "f.prev_hash": ("prev_hash", 332, 332),  # as the drawer's terms
    "scope.plus_n": ("+ {n} user overrides", 499, 499), "requires_reload": ("Requires reload", 188, 188),
    "revert": ("Revert to {previous}", 502, 502),
    "motion.col.safe": ("motion-safe: property · duration · easing", 655, 655),  # §13's column headers
    "motion.col.reduce": ("motion-reduce", 655, 655),
    "motion.col.carrier": ("Carries information? (carrier)", 655, 655),
    **{f"sheet.{w_}": (w_, 765, 765) for w_ in ("severity", "outcome", "tamper", "export", "flag")},  # §15's words
    "sheet.maintenance": ("maintenance", 766, 766), "sheet.kinds": ("Shape or kind", 380, 380),  # §6's table header
    "grace.flags": ("flag changes", 185, 185), "grace.audit": ("audit exports", 185, 185),  # D21: D03 band.grace's
}  # {class}, added by §20's A-row (1), PROPOSED to E42-D03 (L882-884)
_LABELS_ROW = {  # §14 L712's `labels.*` groups -> the kit label keys whose string the group lists (key: snake case)
    "col": ("col.time", "col.actor", "col.role", "col.action", "col.target", "col.env", "col.ip", "col.severity",
            "col.result"),
    "filter": ("filter.from", "filter.to", "filter.utc", "filter.actor", "filter.action", "filter.subject",
               "filter.outcome", "filter.severity", "filter.ip", "filter.search", "filter.env", "clear_filters"),
    "page": ("newest", "newer", "older", "previous", "next"),
    "act": ("signed_export", "run_tamper_check", "export", "cancel", "change", "history", "revert", "turn_on_menu",
            "turn_off_menu", "copy", "close", "download", "reload_now", "security_centre", "to_maintenance",
            "incident_log", "what_to_do"),
    "field": ("why", "compress"),
    "word": ("sev.critical", "sev.error", "sev.warning", "sev.info", "sev.debug", "out.success", "out.failure",
             "out.denied", "ON", "OFF", "role.dash", "env.none", "role.not_recorded", "you"),
    "h": ("route.audit", "my_activity", "route.flags", "group.gated", "group.rollouts", "group.other", "route.maint",
          "record.h2", "sec.who", "sec.what", "sec.diff", "sec.request", "sec.related", "sec.integrity", "sec.raw"),
}
_LABELS_AS = {"record.h2": "Record {id}", "revert": "Revert to {previous}"}  # the §14 form of a filled label


def _snake(s: str) -> str:
    """§14 L712's key rule, "each key the string in snake case" (e.g. labels.act.run_tamper_check)."""
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


LABEL_KEYS: dict[str, str] = {  # label key -> the §14 key that now holds its string (label() records it)
    **{lk: (f"labels.{g}.{_snake(_LABELS_AS.get(lk, LABELS[lk][0]))}" if _snake(LABELS[lk][0]) else
            f"labels.{g}.* '{LABELS[lk][0]}'") for g, lks in _LABELS_ROW.items() for lk in lks},
    "scope.deployment": "flags.scope", "scope.plus_one": "flags.scope.plus_one", "scope.ignored": "flags.scope.ignored",
    "scope.plus_n": "flags.scope.plus_n", "scope.na": "flags.scope_account", "fc_value": "flags.fail_closed_value",
    "open_positions": "dlg.positions",
    "flags.meta": "meta.asof",  # D03's key, filled with SCR-145's 14:02:09 (§9 L492)
}
LABEL_KEY_LINE = {"meta.asof": "E42-D03 §14 (§9 L492)", "dlg.positions": "§14 L710"}  # else §14 L712 / L709
OTHER_LABELS: dict[str, tuple[str, str, int]] = {  # strings from the docs D04 builds on: key -> (string, doc, line)
    "scr006.body": ("This action needs your password and a code.", "D01", 634),  # SCR-006's generic body (AL-19)
    "scr006.password": ("Password", "D02", 262),  # the gate wireframe's field (E09-D06's chassis)
    "scr006.confirm": ("Confirm", "E39", 178),  # "Confirm never default-focused" (the SCR-006 chassis, E39-D03)
    "e17.feed_down": ("Exchange feed down — the server is restoring the connection", "E17", 148),  # MM-5's other cause
}  # grace.flags left: D21 L185 now gives the class words (LABELS grace.flags / grace.audit, G-33's A-row to D03)


def copy(key: str, /, **fills: Any) -> str:
    """The string for key with its fills (e42kit.fill(): mss, hhmmss, hhmm, yyyymmdd, yyyymmddhhmm, value, a, b, env,
    n, s, from_/to via **{"from": …}): a D04 §14 key (COPY), an inherited D09 / E30-D02 key (INHERITED) or an
    E42-D03 §14 key (e42kit.COPY, recorded in e42kit.LOG). Records the key."""
    if key in COPY_PIECES:
        raise KeyError(f"{key} is a piece of dlg.flag.body: use flag_body()")
    if key in COPY:
        NOTES.add("copy_keys", key)
        _src("copy")
        if key in COPY_SOURCE:
            doc, ln = COPY_SOURCE[key]
            NOTES.add("sources", f"{doc}:{ln} ({key}'s string, §14 L709)")
        return k.fill(COPY[key], **fills)
    if key in INHERITED:
        s, doc, ln = INHERITED[key]
        NOTES.add("copy_keys", key)
        NOTES.add("sources", f"{doc}:{ln} ({key}, inherited by §14 L713)")
        return k.fill(s, **fills)
    if key in k.COPY:
        return k.copy(key, **fills)  # E42-D03 §14, inherited by §14 L713 (recorded in e42kit.LOG)
    raise KeyError(f"copy key {key!r} is in neither D04 §14, the inherited decks nor E42-D03 §14")


def raw(key: str, /) -> str:
    """The unfilled template of key (any deck copy() reads); records nothing."""
    if key in COPY:
        return COPY[key]
    if key in INHERITED:
        return INHERITED[key][0]
    v = k.COPY[key]
    return " ".join(v) if isinstance(v, tuple) else v


def items(key: str, /, **fills: Any) -> list[str]:
    """A " · "-joined list string (maint.list, dlg.engage.*.list) as its items (outside parentheses)."""
    return k.list_items(copy(key, **fills))


def label(key: str, /, **fills: Any) -> str:
    """A string the spec writes in §1-§13 (LABELS) or a doc D04 builds on gives (OTHER_LABELS); fills as copy(). A
    string §14 now keys (LABEL_KEYS: L712's `labels.*`, or flags.scope*, flags.scope_account,
    flags.fail_closed_value, dlg.positions, D03's meta.asof) is recorded as that copy key with its §14 line; any other
    as a copy gap with its lines."""
    if key in LABELS:
        s, a, b = LABELS[key]
        if key in LABEL_KEYS:
            ck = LABEL_KEYS[key]
            NOTES.add("copy_keys", ck)
            where = LABEL_KEY_LINE.get(ck, "§14 L712, proposed" if ck.startswith("labels.") else "§14 L709")
            NOTES.add("sources", f"E42-D04 {where}: {ck} '{s}' (the anatomy writes it at L{a}" +
                      (")" if a == b else f"-{b})"))
            _src("copy")
        else:
            NOTES.add("copy_gaps", f"'{s}': spec text outside §14 (L{a})" if a == b else
                      f"'{s}': spec text outside §14 (L{a}-{b})")
    elif key in OTHER_LABELS:
        s, doc, ln = OTHER_LABELS[key]
        NOTES.add("copy_gaps", f"'{s}': not keyed in E42-D04 §14 ({doc}:{ln})")
    else:
        raise KeyError(f"label {key!r} is not in LABELS or OTHER_LABELS (add it with its line; never invent it)")
    return k.fill(s, **fills) if fills else s


def flag_body(a: str, b: str, n: int, yours: str | None = None) -> str:
    """dlg.flag.body with §14's own variants (L710): "1 user override stays" for n = 1, and "; yours: {VALUE}" only
    when overrides hold the Owner's user_id (yours = the Owner's value), e.g. FF-5 (L532): flag_body("OFF", "ON", 1,
    "ON") -> "Deployment value from OFF to ON. 1 user override stays; yours: ON."."""
    tpl = COPY["dlg.flag.body"]
    if n == 1:
        tpl = tpl.replace("{n} user overrides stay", COPY["dlg.flag.body.one"])
    if yours is None:
        tpl = tpl.replace(COPY["dlg.flag.body.yours"], "")
    NOTES.add("copy_keys", "dlg.flag.body")
    _src("copy")
    return k.fill(tpl, a=a, b=b, n=n, value=yours or "")


# --- §1's worked example (L136-149) and the state rows' literals: every frame's data. Anything else is a bar().
SAMPLE: dict[str, Any] = {
    "owner": "basiltt", "managers": {"alex": ("sub_001", "sub_002"), "bea": ("sub_003",)}, "viewer": "carol",
    "env": "LIVE", "date": "2026-10-22", "asof": "14:02:11",  # L136-137
    "asof_break": "14:06:02",  # Two moments (L140-143, G-5): AL-13, AL-14 and AD-5 read SCR-144's clock
    "break_entry": "1,204,118", "found_at": "14:05:07", "range_from": "204,119", "range_to": "1,204,118",  # L137-138
    "record": "1,204,118", "record_ts": "2026-10-22 14:01:50.212",  # SCR-136's header and summary (L324-325)
    "flags_asof": "14:02:09",  # SCR-145's meta (L492)
    "maint_since": "2026-10-22 14:02", "maint_hhmm": "14:02",  # MM-4 (L580)
    "open_positions": 2,  # FF-8 / MM-2: "Open positions: 2" (L535)
    "deleted_user": "deleted-user-3f9a…", "system_actor": "system:maintenance",  # AL-5 (L269), L248
    "nested_path": "overrides › 9f1c…",  # §6 (L376)
}
# The three §1 / §4 gaps of 58f901df are closed by the folds: Two moments (§1 L140-143, G-5: frames read 14:02:11 and
# hold no failed run, but AL-13, AL-14 and AD-5 at 14:06:02), AL-2's two named high rows (L143-146) and the Action row
# (L250, G-8: D02's and D03's labels where one exists, else the exact code, CG-3 L917).
ACTIONS: dict[str, tuple[str | None, str]] = {  # registered code -> (label, where the label is written)
    "orders.submit": ("Order submitted", "L325"), "flags.change": ("Flag changed", "L496"),
    "admin.audit_read": ("Audit log viewed", "L172"), "admin.audit_export": ("Audit log exported", "L450"),
    "maintenance.enabled": ("Maintenance on", "L568"), "maintenance.disabled": ("Maintenance off", "L569"),
    "admin.area_entered": ("Area entered", "E42-D03 §14 footer.area_entered"),
    "admin.audit_verify": (None, "CG-3 L917"), "api_key.import": (None, "CG-3 L917"),
    "rbac.denied": (None, "CG-3 L917"), "admin.audit_denied": (None, "CG-3 L917"),
    # §4's Action row (L250, G-8): D02's and D03's labels where one exists, else the exact code (CG-3); the folded
    # spec names Maintenance off (§10 L569) and keys every label under §14's labels.action.* (L712)
    "security.key_policy_violation": (None, "CG-3 L917"), "backup.downloaded": (None, "CG-3 L917"),  # AL-2's high rows
}
SEVERITY = ("critical", "error", "warning", "info", "debug")  # the AuditSeverity enum's words (D2 L166)
HIGH = frozenset({"critical", "error"})  # D2: error and critical are "high"
OUTCOME_KEY = {"success": "out.success", "failure": "out.failure", "denied": "out.denied",
               "started": "audit.result_started", "intent": "audit.result_intent"}  # D3 L167


class Entry(NamedTuple):
    """One audit entry the worked example names; None = not given (a bar)."""

    code: str
    severity: str | None
    outcome: str | None
    ts: str | None  # "2026-10-22 14:01:50.212" (UTC, to the ms)
    actor: str | None
    target: str | None
    env: str | None
    ip: str | None
    source: str


ENTRIES: tuple[Entry, ...] = (  # §1 L138-140's rows and AL-2's Started row (L266); only orders.submit has a time, so
    # the order is the kit's: the rows AL-2 calls out (the high one, the Intent and Started write-ahead rows) lead
    Entry("admin.audit_verify", "critical", None, None, None, None, None, None,
          "§1 L139-140: the failed run (critical)"),
    Entry("flags.change", "warning", "intent", None, "basiltt", None, None, None,
          "§1 L138-139 (written at warning); AL-2 L266 'one Intent flag row'; actor: flags:write is Owner only (L549)"),
    Entry("admin.audit_verify", None, "started", None, None, None, None, None,
          "AL-2 L266 'one Started verify row' (reason: started, D3 L167)"),
    Entry("orders.submit", "info", "success", "2026-10-22 14:01:50.212", None, None, "LIVE", None,
          "§1 L139; SCR-136's record 1,204,118 (L324-325: Success · Info · LIVE)"),
    Entry("api_key.import", None, None, None, None, None, None, None, "§1 L139"),
    Entry("rbac.denied", "warning", None, None, None, None, None, None,
          "§1 L140; written at warning (svc/auth/scopes.py:237)"),
)  # §1's worked-example rows, the failed run's critical record first: since Two moments (L140-143) only the 14:06:02
# pages of AL-13, AL-14 and AD-5 hold it (ROWS_AFTER_BREAK); every other grid draws AL-2's page, ROWS (G-44).
ROWS: tuple[Entry, ...] = (  # AL-2's page 1 (L266): board 02's rows after G-5, G-6, shared by every grid board (G-44)
    Entry("security.key_policy_violation", "critical", None, None, None, None, None, None,
          "AL-2 L266 'two high': §1 L143-146's critical high row, a refused key with a right that moves funds "
          "(svc/accounts/key_import.py:18-20); §1 gives none of its other fields (bars)"),
    Entry("flags.change", "warning", "intent", None, "basiltt", None, None, None,
          "§1 L138-139 (written at warning, svc/admin/flags/writes.py:288); AL-2 L266 'one \"Intent\" flag row' (D3 "
          "L167); actor: flags:write is Owner only (L549), §1's owner basiltt (L136)"),
    Entry("backup.downloaded", "error", None, None, None, None, None, None,
          "AL-2 L266 'two high': §1 L145's error high row (Y:10975-10976); §1 gives none of its other fields (bars)"),
    Entry("admin.audit_verify", "info", "started", None, "basiltt", None, None, None,
          "AL-2 L266 'one \"Started\" verify row': the write-ahead record, success/info with reason started "
          "(svc/api/audit.py:707-708; D3 L167); actor: a run is Owner only (L305-306), §1's owner basiltt (L136)"),
    Entry("orders.submit", "info", "success", "2026-10-22 14:01:50.212", None, None, "LIVE", None,
          "§1 L139; SCR-136's record 1,204,118, row 05 of AL-2's page (AD-1 L342; L324-325: Success · Info · "
          "2026-10-22 14:01:50.212 UTC · LIVE)"),
    Entry("api_key.import", None, None, None, None, None, None, None, "§1 L139"),
    Entry("rbac.denied", "warning", "denied", None, None, None, None, None,
          "§1 L140; written at warning with outcome denied (svc/auth/scopes.py:266-267)"),
)
ROWS_AFTER_BREAK: tuple[Entry, ...] = (  # the 14:06:02 pages of AL-13, AL-14 and AD-5 (§1 L140-143; boards 13, 14, 34)
    Entry("admin.audit_verify", "info", "started", None, None, None, None, None,
          "§1 L142-143: the failed run's Started record (the write-ahead, reason started), above the other rows; "
          "§1 names no actor (a run is on demand or scheduled, §7 L432)"),
    Entry("admin.audit_verify", "critical", "failure", None, None, None, None, None,
          "§1 L139-143: the failed run's critical Failure record, after 14:05:07 (Y:9673-9675); no actor given"),
    *ROWS,
)
PAGE_ROWS = 200  # AL-2 L266 "200 rows": limit=200, the client's page size (D4 L168; `14:2601`)
CALLED_OUT = 4  # rows 01-04 of ROWS: the two high rows, the Intent row and the Started row (AL-2 L266)


class Flag(NamedTuple):
    """One served flag (§9 L505-512; svc/admin/flags/catalogue.py:27-100, read by the self-test)."""

    key: str
    desc: str  # the served description, verbatim
    group: str  # safety | gated | rollouts | other (D18, the client key map, CG-15)
    default: bool  # the catalogue default (a deployment value only when nothing is stored)
    owner_only: bool  # Visibility.OWNER_ONLY
    affects: bool  # flags.affects "Affects order entry" (D18 L182; L511-512)
    affects_desktop: bool  # flags.affects_desktop (L511)


_ALGO = "Emulated {name} algo, enabled per release."
FLAGS: tuple[Flag, ...] = (
    Flag("killswitch.order_entry", "Refuses order acceptance.", "safety", False, False, False, False),
    Flag("killswitch.ingestion", "Stops market-data ingestion.", "safety", False, True, False, False),
    Flag("maintenance.mode", "Maintenance mode: refuses order acceptance, cancels emulated algos, never touches native "
         "exchange stops.", "safety", False, False, False, False),
    Flag("trading.live_enabled", "Master switch for live-environment order entry; stays off until the pen-test "
         "passes.", "gated", False, False, False, False),
    Flag("engine.webgl_v2", "Custom WebGL engine rollout.", "rollouts", False, False, False, False),
    *(Flag(f"algo.{n}", _ALGO.format(name=n), "rollouts", False, False, True, False)
      for n in ("twap", "chase", "iceberg", "scaled", "oco")),
    Flag("desktop.backend_connection", "CORS answers, the CSRF token response header and the desktop cookie "
         "attributes for the SR-042 allow-list (ADR-0038); owner @basiltt, removal #3931", "rollouts", False, True,
         False, True),
    Flag("trading.one_click", "One-click trading; requires an explicit arm.", "other", False, False, True, False),
    Flag("rules.graph_editor", "Node-graph rule editor surface.", "other", True, False, False, False),
    Flag("rules.form_editor", "Form rule editor surface.", "other", True, False, False, False),
    Flag("recorder.auto_record", "Chart and position auto-record.", "other", True, True, False, False),
    Flag("storage.cold_tier", "Parquet/DuckDB routing.", "other", True, True, False, False),
    Flag("maintenance.keep_recorder", "The recorder keeps running while maintenance mode is on.", "other", True, True,
         False, False),
)
FLAG = {f.key: f for f in FLAGS}
GROUPS = ("safety", "gated", "rollouts", "other")  # §9 L507-512, in order
GROUP_LINE = {"safety": 509, "gated": 510, "rollouts": 511, "other": 512}  # §9's group rows (L507-512)
# The three §9 gaps of 58f901df are closed by G-22: the scope cell's forms are §14's flags.scope (L709: "Deployment",
# "+ {n} user overrides" / "+ 1 user override", "overrides ignored", and flags.scope_account), §9's groups quote every
# served description (L509-512), and FF-2 (L529) gives the live row "Deployment: ON" and every other row "its
# registry default", "Changed … by …" as bars (§1 gives none).


class Motion(NamedTuple):
    """One §13 row (L657-679)."""

    id: str
    transition: str
    safe: str
    reduce: str
    carrier: str
    source: str
    line: int


def _parse_motion(lines: list[str]) -> dict[str, Motion]:
    """§13's table rows M1-M23."""
    out: dict[str, Motion] = {}
    for i, row in enumerate(lines, 1):
        if re.match(r"^\|\s*M\d+\s*\|", row):
            c = _cells(row)
            out[c[0]] = Motion(c[0], c[1], c[2], c[3], c[4], c[5], i)
    return out


MOTION = _parse_motion(LINES)
ANIMATED = ("M1", "M2", "M5", "M6", "M12", "M14", "M15", "M19", "M21")  # §13 L696-697
DURATIONS = {"instant": "0 ms", "fast": "100 ms", "normal": "200 ms", "slow": "400 ms"}  # L645-646
EASINGS = {"standard": "(0.2, 0, 0, 1)", "decelerate": "(0, 0, 0, 1)", "accelerate": "(0.3, 0, 1, 1)"}  # L646-647


def plain(s: str) -> str:
    """Spec text without its markdown code ticks and bold (for frames that quote §13 or §6 text)."""
    return s.replace("`", "").replace("**", "")


# --- Generic parts (on e42kit's node builders).
text, hbox, vbox, box, rect, ellipse = k.text, k.hbox, k.vbox, k.box, k.rect, k.ellipse
glyph, icon, button, ring = k.glyph, k.icon, k.button, k.ring
_SLOT = re.compile(r"\{([^{}]+)\}")


def _safe(s: str) -> str:
    """A node-name-safe form of s ('/' splits section paths)."""
    return re.sub(r"\s*/\s*", " or ", s)


def bar(field: str, w: int = 56, h: int = BAR_H, note: str | None = None) -> Node:
    """A value no source gives (§1 L136-149 and the state rows): a neutral bar named by its field, never a number
    (DEVIATIONS["bars"])."""
    _deviate("bars")
    return rect(f"bar · {_safe(field)}", w, h, BAR_FILL, {"radius": R_CONTROL},
                note=note or f"{field}: no worked-example value (§1 L136-149): a bar, never a value")


BUTTON_ACTIONS = ("Retry", "Newest", "Check again", "Use the current value", "Download", "Reload now")


def action(chars: str, focused: bool = False) -> Node:
    """A control named inside a keyed string ("[Retry]"): Copy a CMP-033 composition, the BUTTON_ACTIONS secondary
    CMP-001 buttons, anything else a CMP-021 link (E42-D03's rule)."""
    if chars == "Copy":
        return copy_button(focused=focused)
    if chars in BUTTON_ACTIONS:
        return button(chars, "secondary", focused=focused)
    return link(chars, focused=focused)


def rich(name: str, key: str, /, *, w: int | None = None, typo: str = BODY, color: str = TEXT_1,
         note: str | None = None, focus: str | None = None, **fills: Any) -> Node:
    """A keyed string as one flow: given fills filled in, None fills drawn as bars named by their slot, "[Action]"s as
    controls (action(); focus= names the one with the ring). Every slot must be passed. One text node when nothing is
    unknown and no action sits inside it; else a wrapping row (w=) whose note carries the template."""
    tpl = raw(key)
    vals = {k._norm(f): v for f, v in fills.items()}
    slots = [s for s in _SLOT.findall(tpl)]
    missing = [s for s in slots if k._norm(s) not in vals]
    if missing:
        raise KeyError(f"{key}: pass every slot ({missing} missing; None draws a bar)")
    copy(key, **{f: ("·" if v is None else v) for f, v in fills.items()})  # records the key (and its source)
    s = _SLOT.sub(lambda m: m.group(0) if vals[k._norm(m.group(1))] is None else str(vals[k._norm(m.group(1))]), tpl)
    if "{" not in s and "[" not in s:
        return text(name, s, typo, color, w=w, note=note)
    kids: list[Node] = []
    for i, t in enumerate(re.split(r"(\{[^{}]+\}|\[[^\]]+\])", s), 1):
        if not t.strip():
            continue
        if t.startswith("{"):
            kids.append(bar(t[1:-1]))
        elif t.startswith("["):
            kids.append(action(t[1:-1], focused=focus == t[1:-1]))
        else:
            run = t.strip()
            wide = w is not None and k.text_w(run, typo) > w
            kids.append(text(f"text-{i:02d}", run, typo, color, w=w if wide else None))
    tail = f"; {note}" if note else ""
    return hbox(name, kids, {"wrap": "wrap", "colGap": INSET_XS, "rowGap": STACK_XS}, w=w,
                note=f'copy {key}: "{tpl}"{tail}')


def link(chars: str, *, name: str | None = None, typo: str = BODY, color: str = TEXT_LINK,
         focused: bool = False, note: str | None = None) -> Node:
    """A CMP-021 link: color.text.link with a drawn 1 px underline as wide as its estimated text (DEVIATIONS
    ["link"]); focused adds the CMP-039 ring."""
    _deviate("link")
    n = vbox(name or f"CMP-021 Link (composition) · {_safe(chars)}",
             [text("label", chars, typo, color), rect("underline", max(round(k.text_w(chars, typo)), 4), 1, color)],
             None, note=note)
    return ring(n, R_CONTROL) if focused else n


def copy_button(copied: bool = False, focused: bool = False, name: str | None = None,
                words: str | None = None) -> Node:
    """CMP-033 CopyButton (composition): the copy glyph and "Copy" ("Copied" for 2 s, AD-2 L343, M18), secondary,
    32 px (the library set's look is unverified, so it is composed)."""
    _deviate("compose")
    k._fallback("CONTROL")
    words = words or (label("copied") if copied else label("copy"))
    kids = [icon("icon", "check" if copied else "copy", TEXT_1), text("label", words, BODY_STRONG, TEXT_1)]
    w = round(k.est_width(hbox("m", kids, {"gap": INSET_XS})) + 2 * PX[k.BUTTON_PADX] + 2)
    btn = hbox(name or f"CMP-033 CopyButton (composition) · {words}", kids,
               {"gap": INSET_XS, "padX": k.BUTTON_PADX, "radius": R_CONTROL, "height": k.CONTROL_COMF,
                "fill": k.ACTION_SECONDARY, "justify": "center"}, w=w, h=CONTROL_H,
               note="'Copied' polite once, 2 s (CMP-033, 15:348); unaudited (D02:232)" if copied else
               "copies the full value; unaudited (D02:232)")
    return ring(btn) if focused else btn


def callout(tone: str, *, title: str | None = None, paras: Iterable[str | Node] = (), controls: Iterable[Node] = (),
            after: Iterable[Node] = (), w: int | None = None, shell: bool = False, name: str | None = None,
            note: str | None = None) -> Node:
    """A CMP-028 Callout composition: the tone's .subtle fill and .strong glyph (octagon, triangle, info, check), the
    title (body-strong) and paragraphs (body) in color.text.primary, a controls row under them, then after= (e.g.
    an open disclosure's content); shell=True spans the
    frame under the TopBar (the shell-band slot, no radius). Never dismissible here."""
    if tone not in ("danger", "warning", "info", "success"):
        raise ValueError("callout tone: danger | warning | info | success")
    _deviate("compose")
    fill_, kind, gcol = TONES[tone]
    tw = (w - 2 * PX[INSET_LG] - 16 - PX[INSET_SM]) if w else None
    words: list[Node] = [text("title", title, BODY_STRONG, TEXT_1, w=tw)] if title else []
    for i, p in enumerate(paras, 1):
        words.append(text(f"para-{i}", p, BODY, TEXT_1, w=tw) if isinstance(p, str) else dict(p, name=f"para-{i}"))
    ctl = list(controls)
    if ctl:
        words.append(hbox("controls", ctl, {"gap": INSET_SM, "wrap": "wrap", "align": "center"}, w=tw))
    words += [dict(a) for a in after]
    o: dict[str, Any] = {"gap": INSET_SM, "padX": INSET_LG, "padY": INSET_SM, "fill": fill_, "align": "start"}
    if not shell:
        o["radius"] = R_CARD
    return hbox(name or f"CMP-028 Callout (composition) · {tone}",
                [glyph(kind, gcol), vbox("words", words, {"gap": STACK_XS})], o, w=w, hs="fill" if shell else None,
                note=note or ("the shell-band slot under the TopBar" if shell else None))


def status_line(name: str, tone: str | None, words: str | Node, *, typo: str = BODY, w: int | None = None,
                controls: Iterable[Node] = (), note: str | None = None) -> Node:
    """A status line: the tone's glyph (none for tone None) and its words (a string or a node), then controls; the
    words carry the state, the glyph shape repeats it (§15 L765-767)."""
    kids: list[Node] = [glyph(TONES[tone][1], TONES[tone][2])] if tone else []
    kids.append(text("words", words, typo, TEXT_1, w=w) if isinstance(words, str) else dict(words, name="words"))
    kids += list(controls)
    return hbox(name, kids, {"gap": INSET_SM, "align": "center"}, note=note)


# --- T2 (§12.1 L632-637; E09-D09 §2.2; standing gate G-T2): native role, full label, aria-disabled (never disabled),
# a CMP-019 lock leading the label, the reason in the DOM at mount by aria-describedby; raised fill + border.default
# hairline, label and lock text.tertiary, reason text.secondary; CMP-079 RbacGate wraps it. Never text.disabled or
# opacity.disabled. Busy (a control's own action in flight) and outcomes are not T2 (standing gates).
REASON_PREFIXES = ("admin.", "rbac.")
REASON_KEYS = ("maintenance",)  # MM-5 L581: the ticket's new-risk submit, T2 under a maintenance banner (G-39)


def reason(key: str, /, **fills: Any) -> str:
    """A T2 reason string: a §14 admin.* key, a D09 rbac.* key (verb= for rbac.owner_only / rbac.permission, user=
    for rbac.view_as) or, on the order ticket under maintenance, MM-5's PROPOSED E30-D02 state key "maintenance"
    (§12.1 L637; G-39); ≤ 60 characters, one sentence with a full stop (§14 L711; E09-D09 §3.1)."""
    if not key.startswith(REASON_PREFIXES) and key not in REASON_KEYS:
        raise ValueError(f"T2 reason {key!r}: an admin.* or rbac.* key, or {REASON_KEYS} (§12.1 L637)")
    s = copy(key, **fills)
    if len(s) > 60 or not s.endswith("."):
        raise ValueError(f"T2 reason {key}: {s!r} is over 60 characters or lacks its full stop (E09-D09 §3.1)")
    _src("t2")
    return s


def _t2_note(key: str | None, pointer: str | None) -> str:
    """The note every T2 control carries."""
    why = (f"aria-describedby → the one notice '{pointer}' (one notice, many pointers, §12.1 L637)" if pointer
           else f"aria-describedby → its reason ({key}), in the DOM at mount")
    return (f"T2 (§12.1): aria-disabled='true', never disabled; keeps its Tab stop; CMP-079 RbacGate; CMP-019 lock "
            f"'Not available' leads the label; Enter / Space re-show the reason, polite once, send nothing; {why}")


def t2(chars: str, key: str, /, *, variant: str = "secondary", focused: bool = False, name: str | None = None,
       w: int | None = None, **fills: Any) -> Node:
    """A T2 control, rendering 2a (the reason inline under it): e42kit's t2_button with the reason key resolved; w= the
    reason's wrap width in a narrow cell."""
    n = k.t2_button(chars, reason(key, **fills), variant, name=name)
    if w:
        n["kids"][1]["w"] = w
    n["kids"][0]["note"] = _t2_note(key, None) + f"; variant {variant} when enabled"
    if focused:
        n["kids"][0] = ring(n["kids"][0])
    return n


def t2_pointer(chars: str, notice: str, *, variant: str = "secondary", focused: bool = False,
               name: str | None = None) -> Node:
    """A T2 control whose reason is one shared notice (pointer): the control alone, its note naming the notice."""
    ctl = k.t2_button(chars, "-", variant)["kids"][0]
    ctl["note"] = _t2_note(None, notice) + f"; variant {variant} when enabled"
    if name:
        ctl["name"] = name
    return ring(ctl) if focused else ctl


def t2_notice(key: str, /, *, name: str | None = None, **fills: Any) -> Node:
    """The one notice several T2 controls point at (under the region's header, beside AL-16's line, under the pager's
    T2 pair, the window section's legend): its lock decorative (aria-hidden; text.tertiary) and the reason
    (type.ui.caption, text.secondary), so each pointing control's aria-describedby is the reason sentence alone
    (D09:236; G-41). The controls' own locks stay named (CMP-019, "Not available"; §12.1 L636)."""
    lock = dict(glyph("lock", TEXT_3, "lock"),
                note="decorative (aria-hidden): ties the notice to its T2 controls, whose own locks are named; their "
                     "aria-describedby is the reason text alone (D09:236; §12.1 L637)")
    return hbox(name or f"T2 notice · {key}", [lock, text("reason", reason(key, **fills), CAPTION, TEXT_2)],
                {"gap": INSET_XS}, note="the shared reason node, in the DOM at mount (§12.1 L637)")


def t2_sentence(chars: str, *, name: str | None = None, w: int | None = None, note: str | None = None) -> Node:
    """D09's sentence form: a region whose sole control is withheld shows the sentence alone, no button (§12.1 L637;
    AD-3's rec.raw_flagged is its notice)."""
    return text(name or "T2 sentence form", chars, BODY, TEXT_2, w=w,
                note=note or "D09's sentence form: no button, no glyph (§12.1 L637; G-T2.1c)")


def t2_field(label_: str, value: str | None = None, *, key: str | None = None, pointer: str | None = None,
             w: int = 160, picker: bool = False, name: str | None = None, **fills: Any) -> Node:
    """A T2 field or picker (§12.1 L636: also readonly / aria-readonly, so typing, arrows and paste change nothing):
    the lock leads its label (text.tertiary), the well raised with a border.default hairline, the value text.tertiary,
    then the reason (key=) or a pointer to one notice (pointer=)."""
    k._fallback("CONTROL")
    _deviate("compose")
    head = hbox("label", [glyph("lock", TEXT_3, "lock"), text("text", label_, LABEL, TEXT_3)], {"gap": INSET_XS})
    inner: list[Node] = [text("value", value, BODY, TEXT_3)] if value else []
    if picker:
        inner.append(icon("chevron", "chevron-down", TEXT_3))
    well = hbox("input", inner, {"padX": INSET_SM, "radius": R_CONTROL, "fill": RAISED, "height": k.CONTROL_COMF,
                                 "stroke": BORDER_DEFAULT, "strokeWidth": HAIRLINE, "strokeAlign": "inner",
                                 "justify": "space-between"}, w=w, h=CONTROL_H,
                note=_t2_note(key, pointer) + "; readonly" + ("; aria-readonly (a picker)" if picker else ""))
    kids = [head, well]
    if key:
        kids.append(text("reason", reason(key, **fills), CAPTION, TEXT_2, w=w))
    return vbox(name or f"T2 field · {_safe(label_)}", kids, {"gap": STACK_XS})


# R-2 (§20 L888-899, the CMP-044 C-rows; §15 L752; `15:479` on main, #4414): a dialog's danger confirm is CMP-044's
# merged Confirm, a CMP-001 `danger` (color.text.on-action on color.status.danger.default: 5.05 dark, 10.31 light, 4.54
# hc), never D02 D3's text.primary on danger.subtle with a danger.strong border (D02:129; that border is §15 L752's
# follow-up). (fill, label, stroke) as e42kit.BUTTON_LOOK's rows.
DANGER_DEFAULT = k.DANGER_DEFAULT
CONFIRM_LOOK = (DANGER_DEFAULT, TEXT_ON, None)
R2_NOTE = ("CMP-044's merged Confirm, a CMP-001 `danger`: color.text.on-action on color.status.danger.default (R-2, "
           "§20 L888-899; §15 L752: 5.05 dark · 10.31 light · 4.54 hc; `15:479` on main); D02 D3's danger.strong "
           "border is §15 L752's follow-up")


def danger_confirm(chars: str, *, name: str | None = None) -> Node:
    """A dialog's danger confirm (R-2): e42kit.button()'s geometry, name and label node with CONFIRM_LOOK in place of
    its "destructive" row (D02 D3's look); never auto-focused (§11)."""
    k._fallback("CONTROL")
    _deviate("compose")
    fill_, col, _stroke = CONFIRM_LOOK
    kids = [text("label", chars, BODY_STRONG, col)]
    o: dict[str, Any] = {"gap": INSET_XS, "padX": k.BUTTON_PADX, "radius": R_CONTROL, "height": k.CONTROL_COMF,
                         "justify": "center", "fill": fill_}
    w = round(k.est_width(hbox("m", kids, {"gap": INSET_XS})) + 2 * PX[k.BUTTON_PADX] + 2)
    return hbox(name or f"CMP-001 Button (composition) · {chars}", kids, o, w=w, h=CONTROL_H, note=R2_NOTE)


def waiting_confirm(chars: str, *, name: str | None = None) -> Node:
    """D22 (L186; R-2): a protective engage's confirm while the count read is in flight: natively disabled and skipped
    by Tab, never T2 and never busy (CMP-044's merged form, a Confirm natively disabled until the summary has loaded,
    `15:477` on main). The look is E42-D03's natively disabled validity form (e42kit.validity_native(), D03 4babb1f62
    §12 L584, R-2): the danger fill dropped to color.surface.raised with a color.border.default hairline, the label
    color.text.tertiary; no hint (the settled count is announced once, politely: §12)."""
    k._fallback("CONTROL")
    _deviate("compose")
    kids = [text("label", chars, BODY_STRONG, TEXT_3)]
    o: dict[str, Any] = {"gap": INSET_XS, "padX": k.BUTTON_PADX, "radius": R_CONTROL, "height": k.CONTROL_COMF,
                         "justify": "center", "fill": RAISED, "stroke": BORDER_DEFAULT, "strokeWidth": HAIRLINE,
                         "strokeAlign": "inner"}
    w = round(k.est_width(hbox("m", kids, {"gap": INSET_XS})) + 2 * PX[k.BUTTON_PADX] + 2)
    return hbox(name or f"CMP-001 Button (composition) · {_safe(chars)} (disabled)", kids, o, w=w, h=CONTROL_H,
                note="natively disabled until the count read settles (D22 L186; CMP-044's merged form, `15:477` on "
                     "main; R-2, §20 L888-899): the disabled attribute, skipped by Tab (§12 L629), no lock, no "
                     "CMP-079, never T2 and never busy; E42-D03's natively disabled look (validity_native()); "
                     f"variant danger once the count settles ({R2_NOTE})")


def busy(chars: str, inflight_key: str | None, *, variant: str = "destructive", name: str | None = None) -> Node:
    """A control whose own request is in flight (MM-3 L579, M14 L670): CMP-001 `loading`, aria-busy, focus kept, the
    CMP-014 spinner in place of the label at the label's width, and the in-flight label as status text beside it
    (inflight_key None: none, as the busy Signed export…, whose progress is the export line's, M14, G-1); busy, not
    T2: no lock, no reason key; labels keep their colours (D09:286)."""
    fill_, col, stroke = CONFIRM_LOOK if variant == "destructive" else k.BUTTON_LOOK[variant]  # R-2
    k._fallback("CONTROL")
    _deviate("compose")
    w = round(k.text_w(chars, BODY_STRONG) + 2 * PX[k.BUTTON_PADX] + 2)
    o: dict[str, Any] = {"padX": k.BUTTON_PADX, "radius": R_CONTROL, "height": k.CONTROL_COMF, "justify": "center"}
    if fill_:
        o["fill"] = fill_
    if stroke:
        o.update(stroke=stroke, strokeWidth=HAIRLINE, strokeAlign="inner")
    spin = k.inst("CMP-014 Spinner", "CMP-014 · Spinner", {"Size": "sm"})  # live set: Size only
    btn = hbox(f"CMP-001 Button (composition) · {_safe(chars)} (loading)", [spin], o, w=w, h=CONTROL_H,
               note=f"aria-busy='true'; its name stays '{chars}'; width locked; focus kept; Enter / Space do nothing")
    if inflight_key is None:
        return dict(btn, name=name or btn["name"])
    return hbox(name or f"busy · {_safe(chars)}", [btn, text("in-flight", copy(inflight_key), BODY, TEXT_2)],
                {"gap": INSET_SM}, note="M14 (L670): the spinner for the request's whole life; at 5 s the slow line")


def skeleton(shape: str = "text", count: int = 1, w: int | None = None, h: int | None = None,
             name: str | None = None) -> Node:
    """A CMP-015 Skeleton instance with the props the live set takes, Shape and Count only (G-48: e42kit.skeleton()
    also sets State, which the live CMP-015 lacks; boards 01, 38, 71); static two-tone under reduced motion (M12)."""
    if (shape, str(count)) not in k.SKELETONS:
        raise ValueError(f"CMP-015 has no variant Shape={shape} Count={count}")
    return k.inst(name or f"CMP-015 Skeleton · {shape} ×{count}", "CMP-015 · Skeleton",
                  {"Shape": shape, "Count": str(count)}, w=w, h=h)


def count_text(name: str, chars: str, *, typo: str = BODY, color: str = TEXT_1, w: int | None = None,
               note: str | None = None) -> Node:
    """chars with each whole-word count ("2", "1", "1,204,118") in type.num.base as its own text node and the words
    around it in typo, in a row whose space.inset.xs gap stands for the word space (G-45: D02:120 "type.num.base for
    every count and clock", D02:154 "counts in type.num"; E42-D03's count_text()); the row's note carries the string.
    A string with no count is one text node."""
    segs: list[Node] = []
    buf: list[str] = []

    def flush() -> None:
        """The words gathered so far as one text."""
        if buf:
            run = " ".join(buf)
            wide = w is not None and k.text_w(run, typo) > w
            segs.append(text(f"seg-{len(segs) + 1}", run, typo, color, w=w if wide else None))
            buf.clear()

    for word in chars.split(" "):
        if re.fullmatch(r"\d{1,3}(,\d{3})*", word):
            flush()
            segs.append(text(f"seg-{len(segs) + 1}", word, NUM_BASE, color))
        else:
            buf.append(word)
    flush()
    if len(segs) == 1 and segs[0]["typo"] == typo:
        return dict(segs[0], name=name, **({"note": note} if note else {}))
    _deviate("counts")
    return hbox(name, segs, {"gap": INSET_XS, "wrap": "wrap", "rowGap": STACK_XS}, w=w,
                note=f'copy: "{chars}"' + (f"; {note}" if note else ""))


def why_field(value: str | None = None, *, error: str | None = None, focused: bool = False, readonly: bool = False,
              w: int = 592, name: str = "CMP-040 FormField (composition) · Why?", kept: bool = False) -> Node:
    """§11's Why? (L598; `reason`, ≤ 280, server-required) as CMP-040 FormField (`15:415`, label + control + help /
    error) over a two-line CMP-007 composition (`15:107` is single-line and `15` has no multi-line input: DJ, G-48):
    the well color.surface.sunken with DS-3's color.text.tertiary boundary; value= its text, or kept=True a reason
    the board keeps but §1 does not give (a neutral bar); error= an error key under it (aria-describedby, focus
    there); readonly= while a request is in flight (MM-3: aria-disabled + readonly, never disabled). A focused well
    is drawn 8 px narrower, so its CMP-039 ring keeps the w px column (boards 48, 60's local why_fit())."""
    k._fallback("DS-3")
    _deviate("compose")
    ww = w - 8 if focused else w
    val = ([text("value", value, BODY, TEXT_1, w=ww - 2 * PX[INSET_SM])] if value else
           [bar("reason (kept)", min(240, ww - 2 * PX[INSET_SM]))] if kept else [])
    well = vbox("CMP-007 TextInput (composition) · two lines", val,
                {"pad": INSET_SM, "radius": R_CONTROL, "fill": SUNKEN, "stroke": k.FIELD_EDGE,
                 "strokeWidth": HAIRLINE, "strokeAlign": "inner"}, w=ww, h=56,
                note=("readonly + aria-disabled while in flight (MM-3)" if readonly else "a textarea; Enter never "
                      "confirms (D02 D18; a line break is refused, L538); reason ≤ 280 (L488-489)"))
    kids: list[Node] = [text("label", label("why"), LABEL, TEXT_2), ring(well) if focused else well]
    if error:
        kids.append(k.inline_error(copy(error), w=w))
    return vbox(name, kids, {"gap": STACK_XS}, w=w,
                note="CMP-040: label + control + help/error text (`15:415`); its label is §14's labels.field.why")


def disclosure(chars: str, *, expanded: bool = False, focused: bool = False, name: str | None = None) -> Node:
    """A disclosure button (aria-expanded): the chevron (right closed, down open) and its label, ghost."""
    kids = [icon("chevron", "chevron-down" if expanded else "chevron-right", TEXT_2),
            text("label", chars, BODY_STRONG, TEXT_1)]
    n = hbox(name or f"disclosure · {_safe(chars)}", kids, {"gap": INSET_XS, "padX": INSET_SM, "radius": R_CONTROL,
                                                           "height": k.CONTROL_COMF}, h=CONTROL_H,
             note=f"button, aria-expanded='{'true' if expanded else 'false'}'; a cut, heights never animate (M4)")
    return ring(n) if focused else n


def fold(w: int, what: str) -> Node:
    """A fold marker: the page continues off-frame here (no text); its name and note say what is elided (G-46: the
    frame is a 1:1 viewport, so rows between its ends are elided, never "scrolled past")."""
    return rect(f"fold · {_safe(what)}", w, 1, BORDER_DEFAULT,
                note=f"the frame is a viewport: {what} (elided in this frame); not a UI element")


def audit_marker(label_: str, code: str | None) -> Node:
    """The CMP-093 marker "Recorded in the audit log · <label> (<code>)" (§1 L128, D02 D5; e42kit's marker()): the
    code registered or absent (D28); recorded as a copy gap (the convention, not a §14 key)."""
    n = k.marker(label_, code)
    EMITTED.add(n["chars"])
    NOTES.add("copy_gaps", "'Recorded in the audit log · <label> (<code>)': §1 L128's marker convention (D02 D5)")
    return n

# --- The CMP-087 shell (E42-D03 §4, by reference; D1 L165) with the E42-D03 board reviews' kit fixups applied.
ROUTE_KEY = {"SCR-135": "route.audit", "SCR-145": "route.flags", "SCR-148": "route.maint"}
FOOTER_NOTE = {  # who writes admin.area_entered on each D04 admin route (E42-D03's footer.area_entered)
    "SCR-135": ("admin.area_entered: /admin/audit writes none (its router is not the admin guard's, §4 Events "
                "L308-316); on SCR-135 it comes from the strip's /admin/* reads and the incident read "
                "GET /admin/incidents on entry and every 60 s (§7 L432-435)"),
    "SCR-145": "admin.area_entered: every /admin/feature-flags call writes it (§9 Events L550-555)",
    "SCR-148": "admin.area_entered: its flags read and write are /admin/* calls (§9 L552-555; §10 L559-560)",
}
RENAMES = {"RightRail (composition)": "CMP-209 RightRail (composition)",
           "primary action": "primary action · CMP-001 Button (composition)",
           "footer marker (CMP-093)": "CMP-093 AuditActionTrigger (composition) · footer marker"}
TRIGGER = "CMP-093 AuditActionTrigger"  # "Signed export…" is CMP-001 in CMP-093 (§4 L221, §8 L449)
EDGE = {"stroke": k.ADMIN_RULE, "strokeWidth": THICK, "strokeAlign": "inner"}  # DS-2's nav-entry edge (D02:1003)


def find(n: Node, name: str) -> Node:
    """The first node named name in n's subtree (pre-order); KeyError when there is none."""
    for _p, x in k.walk(n):
        if x["name"] == name:
            return x
    raise KeyError(f"{name!r} is not under {n['name']!r}")


def fixups(fr: Node, screen: str | None = None) -> Node:
    """E42-D03's kit-level review findings on one e42kit frame, in place: the current Admin entry gets DS-2's edge,
    the compositions in RENAMES their build-notes names (a PageHeader primary that is export_control()'s CMP-093
    composition is named for it), the footer marker its D04 route's note."""
    for _p, n in k.walk(fr):
        if n["name"] == "Admin entry" and (n.get("o") or {}).get("fill") == SELECTED and "stroke" not in n["o"]:
            n["o"].update(EDGE)
            n["note"] = f"{n.get('note', '')}; DS-2 edge (D02:1003): text.tertiary, border.thick, inner"
            k.LOG.add("tokens", THICK)
            _deviate("edge")
        for kid in n.get("kids") or []:
            if kid["name"] == "primary action" and str(kid.get("note", "")).startswith(TRIGGER):
                kid["name"] = f"primary action · {TRIGGER} (composition)"
                _deviate("renames")
            elif kid["name"] in RENAMES:
                kid["name"] = RENAMES[kid["name"]]
                _deviate("renames")
            if kid["name"] == RENAMES["footer marker (CMP-093)"] and screen in FOOTER_NOTE:
                kid["note"] = FOOTER_NOTE[screen]
    return fr


def meta_line(asof: str | None = None) -> str:
    """The PageHeader meta (§1 L146-149, G-14): D03's meta.asof "All times UTC · as of {hh:mm:ss}" once a read has
    answered (asof= its time, default §1's 14:02:11), or "All times UTC" alone before the first answer and after a
    failed first read (AL-1, AL-15, FF-1, FF-17, MM-10, MM-11): pass asof="" for that."""
    if asof == "":
        return label("meta.utc_only")
    return k.copy("meta.asof", hhmmss=asof or SAMPLE["asof"])


def shell(px: int, screen: str, *, h1: str | None = None, meta: str | Node | None = None, primary: Node | None = None,
          marker_line: str | None = None, items: Iterable[Node] = (), right: Node | None = None,
          content: Iterable[Node] = (), banners: Iterable[Node] = (), overlays: Iterable[Node] = (),
          name: str | None = None, footer: bool = True, gap: str = STACK_MD) -> Node:
    """An admin route's frame (SCR-135, SCR-145, SCR-148) on e42kit's CMP-087 shell: band "◆ Admin area · <route>"
    (no badge: DEVIATIONS["shell"] unless right= passes e42kit.badge() or grace_line()), rule, strip (items= e42kit
    strip_item()s, else strip.none), PageHeader (h1, meta: a string, default meta_line(), or a node such as a
    CMP-015 skeleton, drawn in the meta's place, G-48; primary; marker line), the route content in one column with
    gap= between parts, the footer marker; banners= in the shell-band slot under the TopBar (D26: maintenance right
    after the EnvBanner, one banner per cause); overlays= modal() or an absolute drawer."""
    if screen not in ROUTE_KEY:
        raise ValueError(f"shell(): an admin route of D04 ({sorted(ROUTE_KEY)}); others use app_frame()")
    route = label(ROUTE_KEY[screen])
    if right is None:
        _deviate("shell")
    body = [vbox("route content", list(content), {"gap": gap}, w=SIZES[px].inner)] if content else []
    fr = k.shell(px, route=route, h1=h1 or route, right=right, items=items,
                 meta=meta if isinstance(meta, str) else None, primary=primary, marker_line=marker_line,
                 content=body, banners=banners, overlays=overlays, name=name, footer=footer)
    if isinstance(meta, dict):
        titles = find(fr, "titles")
        i = [x["name"] for x in titles["kids"]].index("meta")
        titles["kids"][i] = dict(meta, name="meta")
    _src("decisions")
    _deviate("chrome")
    return fixups(fr, screen)


def app_frame(px: int, content: Iterable[Node] = (), *, admin_entry: bool = False, banners: Iterable[Node] = (),
              overlays: Iterable[Node] = (), center: bool = False, name: str | None = None) -> Node:
    """A non-admin route's frame (a Manager's "My activity", SCR-154 / SCR-155, a role's workspace under a banner):
    e42kit's SCR-010 shell without CMP-087; admin_entry=False is a Manager's or Viewer's NavRail."""
    fr = k.app_shell(px, content, admin_entry=admin_entry, banners=banners, overlays=overlays, center=center,
                     name=name)
    _deviate("chrome")
    return fixups(fr, None)


# --- SCR-135 Audit log (§4 L216-316): columns, cells, rows and the grid (CMP-049 composition, an APG grid).
AUDIT_COLS = (("expander", None, 24), ("time", "col.time", 104), ("actor", "col.actor", 144), ("role", "col.role", 56),
              ("action", "col.action", 128), ("target", "col.target", 144), ("env", "col.env", 80),
              ("ip", "col.ip", 104), ("severity", "col.severity", 96), ("result", "col.result", 64))  # L239-241 (G-7)
EXPANDER_W = 24  # CMP-173's expander button cell (L239-240; E11-D04:189 "fixed"): not scaled (DEVIATIONS)
ROLE_MIN_2560 = 96  # "Role never under 96 px ('not recorded')" at 2560 (L242-243)
NARROW = 96  # a column this wide or narrower pads its cells with space.inset.xs (else space.inset.sm)


def _pad(width: int) -> str:
    """A grid cell's horizontal padding token for its column width."""
    return INSET_XS if width <= NARROW else INSET_SM


def audit_cols(px: int = 1280, inner: int | None = None) -> tuple[k.Col, ...]:
    """§4's ten columns (L238-243, G-7): at 1280 the 944 px widths as written (expander 24 · Time 104 · Actor 144 ·
    Role 56 · Action 128 · Target 144 · Environment 80 · IP 104 · Severity 96 · Result 64); at 2560 "the same order
    scaled to 2,048 px, or to 1,392 px beside the docked drawer" (inner= the grid's width), the expander staying a
    24 px button cell (DEVIATIONS["expander"]) and Role never under 96 px or its 'not recorded' min-content (L242-243;
    G-48). A header wider than its column takes its shortfall from Target, as a browser's min-content would (DJ)."""
    inner = inner or SIZES[px].inner
    rest = 944 - EXPANDER_W
    widths = [EXPANDER_W if cid == "expander" else int(w * (inner - EXPANDER_W) / rest) for cid, _k, w in AUDIT_COLS]
    widths[-1] += inner - sum(widths)
    cols = [k.Col(cid, label(key) if key else "", w) for (cid, key, _w), w in zip(AUDIT_COLS, widths, strict=True)]
    if inner != 944 or px != 1280:
        _deviate("expander")
    ids = [c.id for c in cols]
    ti = ids.index("target")

    def widen(i: int, need: int, why: str) -> None:
        """Column i to need px, the shortfall from Target, with the deviation recorded."""
        c = cols[i]
        short = need - c.width
        cols[i], cols[ti] = c._replace(width=need), cols[ti]._replace(width=cols[ti].width - short)
        _deviate("cols", f"SCR-135's {c.header} column is {need} px in a {inner} px grid, not {c.width} px: {why}, "
                         f"so Target gives {short} px (L239-243; a browser's min-content does the same).")

    for i, c in enumerate(cols):
        if c.id == "expander":
            continue
        need = math.ceil(k.text_w(c.header, LABEL) + 2 * PX[_pad(c.width)])
        if need > c.width:
            widen(i, need, f"its header in type.ui.label needs about {need} px with its padding")
    if px == 2560:
        ri = ids.index("role")
        txt = label("role.not_recorded")
        need = max(ROLE_MIN_2560, math.ceil(k.text_w(txt, BODY) + 2 * PX[INSET_SM]))
        if cols[ri].width < need:
            widen(ri, need, f"Role is never under {ROLE_MIN_2560} px at 2560 and '{txt}' needs about {need} px")
    return tuple(cols)


def audit_header(cols: Iterable[k.Col], name: str = "header") -> Node:
    """The column header row (32 px, color.surface.hover, type.ui.label in text.secondary): Time carries the
    arrow-down glyph (text.tertiary) for aria-sort="descending", not operable (D6 L170); the expander's header cell
    holds no text (its buttons carry their own names)."""
    kids = []
    for c in cols:
        if c.id == "expander":
            kids.append(box(c.id, [], None, w=c.width, h=ROW_H, note="the expander column's header: no text"))
            continue
        ck = [text("label", c.header, LABEL, TEXT_2)]
        note = None
        if c.id == "time":
            ck.append(icon("sort", "arrow-down", TEXT_3))
            note = "aria-sort='descending' on Time only, not operable (D6 L170): newest first"
        kids.append(hbox(c.id, ck, {"gap": INSET_XS, "padX": _pad(c.width)}, w=c.width, h=ROW_H, note=note))
    return hbox(name, kids, {"fill": HOVER, "height": k.ROW_COMF}, h=ROW_H, note="role='row' of columnheaders")


def expander_cell(*, expanded: bool = False, selected: bool = False, focused: bool = False) -> list[Node]:
    """The 24 px expander cell (CMP-173's button, L239-240): the chevron (right closed, down open; aria-expanded),
    and on the selected row the check glyph at the cell's left edge before it (D14 L178, G-38: CMP-019 check,
    color.text.primary, aria-hidden; E11-D04:296's two glyphs in one 24 px cell), both size.icon.sm."""
    _fallback("ICON_SM")
    chev = icon("chevron", "chevron-down" if expanded else "chevron-right", TEXT_2, size=k.ICON_SM,
                note=f"CMP-173's expander button, aria-expanded='{'true' if expanded else 'false'}' (Space, D14)")
    kids: list[Node] = []
    if selected:
        kids.append(icon("selected", "check", TEXT_1, size=k.ICON_SM,
                         note="the selected row's non-colour marker (D14 L178; G-38): CMP-019 check, "
                              "color.text.primary, aria-hidden='true' (selection is aria-selected); 10.17 on selected "
                              "(§15 L745)"))
    kids.append(chev)
    cell = hbox("button", kids, {"justify": "start" if selected else "end"}, w=EXPANDER_W, h=ROW_H)
    return [ring(cell, R_CONTROL) if focused else cell]


def cell_text(name: str, chars: str, *, typo: str = BODY, color: str = TEXT_1) -> Node:
    """One cell value (single line; the grid never wraps a value)."""
    return text(name, chars, typo, color)


def time_cell(ts: str | None) -> list[Node]:
    """`ts` "shown to the ms with the date" (L247), UTC, in type.num.sm text.secondary, date over time."""
    if ts is None:
        return [bar("ts", 72)]
    d, t = ts.split(" ")
    return [vbox("ts", [text("date", d, NUM_SM, TEXT_2), text("time", t, NUM_SM, TEXT_2)], None,
                 note=f"{ts} UTC (Clocks, L146-149)")]


def severity_cell(sev: str | None) -> list[Node]:
    """D2 (L166): the enum's word in text.primary; error and critical "high": the octagon (danger.strong) and the
    word in font.weight.semibold (FALLBACKS["SEMIBOLD"]); warning the triangle; info and debug the word alone."""
    if sev is None:
        return [bar("severity", 48)]
    word = label(f"sev.{sev}")
    if sev in HIGH:
        _fallback("SEMIBOLD")
        return [glyph("octagon", DANGER_STRONG), text("word", word, HIGH_TYPO, TEXT_1)]
    if sev == "warning":
        return [glyph("triangle", WARN_STRONG), text("word", word, BODY, TEXT_1)]
    return [text("word", word, BODY, TEXT_1)]


def result_cell(outcome: str | None) -> list[Node]:
    """D3 (L167): the outcome as a word on a terminal record; a write-ahead record reads Started or Intent."""
    if outcome is None:
        return [bar("outcome", 40)]
    key = OUTCOME_KEY[outcome]
    return [text("word", copy(key) if key.startswith("audit.") else label(key), BODY, TEXT_1)]


def action_cell(code: str, px: int) -> list[Node]:
    """The label D02 and D03 give the code where one exists (L250, G-8; "Order submitted"), keyed in §14 as
    labels.action.* (L712, recorded as a copy key); at 2560 the code under it in type.num.sm (L242); no label: the
    exact code (CG-3 L917)."""
    lab, _where = ACTIONS.get(code, (None, ""))
    if lab is None:
        return [text("code", code, NUM_SM, TEXT_1, note="no D02 / D03 label (L250; CG-3): the exact code")]
    NOTES.add("copy_keys", f"labels.action.{_snake(lab)}")
    if px == 2560:
        return [vbox("action", [text("label", lab, BODY, TEXT_1), text("code", code, NUM_SM, TEXT_2)], None)]
    return [text("label", lab, BODY, TEXT_1, note=f"code {code} (shown in SCR-136 at 1280)")]


def env_cell(env: str | None, *, projected: bool = False) -> list[Node]:
    """`environment` (L252): LIVE / DEMO as the CMP-012 env badge, TESTNET as its word, null "—"; a Manager's
    projection "not shown in your view" (rec.hidden)."""
    if projected:
        return [text("hidden", copy("rec.hidden"), CAPTION, TEXT_2)]
    if env is None:
        return [bar("environment", 36)]
    if env in ("LIVE", "DEMO"):
        return [k.env_badge(env)]
    return [text("word", label("env.none") if env == "—" else label(f"env.{env}"), BODY, TEXT_1)]


def audit_row(e: Entry, cols: Iterable[k.Col], *, px: int, name: str, selected: bool = False,
              focus: str | None = None, projected: bool = False, expanded: bool = False) -> Node:
    """One CMP-173 row (32 px, color.surface.raised, a 1 px color.border.subtle divider): the expander cell (CMP-173's
    button; expanded= AL-3's open row) and §4's cells from an Entry (None values are bars); a high row adds the 2 px
    color.status.danger.strong left rule (D2; §15 L763: a real border-left); selected = the color.surface.selected
    row with D14's non-colour marker, the check glyph at the expander cell's left edge (G-38; aria-selected), meta
    staying text.secondary (L744); focus= a column id gets the inner 2 px ring (the grid's roving cell); projected =
    a Manager's row (L251-253)."""
    cl = list(cols)
    cells: dict[str, list[Node]] = {
        "expander": expander_cell(expanded=expanded, selected=selected),
        "time": time_cell(e.ts),
        "actor": [cell_text("actor", e.actor)] if e.actor else [bar("actor_username", 64)],
        "role": [role_text(px)],
        "action": action_cell(e.code, px),
        "target": [cell_text("target", e.target, color=TEXT_2)] if e.target else [bar("subject_type · subject", 96)],
        "env": env_cell(e.env, projected=projected),
        "ip": ([text("hidden", copy("rec.hidden"), CAPTION, TEXT_2)] if projected else
               [text("ip", e.ip, NUM_SM, TEXT_2)] if e.ip else [bar("ip", 72)]),
        "severity": severity_cell(e.severity),
        "result": result_cell(e.outcome),
    }
    kids = []
    for c in cl:
        o: dict[str, Any] = {"gap": INSET_XS, "padX": _pad(c.width)} if c.id != "expander" else {}
        if focus == c.id:
            o.update(stroke=FOCUS_RING, strokeWidth=FOCUS_W, strokeAlign="inner")
        kids.append(hbox(c.id, cells[c.id], o or None, w=c.width, h=ROW_H))
    total = sum(c.width for c in cl)
    kids.append(rect("divider", total, 1, BORDER_SUBTLE, x=0, y=ROW_H - 1, abs=True))
    high = e.severity in HIGH
    if high:
        _fallback("THICK")
        kids.append(rect("high rule", HIGH_RULE_W, ROW_H, DANGER_STRONG, x=0, y=0, abs=True,
                         note="border-left 2 px (border.thick) color.status.danger.strong: a carrier with the word and "
                              "its weight (D2; AC-4; §15 L762-763: ΔL* 67.4 / 45.9)"))
    note = f"{e.code}: {e.source}" + ("; high" if high else "")
    if selected:
        note += ("; selected: aria-selected='true', the check at the expander cell's left edge and the fill (the fill "
                 "1.41:1 on raised carries nothing; D14 L178, §15 L745)")
    return hbox(name, kids, {"height": k.ROW_COMF, "fill": SELECTED if selected else RAISED}, w=total, h=ROW_H,
                note=note + "; Space expands (aria-expanded), Enter opens SCR-136 (D14)")


def role_text(px: int) -> Node:
    """The Role cell's fixed text: "—" at 1280, "not recorded" at 2560 (§4 L249; CG-1, D17), text.secondary."""
    return text("role", label("role.dash") if px == 1280 else label("role.not_recorded"), BODY, TEXT_2,
                note="no role at the time is recorded (CG-1, D17)")


def _px_of(cols: list[k.Col]) -> int:
    """The frame size a column set was scaled for: 944 px and under is 1280's grid, wider is 2560's."""
    return 1280 if sum(c.width for c in cols) <= SIZES[1280].inner else 2560


def bar_row(cols: Iterable[k.Col], name: str, px: int | None = None) -> Node:
    """A row the worked example gives no data for (density only): every cell a bar named by its field but the
    expander's chevron and Role, which reads "—" at 1280 and "not recorded" at 2560 as audit_row() draws it (§4 L249;
    G-40); px defaults to the columns' size."""
    cl = list(cols)
    size = px or _px_of(cl)
    fields = {"time": "ts", "actor": "actor_username", "action": "action", "target": "subject",
              "env": "environment", "ip": "ip", "severity": "severity", "result": "outcome"}
    kids = []
    for c in cl:
        if c.id == "expander":
            kids.append(hbox(c.id, expander_cell(), None, w=c.width, h=ROW_H))
        elif c.id == "role":
            kids.append(hbox(c.id, [role_text(size)], {"padX": _pad(c.width)}, w=c.width, h=ROW_H))
        else:
            kids.append(hbox(c.id, [bar(fields[c.id], min(64, c.width - 2 * PX[_pad(c.width)]))],
                             {"padX": _pad(c.width)}, w=c.width, h=ROW_H))
    total = sum(c.width for c in cl)
    kids.append(rect("divider", total, 1, BORDER_SUBTLE, x=0, y=ROW_H - 1, abs=True))
    return hbox(name, kids, {"height": k.ROW_COMF, "fill": RAISED}, w=total, h=ROW_H,
                note="a row of the 200 with no worked-example data (§1 L136-149): bars, and Role's fixed '—' / "
                     "'not recorded' (L249)")


def entry_rows(px: int, cols: Iterable[k.Col] | None = None, entries: Iterable[Entry] = ROWS, *,
               selected: int | None = None, focus: tuple[int, str] | None = None, projected: bool = False,
               fill_to: int = 0, expanded: int | None = None) -> list[Node]:
    """entries (default ROWS, AL-2's page, G-44; ENTRIES and ROWS_AFTER_BREAK are the other sets) as CMP-173 rows,
    then bar rows up to fill_to rows in all; selected= / expanded= a 1-based row index; focus= (row index, column
    id)."""
    cl = list(cols or audit_cols(px))
    rows = [audit_row(e, cl, px=px, name=f"row-{i:02d}", selected=selected == i, expanded=expanded == i,
                      focus=focus[1] if focus and focus[0] == i else None, projected=projected)
            for i, e in enumerate(entries, 1)]
    rows += [bar_row(cl, f"row-{i:02d}", px) for i in range(len(rows) + 1, fill_to + 1)]
    return rows


def page_rows(px: int, cols: Iterable[k.Col] | None = None, entries: Iterable[Entry] = ROWS, *,
              n: int = PAGE_ROWS, **kw: Any) -> list[Node]:
    """A whole page as rows: entries (default ROWS, AL-2's page 1) then bar rows to n (AL-2's 200; G-44); kw as
    entry_rows() (selected, focus, projected, expanded). audit_page() folds the rows a frame cannot hold."""
    return entry_rows(px, cols, entries, fill_to=n, **kw)


def diff_row(cols: Iterable[k.Col], diff_node: Node, controls: Iterable[Node] = (), name: str = "diff row") -> Node:
    """AL-3's expansion (L267): a full-width grid row under its row holding §6's full form; its Copy and disclosure
    buttons are cells (← →; Enter or Space acts)."""
    w = sum(c.width for c in cols)
    kids = [diff_node] + ([hbox("cells", list(controls), {"gap": INSET_SM})] if controls else [])
    return vbox(name, kids, {"fill": RAISED, "padX": INSET_LG, "padY": INSET_SM, "gap": STACK_SM}, w=w,
                note="role='row' spanning the grid (aria-expanded on its row); a cut, heights never animate (M4)")


def audit_grid(rows: Iterable[Node], cols: Iterable[k.Col], *, caption: bool = True, end: Node | None = None,
               name: str = "CMP-049 grid region") -> Node:
    """The caption (audit.caption, type.ui.caption, text.secondary) over the CMP-049 grid (header + rows) and, when
    has_more is false, the end line under the last row (audit.end = admin.oldest's node, AL-9)."""
    cl = list(cols)
    grid = vbox("CMP-049 grid (composition)", [audit_header(cl), *rows] + ([end] if end else []), None,
                w=sum(c.width for c in cl),
                note="role='grid', one tab stop, roving tabindex, aria-rowindex when virtualised; ↑ ↓ rows, ← → cells, "
                     "Home / End, PgUp / PgDn; Space expands; Enter opens SCR-136 (L296-298)")
    kids = ([text("caption", copy("audit.caption"), CAPTION, TEXT_2, note="the grid's caption (D17)")] if caption
            else []) + [grid]
    return vbox(name, kids, {"gap": STACK_SM})


PAGER_STATES = ("first", "middle", "end", "empty", "limited")


def pager(state: str = "first", *, focus: str | None = None, name: str = "CMP-053 Pagination (composition)") -> Node:
    """CMP-053 in cursor mode (D4 L168; Appendix A L1029-1030): [Newest] [Newer] [Older], no page number, no
    aria-current; T2 buttons keep e42kit's names, "CMP-001 Button (composition) · Newest (T2)" (G-41). first: Newest
    and Newer T2 admin.newest with its one notice right after Newer, under the pair it describes (2a, §12.1 L637; its
    lock decorative, so their aria-describedby is the sentence alone, D09:236), Older after the pair; end: Older T2
    admin.oldest, whose node is the audit.end line under the last row (AL-9); empty: as first, and Older pointing at
    the no-match line; limited: every button T2 admin.rate_limited pointing at AL-16's one notice beside
    audit.limited. Before the first answer there is no pager (D4 L168: audit_page(pager_state="none"))."""
    if state not in PAGER_STATES:
        raise ValueError(f"pager state: one of {PAGER_STATES}")
    _src("audit")
    names = {b: label(b) for b in ("newest", "newer", "older")}
    gated: dict[str, str] = {}
    if state in ("first", "empty"):
        gated.update(newest="admin.newest", newer="admin.newest")
    if state == "end":
        gated["older"] = "admin.oldest"
    if state == "empty":
        gated["older"] = "the no-match line (audit.no_match or audit.own_no_match)"
    if state == "limited":
        gated = {b: "admin.rate_limited" for b in names}
    ctl: dict[str, Node] = {}
    for b, chars in names.items():
        if b in gated:
            target = gated[b]
            if target.startswith("admin."):
                reason(target)  # records the key and proves its length
            where = {"admin.newest": "the one admin.newest notice right after Newer, under the pair (L168)",
                     "admin.oldest": "the audit.end line under the last row (admin.oldest's node, L273, L711)",
                     "admin.rate_limited": "AL-16's notice beside the audit.limited line (L280)"}.get(target, target)
            ctl[b] = t2_pointer(chars, where, focused=focus == b)
        else:
            ctl[b] = button(chars, "secondary", focused=focus == b)
    kids: list[Node]
    if state in ("first", "empty"):
        pair = vbox("T2 pair and its reason",
                    [hbox("T2 pair", [ctl["newest"], ctl["newer"]], {"gap": INSET_SM}),
                     t2_notice("admin.newest", name="reason · admin.newest")], {"gap": STACK_XS},
                    note="2a: the one reason under the two controls it describes, each pointing at it by "
                         "aria-describedby (§12.1 L637); in the DOM right after Newer, before Older (G-41)")
        kids = [pair, ctl["older"]]
    else:
        kids = [ctl["newest"], ctl["newer"], ctl["older"]]
    return hbox(name, kids, {"gap": INSET_SM, "align": "start"},
                note="nav aria-label='Pagination', cursor mode: no aria-current; once a page loads focus moves to its "
                     "first row (L298-300); a T2 press loads nothing and re-shows its reason")


FILTERS = (("from", "filter.from", 150, False), ("to", "filter.to", 150, False), ("actor", "filter.actor", 140, True),
           ("action", "filter.action", 180, True), ("subject", "filter.subject", 160, False),
           ("outcome", "filter.outcome", 130, True), ("severity", "filter.severity", 130, True),
           ("ip", "filter.ip", 140, False), ("search", "filter.search", 220, False),
           ("env", "filter.env", 200, True))  # L256-259 (id, label key, width, picker); widths are the kit's


def filter_field(fid: str, label_: str, value: str | Node | None, *, w: int, picker: bool, focused: bool = False,
                 error: str | None = None) -> Node:
    """One CMP-174 control: the label (type.ui.label, text.secondary) over a 32 px CMP-007 / CMP-009 well
    (color.surface.sunken with DS-3's boundary); From / To carry "UTC" (Appendix A L1016: "From and To say UTC"); a
    picker its chevron; value= text or a node (a bar); an empty well keeps "UTC" or its chevron at its right end
    (justify end, G-48), a filled one the value at the left; error= a key under it (aria-describedby; focus moves
    there, nothing is announced)."""
    k._fallback("DS-3")
    _deviate("compose")
    inner: list[Node] = ([text("value", value, BODY, TEXT_1)] if isinstance(value, str) and value else
                         [dict(value, name="value")] if isinstance(value, dict) else [])
    if fid in ("from", "to"):
        inner.append(text("utc", label("filter.utc"), CAPTION, TEXT_3))
    if picker:
        inner.append(icon("chevron", "chevron-down", TEXT_2))
    well = hbox("input", inner, {"padX": INSET_SM, "radius": R_CONTROL, "fill": SUNKEN, "height": k.CONTROL_COMF,
                                 "stroke": k.FIELD_EDGE, "strokeWidth": HAIRLINE, "strokeAlign": "inner",
                                 "justify": "space-between" if value else "end"}, w=w, h=CONTROL_H)
    kids = [text("label", label_, LABEL, TEXT_2), ring(well, R_CONTROL) if focused else well]
    if error:
        kids.append(k.inline_error(copy(error), w=w))
    return vbox(f"filter · {fid}", kids, {"gap": STACK_XS})


def filter_bar(px: int, *, values: dict[str, str] | None = None, view: str = "raw", blocked: bool = False,
               errors: dict[str, str] | None = None, focus: str | None = None, w: int | None = None) -> Node:
    """CMP-174 AuditFilterBar (composition; L256-261, Appendix A L1014-1017): From / To (UTC), Actor, Action, Subject,
    Outcome, Severity (one value, D7), IP, Search, Environment ("this page only", D7); values= {id: shown text}, e.g.
    {"env": copy("audit.env_page", env="LIVE")}; view="own" (AL-25): Actor fixed to "you" and IP, Search, Environment
    T2 rbac.owner_only with their verbs (OWNER_ONLY_VERBS); blocked=True (AL-16): every control T2 admin.rate_limited
    pointing at the one notice beside audit.limited; errors= {id: key} (AL-17)."""
    _src("audit")
    vals, errs = dict(values or {}), dict(errors or {})
    width = w or SIZES[px].inner
    kids: list[Node] = []
    own = {"actor": "actor", "ip": "ip", "search": "search", "env": "env"}
    for fid, key, fw, picker in FILTERS:
        lab = label(key)
        if blocked:
            kids.append(t2_field(lab, vals.get(fid), pointer="AL-16's notice beside the audit.limited line (L280)",
                                 w=fw, picker=picker, name=f"filter · {fid}"))
        elif view == "own" and fid in own:
            value = label("you") if fid == "actor" else vals.get(fid)
            kids.append(t2_field(lab, value, key="rbac.owner_only", verb=OWNER_ONLY_VERBS[own[fid]], w=fw,
                                 picker=picker, name=f"filter · {fid}"))
        else:
            kids.append(filter_field(fid, lab, vals.get(fid), w=fw, picker=picker, focused=focus == fid,
                                     error=errs.get(fid)))
    return hbox("CMP-174 AuditFilterBar (composition)", kids, {"wrap": "wrap", "gap": FIELD_GAP, "align": "start"},
                w=width, note="<form role='search' aria-label='Filter the audit log'>; the set is URL state, a change "
                              "resets the cursor, which is never URL state (Environment re-filters the loaded rows and "
                              "keeps it, D7; L260-261); a 422 moves focus to its field and announces nothing")


def new_pill(n: int | None = None, *, focused: bool = False, w: int | None = None) -> Node:
    """The new-entries pill (D5 L169, AL-8): audit.new_n ("1 new entry …", "200+ …" at the cap) on
    color.status.info.subtle with the info glyph (§15 L748); None draws the count as a bar; the row holds it above
    row 1 and nothing moves until it is pressed."""
    if n is None:
        words = rich("text", "audit.new_n", n=None)
    else:
        key = "audit.new_n.one" if n == 1 else "audit.new_n.cap" if n >= 200 else "audit.new_n"
        words = text("text", copy(key, n=n), BODY_STRONG, TEXT_1)
    pill = hbox("CMP-001 Button (composition) · new entries", [glyph("info", INFO_STRONG), words],
                {"gap": INSET_XS, "padX": INSET_MD, "radius": R_BADGE, "fill": INFO_SUBTLE, "height": k.CONTROL_COMF},
                h=CONTROL_H, note="appears polite once; its count leaves out the viewer's own admin.area_entered "
                                  "rows, a client-side subtraction (D5 L169; G-32); on press loads the newest page, "
                                  "focus to row 1, polite audit.new_loaded (L272); at 0 ms, rows land in one frame "
                                  "(M16)")
    return hbox("pill row", [ring(pill) if focused else pill], None, w=w)


def append_only(w: int | None = None) -> Node:
    """The page text audit.append_only (B4, B8; AC-3): the guarantee and the retention, type.ui.body in
    color.text.tertiary, §15 L742's "page text and marker `text.tertiary`" (6.29 on the page, dark; G-42)."""
    return text("page text · audit.append_only", copy("audit.append_only"), BODY, TEXT_3, w=w,
                note="the append-only guarantee and 'Kept indefinitely.' as page text (D9 L173; B8 L803): "
                     "color.text.tertiary (§15 L742)")


TAMPER = {  # state -> (tone, key): the tamper line's word carries the state; the glyph repeats it (kit tones, DJ)
    "page_passed": ("success", "tamper.page_passed"), "page_partial": ("warning", "tamper.page_partial"),
    "newest_partial": ("warning", "tamper.newest_partial"),
    "incidents_unavailable": ("warning", "tamper.incidents_unavailable"),
    "range_passed": ("success", "tamper.range_passed"), "range_empty": ("info", "tamper.range_empty"),
    "busy": ("warning", "tamper.busy"), "limited": ("warning", "tamper.limited"),
    "stopped": ("warning", "tamper.stopped"),
    "stopped_entry": ("warning", "tamper.stopped_entry"), "failed": ("danger", "tamper.failed.title"),
    "page_partial_own": ("warning", "tamper.page_partial_own"),  # a Manager's page not fully checked (L236; G-12)
}  # the footer's line by state is §4's table (L228-236); "none" (AL-7, AL-26, AL-15) draws no line (tamper_footer)
RUN_STATES = ("enabled", "busy", "rate_limited", "owner_only", "view_as", "read_only")


def tamper_footer(state: str = "page_passed", *, run: str = "enabled", focused: bool = False, user: str = "alex",
                  w: int | None = None, **fills: Any) -> Node:
    """SCR-135's footer (L225-226, D10): the tamper line by state (TAMPER; §4's table L228-236; state="none" for
    AL-7, AL-26 and AL-15, no line) and [Run tamper check] — enabled, busy ("Checking entries…" beside it, M14), T2
    admin.rate_limited (AL-12), T2 rbac.owner_only (a Manager, AL-25), T2 rbac.view_as (the Owner viewing as a
    Manager), or read_only (enabled, inflight.read_only at the button: AL-12's 403)."""
    if (state not in TAMPER and state != "none") or run not in RUN_STATES:
        raise ValueError(f"tamper_footer: state in {sorted(TAMPER)} or 'none', run in {RUN_STATES}")
    _src("audit")
    line: Node | None = None
    if state != "none":  # none: an empty page (AL-7, AL-26) or no page read (AL-15) checks nothing (L232, L235)
        tone, key = TAMPER[state]
        line = rich("line", key, **fills) if _SLOT.search(raw(key)) else text("line", copy(key), BODY, TEXT_1)
    lab = label("run_tamper_check")
    ctl: list[Node]
    if run == "enabled":
        ctl = [button(lab, "secondary", focused=focused)]
    elif run == "busy":
        ctl = [busy(lab, "tamper.checking", variant="secondary")]
    elif run == "rate_limited":
        ctl = [t2(lab, "admin.rate_limited", focused=focused)]
    elif run == "owner_only":
        ctl = [t2(lab, "rbac.owner_only", verb=OWNER_ONLY_VERBS["verify"], focused=focused)]
    elif run == "view_as":
        ctl = [t2(lab, "rbac.view_as", user=user, focused=focused)]
    else:
        ctl = [button(lab, "secondary", focused=focused),
               hbox("refusal", [glyph("octagon", DANGER_STRONG),
                                text("text", copy("inflight.read_only"), BODY, TEXT_1)],
                    {"gap": INSET_XS}, note="403 session_read_only at the button, and D09's banner (AL-12, as FF-11)")]
    head = [status_line("tamper line", tone, line)] if line is not None else []
    return hbox("tamper footer", [*head, *ctl],
                {"gap": INSET_LG, "align": "center", "wrap": "wrap"}, w=w,
                note="the tamper line is a status, polite once on a result; Run tamper check is never in the incident "
                     "banner (D10 L174); writes admin.audit_verify")


# --- §8 the export: the control in the page header, the export line under it, CMP-023 progress.
EXPORT_CONTROL = ("not_built", "enabled", "running", "rate_limited", "owner_only", "view_as")


def export_control(state: str = "not_built", *, focused: bool = False, user: str = "alex") -> Node:
    """"Signed export…" as CMP-001 in CMP-093 (L221, L449-454; secondary: the kit's variant), the trigger's marker
    "Recorded · needs your confirmation — Audit log exported (admin.audit_export)" kept under it in every state
    (G-48; §12.1 L637: visible while T2, outside its aria-describedby, rejoining the description once enabled):
    not_built T2 admin.export_not_built on every Owner frame but boards 18, 19, 21-24 (Q15); enabled, described by
    the marker; running busy, never T2, while this client's job is queued or running (G-1: CMP-001 loading,
    aria-busy, focusable, no lock and no reason, its progress the export line's, Enter / Space nothing); rate_limited
    T2 admin.rate_limited after a 429 (AL-24); a Manager's T2 rbac.owner_only "export the audit log"; view-as T2."""
    if state not in EXPORT_CONTROL:
        raise ValueError(f"export_control: one of {EXPORT_CONTROL}")
    _src("export")
    lab = label("signed_export")
    if state == "enabled":
        ctl = button(lab, "secondary", focused=focused)
    elif state == "running":
        ctl = busy(lab, None, variant="secondary")
        ctl = ring(ctl, R_CONTROL) if focused else ctl
    elif state == "owner_only":
        ctl = t2(lab, "rbac.owner_only", verb=OWNER_ONLY_VERBS["export"], focused=focused)
    elif state == "view_as":
        ctl = t2(lab, "rbac.view_as", user=user, focused=focused)
    else:
        ctl = t2(lab, {"not_built": "admin.export_not_built", "rate_limited": "admin.rate_limited"}[state],
                 focused=focused)
    marker = text("marker", label("export_marker"), CAPTION, TEXT_3,
                  note=("its aria-describedby while enabled (D02:193)" if state == "enabled" else
                        "CMP-093's marker, visible while the control is T2 or busy, outside its aria-describedby; it "
                        "rejoins the description once enabled (§12.1 L637: D09:236 over D02:191; §8 L449-450)"))
    return vbox(f"{TRIGGER} (composition) · Signed export…", [ctl, marker], {"gap": STACK_XS, "align": "end"},
                note=f"{TRIGGER}: Signed export… ({state}; §8 L449-454)")


def progress(pct: int | None = None, w: int = 160, name: str = "CMP-023 Progress Bar (composition) · export") -> Node:
    """CMP-023 (8 px): the color.surface.hover track (color.track's stand-in, §15 L727-728) and the
    color.action.primary.default fill; pct=None draws the track alone (no worked-example %); aria-live off, the
    "{n} %" text carries it (§8 L477, M15)."""
    _fallback("TRACK")
    kids = [rect("track", w, 8, TRACK, {"radius": R_BADGE}, x=0, y=0)]
    if pct is not None:
        kids.append(rect("fill", max(round(w * pct / 100), 1), 8, ACTION_PRIMARY, {"radius": R_BADGE}, x=0, y=0))
    return box(name, kids, None, w=w, h=8, note="role='progressbar'; aria-live off; polite at 25 % steps (L477)")


EXPORT_LINES = ("accepted", "running", "poll_failed", "ready", "failed", "cancelled", "lost", "expired", "limited",
                "download_failed", "not_built")
EXPORT_TONE = {"accepted": "info", "running": "info", "poll_failed": "warning", "ready": "success", "failed": "danger",
               "cancelled": None, "lost": "warning", "expired": "warning", "limited": "warning",
               "download_failed": "danger", "not_built": "info"}  # the kit's tones (DJ); the words carry the state


def _ready(width: int, focus: str | None, fills: dict[str, Any], download: str = "enabled") -> Node:
    """AL-22's ready flow: export.ready with [Copy] and [Download] inline (every unknown fill a bar); download="t2"
    makes Download T2 admin.rate_limited (after the download's 429, AL-23)."""
    f = {s: fills.pop(s, None) for s in ("rows", "from", "to", "size", "hex8", "key_id", "yyyy-mm-dd hh:mm")}
    flow = rich("ready", "export.ready", w=width - 32, focus=None if download == "t2" else focus, **f)
    if download == "t2":
        names = [x["name"] for x in flow["kids"]]
        i = next(j for j, nm in enumerate(names) if nm.startswith("CMP-001 Button (composition) · Download"))
        flow["kids"][i] = t2(label("download"), "admin.rate_limited", focused=focus == "Download",
                             name="T2 · Download")
    return flow


def export_line(px: int, state: str, *, code: str | None = None, pct: int | None = None, focus: str | None = None,
                w: int | None = None, pct_served: bool = True, **fills: Any) -> Node:
    """§8's export line under the header while a job exists (X4-X12, AL-20-AL-23): running "Preparing the export…
    {n} % · job {id8}" beside CMP-023 (pct and id8 None draw bars), or with pct_served=False the line before the
    first progress_pct, export.running's second form with no bar and no "0 %" (X5 L468, G-17); poll_failed keeps the
    last % with export.poll_failed; ready export.ready ([Copy] and [Download] inline) over export.trust; failed
    export.fail.<code>; cancelled, lost, expired; limited and download_failed keep AL-22's ready flow (the job is
    still succeeded, AL-23 L287; G-47), the code's line under it above export.trust: limited with Download T2
    admin.rate_limited and export.limited, download_failed with Download enabled (export.download_failed's "Try
    again" target) and its line; not_built (a 501 that still arrives). Unknown fills: pass None (a bar)."""
    if state not in EXPORT_LINES:
        raise ValueError(f"export_line state: one of {EXPORT_LINES}")
    _src("export")
    width = w or SIZES[px].inner
    tone = EXPORT_TONE[state]
    kids: list[Node] = []
    if state in ("accepted", "running", "poll_failed"):
        n = pct if pct is not None else fills.pop("n", None)
        id8 = fills.pop("id8", None)
        if pct_served:
            kids += [progress(n), rich("running", "export.running", n=n, id8=id8)]
        else:
            kids.append(rich("running", "export.running.no_pct", id8=id8,
                             note="before the first progress_pct: no bar, no percentage, never '0 %' (X5 L468)"))
        if state == "poll_failed":
            kids.append(text("poll failed", copy("export.poll_failed"), BODY, TEXT_2))
        body: Node = hbox("line", kids, {"gap": INSET_SM, "wrap": "wrap"}, w=width - 32)
    elif state in ("ready", "limited", "download_failed"):
        lines = [_ready(width, focus, fills, "t2" if state == "limited" else "enabled")]
        if state == "limited":
            lines.append(status_line("download refusal · 429", "warning",
                                     rich("text", "export.limited", hhmm=fills.pop("hhmm", None)),
                                     note="the download's 429 (X10 L473): Download T2 until Retry-After (AL-23 L287)"))
        elif state == "download_failed":
            lines.append(status_line("download refusal · 503", "danger", copy("export.download_failed"),
                                     note="the download's 503 (X10 L473): nothing was sent; Download stays enabled, "
                                          "the target of 'Try again' (AL-23 L287)"))
        lines.append(text("trust", copy("export.trust"), CAPTION, TEXT_2, w=width - 32))
        body = vbox("line", lines, {"gap": STACK_XS})
        tone = EXPORT_TONE["ready"]
    elif state == "failed":
        if code not in ("export_too_large", "signing_key_rotated", "signing_unavailable", "audit_unavailable",
                        "internal_error"):
            raise ValueError("export_line failed: code= one of X7's five error codes (L470)")
        body = text("line", copy(f"export.fail.{code}"), BODY, TEXT_1)
    elif state == "expired":
        body = rich("line", "export.expired", **{"yyyy-mm-dd hh:mm": fills.pop("yyyy-mm-dd hh:mm", None)})
    else:
        body = text("line", copy({"cancelled": "export.cancelled", "lost": "export.lost",
                                  "not_built": "export.not_built"}[state]), BODY, TEXT_1)
    if fills:
        raise KeyError(f"export_line({state}): unused fills {sorted(fills)}")
    return status_line(f"export line · {state}", tone, body,
                       note="under the page header while a job exists (§8 X4); polite once per state, at 25 % steps "
                            "while running; each poll writes admin.area_entered (D13)")


# --- §7 the integrity incident (named for the security reviewer; boards 13, 14, 34).
def incident_banner(px: int, *, w: int | None = None, steps_open: bool = False, focus: str | None = None,
                    facts: str | None = None) -> Node:
    """§7's banner between the page header and the filters: CMP-028 danger (octagon), non-dismissible, role="alert"
    on the episode's first mount only, then static (D11): tamper.failed.title · .facts (§1's break: entry 1,204,118,
    14:05:07 UTC, 2026-10-22, entries 204,119–1,204,118; facts= another filled line, e.g. from an incident) · .meaning ·
    .safe · .recheck; [Copy details] (CMP-033), the "What to do now" disclosure (tamper.failed.steps when open), the
    links "Incident log" (SCR-144) and "Security centre" (SCR-137). Never Retry, a re-run, dismiss, a cause or a
    toast (L429-431). focus= "copy" | "steps" | "incidents" | "security"."""
    _src("incident")
    s = SAMPLE
    title_ = copy("tamper.failed.title", n=s["break_entry"])
    line = facts or copy("tamper.failed.facts", hhmmss=s["found_at"], yyyymmdd=s["date"],
                         **{"from": s["range_from"], "to": s["range_to"]})
    paras = [line, copy("tamper.failed.meaning"), copy("tamper.failed.safe"), copy("tamper.failed.recheck")]
    controls = [copy_button(focused=focus == "copy", name="CMP-033 CopyButton (composition) · Copy details",
                            words=copy("tamper.failed.copy")),
                disclosure(label("what_to_do"), expanded=steps_open, focused=focus == "steps"),
                link(label("incident_log"), focused=focus == "incidents",
                     note="→ SCR-144, where the incident persists"),
                link(label("security_centre"), focused=focus == "security", note="→ SCR-137")]
    after = [text("steps", copy("tamper.failed.steps"), BODY, TEXT_1,
                  w=(w or SIZES[px].inner) - 2 * PX[INSET_LG] - 24)] if steps_open else []
    return callout("danger", title=title_, paras=paras, controls=controls, after=after, w=w or SIZES[px].inner,
                   name="CMP-028 Callout (composition) · integrity incident",
                   note="role='alert' on the episode's first mount anywhere (keyed by first_bad_id or the incident "
                        "id), "
                        "static on later mounts (D11, §12 L621); non-dismissible; Copy details copies first_bad_id, "
                        "checked_at, from_id–to_id, last_hash, anchor_hash (L421-422); focus order Copy details → What "
                        "to do now → Incident log → Security centre (L295)")


# --- SCR-135's frame: the shell plus §4's parts, a drawer (D1) and row folding.
FILTER_NAME = "CMP-174 AuditFilterBar (composition)"
DRAWER_W = {1280: 480, 2560: 640}  # D1 L165: over the grid's right 480 px at 1280; docked at 640 px at 2560


def main_overflow(fr: Node) -> float:
    """How many px the frame's main column content runs past its height (estimated; ≤ 0 fits)."""
    main = find(fr, "main")
    used = sum(k.est_height(x) for x in main.get("kids") or []) + 2 * PX[INSET_LG]
    return used - float(main["h"])


def _drawer_top(fr: Node, px: int, banners: Iterable[Node]) -> float:
    """The y (in the frame) just under the filter bar plus one gap: where the 1280 drawer starts (D1)."""
    y = SIZES[px].top + sum(k.est_height(b) for b in banners) + PX[INSET_LG]
    for kid in find(fr, "main").get("kids") or []:
        if kid["name"] != "route content":
            y += k.est_height(kid)
            continue
        for p in kid.get("kids") or []:
            y += k.est_height(p) + PX[STACK_MD]
            if p["name"] == FILTER_NAME:
                break
        break
    return y


def audit_frame(px: int, parts: Iterable[Node], *, export: str | Node = "not_built", marker: bool = True,
                drawer: Node | None = None, items: Iterable[Node] = (), banners: Iterable[Node] = (),
                overlays: Iterable[Node] = (), right: Node | None = None, name: str | None = None,
                meta: str | Node | None = None) -> Node:
    """SCR-135 (L220-226): the shell "◆ Admin area · Audit log", h1 "Audit log", meta.asof, "Signed export…"
    (export= an export_control() state or a node), the marker line audit.marker (D8), then parts in §4's order
    (export line, incident banner, filter bar, pill row, grid region, pager, page text, tamper footer). drawer= a
    record_drawer(): at 1280 it overlays the grid's right 480 px under the filter bar, left of the RightRail; at 2560
    it docks 640 px wide beside every part after the filter bar (the grid keeps every column; D1)."""
    _src("audit")
    g = SIZES[px]
    ps = list(parts)
    bn = list(banners)
    primary = export if isinstance(export, dict) else export_control(export)
    if drawer is not None and px == 2560:
        idx = [i for i, p in enumerate(ps) if p["name"] == FILTER_NAME]
        cut = idx[0] + 1 if idx else 0
        left = vbox("grid column", ps[cut:], {"gap": STACK_MD}, w=g.inner - DRAWER_W[2560] - PX[INSET_LG])
        ps = ps[:cut] + [hbox("grid and record", [left, drawer], {"gap": INSET_LG, "align": "start"}, w=g.inner,
                              note="SCR-136 docked at 640 px (D1); non-modal, traps nothing")]
    fr = shell(px, "SCR-135", primary=primary, marker_line=copy("audit.marker") if marker else None, items=items,
               right=right, content=ps, banners=bn, overlays=overlays, name=name, meta=meta)
    if drawer is not None and px == 1280:
        y = round(_drawer_top(fr, px, bn))
        x = g.nav + PX[INSET_LG] + g.inner - DRAWER_W[1280]
        fr["kids"].append(dict(drawer, x=x, y=y, h=g.h - g.status - y, abs=True))
        live(f"drawer: frame-1280's SCR-136 sits at x {x}, y {y} (estimated under the filter bar); after relayout "
             f"align "
             f"its top with the filter bar's bottom + 12 px and keep its right edge at the RightRail's left (x 1040)")
    return fr


def audit_page(px: int, *, rows: Iterable[Node] | None = None, cols: Iterable[k.Col] | None = None,
               before: Iterable[Node] = (), filters: Node | None = None, pill: Node | None = None,
               end: Node | None = None, pager_state: str = "first", footer_state: str = "page_passed",
               run: str = "enabled", export: str | Node = "not_built", drawer: Node | None = None,
               banners: Iterable[Node] = (), items: Iterable[Node] = (), overlays: Iterable[Node] = (),
               fold_rows: bool = True, fill: bool = True, name: str | None = None, meta: str | Node | None = None,
               called_out: int | None = None, **footer_fills: Any) -> Node:
    """SCR-135 with the kit's defaults (AL-2): before= parts (export line, incident banner), the filter bar, [pill],
    the grid region (rows default page_rows(): AL-2's 200-row page, ROWS then bar rows, G-44; with custom rows and
    fill=True, bar rows down to the frame's foot), the pager (pager_state="none": no pager before the first answer,
    D4 L168), audit.append_only and the tamper footer (footer_state="none": no line); meta= as shell(). When the rows
    overflow, the grid keeps the rows that fit, a fold marker and the last row (row 200), so the page end stays in
    frame (a viewport showing both; the rows between are elided, G-46); when keeping row 200 would leave fewer than
    called_out rows above the fold (default 4 on AL-2's page, its called-out rows 01-04, L266; else 1), the fold ends
    the grid instead (board 02's 1280 frame)."""
    docked = drawer is not None and px == 2560
    gw = SIZES[px].inner - (DRAWER_W[2560] + PX[INSET_LG] if docked else 0)
    cl = list(cols or audit_cols(px, gw))
    all_rows = list(rows if rows is not None else page_rows(px, cl))
    total = sum(c.width for c in cl)

    def build(rs: list[Node]) -> Node:
        """The frame with rows rs."""
        parts = [*before, filters or filter_bar(px), *([pill] if pill else []), audit_grid(rs, cl, end=end),
                 *([pager(pager_state)] if pager_state != "none" else []), append_only(w=gw),
                 tamper_footer(footer_state, run=run, w=gw, **footer_fills)]
        return audit_frame(px, parts, export=export, drawer=drawer, banners=banners, items=items,
                           overlays=overlays, name=name, meta=meta)

    fr = build(all_rows)
    over = main_overflow(fr)
    if fill and rows is not None and over < -ROW_H:
        more = int((-over - PX[STACK_MD]) // ROW_H)
        all_rows += [bar_row(cl, f"row-{i:02d}", px) for i in range(len(all_rows) + 1, len(all_rows) + more + 1)]
        fr = build(all_rows)
        over = main_overflow(fr)
    if over > 0 and fold_rows and len(all_rows) > 2:
        need = called_out if called_out is not None else (CALLED_OUT if rows is None else 1)

        def most(last_: list[Node]) -> int:
            """The most rows above the fold that fit with last_ after it (the estimate, then down to 1)."""
            n = min(max(len(all_rows) - math.ceil(over / ROW_H) + 2, 1), len(all_rows) - len(last_) - 1)
            while n > 1 and main_overflow(build(all_rows[:n] + [fold(total, "-")] + last_)) > 0:
                n -= 1
            return n

        last = all_rows[-1:]
        keep = most(last)
        if keep < need:
            alone = most([])
            if alone >= need:
                keep, last = alone, []  # the fold ends the grid: the called-out rows stay in frame
        if keep < len(all_rows) - len(last):
            what = (f"rows {keep + 1:02d}–{len(all_rows) - len(last):02d} of the page are elided" +
                    ("" if last else ", the fold ending the grid"))
            k.LOG.notes["live_checks"] = [ln for ln in k.LOG.notes["live_checks"]
                                          if not ln.startswith(f"fit: frame-{px} main")]
            fr = build(all_rows[:keep] + [fold(total, what)] + last)
            NOTES.add("deviations", f"frame-{px}: {what} (a fold marker in the grid), so the page end (pager, page "
                                    f"text, tamper footer) stays in the 1:1 frame")
    return fr


# --- §6 the diff language (L358-405): one renderer, a typed value slot, an inline and a full form. The secret rule
# is structural: a kind carries no secret; nothing is hashed client-side; CMP-034 MaskedValue is never used.
VALUE_KINDS = ("value", "fingerprint", "identifier", "secret", "secret_named", "credential", "personal", "oversize",
               "none", "withheld", "hidden", "not_sent", "overrides_kept")  # §6 L380-395 (+ L383's request members)
KIND_KEY = {"secret": "diff.secret", "secret_named": "diff.secret_named", "credential": "diff.credential",
            "oversize": "diff.oversize", "none": "diff.none", "withheld": "diff.withheld", "hidden": "diff.hidden",
            "not_sent": "diff.not_sent", "overrides_kept": "diff.overrides_kept"}
LOCKED = ("secret", "secret_named", "credential")


class Val(NamedTuple):
    """A typed value: kind (VALUE_KINDS); text the shown value (value, fingerprint, identifier; personal: its 8 hex)
    or None (a bar); num: numbers and ids in type.num.sm; long: over 120 characters, folded behind diff.full."""

    kind: str
    text: str | None = None
    num: bool = False
    long: bool = False


class Field(NamedTuple):
    """One changed field: its path ("overrides › 9f1c…"), status (changed | added | removed in the state shape;
    requested in the request shape; fact: a request or record fact; result: a recorded result's field) and values."""

    path: str
    status: str
    before: Val | None = None
    after: Val | None = None


def diff_value(v: Val, *, name: str = "value", copied: bool = False) -> Node:
    """One typed value (§6 L385-395): value (type.num.sm when num), fingerprint (+ Copy), identifier (+ Copy and
    diff.key_id_note), secret / secret_named / credential (the decorative lock + their words), personal ("Personal
    data, hashed · {hex8}…"), oversize, none (text.tertiary), withheld, hidden, not_sent, overrides_kept."""
    if v.kind not in VALUE_KINDS:
        raise ValueError(f"value kind {v.kind!r}: one of {VALUE_KINDS}")
    _src("diff")
    if v.kind in LOCKED:
        return hbox(name, [glyph("lock", TEXT_2, "lock"), text("text", copy(KIND_KEY[v.kind]), BODY, TEXT_1)],
                    {"gap": INSET_XS}, note=f"kind {v.kind}: the lock is decorative (aria-hidden; §12.1 L636), the "
                                            "words carry the kind; no value reaches the client (§6 L397-404)")
    if v.kind == "none":
        return text(name, copy("diff.none"), BODY, TEXT_3, note="a stored null (§6 L393)")
    if v.kind in KIND_KEY:
        return text(name, copy(KIND_KEY[v.kind]), BODY, TEXT_1, note=f"kind {v.kind}")
    if v.kind == "personal":
        return rich(name, "diff.personal", hex8=v.text, note="kind personal: <hashed:pii>:<sha256 hex> (§6 L391)")
    if v.long:
        return hbox(name, [bar(f"{v.kind} (its first 120 characters)", 240), disclosure(copy("diff.full"))],
                    {"gap": INSET_SM}, note="a value over 120 characters shows its first 120, then diff.full (§6 "
                                            "L376-377; G-11)")
    shown = text("text", v.text, NUM_SM if v.num else BODY, TEXT_1) if v.text is not None else bar(v.kind)
    if v.kind == "value":
        return dict(shown, name=name)
    kids = [shown, copy_button(copied=copied)]
    if v.kind == "identifier":
        kids.append(text("note", copy("diff.key_id_note"), CAPTION, TEXT_2))
    return hbox(name, kids, {"gap": INSET_SM}, note=f"kind {v.kind} (§6 L386-387): a contract-safe identifier")


TERM_W = 88  # the Before / After / Requested term column (kit choice)


def _term_row(term: str, v: Val, name: str) -> Node:
    """One nested <dt>/<dd> pair: the visible term (type.ui.label, text.secondary) and the typed value."""
    return hbox(name, [text("term", term, LABEL, TEXT_2, w=TERM_W), diff_value(v)], {"gap": INSET_SM, "align": "start"})


def diff_full(fields: Iterable[Field], *, shape: str = "state", head_reason: str | None = None, intent: bool = False,
              no_before: bool = False, unchanged: int = 0, unchanged_open: bool = False, w: int = 560,
              name: str | None = None, started: bool = False) -> Node:
    """§6's full form (L367-369): a <dl> with one term per changed field (its path) whose description is a nested
    <dl> with the visible terms Before and After. shape="state": the status word (Changed / Added / Removed) in its
    own column, never a colour or strike-through; no_before=True heads it with diff.no_before. shape="request" (a
    refused, conflicting or intent write, L383): the head diff.head_failed (head_reason=) or diff.head_intent
    (intent=True), the second term Requested, never After; no row says Changed; facts (reason, evidence_url, result,
    phase) as fact rows. shape="result" (L384): diff.result, the result's fields as values; started=True a
    write-ahead admin.audit_verify record (reason started), headed diff.head_started instead (G-11). unchanged= folds
    that many fields into diff.unchanged_n ("1 unchanged field" for one, L708)."""
    if shape not in ("state", "request", "result"):
        raise ValueError("diff_full shape: state | request | result")
    _src("diff")
    kids: list[Node] = []
    if shape == "request":
        head = copy("diff.head_intent") if intent else copy("diff.head_failed", reason=head_reason)
        kids.append(text("head", head, BODY_STRONG, TEXT_1, w=w))
    elif shape == "result":
        kids.append(text("head", copy("diff.head_started" if started else "diff.result"), BODY_STRONG, TEXT_1, w=w))
    if no_before:
        kids.append(text("no before", copy("diff.no_before"), BODY, TEXT_2, w=w))
    words = {"changed": "diff.changed", "added": "diff.added", "removed": "diff.removed"}
    for i, f in enumerate(fields, 1):
        EMITTED.add(f.path)  # the record's own field path (data)
        rows: list[Node] = [text("path", f.path, NUM_SM, TEXT_1, note="the field's path (nested objects keep it)")]
        if f.status in ("fact", "result"):
            rows = [hbox("fact", [text("term", f.path, LABEL, TEXT_2, w=TERM_W), diff_value(f.after or Val("none"))],
                         {"gap": INSET_SM, "align": "start"})]
        else:
            second = copy("diff.requested") if shape == "request" else copy("diff.after")
            if f.before is not None:
                rows.append(_term_row(copy("diff.before"), f.before, "before"))
            if f.after is not None:
                rows.append(_term_row(second, f.after, "after" if shape == "state" else "requested"))
        status = [text("status", copy(words[f.status]), LABEL, TEXT_1, w=72)] if (
            shape == "state" and f.status in words) else []
        if shape != "state" and f.status in words:
            raise ValueError("a request or result record never says Changed / Added / Removed (§6 L383)")
        kids.append(hbox(f"field-{i:02d}", status + [vbox("dl", rows, {"gap": STACK_XS})],
                         {"gap": INSET_SM, "align": "start"}, w=w))
    if unchanged:
        kids.append(disclosure(copy("diff.unchanged_n.one") if unchanged == 1 else
                               copy("diff.unchanged_n", n=unchanged), expanded=unchanged_open))
    return vbox(name or f"CMP-173 diff part (composition) · full · {shape}", kids, {"gap": STACK_SM}, w=w,
                note="<dl>: one <dt> per changed field (its path), each <dd> a nested <dl> with visible Before / After "
                     "(Requested) terms (L367-369; #887 A11y notes)")


def diff_inline(path: str, a: str, b: str, *, requested: bool = False, name: str | None = None) -> Node:
    """§6's inline form (L364-367): "value: OFF → ON" (G-11: a flags.change records overrides as an object), the
    arrow aria-hidden and the line read "changed from OFF to ON" (diff.inline); requested=True the request shape's
    "value: requested ON (stored OFF)" (diff.inline_requested), read as written."""
    _src("diff")
    if requested:
        line = f"{path}: {copy('diff.inline_requested', a=a, b=b)}"
        EMITTED.add(line)  # the field's path + diff.inline_requested (§6 L383's own example: "value: requested ON …")
        return text(name or "inline · requested", line, BODY, TEXT_1,
                    note="read as diff.inline_requested, never diff.inline (§6 L383)")
    reads = copy("diff.inline", a=a, b=b)
    EMITTED.update({f"{path}: {a}", b})  # the field's path and its values (data)
    return hbox(name or "inline · changed", [text("from", f"{path}: {a}", BODY, TEXT_1),
                                             text("arrow", "→", BODY, TEXT_2, note="aria-hidden"),
                                             text("to", b, BODY, TEXT_1)],
                {"gap": INSET_XS}, note=f"reads '{path}: {reads}' (the arrow is aria-hidden, §6 L364-366)")


# --- SCR-136 Audit event detail (§5 L318-356): a non-modal CMP-046 drawer rendering the page's AuditEntry.
RECORD: dict[str, Any] = {  # SCR-136's worked record (L324-325); every other field is not given (a bar)
    "id": "1,204,118", "code": "orders.submit", "outcome": "success", "severity": "info",
    "ts": "2026-10-22 14:01:50.212", "env": "LIVE", "actor": None, "session_id": None, "ip": None, "subject": None,
    "reason": None, "request_id": None, "entry_hash": None, "prev_hash": None,
}
KV_W = 104  # the drawer's term column (kit choice)


def _kv(term: str, value: Node | str | None, *, field: str, copyable: bool = False, hidden: bool = False,
        t2_copy: str | None = None, name: str | None = None) -> Node:
    """One drawer row: the term (type.ui.label, text.secondary) and its value (type.num.sm for ids; None a bar);
    copyable adds CMP-033; hidden = a Manager's "not shown in your view"; t2_copy= the notice a T2 Copy points at."""
    if hidden:
        v: Node = text("value", copy("rec.hidden"), BODY, TEXT_2)
    elif value is None:
        v = bar(field, 96)
    elif isinstance(value, str):
        v = text("value", value, NUM_SM, TEXT_1)
    else:
        v = value
    kids = [text("term", term, LABEL, TEXT_2, w=KV_W), v]
    if t2_copy:
        kids.append(t2_pointer(label("copy"), t2_copy, name=f"T2 · Copy {field}"))
    elif copyable and not hidden:
        kids.append(copy_button(name=f"CMP-033 CopyButton (composition) · {field}"))
    return hbox(name or f"row · {field}", kids, {"gap": INSET_SM, "align": "center"})


def _section(heading: str, rows: Iterable[Node], name: str) -> Node:
    """One drawer section: its heading (type.ui.label, text.secondary) and rows."""
    return vbox(name, [text("heading", heading, LABEL, TEXT_2), *rows], {"gap": STACK_XS})


def summary_line(rec: dict[str, Any]) -> str:
    """The drawer's summary "<label> (<code>) · <Outcome> · <Severity> · <ts> UTC · <ENV>" (L325); RECORD's is §5's
    literal."""
    if rec == RECORD:
        return label("summary")
    lab = ACTIONS.get(rec["code"], (None, ""))[0]
    out = label(OUTCOME_KEY[rec["outcome"]]) if rec["outcome"] in ("success", "failure", "denied") else copy(
        OUTCOME_KEY[rec["outcome"]])
    parts = [f"{lab} ({rec['code']})" if lab else rec["code"], out, label(f"sev.{rec['severity']}"),
             f"{rec['ts']} UTC", rec["env"] or label("env.none")]
    return " · ".join(parts)


def record_drawer(px: int, *, rec: dict[str, Any] | None = None, diff: Node | None = None, h: int | None = None,
                  focus: str | None = None, prev: str = "enabled", nxt: str = "enabled", raw: str = "collapsed",
                  copied: bool = False, integrity: str = "not_checked", verified: dict[str, str] | None = None,
                  projected: bool = False, reason_given: bool = False, actor_pivot: bool = True,
                  subject_link: bool = True) -> Node:
    """SCR-136 (L324-335): header h2 "Record 1,204,118", [Previous] [Next] (T2 admin.page_edge at the loaded page's
    ends: prev / nxt = "t2"), Close; the summary; Who (actor, rec.role, session and IP with Copy, rec.agent_none);
    What (the subject's link or text; reason as rec.reason_code or rec.reason_given); Before / after (diff= a
    diff_full(); a Manager's {} → diff.hidden); Request (request_id + Copy, rec.correlation_none); Related (the three
    pivots; actor_pivot=False when actor_user_id is null; a Manager gets subject and time only); Integrity (hashes
    with Copy, rec.chain, the verified line: integrity = "verified" (verified= its fills) | "not_checked" |
    "after_break" in the danger treatment); Raw record (raw = "collapsed" | "open" | "withheld" (rec.raw_flagged,
    D09's sentence form) | "owner_only" (T2 to the one notice)); footer rec.immutable. projected=True is AD-7."""
    _src("drawer")
    r = dict(RECORD, **(rec or {}))
    w = DRAWER_W[px]
    iw = w - 2 * PX[INSET_LG]
    notice = "the one notice under the drawer header (AD-7, §12.1 L637)"
    nav = []
    for which, state, key in (("Previous", prev, "previous"), ("Next", nxt, "next")):
        nav.append(t2(label(key), "admin.page_edge", focused=focus == which) if state == "t2" else
                   button(label(key), "secondary", focused=focus == which))
    head = hbox("header", [text("h2", label("record.h2") if r["id"] == RECORD["id"] else f"Record {r['id']}",
                                HEADING_MD, TEXT_1, note="h2; focus lands here in frame 0 (M1, D14)"),
                           hbox("controls", nav + [k.icon_button("close", "close")], {"gap": INSET_SM})],
                {"justify": "space-between", "align": "start"}, w=iw)
    kids: list[Node] = [head]
    if projected:
        kids.append(t2_notice("rbac.owner_only", verb=OWNER_ONLY_VERBS["raw"], name="notice · rbac.owner_only"))
    kids.append(text("summary", summary_line(r), BODY, TEXT_1, w=iw))
    actor = text("value", r["actor"], BODY, TEXT_1) if r["actor"] else None
    who = [_kv(label("col.actor"), actor, field="actor_username"),
           text("role", copy("rec.role"), BODY, TEXT_2, note="CG-1: never the current role (D17)"),
           _kv(label("f.session"), r["session_id"], field="session_id", copyable=True, hidden=projected,
               t2_copy=notice if projected else None),
           _kv(label("f.ip"), r["ip"], field="ip", copyable=True, hidden=projected,
               t2_copy=notice if projected else None),
           text("agent", copy("rec.agent_none") if not projected else copy("rec.hidden"), BODY, TEXT_2)]
    kids.append(_section(label("sec.who"), who, "section · Who"))
    subj = (bar("subject_type · subject_label", 160) if r["subject"] is None else
            link(r["subject"]) if subject_link else text("value", r["subject"], BODY, TEXT_1))
    why_term = copy("rec.reason_given") if reason_given else copy("rec.reason_code")
    what = [_kv(label("filter.subject"), subj, field="subject"),
            _kv(why_term, r["reason"], field="reason", hidden=projected)]
    kids.append(_section(label("sec.what"), what, "section · What"))
    ba = text("hidden", copy("diff.hidden"), BODY, TEXT_1) if projected else (diff or bar("detail", 160))
    kids.append(_section(label("sec.diff"), [ba], "section · Before and after"))
    req = [_kv(label("f.request_id"), r["request_id"], field="request_id", copyable=True),
           text("correlation", copy("rec.correlation_none"), BODY, TEXT_2, note="CG-4")]
    kids.append(_section(label("sec.request"), req, "section · Request"))
    pivots = ([("actor", "rec.related_actor")] if actor_pivot and not projected else []) + [
        ("subject", "rec.related_subject"), ("time", "rec.related_time")]
    rel = [link(copy(key), focused=focus == pid, name=f"CMP-021 Link (composition) · related {pid}",
                note=("a deep link to 'My activity' with that filter (AD-7)" if projected else
                      "a deep link to SCR-135 with that filter set; one admin.audit_read")) for pid, key in pivots]
    kids.append(_section(label("sec.related"), [hbox("pivots", rel, {"gap": INSET_MD, "wrap": "wrap"}, w=iw)],
                         "section · Related"))
    if integrity == "verified":
        v = verified or {}
        vline: Node = rich("verified", "rec.verified_to", w=iw, **{"from": v.get("from"), "to": v.get("to"),
                                                                   "hhmm": v.get("hh:mm")})
    elif integrity == "after_break":
        vline = hbox("verified", [glyph("octagon", DANGER_STRONG), text("text", copy(
            "rec.after_break", n=SAMPLE["break_entry"]), BODY_STRONG, TEXT_1)], {"gap": INSET_XS, "padX": INSET_SM,
                                                                                  "padY": INSET_XS, "radius": R_CONTROL,
                                                                                  "fill": DANGER_SUBTLE},
                     note="AD-5: the danger treatment (danger.subtle, the octagon, the words)")
    else:
        vline = text("verified", copy("rec.not_checked"), BODY, TEXT_2)
    integ = [_kv(label("f.entry_hash"), r["entry_hash"], field="entry_hash", copyable=True, hidden=projected,
                 t2_copy=notice if projected else None),
             _kv(label("f.prev_hash"), r["prev_hash"], field="prev_hash", copyable=True, hidden=projected,
                 t2_copy=notice if projected else None),
             text("chain", copy("rec.chain"), BODY, TEXT_2), vline]
    kids.append(_section(label("sec.integrity"), integ, "section · Integrity"))
    kids.append(_section(label("sec.raw"), [raw_record(raw, w=iw, focused=focus == "raw", copied=copied)],
                         "section · Raw record"))
    kids.append(text("footer", copy("rec.immutable"), BODY, TEXT_2))
    return vbox("CMP-046 Drawer (composition) · SCR-136", kids,
                {"fill": OVERLAY, "shadow": E_POPOVER, "pad": INSET_LG, "gap": STACK_MD, "clip": True}, w=w, h=h,
                note="non-modal (D1, D14): traps nothing; Esc or Close returns focus to the row; no fetch (L321-323)")


def raw_record(state: str = "collapsed", *, w: int = 448, focused: bool = False, copied: bool = False) -> Node:
    """The raw record (AD-2, AD-3, AD-7): collapsed = the "Show raw record" disclosure; open = it expanded over the
    CMP-068 <pre> (color.surface.sunken, a focusable scroll region named "Raw record"; its lines are bars: no entry
    data is given) with its Copy; withheld = rec.raw_flagged alone (no button, no Copy); owner_only = Show raw
    record T2 pointing at the drawer's one notice."""
    if state == "withheld":
        return t2_sentence(copy("rec.raw_flagged"), w=w, name="raw record · withheld",
                           note="AD-3: the region stays collapsed, rec.raw_flagged in its place, no Show raw record, "
                                "no "
                                "Copy (D09's sentence form)")
    if state == "owner_only":
        return t2_pointer(copy("rec.raw_show"), "the one notice under the drawer header (AD-7)",
                          name="T2 · Show raw record")
    show = disclosure(copy("rec.raw_show"), expanded=state == "open", focused=focused and state != "open")
    if state != "open":
        return show
    _fallback("CODE")
    pre = vbox("CMP-068 pre (composition)", [bar(f"raw line {i}", w - 40 - 24 * (i % 3)) for i in range(1, 6)],
               {"fill": CODE_SURFACE, "pad": INSET_SM, "gap": STACK_XS, "radius": R_CONTROL}, w=w,
               note="tabindex='0', named 'Raw record': the server-redacted entry (D02:1064); no entry data is given, "
                    "so "
                    "its lines are bars")
    return vbox("raw record · open", [show, ring(pre) if focused else pre, copy_button(copied=copied)],
                {"gap": STACK_SM}, note="expands in one frame (M4); 'Copied' for 2 s, polite once (AD-2)")


# --- SCR-145 Feature flags (§9 L485-555): CMP-179 rows in one CMP-049 table per h2 group (not an arrow grid).
class FlagState(NamedTuple):
    """A row's served state: deployment "ON" | "OFF" | None (a bar); yours ("override" | "resolved", value) when the
    Owner's resolved value differs (D19); overrides (user overrides); changed (yyyy-mm-dd hh:mm, user), None parts are
    bars; revert the previous value after a change in this session; reload D24's labelled target; unreadable
    (FF-12); default=True marks deployment as the catalogue default (no stored value is given)."""

    deployment: str | None
    yours: tuple[str, str] | None = None
    overrides: int = 0
    changed: tuple[str | None, str | None] = (None, None)
    revert: str | None = None
    reload: bool = False
    unreadable: bool = False
    default: bool = False


def ff2_state(f: Flag, *, reload: bool = False) -> FlagState:
    """FF-2's row state (L529; G-22, G-46): trading.live_enabled "Deployment: ON", as live trading is on in §1's
    LIVE world (D03 OV-2; the registry's OFF default is a deployment never enabled); rules.graph_editor "Deployment:
    OFF", "You: ON — your override", "+ 1 user override"; every other row its registry default. reload=True puts
    [Reload now] on engine.webgl_v2 as a labelled target (D24 L188: FF-2 [39] alone draws it, on board 05; its twin
    [53] and the component sheet [68] too)."""
    if f.key == "trading.live_enabled":
        return FlagState("ON")
    if f.key == "rules.graph_editor":
        return FlagState("OFF", ("override", "ON"), 1)
    return FlagState("ON" if f.default else "OFF", reload=reload and f.key == "engine.webgl_v2", default=True)


FLAG_COLS = (("flag", 290), ("value", 200), ("scope", 120), ("changed", 154), ("actions", 180))  # 944 (kit widths)


def flag_cols(px: int = 1280, inner: int | None = None) -> tuple[tuple[str, int], ...]:
    """The flag table's columns scaled to inner (no source sets them: the kit's widths, DEVIATIONS)."""
    inner = inner or SIZES[px].inner
    ws = [int(w * inner / 944) for _i, w in FLAG_COLS]
    ws[-1] += inner - sum(ws)
    _deviate("flag-cols", "SCR-145's table columns are the kit's (flag 290, values 200, scope 120, changed 154, "
                          "actions 180 at 1280; scaled at 2560): no source sets them; no header row is drawn, every "
                          "cell carries its own words (§9 L496-504; the group's h2 captions the table).")
    return tuple((cid, w) for (cid, _w), w in zip(FLAG_COLS, ws, strict=True))


def group_heading(group: str) -> str:
    """A group's h2 (§9 L507-512): flags.group.safety (D02:717) or Gated / Rollouts / Other."""
    return copy("flags.group.safety") if group == "safety" else label(f"group.{group}")


def flag_scope(f: Flag, overrides: int = 0, *, fail_closed: bool = False) -> Node:
    """The derived scope, §14's flags.scope (L499-500, L709; FF-2 L529; G-22): "Deployment" first, then "+ 1 user
    override" / "+ {n} user overrides", the count in type.num.base (G-45); safety and gated flags "Deployment" with
    "overrides ignored"; under fail_closed the static words only, as fail_closed omits overrides (FF-12 L539)."""
    lines = [text("deployment", copy("flags.scope"), BODY, TEXT_2)]
    if f.group in ("safety", "gated"):
        lines.append(text("ignored", copy("flags.scope.ignored"), BODY, TEXT_2))
    elif not fail_closed and overrides == 1:
        lines.append(count_text("overrides", copy("flags.scope.plus_one"), color=TEXT_2))
    elif not fail_closed and overrides > 1:
        lines.append(count_text("overrides", copy("flags.scope.plus_n", n=overrides), color=TEXT_2))
    return vbox("scope", lines, None, note="per account flags.scope_account 'not available' (CG-19, L500); per role "
                                           "not exposed")


def flag_values(f: Flag, st: FlagState, *, fail_closed: bool = False) -> Node:
    """flags.deployment from default_value and, when the Owner's value differs, flags.your_override /
    flags.your_resolved (D19); under fail_closed each value labelled "fail-closed value" (D23); an unreadable row's
    flags.unreadable note (warning)."""
    if st.deployment is None:
        dep: Node = rich("deployment", "flags.deployment", value=None)
    else:
        dep = text("deployment", copy("flags.deployment", value=label(st.deployment)), BODY_STRONG, TEXT_1,
                   note="the registry default: FF-2 L529 'every other row its registry default'" if st.default
                   else None)
    lines: list[Node] = [dep]
    if fail_closed:
        lines.append(text("fail-closed", copy("flags.fail_closed_value"), CAPTION, TEXT_2,
                          note="D23: each value labelled flags.fail_closed_value (L498, FF-12)"))
    if st.yours:
        lines.append(text("yours", copy(f"flags.your_{st.yours[0]}", value=label(st.yours[1])), BODY, TEXT_2,
                          note="only when the Owner's resolved value differs (D19)"))
    if st.unreadable:
        lines.append(status_line("unreadable", "warning", copy("flags.unreadable"), typo=CAPTION, w=180))
    return vbox("values", lines, {"gap": STACK_XS}, note="words change only on the server's answer, in one frame (M9)")


def flag_actions(f: Flag, st: FlagState, *, pointer: str | None = None, focus: str | None = None,
                 live_reshown: bool = False, w: int | None = None) -> Node:
    """[Change…] [History] (+ [Revert to …]), History on every row (L502-504; G-46): maintenance.mode's "→ Maintenance"
    (SCR-148) replaces Change… alone; trading.live_enabled's Change… is T2 admin.live_gate with the visible link
    "Security centre" (D20; live_reshown = FF-4's re-shown reason), Tab order Change… → Security centre → History
    (FF-4 L531); pointer= every Change… and Revert T2 pointing at one notice (FF-12; an unreadable row keeps its
    Change as the repair); reload adds [Reload now] as a labelled target (D24)."""
    ch = label("change")
    kids: list[Node]
    if f.key == "maintenance.mode":
        kids = [link(label("to_maintenance"), focused=focus == "change", note="→ SCR-148: no Change here (L509)"),
                button(label("history"), "ghost", focused=focus == "history")]
    elif f.key == "trading.live_enabled":
        ctl = t2(ch, "admin.live_gate", focused=focus == "change", name="T2 · Change… (live gate)", w=w)
        if live_reshown:
            ctl["note"] = "FF-4: Enter or Space re-showed the reason, polite once per press; nothing was sent"
        kids = [ctl, link(label("security_centre"), focused=focus == "security", note="→ SCR-137, the live gate"),
                button(label("history"), "ghost", focused=focus == "history")]
    else:
        gated = pointer if pointer and not st.unreadable else None  # an unreadable row keeps Change as the repair
        kids = [t2_pointer(ch, gated, focused=focus == "change") if gated else
                button(ch, "secondary", focused=focus == "change"),
                button(label("history"), "ghost", focused=focus == "history")]
        if st.revert:
            rv = label("revert", previous=label(st.revert))  # L502 "[Revert to {previous}]" (FF-7 L534)
            kids.append(t2_pointer(rv, gated) if gated else button(rv, "secondary", focused=focus == "revert"))
    if st.reload:
        kids.append(button(label("reload_now"), "secondary", name="CMP-001 Button (composition) · Reload now (target)"))
    return hbox("actions", kids, {"gap": INSET_XS, "wrap": "wrap", "align": "start"}, w=w)


def flag_row(f: Flag, st: FlagState, cols: Iterable[tuple[str, int]], *, fail_closed: bool = False,
             pointer: str | None = None, focus: str | None = None, live_reshown: bool = False,
             name: str | None = None) -> Node:
    """One CMP-179 FeatureFlagRow (composition): the served description and the key (type.num.sm), its marks
    (flags.affects, flags.affects_desktop, D24's "Requires reload" target); the values; the scope; flags.changed_by
    (bars where not given); the actions. Raised, padded, a subtle divider."""
    cl = list(cols)
    marks: list[Node] = []
    if f.affects:
        marks.append(k.tag(copy("flags.affects"), "warning"))
    if f.affects_desktop:
        marks.append(k.tag(copy("flags.affects_desktop"), "warning"))
    if st.reload:
        marks.append(k.tag(label("requires_reload"), "info", name="CMP-011 Tag (composition) · requires reload"))
    w0 = cl[0][1] - 2 * PX[INSET_SM]
    flag_cell = [text("description", f.desc, BODY, TEXT_1, w=w0),
                 hbox("key and marks", [text("key", f.key, NUM_SM, TEXT_2), *marks],
                      {"gap": INSET_XS, "wrap": "wrap", "align": "center"}, w=w0)]
    when, who = st.changed
    cells: dict[str, list[Node]] = {
        "flag": [vbox("flag", flag_cell, {"gap": STACK_XS})], "value": [flag_values(f, st, fail_closed=fail_closed)],
        "scope": [flag_scope(f, st.overrides, fail_closed=fail_closed)],
        # fail_closed omits updated_at and updated_by: no "Changed … by …" line (FF-12 L539)
        "changed": [] if fail_closed else [rich("changed", "flags.changed_by", w=cl[3][1] - 2 * PX[INSET_SM],
                                                typo=CAPTION, color=TEXT_2, **{"yyyy-mm-dd hh:mm": when, "user": who})],
        "actions": [flag_actions(f, st, pointer=pointer, focus=focus, live_reshown=live_reshown,
                                 w=cl[4][1] - 2 * PX[INSET_SM])]}
    kids = [hbox(cid, cells[cid], {"padX": INSET_SM, "padY": INSET_SM, "align": "start"}, w=w) for cid, w in cl]
    total = sum(w for _c, w in cl)
    row = hbox(name or f"CMP-179 FeatureFlagRow (composition) · {f.key}", kids, {"fill": RAISED, "align": "start"},
               w=total, note=f"Change… named by description, key and deployment value; served description verbatim "
                             f"(svc/admin/flags/catalogue.py); {'owner-only flag; ' if f.owner_only else ''}"
                             "the row never flips on its own (D19)")
    return vbox(f"row · {f.key}", [row, rect("divider", total, 1, BORDER_SUBTLE)], None)


def flag_group(group: str, rows: Iterable[Node], *, w: int, folded: bool = False) -> Node:
    """One h2 group (type.ui.heading-sm, text.primary) captioning its CMP-049 table of rows; folded=True (FF-3: no
    match in the group) draws the heading alone."""
    _src("flags")
    h2 = text("h2", group_heading(group), HEADING_SM, TEXT_1, w=w, note="h2; the table's caption (§9 L494-495)")
    kids = [h2] if folded else [h2, vbox("CMP-049 table (composition)", list(rows), None, w=w,
                                         note="a table captioned by its h2, not an arrow grid (FF-2 L529)")]
    return vbox(f"group · {group}", kids, {"gap": STACK_SM}, w=w)


def flag_search(value: str | None = None, *, w: int = 320, focused: bool = False) -> Node:
    """CMP-054 SearchBox (composition; L494: over description and key, its placeholder and accessible name
    flags.search "Search flags", G-15 / G-29): the search glyph and the value, or the placeholder in
    color.text.tertiary when empty (6.83 on sunken, §15 L743), in a color.surface.sunken well with DS-3's boundary;
    its clear button ("Clear search", `15:543`) is the next Tab stop once text is in (FF-3)."""
    k._fallback("DS-3")
    _deviate("compose")
    words = (text("value", value, BODY, TEXT_1) if value else
             text("placeholder", copy("flags.search"), BODY, TEXT_3, note="the placeholder; also the accessible name"))
    well = hbox("input", [icon("search", "search", TEXT_2), words],
                {"gap": INSET_XS, "padX": INSET_SM, "radius": R_CONTROL, "fill": SUNKEN, "height": k.CONTROL_COMF,
                 "stroke": k.FIELD_EDGE, "strokeWidth": HAIRLINE, "strokeAlign": "inner"}, w=w, h=CONTROL_H,
                note="role='searchbox', named by flags.search (L494)")
    return vbox("CMP-054 SearchBox (composition)", [ring(well, R_CONTROL) if focused else well], None)


def flag_groups(px: int, states: dict[str, FlagState] | None = None, *, w: int | None = None,
                show: Iterable[str] | None = None, fail_closed: bool = False, pointer: str | None = None,
                focus: tuple[str, str] | None = None, live_reshown: bool = False,
                hidden: Iterable[str] = ()) -> list[Node]:
    """The four groups of the 17 flags in §9's order (states default ff2_state); show= the keys a search matched
    (FF-3: empty groups fold to their heading); hidden= rows elided (each run one fold marker, G-46); fail_closed /
    pointer as flag_row(); focus= (key, control)."""
    width = w or SIZES[px].inner
    cols = flag_cols(px, width)
    st = states or {}
    keep = set(show) if show is not None else None
    gone = set(hidden)
    out = []
    for g in GROUPS:
        rows: list[Node] = []
        run = 0
        members = [f for f in FLAGS if f.group == g and (keep is None or f.key in keep)]
        for i, f in enumerate(members):
            if f.key in gone:
                run += 1
            else:
                rows.append(flag_row(f, st.get(f.key, ff2_state(f)), cols, fail_closed=fail_closed, pointer=pointer,
                                     focus=focus[1] if focus and focus[0] == f.key else None,
                                     live_reshown=live_reshown))
            if run and (i == len(members) - 1 or members[i + 1].key not in gone):
                rows.append(fold(width, f"{run} {g} flag row{'s' if run > 1 else ''} elided"))
                run = 0
        out.append(flag_group(g, rows, w=width, folded=not members))
    return out


def _notable(st: FlagState) -> bool:
    """A row whose state the board must show (the Owner's value, overrides, reload, unreadable, a revert)."""
    return bool(st.yours or st.overrides or st.reload or st.unreadable or st.revert)


def flags_frame(px: int, content: Iterable[Node], *, banners: Iterable[Node] = (), overlays: Iterable[Node] = (),
                items: Iterable[Node] = (), marker: bool = True, name: str | None = None,
                meta: str | Node | None = None) -> Node:
    """SCR-145 (L492-496): the shell "◆ Admin area · Feature flags", h1 "Feature flags", meta D03's meta.asof "All
    times UTC · as of 14:02:09" (G-14: never "Resolved from the store", which fail_closed makes false; meta="" the
    meta_line() before the first answer, FF-1, FF-17; or a node), no primary action (definitions are code: no Add
    flag, L491), then content (search, notices, groups) and the footer marker "Changes here are recorded in the audit
    log · Flag changed (flags.change)"."""
    _src("flags")
    body = list(content) + ([text("CMP-093 marker · flags", label("flags.marker"), CAPTION, TEXT_3,
                                  note="D02:534; the marker joins a control's description only while enabled")]
                            if marker else [])
    m = meta_line(SAMPLE["flags_asof"]) if meta is None else meta_line("") if meta == "" else meta
    if meta is None:
        label("flags.meta")  # records meta.asof (LABEL_KEYS) and its §9 line
    return shell(px, "SCR-145", meta=m, content=body, banners=banners, overlays=overlays, items=items, name=name)


def flags_page(px: int, *, states: dict[str, FlagState] | None = None, search: str | None = None,
               show: Iterable[str] | None = None, notice: Node | None = None, fail_closed: bool = False,
               pointer: str | None = None, banners: Iterable[Node] = (), overlays: Iterable[Node] = (),
               focus: tuple[str, str] | None = None, live_reshown: bool = False, keep: Iterable[str] = (),
               fold_rows: bool = True, name: str | None = None) -> Node:
    """SCR-145 with the kit's defaults (FF-2): the search, [notice], the four groups, the marker. When the rows
    overflow the frame, plain rows are folded from the bottom up (each run one fold marker in its table), never the
    live row, maintenance.mode, a row with a notable state (_notable), the focused row or keep= keys."""
    st = states or {}
    vis = [f.key for f in FLAGS if show is None or f.key in set(show)]
    must = set(keep) | {"trading.live_enabled", "maintenance.mode"} | ({focus[0]} if focus else set())
    must |= {key for key in vis if _notable(st.get(key, ff2_state(FLAG[key])))}
    hidden: list[str] = []

    def build() -> Node:
        """The frame with the current hidden rows."""
        groups = flag_groups(px, st, show=show, fail_closed=fail_closed, pointer=pointer, focus=focus,
                             live_reshown=live_reshown, hidden=hidden)
        content = [flag_search(search)] + ([notice] if notice else []) + groups
        return flags_frame(px, content, banners=banners, overlays=overlays, name=name)

    fr = build()
    over = main_overflow(fr)
    if fold_rows and over > 0:
        cols = flag_cols(px)
        for key in reversed(vis):
            if over <= 0:
                break
            if key not in must:
                hidden.append(key)
                over -= k.est_height(flag_row(FLAG[key], st.get(key, ff2_state(FLAG[key])), cols)) - 1
        k.LOG.notes["live_checks"] = [ln for ln in k.LOG.notes["live_checks"] if not ln.startswith(f"fit: frame-{px}")]
        fr = build()
        NOTES.add("deviations", f"frame-{px}: {len(hidden)} plain flag rows are elided (fold markers in their "
                                f"tables: {', '.join(reversed(hidden))}); every row the state names stays in frame")
    return fr


def history_row(outcome: str, lines: Iterable[Node], *, actor: str = "basiltt", ts: str | None = None,
                severity: str = "warning", name: str = "history row", w: int = 560) -> Node:
    """One D25 history row (CMP-173 compact composition): time (UTC; None a bar), actor, "Flag changed
    (flags.change)", the outcome word (or flags.history_no_outcome for an intent with no outcome), the severity word
    (flags.change is written at warning), then its inline diff lines (diff_inline())."""
    out = (copy("flags.history_no_outcome") if outcome == "no_outcome" else
           copy(OUTCOME_KEY[outcome]) if outcome in ("started", "intent") else label(OUTCOME_KEY[outcome]))
    head = hbox("head", [text("ts", ts, NUM_SM, TEXT_2) if ts else bar("ts", 72), text("actor", actor, BODY, TEXT_1),
                         text("action", f"{ACTIONS['flags.change'][0]} (flags.change)", BODY, TEXT_1),
                         text("outcome", out, BODY, TEXT_1), *severity_cell(severity)], {"gap": INSET_SM})
    return vbox(name, [head, *lines], {"gap": STACK_XS}, w=w,
                note="intent and outcome merged by request_id (D25); links to SCR-136")


def flag_history(rows: Iterable[Node], *, w: int = 560) -> Node:
    """D25's on-demand History disclosure (FF-14): three compact rows and "Full history → Audit log"."""
    return vbox("History (disclosure)", [*rows, link(copy("flags.history_full"))], {"gap": STACK_SM}, w=w,
                note="aria-expanded; History writes admin.audit_read (§9 Events L555); a cut (M4)")


# --- §11 Dialogs and rungs (L596-615; D02 §4.1 and E42-D03 §12 by reference): "<Verb> <object>" · consequences ·
# counts · Why? · the step-up line · the marker · [ Cancel ] (focus) [ <Verb> ]; CMP-043 Large at both sizes.
DIALOG_W = k.DIALOG_W["large"]
IW = DIALOG_W - 2 * PX[DIALOG_PAD]  # 592: a Large dialog's inner width


def step_up_line(cls: str, *, grace: int | None = None) -> Node:
    """D21 (L185): the line predicts the server's class: flags and audit "You'll confirm with your password and a
    code." (E42-D03 dlg.step_up.code); inside a live grace window D03's "Still trusted for {class} · {m:ss}"
    (dlg.step_up.grace), its {class} "flag changes" (flags) or "audit exports" (audit), PROPOSED to D03 §14
    band.grace by §20's A-row (1) (L882-884; G-33); killswitch "This always needs a fresh code." in its own slot
    (L582, §11 L602: no grace)."""
    _src("rungs")
    if cls in ("flags", "audit"):
        if grace is None:
            return text("step-up line", copy("dlg.step_up.code"), CAPTION, TEXT_2)
        return k.clock_text("step-up line", copy("dlg.step_up.grace", cls=label(f"grace.{cls}"), mss=k.mss(grace)),
                            CAPTION, TEXT_2, num=NUM_SM, note="the grace line D03's dialogs share with SH-5 (D21)")
    if cls == "killswitch":
        return text("step-up line", label("fresh_code"), CAPTION, TEXT_2)
    raise ValueError("step-up class: flags | audit | killswitch")


def grace_line(cls: str = "flags", seconds: int = 134) -> Node:
    """The band's (b) grace line for D04's step-ups (D21 L185; E42-D03 SH-5): "Still trusted for flag changes · 2:14"
    (cls "flags") or "… audit exports …" ("audit"), D03's band.grace with the class words §20's A-row (1) proposes
    (L882-884; G-33): pass it as shell(right=…). color.text.secondary, the clock type.num.base; polite at 60 s and
    10 s (D03 SH-5)."""
    if cls not in ("flags", "audit"):
        raise ValueError("D04 grace class: flags | audit (e42kit.grace_line() draws D03's own classes)")
    _src("decisions")
    line = k.copy("band.grace", cls=label(f"grace.{cls}"), mss=k.mss(seconds))
    return k.clock_text("grace line", line, BODY, TEXT_2, note="SH-5: polite at 60 s and 10 s; D21's class words "
                                                                "PROPOSED to E42-D03 (§20 A-row (1))")


# §8 L459 / D21: the audit class word is no longer a gap: D21 L185 gives "audit exports" (G-33, PROPOSED).


def bullets(name: str, entries: Iterable[str], *, w: int = IW) -> Node:
    """A real list (maint.list, dlg.engage.*.list): a 4 px dot (text.secondary) before each item; no text glyph."""
    rows = [hbox(f"item-{i:02d}", [box("dot", [ellipse("dot", 4, 4, {"fill": TEXT_2}, x=0, y=7)], None, w=4, h=18),
                                   text("text", s, BODY, TEXT_1, w=w - 16)], {"gap": INSET_SM, "align": "start"})
            for i, s in enumerate(entries, 1)]
    return vbox(name, rows, {"gap": STACK_XS}, w=w, note="<ul>: a real list (L563-565)")


def validity_button(chars: str, hint_key: str, /, *, variant: str = "destructive", focused: bool = False,
                    name: str | None = None, note: str | None = None) -> Node:
    """A confirm waiting on the user's own input, in D03 §12's form-validity form, never T2 (FF-10 L537; G-4): the
    native role and full label, aria-disabled="true", focusable, no lock and no CMP-079, the fill
    color.surface.raised with a color.border.default hairline and the label color.text.tertiary, described by the
    visible hint (hint_key, e.g. dlg.conflict_first) under it."""
    k._fallback("CONTROL")
    _deviate("compose")
    w = round(k.text_w(chars, BODY_STRONG) + 2 * PX[k.BUTTON_PADX] + 2)
    o: dict[str, Any] = {"padX": k.BUTTON_PADX, "radius": R_CONTROL, "height": k.CONTROL_COMF, "justify": "center"}
    if k.BUTTON_LOOK[variant][0]:
        o.update(fill=RAISED, stroke=BORDER_DEFAULT, strokeWidth=HAIRLINE, strokeAlign="inner")
    ctl = hbox(f"CMP-001 Button (composition) · {_safe(chars)} (form validity)", [text("label", chars, BODY_STRONG,
                                                                                     TEXT_3)], o, w=w, h=CONTROL_H,
               note=note or (f"form validity, never T2 (D03 §12): aria-disabled='true', focusable, no lock, no "
                             f"CMP-079; aria-describedby the hint {hint_key}; variant {variant} once valid"))
    return vbox(name or f"validity · {_safe(chars)}", [ring(ctl, R_CONTROL) if focused else ctl,
                                                       text("hint", copy(hint_key), CAPTION, TEXT_2)],
                {"gap": STACK_XS, "align": "end"})


def rung(n: int, title_: str, kids: Iterable[Node] = (), *, confirm: str, state: str = "enabled",
         why: Node | None = None, step: str | None = "flags", grace: int | None = None,
         marker: tuple[str, str | None] | str | None = None, cancel_focused: bool = True,
         name: str | None = None, after: Iterable[Node] = ()) -> Node:
    """A rung dialog in §11's order (L598-602): title, kids (consequences, counts, refusal lines), why= (why_field()),
    the step-up line in its own slot (step= flags | audit | killswitch | None), the marker (a (label, code) pair or a
    literal), then [Cancel] (focused, always safe) [confirm], CMP-044's merged CMP-001 `danger` (R-2: text.on-action
    on danger.default, danger_confirm(); never auto-focused). state = "enabled" | "waiting" (the count read in flight:
    natively disabled and skipped by Tab, never T2 and never busy, D22 L186, R-2; waiting_confirm()) | "busy:<in-flight
    key>" (MM-3: Cancel and Why? aria-disabled, labels keep their
    colours) | "validity:<hint key>" (FF-10's form-validity confirm, G-4) | "t2:<reason key>" (admin.rate_limited)."""
    _src("rungs")
    body = list(kids)
    if why is not None:
        body.append(why)
    if step:
        body.append(step_up_line(step, grace=grace))
    if isinstance(marker, tuple):
        body.append(audit_marker(*marker))
    elif marker:
        body.append(text("CMP-093 marker", marker, CAPTION, TEXT_3))
    body += list(after)  # after= lines above the footer (D29: save.not_saved / export.not_sent after SCR-006)
    cancel = button(label("cancel"), "secondary", focused=cancel_focused)
    if state == "enabled":
        conf = danger_confirm(confirm)
    elif state == "waiting":
        conf = waiting_confirm(confirm)
    elif state.startswith("busy:"):
        conf = busy(confirm, state[5:])
        cancel["note"] = "aria-disabled while in flight, never disabled; described by the in-flight label (MM-3)"
    elif state.startswith("validity:"):
        conf = validity_button(confirm, state[9:])
    elif state.startswith("t2:"):
        conf = t2(confirm, state[3:], variant="destructive")
    else:
        raise ValueError("rung state: enabled | waiting | busy:<key> | validity:<hint key> | t2:<key>")
    return k.dialog(title_, body, [cancel, conf], "large", name=name or f"CMP-044 rung-{n} dialog (composition)")


def _desc(f: Flag) -> str:
    """A flag's description without its full stop (dlg.flag.title's rule, L710)."""
    return f.desc[:-1] if f.desc.endswith(".") else f.desc


FLAG_DIALOG_STATES = ("idle", "saving", "conflict", "invalid", "store_down", "audit_down", "checking", "read_only",
                      "not_saved")


def _flag_body_node(a: str, b: str, overrides: int | None, yours: str | None) -> Node:
    """dlg.flag.body as drawn: its count in type.num.base (G-45), or a bar when the override count is not given
    (overrides=None; G-48: flag_dialog() took counts as ints only)."""
    if overrides is not None:
        return count_text("consequence", flag_body(a, b, overrides, yours), w=IW)
    tpl = COPY["dlg.flag.body"] if yours is not None else COPY["dlg.flag.body"].replace(COPY["dlg.flag.body.yours"],
                                                                                        "")
    head, tail = tpl.split("{n}")
    NOTES.add("copy_keys", "dlg.flag.body")
    _src("copy")
    pieces = [k.fill(head, a=a, b=b).strip(), k.fill(tail, value=yours or "").strip()]
    EMITTED.update(pieces)  # dlg.flag.body's own text around its {n}
    kids = [text("text-01", pieces[0], BODY, TEXT_1), bar("n (user overrides)", 24),
            text("text-02", pieces[1], BODY, TEXT_1)]
    return hbox("consequence", kids, {"gap": INSET_XS, "wrap": "wrap", "rowGap": STACK_XS}, w=IW,
                note=f'copy dlg.flag.body: "{tpl}"; the override count not given (a bar)')


def flag_dialog(f: Flag, *, to: str = "ON", overrides: int | None = 0, yours: str | None = None,
                why: str | None = None, why_error: str | None = None, state: str = "idle", focus: str = "cancel",
                conflict: dict[str, str | None] | None = None) -> Node:
    """§11 rung 1 (FF-5, L532): dlg.flag.title "Turn on '<description>' (<key>)", flag_body() (FF-5: "Deployment value
    from OFF to ON. 1 user override stays; yours: ON.", the count in type.num.base, G-45; overrides=None a bar,
    G-48), dlg.flag.desktop when desktop.backend_connection turns off, Why? (past idle the typed reason is kept: a
    bar unless why= gives it), the flags step-up line, the marker Flag changed (flags.change), [Cancel] [Turn on].
    state: saving (FF-7: busy "Saving…"), conflict (FF-10 L537: flags.conflict with [Use the current value] before
    Why?, the confirm in D03 §12's form-validity form described by dlg.conflict_first, never T2, G-4; conflict= its
    fills value, user, hh:mm:ss), invalid (FF-11: why_error= a flags.err_* key), audit_down (FF-13: nothing was
    written), store_down (FF-13 L540: an unknown outcome, flags.store_down, then the no-answer path's re-read in
    flight; G-34), checking (FF-13: no answer), read_only (FF-11: inflight.read_only), not_saved (FF-6, D29: SCR-006
    closed unconfirmed, D03's save.not_saved a polite line above the footer)."""
    if state not in FLAG_DIALOG_STATES:
        raise ValueError(f"flag_dialog state: one of {FLAG_DIALOG_STATES}")
    _src("flags")
    frm = "OFF" if to == "ON" else "ON"
    t = copy("dlg.flag.title", **{"on / off": "on" if to == "ON" else "off", "description": _desc(f), "key": f.key})
    kids: list[Node] = [_flag_body_node(label(frm), label(to), overrides, label(yours) if yours else None)]
    if f.affects_desktop and to == "OFF":
        kids.append(text("desktop", copy("dlg.flag.desktop"), BODY, TEXT_1, w=IW))
    cstate = "enabled"
    if state == "saving":
        cstate = "busy:flags.saving"
    elif state == "checking":
        cstate = "busy:flags.checking"
    elif state == "conflict":
        c = conflict or {}
        kids.append(callout("warning", paras=[rich("conflict", "flags.conflict", w=IW - 64, value=c.get("value"),
                                                   user=c.get("user"), hhmmss=c.get("hh:mm:ss"))], w=IW,
                            name="CMP-028 Callout (composition) · conflict",
                            note="assertive once (§12 L622); [Use the current value] precedes Why? in the Tab order"))
        cstate = "validity:dlg.conflict_first"
    elif state == "audit_down":
        kids.append(callout("danger", paras=[copy("flags.audit_down")], w=IW,
                            note="assertive once; nothing was written (FF-13 L540); the reason is kept"))
    elif state == "store_down":
        kids.append(callout("danger", paras=[copy("flags.store_down")], w=IW,
                            note="an unknown outcome (FF-13 L540; CG-35): never 'Nothing was changed.'; the "
                                 "no-answer path's re-read follows"))
        cstate = "busy:flags.checking"
    elif state == "read_only":
        kids.append(callout("danger", paras=[copy("inflight.read_only")], w=IW,
                            note="403 session_read_only: a refusal at the point of action, not T2 (D09 §3.3)"))
    wf = why_field(why, error=why_error if state == "invalid" else None, focused=focus == "why",
                   readonly=cstate.startswith("busy:"), kept=state != "idle" and why is None)
    after = ([text("not saved", k.copy("save.not_saved"), BODY, TEXT_2, w=IW,
                   note="FF-6, D29: SCR-006 closed unconfirmed; polite once; the reason kept; focus on the confirm")]
             if state == "not_saved" else [])
    return rung(1, t, kids, confirm=label("turn_on") if to == "ON" else label("turn_off"), state=cstate, why=wf,
                step="flags", marker=(ACTIONS["flags.change"][0] or "", "flags.change"),
                cancel_focused=focus == "cancel", after=after)


def count_line(count: int | str | None, *, key: str = "dlg.positions") -> Node:
    """D22's count line (FF-8, MM-2): dlg.positions "Open positions: {n}" with its count in type.num.base (G-45),
    "unavailable" for a failed read (dlg.positions.unavailable), or while the read is in flight its head and one
    CMP-015 line (count=None; the confirm natively disabled, D22, R-2)."""
    if count is None:
        head = raw(key).split("{n}")[0].strip()
        NOTES.add("copy_keys", key)
        return hbox("count", [text("label", head, BODY, TEXT_1), skeleton("text", 1, w=48)], {"gap": INSET_XS},
                    note="the count read in flight (D22 L186): the confirm natively disabled, never busy or T2 (R-2)")
    if count == "unavailable":
        return text("count", copy(f"{key}.unavailable"), BODY, TEXT_1, note="a failed read (D22 L186)")
    return count_text("count", copy(key, n=count), note="settled: announced once, politely (D22 L186)")


def engage_dialog(which: str = "order_entry", *, count: int | str | None = 2, why: str | None = None,
                  focus: str = "cancel") -> Node:
    """§11 rung 2 (FF-8, L535): dlg.engage.<which>.title, its list, the count line (count_line(): "Open positions:
    2", "unavailable", or while it loads (count=None) a CMP-015 line with the confirm natively disabled, never busy or
    T2: D22, R-2); Why?,
    the flags step-up line, the marker, [Cancel] [Turn on]. which="ingestion" is board 74's target (CG-31: nothing
    reads that switch): no count and no wait (FF-8)."""
    if which not in ("order_entry", "ingestion"):
        raise ValueError("engage_dialog which: order_entry | ingestion")
    _src("flags")
    kids: list[Node] = [bullets("consequences", items(f"dlg.engage.{which}.list"))]
    waits = which == "order_entry" and count is None
    if which == "order_entry":
        kids.append(count_line(count))
    return rung(2, copy(f"dlg.engage.{which}.title"), kids, confirm=label("turn_on"),
                state="waiting" if waits else "enabled", why=why_field(why, focused=focus == "why"), step="flags",
                marker=(ACTIONS["flags.change"][0] or "", "flags.change"), cancel_focused=focus == "cancel",
                name=f"CMP-044 rung-2 dialog (composition) · engage {which}")


def release_dialog(which: str = "order_entry", *, why: str | None = None, focus: str = "cancel") -> Node:
    """§11 rung 4 (FF-9, L536): "Turn off '<description>' (<key>)", dlg.release.<which>, Why?, the step-up line "This
    always needs a fresh code." in its own slot (§11 L602: no list or body string repeats it), the marker, [Cancel]
    [Turn off] → SCR-006, no grace. which="ingestion" is board 46's annotated target (CG-31)."""
    f = FLAG[f"killswitch.{which}"]
    t = copy("dlg.flag.title", **{"on / off": "off", "description": _desc(f), "key": f.key})
    return rung(4, t, [text("consequence", copy(f"dlg.release.{which}"), BODY, TEXT_1, w=IW)],
                confirm=label("turn_off"), why=why_field(why, focused=focus == "why"), step="killswitch",
                marker=(ACTIONS["flags.change"][0] or "", "flags.change"), cancel_focused=focus == "cancel",
                name=f"CMP-044 rung-4 dialog (composition) · release {which}")


EXPORT_DIALOG_STATES = ("idle", "starting", "invalid", "refused", "unknown", "read_only", "rate_limited", "not_sent")


def export_dialog(*, frm: str | None = None, to: str | None = None, state: str = "idle", refusal: str | None = None,
                  error_on: str = "to", focus: str = "cancel") -> Node:
    """§8's rung-1 dialog (L455-460, AL-18, AL-24): export.dlg.title; From / To in UTC (prefilled: the filter's dates
    or the last 24 hours; None draws bars), "Compress (gzip)" on; export.dlg.body (from, to) and export.dlg.pii; the
    audit step-up line; the marker Audit log exported (admin.audit_export); [Cancel] [Export]. state: starting (MM-3's
    controls, the in-flight label export.dlg.starting), invalid (export.dlg.range under error_on's field; Export
    stays enabled), refused (refusal= an export.refused.* key, the window kept), rate_limited (refused.rate with
    Export T2 admin.rate_limited), unknown (export.unknown [Check again]), read_only (inflight.read_only), not_sent
    (AL-19, D29: SCR-006 closed unconfirmed, export.not_sent a polite line above the footer, focus on Export)."""
    if state not in EXPORT_DIALOG_STATES:
        raise ValueError(f"export_dialog state: one of {EXPORT_DIALOG_STATES}")
    _src("export")
    ro = state == "starting"
    fields = []
    for fid, val in (("from", frm), ("to", to)):
        ff = filter_field(fid, label(f"filter.{fid}"), val, w=200, picker=False, focused=focus == fid and not ro,
                          error="export.dlg.range" if state == "invalid" and fid == error_on else None)
        if ro:
            find(ff, "input")["note"] = ("readonly + aria-disabled while the POST is in flight, described by the "
                                         "in-flight label; busy, not T2: it keeps its look (MM-3, AL-18)")
        fields.append(ff)
    kids: list[Node] = [hbox("window", fields, {"gap": INSET_LG, "align": "start"}),
                        k.tick(label("compress"), checked=True, w=IW, focused=focus == "compress"),
                        rich("body", "export.dlg.body", w=IW, **{"from": frm, "to": to}),
                        text("pii", copy("export.dlg.pii"), BODY, TEXT_1, w=IW)]
    cstate = "enabled"
    if state == "starting":
        cstate = "busy:export.dlg.starting"
    elif state in ("refused", "rate_limited"):
        key = "export.refused.rate" if state == "rate_limited" else refusal
        if not key or not key.startswith("export.refused."):
            raise ValueError("export_dialog refused: refusal= an export.refused.* key (L706)")
        slots = {sl: None for sl in _SLOT.findall(raw(key))}  # refused.range {days}, refused.rate {hh:mm}: bars
        kids.append(callout("danger", paras=[rich("refusal", key, w=IW - 64, **slots) if slots else copy(key)], w=IW,
                            note="assertive once; the window is kept, focus on Export (AL-24 L288)"))
        cstate = "t2:admin.rate_limited" if state == "rate_limited" else "enabled"
    elif state == "unknown":
        kids.append(callout("warning", paras=[rich("unknown", "export.unknown", w=IW - 64)], w=IW,
                            note="X11: never re-sent on its own; [Check again] re-sends under the same key"))
    elif state == "read_only":
        kids.append(callout("danger", paras=[copy("inflight.read_only")], w=IW,
                            note="403 session_read_only (as FF-11)"))
    after = ([text("not sent", copy("export.not_sent"), BODY, TEXT_2, w=IW,
                   note="AL-19, D29: polite once; the window kept; focus back on Export")]
             if state == "not_sent" else [])
    return rung(1, copy("export.dlg.title"), kids, confirm=label("export"), state=cstate, step="audit",
                marker=(ACTIONS["admin.audit_export"][0] or "", "admin.audit_export"),
                cancel_focused=focus == "cancel", name="CMP-044 rung-1 dialog (composition) · export", after=after)


def scr006(*, summary: str | None = None, focus: str = "password", name: str = "SCR-006 (composition)") -> Node:
    """SCR-006 "Confirm it's you" (L134; E09-D06's chassis: alertdialog, the flat 60 % scrim, no blur, focus trap),
    code variant only (FF-6, AL-19): summary= the server's action_summary verbatim (L517's example), else the generic
    body (a path-gated challenge has none, CG-11; D01:634); Password (D02:262) and the authenticator code (E42-D03
    gate.code_label / gate.code_hint); [Cancel] [Confirm] (E39-D03:178). Focus starts on the password field."""
    _src("rungs")
    body = text("body", summary or label("scr006.body"), BODY, TEXT_1, w=k.DIALOG_W["default"] - 2 * PX[DIALOG_PAD],
                note="the description; the server's action_summary verbatim, never composed (L517-518)")
    pw = k.field(label("scr006.password"), None, w=k.DIALOG_W["default"] - 2 * PX[DIALOG_PAD] - 8,
                 focused=focus == "password", name="field · password")
    code = k.field(copy("gate.code_label"), None, hint=copy("gate.code_hint"), w=200, mono=True,
                   focused=focus == "code", name="field · code")
    acts = [button(label("cancel"), "secondary", focused=focus == "cancel"),
            button(label("scr006.confirm"), "primary", name="CMP-001 Button (composition) · Confirm")]
    return k.dialog(label("scr006.title"), [body, pw, code], acts, "default", name=name)


SPEC_GAPS.append("§14 L713 inherits 'E09-D06's SCR-006 copy as D03 takes it (§1)', and neither E09-D06.md nor D03 "
                 "spells out its title, generic body, password label or Confirm (their frames hold them): scr006() "
                 "draws §1 L134's title, D01:634's generic body, D02:262's 'Password', D03's gate.code_label / "
                 "gate.code_hint and E39-D03:178's 'Confirm'.")


# --- SCR-148 Maintenance mode (§10 L557-594).
MAINT_STATES = ("off", "on", "on_system", "fail_closed", "unreadable", "loading", "load_failed")


def maint_status(state: str = "off", *, control: str = "enabled", focused: bool = False,
                 since: str | None = None, user: str | None = "basiltt", w: int = 640) -> Node:
    """The status line (L563): maint.off [Turn on…] / maint.on ("… since 2026-10-22 14:02 UTC — turned on by basiltt",
    MM-4) [Turn off…] / maint.on_system / maint.fail_closed / maint.unreadable (MM-8: the state named in the list's
    place); loading the CMP-015 status line and no control (MM-10); load_failed maint.load_failed [Retry] and no
    control (MM-11). control: enabled | t2 (Turn off… T2 admin.flags_store, MM-8) | repair (MM-8's rung-4 repair:
    Turn off… enabled) | none. The words fit the w px column beside the glyph and the control (G-48: boards 54, 57,
    60-62 and 73 fitted the old 560 px words locally). Tones are the kit's (DJ)."""
    if state not in MAINT_STATES:
        raise ValueError(f"maint_status: one of {MAINT_STATES}")
    _src("maint")
    when = since or SAMPLE["maint_since"]
    if state == "loading":
        return hbox("status line", [skeleton("text", 1, w=min(320, w))], None,
                    note="the CMP-015 status line, aria-busy (MM-10 L586); no Turn on… or Turn off…, so no marker")
    if state == "load_failed":
        return status_line("status line", "danger", rich("words", "maint.load_failed", w=w - 24, detail=None),
                           note="MM-11 (L587): CMP-027's error look, role='status'; no Turn on… or Turn off… on an "
                                "unknown state; {detail} is the served problem's (a bar); polite once")
    words = {"off": copy("maint.off"), "on": copy("maint.on", yyyymmddhhmm=when, user=user),
             "on_system": copy("maint.on_system", yyyymmddhhmm=when), "fail_closed": copy("maint.fail_closed"),
             "unreadable": copy("maint.unreadable")}[state]
    tone = None if state == "off" else "warning"
    lab = label("turn_on_menu") if state == "off" else label("turn_off_menu")
    ctl: list[Node] = []
    if control == "enabled" or control == "repair":
        ctl = [button(lab, "secondary", focused=focused)]
    elif control == "t2":
        ctl = [t2(lab, "admin.flags_store", focused=focused)]
    used = sum(round(k.est_width(c)) + PX[INSET_SM] for c in ctl) + (PX[k.ICON] + PX[INSET_SM] if tone else 0)
    return status_line("status line", tone, text("words", words, BODY_STRONG, TEXT_1, w=w - used), controls=ctl,
                       note="words change only on the server's answer, in one frame (M9); never animated (S-2)")


def window_section(w: int = 560, *, focus: str | None = None) -> Node:
    """MM-1's window section (L565-567, L577; #2764, CG-20): CMP-065 under the legend maint.window_later, holding
    maint.window_field (CMP-040 over CMP-047, UTC: a picker, so aria-readonly) and maint.message_field (CMP-040 over
    CMP-007), both T2 and readonly under one notice admin.window_not_built (§12.1 L637), whose lock is decorative
    (G-41); the fields are named "CMP-040 FormField (composition) · window (T2)" / "· message (T2)" (G-24, G-29;
    the boards' local names)."""
    _src("maint")
    legend = copy("maint.window_later")
    ptr = "the one notice admin.window_not_built under the legend (MM-1)"
    fields = [t2_field(copy("maint.window_field"), None, pointer=ptr, w=240, picker=True,
                       name="CMP-040 FormField (composition) · window (T2)"),
              t2_field(copy("maint.message_field"), None, pointer=ptr, w=w - 2 * PX[INSET_LG],
                       name="CMP-040 FormField (composition) · message (T2)")]
    return vbox("CMP-065 FormSection (composition) · window", [
        text("legend", legend, HEADING_SM, TEXT_1, note="<fieldset><legend>"),
        t2_notice("admin.window_not_built", name="notice · admin.window_not_built"), *fields],
        {"fill": RAISED, "radius": R_CARD, "pad": INSET_LG, "gap": STACK_SM}, w=w,
        note="#2764: no schedule, message or scope exists (CG-20); the fields are readonly")


def maint_marker(direction: str = "on") -> Node:
    """The marker under the page's control (§10 L567-572; G-8), naming what it would record: "on" under [Turn on…]
    "Recorded in the audit log · Maintenance on (maintenance.enabled) + Flag changed (flags.change)"; "off" under
    [Turn off…] (MM-4, MM-8, MM-12, an on MM-7) "… Maintenance off (maintenance.disabled) + Flag changed
    (flags.change)"; "repair" under MM-8's repair of an unreadable row, "… Flag changed (flags.change)" alone."""
    if direction == "on":
        return text("CMP-093 marker · maintenance", label("maint.marker"), CAPTION, TEXT_3)
    if direction == "repair":
        return dict(audit_marker(ACTIONS["flags.change"][0] or "", "flags.change"),
                    name="CMP-093 marker · maintenance", note="an unknown row turned off is no stored transition "
                                                              "(svc/admin/flags/policy.py:33-38; L570-572)")
    if direction != "off":
        raise ValueError("maint_marker: on | off | repair")
    head = k.marker(ACTIONS["maintenance.disabled"][0] or "", "maintenance.disabled")["chars"]
    chars = f"{head} + {label('maint.marker_off').split(' + ', 1)[1]}"
    EMITTED.add(chars)
    NOTES.add("copy_gaps", "'Recorded in the audit log · <label> (<code>)': §1 L128's marker convention (D02 D5)")
    return text("CMP-093 marker · maintenance", chars, CAPTION, TEXT_3,
                note="§10 L569-570's marker under Turn off…, the convention's head (L128): a fail-closed page never "
                     "reads as a recorded ON")


def maint_content(state: str = "off", *, control: str = "enabled", focus: str | None = None,
                  w: int = 640) -> list[Node]:
    """SCR-148's route content (L563-573, MM-1..MM-12): the status line; the lead-in maint.list_lead and the
    consequence list maint.list, a real list, in every state but MM-8 (fail_closed, unreadable), whose status line
    names the state in the list's place (G-2); "Still available" maint.stays; the window section; the marker under
    the page's control (maint_marker(): on under Turn on…, off under Turn off…, repair under MM-8's unreadable
    repair). loading (MM-10) and load_failed (MM-11) keep the lead-in, the lists and the window section and have no
    control and no marker (G-35)."""
    _src("maint")
    parts = [maint_status(state, control=control, focused=focus == "toggle", w=w)]
    if state not in ("fail_closed", "unreadable"):
        parts += [text("lead-in · maint.list_lead", copy("maint.list_lead"), BODY, TEXT_1, w=w,
                       note="D02:580: before maint.list, so the list never reads as the state"),
                  bullets("consequences · maint.list", items("maint.list"), w=w)]
    parts += [text("still available · maint.stays", copy("maint.stays"), BODY, TEXT_1, w=w), window_section(w)]
    if state in ("loading", "load_failed") or control == "none":
        return parts
    direction = ("on" if state == "off" else "repair" if state == "unreadable" and control == "repair" else "off")
    return parts + [maint_marker(direction)]


def maint_frame(px: int, content: Iterable[Node], *, banners: Iterable[Node] = (), overlays: Iterable[Node] = (),
                items: Iterable[Node] = (), name: str | None = None) -> Node:
    """SCR-148: the shell "◆ Admin area · Maintenance mode", h1 "Maintenance mode", meta.asof, the content
    (maint_content()); banners= the shell-band slot (maint_banner(), D26: right after the EnvBanner)."""
    _src("maint")
    return shell(px, "SCR-148", content=content, banners=banners, overlays=overlays, items=items, name=name)


def maint_on_dialog(*, count: int | str | None = 2, why: str | None = None, state: str = "idle",
                    focus: str = "cancel", grace: int | None = None) -> Node:
    """MM-2 (L578) rung 2 "Turn on maintenance mode": the lead-in and maint.list, dlg.maint_on.positions ("Open
    positions: 2 — …", the count in type.num.base, G-45; "unavailable" filling its {n} on a failed read; while it
    loads a CMP-015 line and the confirm natively disabled, never busy or T2: D22, R-2, G-48), dlg.maint_on.algos, Why?, the flags step-up
    line, the marker; state="turning_on" is MM-3 (L579: busy maint.turning_on, Why? readonly, Cancel aria-disabled;
    Esc, the scrim and Enter on Cancel do nothing until the answer)."""
    _src("maint")
    kids: list[Node] = [text("lead-in · maint.list_lead", copy("maint.list_lead"), BODY, TEXT_1, w=IW),
                        bullets("consequences · maint.list", items("maint.list"))]
    if count is None:
        kids.append(hbox("positions", [skeleton("text", 1, w=IW)], None,
                         note="the count read in flight (D22 L186): the confirm natively disabled, never busy or "
                              "T2 (R-2)"))
    elif count == "unavailable":
        kids.append(text("positions", copy("dlg.maint_on.positions", n=label("unavailable")), BODY, TEXT_1, w=IW,
                         note="a failed read: 'unavailable' fills {n} (MM-2 L578)"))
    else:
        kids.append(count_text("positions", copy("dlg.maint_on.positions", n=count), w=IW))
    kids.append(text("algos", copy("dlg.maint_on.algos"), BODY, TEXT_1, w=IW))
    cstate = "busy:maint.turning_on" if state == "turning_on" else "waiting" if count is None else "enabled"
    return rung(2, label("maint.on_title"), kids, confirm=label("turn_on"), state=cstate,
                why=why_field(why, focused=focus == "why", readonly=state == "turning_on",
                              kept=state == "turning_on" and why is None),
                step="flags", grace=grace, marker=label("maint.marker"), cancel_focused=focus == "cancel",
                name="CMP-044 rung-2 dialog (composition) · maintenance on")


def maint_off_dialog(*, why: str | None = None, state: str = "idle", focus: str = "cancel") -> Node:
    """MM-6 (L582) rung 4 "Turn off maintenance mode" in §11's order (L598-600): dlg.maint_off.body, Why?, the
    step-up line "This always needs a fresh code." in its own slot, then the marker (§11 L613: flags.change +
    maintenance.disabled, maint_marker("off")) → SCR-006, no grace; state="turning_off" is MM-12 (busy
    maint.turning_off)."""
    _src("maint")
    kids = [text("body", copy("dlg.maint_off.body"), BODY, TEXT_1, w=IW)]
    mk = maint_marker("off")["chars"]
    return rung(4, label("maint.off_title"), kids, confirm=label("turn_off"),
                state="busy:maint.turning_off" if state == "turning_off" else "enabled",
                why=why_field(why, focused=focus == "why", readonly=state == "turning_off",
                              kept=state == "turning_off" and why is None),
                step="killswitch", marker=mk, cancel_focused=focus == "cancel",
                name="CMP-044 rung-4 dialog (composition) · maintenance off")


MAINT_BANNERS = ("on", "fail_closed", "unverified")


def maint_banner(px: int, kind: str = "on", *, hhmm: str | None = None, w: int | None = None) -> Node:
    """The shell-band maintenance banner (D26 L190; M10, M11: at 0 ms, no fade): "on" E42-D03's banner.maintenance
    ("… Since 14:02 UTC."); "fail_closed" banner.maintenance_fail_closed where the Owner's flags read says
    fail_closed or unreadable (D23); "unverified" banner.maintenance_unverified for every other session holding only
    the resolved ON (CG-32). CMP-028 warning, triangle (§15 L747); no control; no live role of its own (§12 L621)."""
    if kind not in MAINT_BANNERS:
        raise ValueError(f"maint_banner kind: one of {MAINT_BANNERS}")
    s = (copy("banner.maintenance", hhmm=hhmm or SAMPLE["maint_hhmm"]) if kind == "on" else
         copy(f"banner.maintenance_{kind}"))
    return callout("warning", paras=[s], w=w or SIZES[px].w, shell=True,
                   name=f"CMP-028 Callout (composition) · maintenance {kind}",
                   note="the shell-band slot under the TopBar, right after the EnvBanner (D26); speaks through the "
                        "shell's one region, assertive once on entry (§12 L621); never animated (S-2)")


def read_only_banner(px: int, w: int | None = None) -> Node:
    """D09's three-strike banner (FF-11, AL-12; D09 §3.3): CMP-028 warning, its own role="alert" once, title
    banner.read_only.title, body banner.read_only.body; no countdown."""
    return callout("warning", title=copy("banner.read_only.title"), paras=[copy("banner.read_only.body")],
                   w=w or SIZES[px].w, shell=True, name="CMP-028 Callout (composition) · read-only (D09)",
                   note="role='alert' once (D09 §3.3, E09-D06 §6); not dismissible while the state holds; writes stay "
                        "enabled until D09's CG-2 lands (FF-11)")


def flags_store_banner(px: int, w: int | None = None) -> Node:
    """FF-12's page banner flags.fail_closed (D23; warning, triangle), with the one T2 notice admin.flags_store under
    the header that every Change… and Revert points at."""
    width = w or SIZES[px].inner
    return vbox("fail-closed", [callout("warning", paras=[copy("flags.fail_closed")], w=width,
                                        name="CMP-028 Callout (composition) · flags fail-closed",
                                        note="assertive once (§12 L621)"),
                                t2_notice("admin.flags_store", name="notice · admin.flags_store")], {"gap": STACK_SM})


# --- G-39 one banner per cause and the ticket's T2 submit; G-43 the scrim; G-31 the ENV badge above it.
def exchange_banner(px: int, w: int | None = None) -> Node:
    """E17-D01's availability banner for an exchange's own maintenance or outage (E17-D01:148, SCR-153 / CMP-092,
    role="status"): "Exchange feed down — the server is restoring the connection"; no lock and no control here (MM-5
    L581; G-39). Its look is E17-D01's (the kit's warning callout stands in, DJ); what still works is E17-D01's."""
    s = label("e17.feed_down")
    return callout("warning", paras=[s], w=w or SIZES[px].w, shell=True,
                   name="SCR-153 availability banner (composition) · exchange feed down",
                   note="E17-D01's (E17-D01:148): role='status'; a different cause from maintenance mode, so both "
                        "banners show when both hold (MM-5 L581)")


def maintenance_banners(px: int, *, mode: bool = True, verified: bool = True, exchange: bool = False,
                        hhmm: str | None = None, w: int | None = None) -> list[Node]:
    """One banner per cause for the shell-band slot (D26 L190, MM-5 L581; orchestrator ruling 2026-10-23, G-39):
    maintenance mode is owner policy, so mode=True draws D03's banner.maintenance once the notice is in (verified,
    "Since {hh:mm}" the notice frame's ts) or banner.maintenance_unverified (verified=False: a later session holds only
    the resolved ON, CG-32), never also E17-D01's Read-only banner; exchange=True adds E17-D01's availability banner
    (exchange_banner()); both show when both hold. Pass the list as shell(banners=…) or app_frame(banners=…)."""
    out: list[Node] = []
    if mode:
        out.append(maint_banner(px, "on" if verified else "unverified", hhmm=hhmm, w=w))
    if exchange:
        out.append(exchange_banner(px, w=w))
    return out


def ticket_submit_t2(w: int = 336, *, label_: str | None = None, focused: bool = False,
                     name: str = "T2 · full-intent submit") -> Node:
    """The order ticket's new-risk submit (E30-D02's SCR-060 / CMP-107) in its T2 form while a maintenance banner
    stands (MM-5 L581; §12.1 L637; E09-D09 §2.1 step 4; G-39): the native role and full label kept (label_=, else a
    neutral bar named for E30-D02's submit label, which E30-D02 owns), aria-disabled, never disabled, its Tab stop
    kept; CMP-079 RbacGate; the fill color.surface.raised with a color.border.default hairline; the CMP-019 lock
    (named "Not available") leading the label, both color.text.tertiary; the reason under it (2a), in the DOM at
    mount and its only aria-describedby: the PROPOSED E30-D02 state key "maintenance" "Order entry is paused for
    maintenance." (38 characters, §14 L713); Enter, Space or Ctrl+Enter re-show it, polite once, and send nothing. A
    refusal that still arrives reads refusal.trading_disabled.maintenance (E30-D02:436)."""
    k._fallback("CONTROL")
    _deviate("compose")
    lw = w - 2 * PX[INSET_SM] - PX[k.ICON] - PX[INSET_XS]
    lab: Node = (text("label", label_, BODY_STRONG, TEXT_3) if label_ else
                 bar("E30-D02 submit label (full intent)", min(160, lw)))
    btn = hbox("CMP-001 Button (composition) · submit (T2)", [k.lock_glyph("lock"), lab],
               {"gap": INSET_XS, "padX": INSET_SM, "radius": R_CONTROL, "fill": RAISED, "stroke": BORDER_DEFAULT,
                "strokeWidth": HAIRLINE, "strokeAlign": "inner", "height": k.CONTROL_COMF}, w=w, h=CONTROL_H,
               note=_t2_note("maintenance", None) + "; E30-D02's submit (Ctrl+Enter), variant per side when enabled")
    rs = text("reason", reason("maintenance"), CAPTION, TEXT_2, w=w,
              note="the PROPOSED E30-D02 §14 state key 'maintenance' (MM-5 L581, §14 L713): a state key, never data")
    return vbox(name, [ring(btn, R_CONTROL) if focused else btn, rs], {"gap": STACK_XS}, w=w,
                note="T2 2a: the reason under the control (§12.1 L637)")


SCRIM = SUNKEN  # G-43: e42kit's SCRIM = SUNKEN, ruled out in every theme but dark (E09-D08 D2; FALLBACKS["SCRIM"])


def scrim(w: int, h: int, *, x: int = 0, y: int = 0, theme: str = "dark", name: str = "scrim") -> Node:
    """The dialog scrim, black at opacity.scrim in every theme (§15 L731-732; E09-D08 D2; G-43): cvsheet v1 cannot
    bind palette.black, so it binds color.surface.sunken, which is palette.black in dark only, and refuses a light
    frame (FALLBACKS["SCRIM"])."""
    if theme != "dark":
        raise ValueError("scrim(): no light-theme binding is black (FALLBACKS['SCRIM']): no D04 light board holds a "
                         "dialog")
    _fallback("SCRIM")
    return rect(name, w, h, SCRIM, {"opacity": OPACITY_SCRIM}, x=x, y=y, abs=True,
                note="black at opacity.scrim: #000000 at 60 % (color.surface.sunken = palette.black in dark); no blur; "
                     "the content under it is not masked (§15 L731-732; E09-D08 D2)")


def env_badges_above(px: int, env: str = "LIVE", *, top: int | None = None, status: int | None = None,
                     w: int | None = None, h: int | None = None) -> list[Node]:
    """The TopBar's CMP-074 and the StatusBar's CMP-075 ENV badges drawn again above a scrim at their chrome places
    (e42kit's topbar(): x = 16 + 88 + 12, centred in the 48 px bar; statusbar(): at its right end), so no scrim or
    card covers them (§11 L599-602; C-2.11; E10-D02:264; G-31). top / status / w / h override the frame's bars and
    size (a 200 % inset's)."""
    g = SIZES[px]
    top, status, w, h = top or g.top, status or g.status, w or g.w, h or g.h
    badge = k.env_badge(env)
    bw = round(k.est_width(badge))
    _deviate("modal-env")
    live(f"ENV badges above the scrim: after relayout align each over its chrome badge (TopBar x {116}, StatusBar "
         f"x {w - PX[INSET_LG] - bw}) and keep both above the scrim and the card")
    return [dict(k.env_badge(env, name=f"CMP-074 EnvBanner (composition) · {env} · above the scrim"),
                 x=PX[INSET_LG] + 88 + PX[INSET_MD], y=round((top - k.ENV_H) / 2), abs=True,
                 note="the TopBar's ENV badge (e42kit draws it as CMP-012), drawn above the scrim at its place: never "
                      "under a scrim or modal (E10-D02:264)"),
            dict(k.env_badge(env, name=f"CMP-075 EnvBadgeLocal (composition) · {env} · above the scrim"),
                 x=w - PX[INSET_LG] - bw, y=h - status + round((status - k.ENV_H) / 2), abs=True,
                 note="the StatusBar's ENV badge, drawn above the scrim at its place (E10-D02:264)")]


def modal(px: int, dialog_node: Node, *, env: str = "LIVE", fill: bool = False, theme: str = "dark") -> list[Node]:
    """One absolute "overlay" board over the whole frame (pass the result as shell(overlays=…)): the scrim (scrim(),
    G-43), the dialog centred on it, and the two ENV badges above both (env_badges_above(), G-31). fill=True is the
    200 % rule: the dialog fills only the area between the TopBar and the StatusBar (AL-28, FF-15; §11 L599-602).
    The dialog's height is estimated; a live check asks to re-centre it after relayout. Use this, not e42kit.modal()
    (whose scrim covers the badges and binds sunken in every theme)."""
    g = SIZES[px]
    sc = scrim(g.w, g.h, theme=theme)
    dw, dh = k.est_width(dialog_node), k.est_height(dialog_node)
    if fill:
        dlg = dict(dialog_node, x=0, y=g.top, w=g.w, h=g.h - g.top - g.status, abs=True)
    else:
        dlg = dict(dialog_node, x=round((g.w - dw) / 2), y=round(max((g.h - dh) / 2, 0)), abs=True)
        live(f"modal: centre '{dialog_node['name']}' in frame-{px} after relayout (estimated {dw:.0f} x {dh:.0f} px)")
    return [box("overlay", [sc, dlg, *env_badges_above(px, env)], None, w=g.w, h=g.h, x=0, y=0, abs=True,
                note="the modal layer (no layout): scrim, dialog, then the ENV badges above both (§11 L599-602)")]


# --- §13 motion (L639-698): cards per row, schematic storyboards (63), reduce twins (64), flash and vestibular (65).
STORY = {"M1": ("slide-in", "normal", "decelerate"), "M2": ("slide-out", "normal", "accelerate"),
         "M5": ("scrim-in", "normal", "standard"), "M6": ("fade-out", "fast", "accelerate"),
         "M12": ("shimmer", None, None), "M14": ("spinner", None, None), "M15": ("scale", "normal", "standard"),
         "M19": ("pop-in", "fast", "standard"), "M21": ("toast", "fast", "decelerate")}  # §13 L657-677
MINI_W, MINI_H = 80, 48


def sheet_frame(kids: Iterable[Node], *, w: int = 1280, h: int = 800, name: str = "frame-1280",
                cols: int = 1) -> Node:
    """A proof or motion sheet frame (not the app shell): w × h at 1:1, color.surface.app, space.inset.lg padding,
    clip on; cols > 1 deals the kids into that many columns, largest first, each to the shortest column."""
    ks = list(kids)
    if cols > 1:
        cw = (w - 2 * PX[INSET_LG] - (cols - 1) * PX[INSET_LG]) // cols
        buckets: list[list[Node]] = [[] for _ in range(cols)]
        heights = [0.0] * cols
        for kid in sorted(ks, key=k.est_height, reverse=True):  # largest first, each to the shortest column
            i = heights.index(min(heights))
            buckets[i].append(kid)
            heights[i] += k.est_height(kid) + PX[STACK_MD]
        if max(heights) > h - 2 * PX[INSET_LG]:
            live(f"{name}: the tallest sheet column is about {max(heights):.0f} px for {h - 32} px: check the export")
        ks = [hbox("columns", [vbox(f"column-{i + 1}", b, {"gap": STACK_MD}, w=cw) for i, b in enumerate(buckets)],
                   {"gap": INSET_LG, "align": "start"})]
    return vbox(name, ks, {"fill": APP, "clip": True, "pad": INSET_LG, "gap": STACK_MD}, w=w, h=h)


def _mini(name: str, kids: Iterable[Node], when: str) -> Node:
    """One storyboard key frame: a 96 × 60 viewport (canvas, border.default hairline, clip) and its time label."""
    vp = box("viewport", list(kids), {"fill": k.CANVAS, "stroke": BORDER_DEFAULT, "strokeWidth": HAIRLINE,
                                      "radius": R_CONTROL, "clip": True}, w=MINI_W, h=MINI_H)
    return vbox(name, [vp, text("when", when, NUM_SM, TEXT_2)], {"gap": STACK_XS})


def storyboard(mid: str) -> Node:
    """A schematic strip of key frames for one animated row (STORY): positions only (raw px), opacities only at
    their token values (0 and opacity.scrim): Penpot draws no in-between token opacity; the row's own words carry the
    timing, its tokens named as text (FALLBACKS["MOTION"])."""
    kind, tok, ease = STORY[mid]
    _fallback("MOTION")
    end = f"{DURATIONS[tok]} · {tok} · {ease}" if tok else ""
    EMITTED.add(end)  # §13 L645-647's token table: the duration, its token and the easing
    panel = lambda x: rect("panel", 40, MINI_H, OVERLAY, x=x, y=0)  # noqa: E731  (a drawer at x)
    card = rect("card", 48, 32, OVERLAY, {"radius": R_CONTROL}, x=24, y=14)
    scrim = rect("scrim", MINI_W, MINI_H, k.SCRIM, {"opacity": OPACITY_SCRIM}, x=0, y=0)
    if kind in ("scrim-in", "fade-out"):
        k._fallback("SCRIM")
    frames: list[tuple[list[Node], str]]
    if kind in ("slide-in", "slide-out"):
        xs = [MINI_W, 72, 56] if kind == "slide-in" else [56, 72, MINI_W]
        frames = [([panel(xs[0])], DURATIONS["instant"]), ([panel(xs[1])], "·"), ([panel(xs[2])], end)]
    elif kind == "scrim-in":
        frames = [([card], DURATIONS["instant"]), ([scrim, dict(card)], end)]
    elif kind == "fade-out":
        frames = [([scrim, dict(card)], DURATIONS["instant"]), ([], end)]
    elif kind == "shimmer":
        frames = [([rect("bone", 80, 10, HOVER, x=8, y=25), rect("shine", 16, 10, SELECTED, x=8 + 28 * i, y=25)],
                   "1,200 ms" if i == 2 else DURATIONS["instant"] if i == 0 else "·") for i in range(3)]
    elif kind == "spinner":
        frames = [([icon("spinner", "refresh", TEXT_2, x=40, y=22)], "800 ms")]  # CMP-014's PROPOSED period (M14)
    elif kind == "scale":
        frames = [([rect("track", 80, 8, TRACK, x=8, y=26), rect("fill", wd, 8, ACTION_PRIMARY, x=8, y=26)],
                   lab) for wd, lab in ((20, DURATIONS["instant"]), (40, "·"), (64, end))]
    elif kind == "pop-in":
        frames = [([], DURATIONS["instant"]), ([rect("menu", 56, 36, OVERLAY, {"radius": R_CONTROL}, x=20, y=12)], end)]
    else:
        frames = [([rect("toast", 64, 20, OVERLAY, {"radius": R_CONTROL}, x=16, y=36)], DURATIONS["instant"]),
                  ([rect("toast", 64, 20, OVERLAY, {"radius": R_CONTROL}, x=16, y=28)], end)]
    minis = [_mini(f"key frame {i}", kids, when) for i, (kids, when) in enumerate(frames, 1)]
    return hbox(f"storyboard · {mid}", minis, {"gap": INSET_SM, "align": "start"},
                note="schematic: positions only; '·' marks an in-between frame; PROPOSED numbers (§13 L653)")


def motion_card(mid: str, mode: str = "safe", *, w: int = 400) -> Node:
    """One §13 row as a card (raised, radius.card, inset.md): the id and transition, the motion-safe (or
    motion-reduce) cell, a storyboard for an animated row in safe mode, the carrier and the source, all §13's text
    without its code ticks (copy gaps, L657-679)."""
    r = MOTION[mid]
    _src("motion")
    NOTES.add("copy_gaps", f"'{mid}': §13's row text (L{r.line}), drawn verbatim without code ticks")
    iw = w - 2 * PX[INSET_MD]
    kids: list[Node] = [hbox("head", [text("id", mid, NUM_BASE, TEXT_1), text("transition", plain(r.transition),
                                                                            BODY_STRONG, TEXT_1, w=iw - 40)],
                             {"gap": INSET_SM, "align": "start"}),
                        text("spec", plain(r.safe if mode == "safe" else r.reduce), BODY, TEXT_1, w=iw,
                             note="§13's motion-safe column" if mode == "safe" else "§13's motion-reduce column")]
    if mode == "safe" and mid in STORY:
        kids.append(storyboard(mid))
    kids += [text("carrier term", label("motion.col.carrier"), LABEL, TEXT_2),
             text("carrier", plain(r.carrier), BODY, TEXT_1, w=iw), text("source", plain(r.source), CAPTION, TEXT_3)]
    return vbox(f"motion card · {mid}", kids, {"fill": RAISED, "radius": R_CARD, "pad": INSET_MD, "gap": STACK_XS},
                w=w, note=f"§13 L{r.line}; {'PROPOSED' if mode == 'safe' else 'its reduce twin'}")


def _bullet(head: str) -> tuple[int, int]:
    """The 0-based line slice of §13's "- **<head>**" bullet (to the next bullet or the next blank line)."""
    a = next(i for i, ln in enumerate(LINES) if ln.startswith(f"- **{head}**"))
    b = next(i for i in range(a + 1, len(LINES)) if LINES[i].startswith("- **") or not LINES[i].strip())
    return a, b


def motion_frame(nn: int, name: str = "frame-1280") -> Node:
    """Board 63 (the nine animated rows, motion-safe, with storyboards), 64 (their reduce twins with carriers) or 65
    (S-1-S-6 and the flash and vestibular rules, L681-695): one 1280 × 800 sheet frame, three columns."""
    if nn == 65:
        sa, sb = _bullet("Safety rules.")  # L681-688
        fa, fb = _bullet("Flash and vestibular.")  # L692-695 (G-27)
        joined = re.sub(r"\s+", " ", " ".join(LINES[sa:sb]))
        rules = re.findall(r"\*\*(S-\d)\*\* (.*?)(?= \*\*S-\d\*\*|$)", joined)
        flash = plain(re.sub(r"\s+", " ", " ".join(LINES[fa:fb])).lstrip("- "))
        NOTES.add("copy_gaps", "S-1-S-6 and 'Flash and vestibular': §13's text (L681-695), verbatim without markup")
        EMITTED.update({flash} | {sid for sid, _b in rules} | {plain(b_) for _s, b_ in rules})  # §13's own text
        cards = [vbox(f"rule · {sid}", [text("id", sid, NUM_BASE, TEXT_1), text("text", plain(body), BODY, TEXT_1,
                                                                                 w=376)],
                      {"fill": RAISED, "radius": R_CARD, "pad": INSET_MD, "gap": STACK_XS}, w=400)
                 for sid, body in rules]
        cards.append(vbox("rule · flash and vestibular", [text("text", flash, BODY, TEXT_1, w=376)],
                          {"fill": RAISED, "radius": R_CARD, "pad": INSET_MD}, w=400))
        return sheet_frame(cards, cols=3, name=name)
    mode = {63: "safe", 64: "reduce"}[nn]
    head = text("column", label("motion.col.safe") if mode == "safe" else label("motion.col.reduce"), HEADING_SM,
                TEXT_1, note="§13's column header (L655): every card below shows that column")
    fr = sheet_frame([motion_card(m, mode) for m in ANIMATED], cols=3, name=name)
    fr["kids"] = [head, *fr["kids"]]
    return fr


# --- The proof sheets: 66 status-sheet (§15 L765-767: every state keeps a word and a glyph shape; high adds the rule
# and the weight) and 67 diff-sheet (§6: every value kind and the three shapes, each in both forms).
SHEET_W = 405  # a column of a three-column 1280 sheet frame


def _sheet_section(key: str, rows: Iterable[Node], w: int = SHEET_W) -> Node:
    """A sheet section: its heading (§15 L765-767's word, type.ui.heading-sm) and rows."""
    return vbox(f"section · {key}", [text("heading", label(f"sheet.{key}"), HEADING_SM, TEXT_1), *rows],
                {"gap": STACK_SM}, w=w)


def severity_strip(sev: str, w: int = SHEET_W) -> Node:
    """One severity as a row shows it (D2): raised, 32 px, the glyph and word, and the 2 px rule when high."""
    kids = severity_cell(sev)
    if sev in HIGH:
        _fallback("THICK")
        kids = kids + [rect("high rule", HIGH_RULE_W, ROW_H, DANGER_STRONG, x=0, y=0, abs=True)]
    return hbox(f"severity · {sev}", kids, {"gap": INSET_XS, "padX": INSET_SM, "fill": RAISED, "height": k.ROW_COMF},
                w=w, h=ROW_H)


def status_sheet(w: int = SHEET_W) -> list[Node]:
    """Board 66's sections (one theme column): severity (D2), outcome (D3), tamper (TAMPER), export (§8's lines),
    flag (deployment ON / OFF, the Owner's value, fail-closed, unreadable, the blocked live row) and maintenance
    (status lines, tiles, the three banners). Values no source gives are bars."""
    _src("tokens")
    fills = {"range_passed": {"from": None, "to": None, "hhmm": None}, "limited": {"hhmm": None},
             "stopped": {"hhmmss": None}, "failed": {"n": SAMPLE["break_entry"]}}
    tamper = [status_line(f"tamper · {st}", tone, rich("words", key, w=w - 24, **fills.get(st, {})))
              for st, (tone, key) in TAMPER.items()]
    exports = [export_line(1280, st, w=w, **({"code": "export_too_large"} if st == "failed" else {}),
                           **({"yyyy-mm-dd hh:mm": None} if st == "expired" else {}),
                           **({"hhmm": None} if st == "limited" else {}))
               for st in ("running", "poll_failed", "ready", "failed", "cancelled", "lost", "expired", "limited",
                          "download_failed", "not_built")]
    live_ = FLAG["trading.live_enabled"]
    flag = [text("on", copy("flags.deployment", value=label("ON")), BODY_STRONG, TEXT_1),
            text("off", copy("flags.deployment", value=label("OFF")), BODY_STRONG, TEXT_1),
            text("override", copy("flags.your_override", value=label("ON")), BODY, TEXT_2),
            text("resolved", copy("flags.your_resolved", value=label("ON")), BODY, TEXT_2),
            text("fail-closed", label("fc_value"), CAPTION, TEXT_2),
            status_line("unreadable", "warning", copy("flags.unreadable"), typo=CAPTION, w=w - 24),
            flag_actions(live_, FlagState("OFF"))]
    maint = [maint_status("off", control="none"), maint_status("on", control="none"),
             status_line("tile · on", "warning", copy("tile.maintenance_on", hhmm=SAMPLE["maint_hhmm"])),
             status_line("tile · fail-closed", "warning", copy("tile.maintenance_fail_closed")),
             *[callout("warning", paras=[copy("banner.maintenance", hhmm=SAMPLE["maint_hhmm"]) if b == "on" else
                                         copy(f"banner.maintenance_{b}")], w=w, name=f"banner · {b}")
               for b in MAINT_BANNERS]]
    for n in maint[:2]:
        find(n, "words")["w"] = w - 24
    return [_sheet_section("severity", [severity_strip(s, w) for s in SEVERITY], w),
            _sheet_section("outcome", [hbox(f"outcome · {o}", result_cell(o), None) for o in OUTCOME_KEY], w),
            _sheet_section("tamper", tamper, w), _sheet_section("export", exports, w),
            _sheet_section("flag", flag, w), _sheet_section("maintenance", maint, w)]


SAMPLE_VALUES = {  # §6's own example values: "value: OFF → ON" (L364), "value: requested ON (stored OFF)" (L383)
    "value": Val("value", "ON"), "number": Val("value", "2", num=True), "fingerprint": Val("fingerprint"),
    "identifier": Val("identifier"), "secret": Val("secret"), "secret_named": Val("secret_named"),
    "credential": Val("credential"), "personal": Val("personal"), "oversize": Val("oversize"), "none": Val("none"),
    "withheld": Val("withheld"), "hidden": Val("hidden"), "long": Val("value", long=True),
    "not_sent": Val("not_sent"), "overrides_kept": Val("overrides_kept"),
}


def diff_sheet(w: int = SHEET_W) -> list[Node]:
    """Board 67's sections: every value kind (secret_named included) and the state, request and result shapes, each
    in its full and inline form (§6 L358-405). Values §6 does not give are bars; kind names are §6's (L385-395)."""
    _src("diff")
    NOTES.add("copy_gaps", "value-kind names (value, fingerprint, …, hidden): §6's table (L380-395), drawn as terms")
    EMITTED.update(v.kind for v in SAMPLE_VALUES.values())
    kinds = vbox("section · kinds", [text("heading", label("sheet.kinds"), HEADING_SM, TEXT_1)] + [
        hbox(f"kind · {v.kind}", [text("kind", v.kind, NUM_SM, TEXT_2, w=96), diff_value(v)], {"gap": INSET_SM},
             note=f"sample {kn}")
        for kn, v in SAMPLE_VALUES.items()], {"gap": STACK_SM}, w=w)
    state = diff_full([Field("value", "changed", Val("value", "OFF"), Val("value", "ON")),
                       Field(SAMPLE["nested_path"], "added", None, Val("value"))], unchanged=1, w=w)
    request = diff_full([Field("value", "requested", Val("value", "OFF"), Val("value", "ON")),
                         Field("overrides", "requested", None, Val("overrides_kept")),
                         Field("reason", "fact", after=Val("credential"))], shape="request",
                        head_reason="credential_in_reason", w=w)
    intent = diff_full([Field("value", "requested", Val("value", "OFF"), Val("value", "ON"))], shape="request",
                       intent=True, w=w)
    result = diff_full([Field("verified", "result", after=Val("value")), Field("first_bad_id", "result",
                                                                             after=Val("value", num=True))],
                       shape="result", no_before=True, w=w)
    inline = vbox("section · inline", [diff_inline("value", "OFF", "ON"),
                                       text("head · failed", copy("diff.head_failed", reason="credential_in_reason"),
                                            BODY_STRONG, TEXT_1),
                                       diff_inline("value", "OFF", "ON", requested=True),
                                       text("head · intent", copy("diff.head_intent"), BODY_STRONG, TEXT_1),
                                       diff_inline("value", "OFF", "ON", requested=True, name="inline · intent"),
                                       text("head · result", copy("diff.result"), BODY_STRONG, TEXT_1),
                                       hbox("result line", [text("term", "verified:", BODY, TEXT_1,
                                                                 note="§7 L410's result field"), bar("verified")],
                                            {"gap": INSET_XS})], {"gap": STACK_SM}, w=w)
    EMITTED.add("verified:")
    return [kinds, state, request, intent, result, inline]


# --- The annotation column (build notes: title, source line (operation, budget, events, mount state), state id and
# trigger, decision ids, roles, keyboard path and focus, announcement, copy keys, tokens, events; footer).
ANN_ORDER = (("source", "Source (operation · budget · events · mount state)"), ("state", "State and trigger"),
             ("decisions", "Decision ids"), ("roles", "Roles"), ("keyboard", "Keyboard path and focus"),
             ("announcement", "Announcement (text, region, when)"), ("copy", "Copy keys used"), ("tokens", "Tokens"),
             ("events", "Analytics and audit events"))
SOURCE = {  # each screen's default source line (D02 D17: operation, budget, events, mount state), cited by spec line
    "SCR-135": ("GET /admin/audit · audit:read, scope self · executed (L238); ≤ 400 ms per filter round-trip, 200 rows "
                "a "
                "page (limit=200) against the server's 4,000 ms stop; 60 calls/min, 2 in flight (L218-219, D4 L168); "
                "events: admin.audit_read on a filter set's first read, admin.audit_denied, admin.audit_verify, "
                "admin.audit_export; a 422, 400 or 503 list read writes no admin.audit_read and a 429 is counted, not "
                "recorded; the incident read writes admin.area_entered (L308-316); export: 501 today, and the "
                "download, mounted, answers 404 as no job exists (X2 L465, X10 L473)"),
    "SCR-136": ("no call: the drawer renders the page's AuditEntry (no single-record read, CG-5); the ≤ 300 ms budget "
                "holds at 0 ms (L320-323); opening records nothing new, copying is unaudited (L355-356)"),
    "SCR-145": ("GET /admin/feature-flags · flags:read · executed; PUT /admin/feature-flags/{flagKey} · flags:write · "
                "executed, reason ≤ 280 and expected_updated_at required; a push within 2 s (L487-491); events: "
                "flags.change at warning (intent + outcome), auth.step_up_required, admin.area_entered on every call, "
                "History admin.audit_read (L550-555)"),
    "SCR-148": ("PUT /admin/feature-flags/maintenance.mode: on flags (5-minute grace), off killswitch (no grace, "
                "single use), reason and expected_updated_at required; refusal ≤ 200 ms, the notice ≤ 2 s; the rung-2 "
                "count has "
                "no provider (CG-21) (L559-562); events: maintenance.enabled|disabled with flags.change, a poll-read "
                "transition as system:maintenance (L590-594)"),
    "motion": "§13 L639-698: every number PROPOSED (L653); the motion tokens are code-only in Penpot (L645-648)",
    "proofs": "§15 L715-767 and §6 L358-405; the §0 audit script re-runs every pair (L119, L717-719)",
}


def annotations(nn: int, blocks: dict[str, Any] | Iterable[tuple[str, Any]] | None = None, *,
                title_: str | None = None, rev: str = REV) -> Node:
    """The 400 px column outside the frames: the title (default title(nn)), labelled blocks in the build notes' order
    (keys of ANN_ORDER; other labels follow), "source" defaulting to SOURCE[screen], "state" to the state row, "copy"
    to every key recorded so far, "tokens" to every token recorded plus every fallback line; then a "Board" block
    (name, export, its board, ★, S) and the footer "page E42-D04 · board NN · r1" (§0 L64-65). Build it last."""
    b = BOARDS.get(nn)
    _src("boards")
    labels = dict(ANN_ORDER)
    by_key: dict[str, list[str]] = {}
    extras: list[tuple[str, list[str]]] = []
    for key, v in ((blocks or {}).items() if isinstance(blocks, dict) else (blocks or ())):
        lines = [v] if isinstance(v, str) else [str(x) for x in v]
        (by_key.setdefault(key, []).extend(lines) if key in labels else extras.append((str(key), lines)))
    if b and "source" not in by_key:
        by_key["source"] = [SOURCE[b.screen]]
    if b and b.state_id and "state" not in by_key:
        by_key["state"] = [f"{b.state_id} {b.state} (L{b.line})"]
    notes = merged_notes()
    if "copy" not in by_key and notes["copy_keys"]:
        by_key["copy"] = [", ".join(notes["copy_keys"])]
    if "tokens" not in by_key:
        by_key["tokens"] = [k.tokens_line(notes["tokens"])]
    by_key["tokens"] += [ln for ln in notes["fallbacks"] if ln not in by_key["tokens"]]
    if b:
        on = NEW_BOARDS.get(b.on or 0)
        extras.append(("Board", [f"{b.name}; " + (f"drawn on board {on.nn:02d} `{on.slug}` (§0 L{on.line})" if on
                                                    else "not drawn (§0 L98-104)")]
                       + (["★ id: its board's greyscale and deuteranopia renders (§0 L91-97)"] if b.star else [])
                       + (["S: named for this PR's security reviewer and E42-X02 (§18 L852-853)"] if b.sec else [])))
    ordered = [(labels[kk], by_key[kk]) for kk, _l in ANN_ORDER if kk in by_key] + extras
    ordered = [(lab, [ln for ln in lines if ln.strip()]) for lab, lines in ordered]
    ordered = [(lab, lines) for lab, lines in ordered if lines]
    kids = [text("title", title_ or (title(nn) if b else f"{nn:02d}"), HEADING_SM, TEXT_1, w=ANN_TEXT_W)]
    for i, (lab, lines) in enumerate(ordered, 1):
        bk = [text("label", lab, LABEL, TEXT_2)] + [text(f"value-{j}", ln, BODY, TEXT_1, w=ANN_TEXT_W)
                                                     for j, ln in enumerate(lines, 1)]
        kids.append(vbox(f"block-{i:02d}", bk, {"gap": STACK_XS}, w=ANN_TEXT_W))
    kids.append(text("footer", f"page {PAGE} · board {nn:02d} · {rev}", CAPTION, TEXT_3, w=ANN_TEXT_W))
    return vbox("annotations", kids, {"gap": STACK_SM, "pad": INSET_LG}, w=ANN_W)


def root_size(nodes: Iterable[Node], ann: Node | None = None) -> tuple[int, int]:
    """The root's width and height: the nodes side by side and the 400 px column, inset.lg padding and gaps; the
    height the tallest of them (the column plus ANN_HEADROOM), rounded up to 8."""
    ns = list(nodes)
    w = ROOT_PAD + sum(round(k.est_width(n)) + ROOT_PAD for n in ns) + (ANN_W + ROOT_PAD if ann else 0)
    tallest = max([k.est_height(n) for n in ns] + [k.est_height(ann) + ANN_HEADROOM if ann else 0.0])
    return w, int(math.ceil((tallest + 2 * ROOT_PAD) / 8) * 8)


def board(nn: int, frames: Iterable[Node], ann: Node, *, extra: Iterable[Node] = (), w: int | None = None,
          h: int | None = None, check: bool = True) -> dict[str, Any]:
    """The sheet's board dict for board nn: its Penpot name, the grid x/y (build notes), the root options (flex row,
    align start, color.surface.app, space.inset.lg padding and gap, clip) and w / h (given, or root_size()). check:
    the frames match the registry (count and widths: BOARDS[nn].frames) and ann carries the title and the footer."""
    if nn not in BOARDS:
        raise ValueError(f"board {nn} is not in §0's plan (01-74)")
    b = BOARDS[nn]
    fr = list(frames)
    if check:
        got = tuple(int(f.get("w") or 0) for f in fr)
        if got != b.frames:
            raise ValueError(f"board {nn:02d}: frames {got} differ from §0's {b.frames} (pass check=False for a 2 x 2 "
                             f"layout or insets)")
    kids = ann.get("kids") or []
    foot = f"page {PAGE} · board {nn:02d} · {REV}"
    if not kids or kids[0]["name"] != "title" or kids[-1].get("chars") != foot:
        raise ValueError(f"board {nn:02d}: the annotation column needs its title first and '{foot}' last")
    if w is None or h is None:
        w, h = root_size([*fr, *extra], ann)
    if w > PITCH_X - 40 or h > PITCH_Y - 40:
        raise ValueError(f"board {nn:02d}: {w} x {h} would touch its neighbours (pitch {PITCH_X} x {PITCH_Y}): shorten "
                         f"the annotation blocks or lay the frames out 2 x 2")
    _deviate("names")
    _src("boards")
    live("root name: after the first section call the root must read back exactly as the sheet's board.name, or later "
         "calls create a duplicate root")
    x, y = grid_xy(nn)
    return {"name": b.name, "w": w, "h": h, "x": x, "y": y, "o": dict(k.ROOT_O)}


def sections_for_board(frames: Iterable[Node], ann: Node | None = None, extra: Iterable[Node] = (),
                       budget: int = SECTION_BUDGET) -> list[dict[str, Any]]:
    """The sheet's sections, each at most budget bytes of JSON (the validator's measure), with into paths that exist
    when used ("" the root, then "frame-1280", "frame-1280/body", "frame-1280/body/main", …): e42kit's packer, in render
    order: the frames, then extra root nodes, then the annotation column."""
    secs = k.sections_for_board(list(frames), ann, list(extra), budget=budget)
    big = [(s["node"]["name"], len(json.dumps(s))) for s in secs if len(json.dumps(s)) > budget]
    if big:
        raise ValueError(f"sections over {budget} bytes: {big}")
    return secs


def write_sheet(target: int | str | Path, board_: dict[str, Any], sections: list[dict[str, Any]],
                notes: dict[str, Any] | None = None, export: str | None = None) -> str:
    """Write the sheet (target: a board number → NN-<slug>.json beside this kit, or a path in this folder with
    export=), notes merged (this kit's, e42kit's re-qualified, then notes=; every inst node a live check); validate it
    with the component inventory; clear the notes; raise RuntimeError on a validator error or a section over
    SECTION_BUDGET; return the validator's summary line."""
    if isinstance(target, int):
        out = KIT_DIR / f"{target:02d}-{BOARDS[target].slug}.json"
        export = export or BOARDS[target].export
    else:
        out = Path(target)
        if not export:
            raise ValueError("write_sheet(path): pass export=")
    out = out.resolve()
    if out.parent != KIT_DIR:
        raise ValueError(f"sheets are written only into {KIT_DIR}")
    merged = merged_notes(notes)
    for sec in sections:
        for _p, n in k.walk(sec["node"]):
            if n["t"] == "inst" and k._inst_check(n) not in merged["live_checks"]:
                merged["live_checks"].append(k._inst_check(n))
    sheet = {"board": board_, "sections": sections, "export": export, "notes": merged}
    out.write_text(json.dumps(sheet, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    reset_notes()
    big = [(s["node"]["name"], len(json.dumps(s))) for s in sections if len(json.dumps(s)) > SECTION_BUDGET]
    res = subprocess.run([sys.executable, "-I", str(VALIDATOR), str(out), "--components", str(COMPONENTS)],
                         capture_output=True, text=True, timeout=120, check=False)
    lines = (res.stdout + res.stderr).strip().splitlines()
    if res.returncode != 0 or big:
        raise RuntimeError(f"{out.name}: validator exit {res.returncode}, sections over {SECTION_BUDGET} B: {big}\n"
                           + "\n".join(lines))
    return lines[-1] if lines else ""


def notes_md(sheet_path: str | Path) -> str:
    """A written sheet's notes as markdown sections (for a generator's .md): sources, copy keys, copy gaps, spec gaps,
    fallbacks, tokens, live checks, deviations."""
    notes = json.loads(Path(sheet_path).read_text(encoding="utf-8"))["notes"]
    out = []
    for kd in ("sources", "copy_keys", "copy_gaps", "spec_gaps", "fallbacks", "tokens", "live_checks", "deviations"):
        lines = notes.get(kd) or []
        out.append(f"## {kd.replace('_', ' ').capitalize()} ({len(lines)})\n")
        out += [f"- {ln}" for ln in lines] + [""]
    return "\n".join(out)


# --- Self-test: python3 -I e42d04kit.py selftest
_copy0, _label0, _body0 = copy, label, flag_body


def _ws(s: str) -> str:
    """s with markdown code ticks dropped and whitespace runs collapsed (markdown wraps long lines)."""
    return re.sub(r"\s+", " ", s.replace("`", ""))


def _span(lines: list[str], a: int, b: int) -> str:
    """Lines a..b (1-based) joined and normalised."""
    return _ws(" ".join(lines[a - 1:b]))


def _doc(doc: str) -> list[str]:
    """A DOCS file's lines."""
    return DOCS[doc].read_text(encoding="utf-8").split("\n")


def _catalogue() -> dict[str, tuple[str, bool, bool]]:
    """svc/admin/flags/catalogue.py's FlagSpec calls read with ast: key -> (description, default, owner_only)."""
    import ast
    names = {"LIVE_ENABLED": "trading.live_enabled", "MAINTENANCE_MODE": "maintenance.mode",
             "MAINTENANCE_KEEP_RECORDER": "maintenance.keep_recorder",
             "DESKTOP_BACKEND_CONNECTION": "desktop.backend_connection"}
    out: dict[str, tuple[str, bool, bool]] = {}
    for node in ast.walk(ast.parse(DOCS["CAT"].read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "FlagSpec":
            a = node.args
            vis = getattr(a[5], "id", "") == "_OWNER"
            dflt = bool(a[4].value) if isinstance(a[4], ast.Constant) else False
            if isinstance(a[0], ast.JoinedStr):  # the algo.{name} comprehension: one template, five names
                for n in ("twap", "chase", "iceberg", "scaled", "oco"):
                    out[f"algo.{n}"] = (_ALGO.format(name=n), dflt, vis)
                continue
            key = a[0].value if isinstance(a[0], ast.Constant) else names[a[0].id]
            out[key] = (a[2].value, dflt, vis)
    return out


def _spec_checks(check: Any) -> None:
    """Every copy, inherited, label and worked-example string at its lines; the flags against the catalogue; the
    motion rows; the registry against §0."""
    L = LINES
    bad = [kk for kk, ln in SRC_LINES.items() if not L[ln - 1].startswith("#")]
    check(not bad, f"{len(SRC_LINES)} cited section headings sit at their lines {bad or ''}")
    sec14 = _span(L, 704, 713)
    bad = [kk for kk, s in COPY.items() if (s not in _doc(COPY_SOURCE[kk][0])[COPY_SOURCE[kk][1] - 1]
                                             if kk in COPY_SOURCE else _ws(s) not in sec14)]
    check(not bad, f"{len(COPY)} copy strings verbatim in §14 L704-713 (three at D02:717) {bad or ''}")
    bad = [kk for kk in ("admin.export_running", "admin.conflict_first", "admin.needs_count")
           if f"`{kk.split('.', 1)[1]}`" in L[710] or kk in COPY]
    check(not bad, f"the folds' dropped T2 keys stay out of §14's admin.* row (L711) and the deck {bad or ''}")
    row = _ws(L[711])
    bad = [lk for lk, ck in LABEL_KEYS.items() if ck.startswith("labels.") and not (
        f'"{_LABELS_AS.get(lk, LABELS[lk][0])}"' in row and f"{ck.split('.')[1]}.*" in row)]
    bad += [lk for lk, ck in LABEL_KEYS.items() if not ck.startswith("labels.") and ck != "meta.asof"
            and ck not in COPY]
    check(not bad, f"{len(LABEL_KEYS)} labels keyed in §14 (L712 labels.*, L709-710) {bad or ''}")
    bad = [kk for kk, (s, doc, ln) in INHERITED.items() if s not in _doc(doc)[ln - 1]]
    check(not bad, f"{len(INHERITED)} inherited D09 / E30-D02 strings at their lines {bad or ''}")
    bad = [kk for kk in k.COPY if kk in COPY or kk in INHERITED]
    check(not bad, f"no D04 key shadows an E42-D03 key {bad or ''}")
    bad = [kk for kk, (s, a, b) in LABELS.items() if _ws(s) not in _span(L, a, b)]
    check(not bad, f"{len(LABELS)} spec strings outside §14 on their lines {bad or ''}")
    check("Recorded in the audit log · <label> (<code>)" in _ws(L[127]), "the marker convention is §1 L128's")
    check("b7154f95153d5357b5c50cc91c5f43000de64335" in _ws(L[16]) and "merged as 58660d32f" in _ws(L[10] + L[11]),
          "the key pins every path:line at b7154f951 and D03 at 58660d32f (L11-12, L17)")
    bad = [dk for dk, m in DOCS_MD5.items() if hashlib.md5(DOCS[dk].read_bytes()).hexdigest()[:8] != m]
    check(not bad, f"{len(DOCS)} quoted files read as at {PIN} (md5) {bad or ''}")
    l15 = _doc("15")
    check("(Workspaces / Journal / Rules / Alerts / Replay / Admin)" in l15[698] and "CMP-070 AppShell" in l15[687]
          and all(t in l15[n - 1] for n, t in CHROME_15.items()),
          "`15:699` NavRail's Admin item and the chrome tokens (CHROME_15) at the pin")
    bad = [kk for kk, (s, doc, ln) in OTHER_LABELS.items() if s not in _doc(doc)[ln - 1]]
    check(not bad, f"{len(OTHER_LABELS)} strings from D01 / D02 / E39-D03 at their lines {bad or ''}")
    ex = _span(L, 136, 149)
    s = SAMPLE
    facts = [s["owner"], "alex", "sub_001", "sub_002", "bea", "sub_003", "carol", "LIVE", s["date"],
             f'"as of {s["asof"]}"', f"entry {s['break_entry']}", f"found at {s['found_at']}",
             f"{s['range_from']}–{s['range_to']}", "flags.change", "orders.submit", "api_key.import",
             "admin.audit_verify", "rbac.denied", "warning", "critical"]
    bad = [f for f in facts if f not in ex]
    lit = {324: f"Record {s['record']}", 325: f"{s['record_ts']} UTC", 492: f"as of {s['flags_asof']}",
           580: f"since {s['maint_since']} UTC", 535: f"Open positions: {s['open_positions']}",
           269: s["deleted_user"], 248: s["system_actor"], 376: s["nested_path"], 142: f"as of {s['asof_break']}",
           144: "security.key_policy_violation", 145: "backup.downloaded"}
    bad += [f"L{ln}" for ln, f in lit.items() if f not in _ws(L[ln - 1])]
    check(not bad, f"§1's worked example (L136-149) and the state rows' literals {bad or ''}")
    bad = [c for c, (lab, wh) in ACTIONS.items() if lab and wh.startswith("L")
           and f"{lab} ({c})" not in _span(L, int(wh[1:]) - 1, int(wh[1:]) + 1)]
    bad += [] if "Area entered (admin.area_entered)" in str(k.COPY["footer.area_entered"]) else ["admin.area_entered"]
    check(not bad, f"{sum(1 for v in ACTIONS.values() if v[0])} action labels at their lines {bad or ''}")
    cat = _catalogue()
    bad = [f.key for f in FLAGS if cat.get(f.key) != (f.desc, f.default, f.owner_only)]
    check(len(cat) == 17 and not bad, f"17 flags match catalogue.py (description, default, owner only) {bad or ''}")
    bad = [f.key for f in FLAGS if f.key not in L[GROUP_LINE[f.group] - 1] and "`." + f.key.split(".")[1] + "`" not in
           L[GROUP_LINE[f.group] - 1]]
    bad += [f.key for f in FLAGS if f.desc not in cat.get(f.key, ("",))[0]]
    check(not bad, f"each flag on its group's row (L509-512) {bad or ''}")
    bad = [m for m in ANIMATED if m not in MOTION] + ([] if len(MOTION) == 23 and "23 rows" in L[695] else ["count"])
    check(not bad, f"§13: 23 motion rows (L657-679), 9 animated (L696-697) {bad or ''}")
    bad = [v for v in OWNER_ONLY_VERBS.values() if v not in _span(L, 289, 289) + _span(L, 348, 348)]
    check(not bad, f"{len(OWNER_ONLY_VERBS)} rbac.owner_only verbs on AL-25 / AD-7 (L289, L348) {bad or ''}")
    b = BOARDS
    nb = NEW_BOARDS
    check(sorted(b) == list(range(1, 75)) and "The 74 earlier state-board ids stay as ids, written in brackets"
          in _span(L, 58, 59), "74 earlier ids 01-74, kept as ids in brackets (§0 L58-60)")
    check(sorted(nb) == list(range(1, 11)) and all(x.status == "PENDING" for x in nb.values())
          and "A board number 01–10 names a drawn board" in _ws(L[57]),
          "ten boards 01-10 in §0's table, each PENDING (L58, L78-89)")
    bad = [n for n, x in b.items() if x.on and n not in nb[x.on].ids]
    bad += [n for x in nb.values() for n in x.ids if b[n].on != x.nn]
    check(not bad and sorted(DRAWN) == sorted(n for x in nb.values() for n in x.ids),
          f"every state row's 'board NN' (L263-293, L340-349, L526-544, L575-588) is its id's board in §0's table "
          f"{bad or ''}")
    nd = _s0_item(L, "Not drawn")
    got = sorted(_ids_in(nd))
    check(got == sorted(n for n, x in b.items() if not x.drawn) and len(got) == 74 - len(DRAWN),
          f"§0's Not-drawn list (L98-104) names the {74 - len(DRAWN)} ids no board draws")
    at1280 = [b[n].state_id for n in sorted(b) if b[n].on_1280]
    check(at1280 == ["AL-3", "AL-18", "AL-20", "AL-21", "AL-29", "AD-5", "AD-7", "FF-16", "MM-2", "MM-5", "MM-6",
                     "MM-9"] and all(s in nd for s in at1280)
          and all(len(b[n].frames) == 2 for n in b if b[n].on_1280 and b[n].theme == "dark"),
          "the rows' '(1280)' after their board are the ids §0 L102-104 draws at 1280 only (the dark ones both "
          "sizes in the earlier plan)")
    count = _s0_item(L, "Count")
    per = [sum(x.frames) for x in nb.values()]
    check(sum(per) == 38 and f"Frames on boards **38** ({' + '.join(map(str, per)).replace('**', '')};" in count
          and sum(len(f) for f in [b[n].frames for n in b]) == 144,
          f"{sum(per)} frames on the ten boards ({' + '.join(map(str, per))}; §0 L91-92); the 74 ids keep the "
          f"earlier plan's 144")
    stars = [n for n, x in nb.items() if x.star]
    pngs = len(nb) + 2 * len(stars)
    check(stars == [1, 2, 8, 9] and f"Renders on the four ★ boards (01, 02, 08, 09): {2 * len(stars)}, so "
          f"**{pngs} PNGs**" in count, f"{len(stars)} ★ boards: {2 * len(stars)} renders, {pngs} PNGs (§0 L92-93)")
    now = {"star": tuple(n for n, x in b.items() if x.star), "sec": tuple(n for n, x in b.items() if x.sec),
           "light": tuple(n for n, x in b.items() if x.theme == "light")}
    check(now == FOLD_MARKS, "the ids keep the fold's marks: 18 ★ (Count, L94-96, and the ★ boards' ids), 6 S "
          "(§18 L852-853), 4 light (the 'in light' rows)")
    check([n for n, x in nb.items() if x.theme == "light"] == [10] and "board 10 is the one light twin"
          in _s0_item(L, "Themes"), "one light board, 10 (§0 L89, L109)")
    check("Boards 02, 03 and 05 ([13], [14], [34], [04], [32] and [41]) go to the security reviewer"
          in _span(L, 852, 853) and sorted({b[n].on for n in now["sec"]}) == [2, 3, 5],
          "S ids 04, 13, 14, 32, 34, 41 on boards 02, 03 and 05 (L852-853)")
    check(f"`{PAGE} / 02 {nb[2].slug} · {BOTH} · {nb[2].theme}`" in _join(L, 61, 62) and nb[2].name ==
          f"{PAGE} / 02 scr135-tamper-failed · {BOTH} · dark", "board 02's name is §0 L61-62's example")
    check('the footer "page E42-D04 · board NN · rN"' in _span(L, 64, 65).replace("`", ""),
          "the footer 'page E42-D04 · board NN · rN' (§0 L64-65)")
    off = [n for n, x in b.items() if n not in KIT_SLUGS and f"`{x.slug}`" not in L[x.line - 1]]
    off += [n for n, x in nb.items() if f"`{x.slug}`" not in L[x.line - 1]]
    check(not off, f"every slug on its id's line and every board's on its §0 row {off or ''}")
    check(grid_xy(13) == (2 * PITCH_X, 2 * PITCH_Y) and grid_xy(74) == (3 * PITCH_X, 14 * PITCH_Y),
          "grid x/y per the build notes")
    check("docs/design/E42/img/E42-D04-NN-<slug>.png" in _ws(L[66])
          and all(x.export == f"docs/design/E42/img/E42-D04-{n:02d}-{x.slug}.png" for n, x in nb.items()),
          "exports docs/design/E42/img/E42-D04-NN-<slug>.png (§0 L67-69)")


def _kit_checks(check: Any) -> None:
    """The boards-PR carries the kit applies (G-30..G-48), each proved on a built node (build-notes "SPEC MOVED (boards
    PR carries)")."""
    def names(n: Node) -> list[str]:
        """Every node name under n, pre-order."""
        return [x["name"] for _p, x in k.walk(n)]

    cl = list(audit_cols(1280))
    check([c.width for c in cl] == [24, 104, 144, 56, 128, 144, 80, 104, 96, 64] and sum(c.width for c in cl) == 944,
          "G-7: SCR-135's ten 1280 columns as §4 L239-241 writes them (944 px)")
    rd = {c.id: c.width for c in audit_cols(2560, 1392)}
    check(rd["role"] >= ROLE_MIN_2560 and rd["expander"] == EXPANDER_W,
          f"G-48: at 2560 docked (1,392 px) Role keeps ≥ {ROLE_MIN_2560} px ({rd['role']}), the expander 24 px")
    roles = {px: [x["chars"] for _p, x in k.walk(bar_row(audit_cols(px), "r", px))
                  if x["name"] == "role" and x["t"] == "text"]
             for px in (1280, 2560)}
    check(roles == {1280: ["—"], 2560: ["not recorded"]}, f"G-40: bar_row() draws Role '—' / 'not recorded' {roles}")
    sel = audit_row(ROWS[4], cl, px=1280, name="row-05", selected=True)
    cell = find(sel, "expander")
    check([x.get("icon") for _p, x in k.walk(cell) if x["t"] == "icon"] == ["check", "chevron-right"]
          and "aria-selected='true'" in sel["note"], "G-38: the selected row's check leads the expander's chevron")
    pg = pager("first")
    order = [nm for nm in names(pg) if nm.startswith(("CMP-001 Button (composition) · ", "reason · "))]
    lock = find(find(pg, "reason · admin.newest"), "lock")
    check(order == ["CMP-001 Button (composition) · Newest (T2)", "CMP-001 Button (composition) · Newer (T2)",
                    "reason · admin.newest", "CMP-001 Button (composition) · Older"]
          and "decorative" in lock.get("note", ""), f"G-41: the pager's notice right after Newer, its lock decorative "
                                                    f"{order}")
    check(append_only()["color"] == TEXT_3, "G-42: audit.append_only binds color.text.tertiary (§15 L742)")
    ov = modal(1280, engage_dialog(count=None))[0]
    kinds = [x["name"] for x in ov["kids"]]
    check(kinds[0] == "scrim" and ov["kids"][0]["o"]["fill"] == SCRIM and kinds[-2:] == [
        "CMP-074 EnvBanner (composition) · LIVE · above the scrim",
        "CMP-075 EnvBadgeLocal (composition) · LIVE · above the scrim"],
          f"G-31, G-43: modal() draws the scrim, the dialog, then both ENV badges above them {kinds}")
    try:
        scrim(10, 10, theme="light")
        light = False
    except ValueError:
        light = True
    check(light, "G-43: scrim() refuses a light frame (no light binding is black)")
    check([e.code for e in ROWS[:3:2]] == ["security.key_policy_violation", "backup.downloaded"]
          and [e.severity for e in ROWS[:3:2]] == ["critical", "error"] and ROWS[4].code == RECORD["code"]
          and len(page_rows(1280)) == PAGE_ROWS,
          "G-44: ROWS, AL-2's page: the two named high rows (§1 L143-146), record 1,204,118 at row 05 (AD-1 L342), "
          "200 rows")
    ct = count_text("c", copy("dlg.positions", n=2))
    check([x["typo"] for _p, x in k.walk(ct) if x["t"] == "text"] == [BODY, NUM_BASE], "G-45: counts in type.num.base")
    st = {f.key: ff2_state(f) for f in FLAGS}
    acts = {key: [x["chars"] for _p, x in k.walk(flag_actions(FLAG[key], st[key])) if x["t"] == "text"]
            for key in ("trading.live_enabled", "maintenance.mode")}
    check(st["trading.live_enabled"].deployment == "ON" and not any(s_.reload for s_ in st.values())
          and ff2_state(FLAG["engine.webgl_v2"], reload=True).reload
          and all(label("history") in v for v in acts.values()) and "elided" in fold(10, "x")["note"],
          "G-46: the live row ON, Reload now only when asked (board 39), History on every row, folds 'elided'")
    rl = export_line(1280, "limited")
    check({"ready", "download refusal · 429", "trust", "T2 · Download"} <= set(names(rl)),
          "G-47: export_line('limited') keeps AL-22's ready flow, its Download T2, the 429 line and the trust note")
    sk = skeleton()
    check(set(sk["props"]) == {"Shape", "Count"}, "G-48: CMP-015 instances take Shape and Count only")
    ec = export_control("not_built")
    check(ec["name"].startswith(TRIGGER) and "marker" in [x["name"] for x in ec["kids"]],
          "G-48: export_control() keeps CMP-093's marker under the T2 control")
    ff = filter_field("from", "From", None, w=150, picker=False)
    check(find(ff, "input")["o"]["justify"] == "end", "G-48: an empty filter well keeps 'UTC' at its right end")
    ms = maint_status("on")
    used = sum(round(k.est_width(x)) for x in ms["kids"]) + PX[INSET_SM] * (len(ms["kids"]) - 1)
    check(used <= 640, f"G-48: maint_status()'s row fits the 640 px column ({used} px)")
    fr = shell(1280, "SCR-145", meta=skeleton("text", 1, w=240))
    check(find(find(fr, "titles"), "meta")["t"] == "inst", "G-48: shell() takes a meta node (board 38's CMP-015)")
    wf = why_field(focused=True)
    check(wf["name"] == "CMP-040 FormField (composition) · Why?" and wf["w"] == 592,
          "G-48: Why? is CMP-040 over a two-line CMP-007, its focused well inside the 592 px column")
    eng = engage_dialog(count=None)
    wait_ok = all(any(nm.endswith("(disabled)") for nm in names(x)) and not any(
        nm.endswith("(loading)") or "(T2)" in nm for nm in names(x)) for x in (eng, maint_on_dialog(count=None)))
    check(wait_ok, "D22, R-2: a confirm waiting on the count read is natively disabled, never busy or T2")
    conf = find(engage_dialog(count=2), f"CMP-001 Button (composition) · {label('turn_on')}")
    check(conf["o"].get("fill") == DANGER_DEFAULT and find(conf, "label")["color"] == TEXT_ON
          and "stroke" not in conf["o"], "R-2: the danger confirm is CMP-001 danger (text.on-action on "
          "danger.default, no danger.strong border)")
    cf = flag_dialog(FLAG["rules.graph_editor"], state="conflict", conflict={"value": None, "user": None,
                                                                            "hh:mm:ss": None})
    check(any(nm.endswith("(form validity)") for nm in names(cf)) and not any("(T2)" in nm for nm in names(cf)),
          "G-4: FF-10's confirm in the form-validity form, described by dlg.conflict_first")
    t2s = ticket_submit_t2()
    check(find(t2s, "reason")["chars"] == "Order entry is paused for maintenance." and len(
        maintenance_banners(1280, exchange=True)) == 2, "G-39: one banner per cause and the ticket's T2 submit")
    check("C-row" in DEVIATIONS["chrome"] and "E10-D02 owns the shell chrome" in DEVIATIONS["chrome"],
          "G-30: the chrome note names E10-D02's ownership and the C-row to the owner")


def _instrument() -> None:
    """Record every string the decks return (this kit's copy / label / flag_body and e42kit's copy / label) in
    EMITTED: in-process only, for the self-test's invention check."""
    def wrap(fn: Any) -> Any:
        """fn, recording what it returns."""
        def inner(*a: Any, **kw: Any) -> Any:
            """The wrapped call."""
            out = fn(*a, **kw)
            EMITTED.add(out)
            return out
        return inner
    g = globals()
    g["copy"], g["label"], g["flag_body"] = wrap(_copy0), wrap(_label0), wrap(_body0)
    k.copy, k.label = wrap(k.copy), wrap(k.label)


def _invented(nodes: Iterable[Node]) -> list[str]:
    """Text in nodes that no deck returned and no worked-example datum gives (a rich() run is a substring)."""
    data = {str(v) for v in SAMPLE.values() if isinstance(v, (str, int))} | {"alex", "bea", "carol", "basiltt", "LIVE",
                                                                             "DEMO", "◆", "→", "ON", "OFF"}
    for e in (*ENTRIES, *ROWS_AFTER_BREAK):
        data |= {x for x in (e.code, e.actor, e.target, e.env, e.ip) if x} | set((e.ts or "").split())
    data |= {lab for lab, _w in ACTIONS.values() if lab} | {f.key for f in FLAGS} | {f.desc for f in FLAGS}
    for r in MOTION.values():
        data |= {r.id, plain(r.transition), plain(r.safe), plain(r.reduce), plain(r.carrier), plain(r.source)}
    corpus = [_ws(x) for x in EMITTED | data if isinstance(x, str)]
    bad = []
    for n in nodes:
        for _p, x in k.walk(n):
            if x["t"] == "text" and not any(_ws(x["chars"]) in c for c in corpus):
                bad.append(x["chars"])
    return bad


def _exercise() -> Node:
    """A kit-exercise block beside the AL-2 frames: every other builder once (spec strings only; unknown values
    bars)."""
    w = 660
    rec_diff = diff_full([Field("value", "changed", Val("value", "OFF"), Val("value", "ON")),
                          Field(SAMPLE["nested_path"], "added", None, Val("value"))], unchanged=1,
                         w=DRAWER_W[1280] - 32)
    c1 = [incident_banner(1280, w=w, steps_open=True, focus="copy"), export_line(1280, "running", w=w),
          export_line(1280, "ready", w=w, focus="Copy"), export_line(1280, "failed", code="signing_unavailable", w=w),
          export_line(1280, "limited", w=w, hhmm=None),
          tamper_footer("range_passed", run="busy", w=w, **{"from": None, "to": None, "hhmm": None}),
          tamper_footer("limited", run="rate_limited", w=w, hhmm=None), pager("end"), pager("limited"),
          new_pill(None), new_pill(1), new_pill(250), filter_bar(1280, view="own", w=w),
          filter_bar(1280, blocked=True, w=w),
          filter_bar(1280, errors={"from": "audit.err_range", "ip": "audit.err_ip"}, w=w),
          t2_sentence(copy("rec.raw_flagged"), w=w), _sheet_section("severity", [severity_strip(x) for x in SEVERITY])]
    c2 = [record_drawer(1280, diff=rec_diff, raw="open", integrity="verified", h=None),
          record_drawer(1280, projected=True, raw="owner_only", integrity="after_break", prev="t2", h=None),
          export_dialog(state="starting"), export_dialog(state="invalid"), export_dialog(state="rate_limited"),
          scr006(summary=label("action_summary"))]
    c3 = [flag_dialog(FLAG["rules.graph_editor"], to="ON", overrides=1, yours="ON"),
          flag_dialog(FLAG["desktop.backend_connection"], to="OFF", state="conflict",
                      conflict={"value": None, "user": None, "hh:mm:ss": None}),
          engage_dialog(count=None), release_dialog(), maint_on_dialog(state="turning_on"), maint_off_dialog(),
          *maint_content("on", w=w), maint_banner(1280, "fail_closed", w=w), read_only_banner(1280, w=w),
          flags_store_banner(1280, w=w),
          vbox("flag rows", flag_groups(1280, w=w, show=["trading.live_enabled", "rules.graph_editor",
                                                         "maintenance.mode", "engine.webgl_v2", "algo.twap"]),
               {"gap": STACK_MD}),
          flag_history([history_row("failure", [text("head", copy("diff.head_failed", reason="credential_in_reason"),
                                                     BODY_STRONG, TEXT_1),
                                                diff_inline("value", "OFF", "ON", requested=True)]),
                        history_row("no_outcome", [diff_inline("value", "OFF", "ON", requested=True)])], w=w),
          motion_card("M1"), motion_card("M5", "reduce"), *diff_sheet(w)[1:3]]
    cl = list(audit_cols(1280, w))  # the boards-PR carries' helpers (G-30..G-48), each once
    c4 = [audit_grid(entry_rows(1280, cl, selected=5, expanded=3)[:6], cl, name="CMP-049 grid region · selected row"),
          export_control("running"), export_control("not_built"),
          export_line(1280, "running", pct_served=False, w=w), export_line(1280, "download_failed", w=w),
          tamper_footer("page_partial_own", run="owner_only", w=w), tamper_footer("none", w=w),
          *maintenance_banners(1280, exchange=True, w=w), ticket_submit_t2(),
          grace_line("flags"), step_up_line("audit", grace=134),
          validity_button(label("turn_on"), "dlg.conflict_first"),
          flag_dialog(FLAG["rules.graph_editor"], to="ON", overrides=None, state="store_down"),
          maint_on_dialog(count=None), engage_dialog("ingestion"),
          vbox("MM-8 repair", maint_content("unreadable", control="repair", w=w), {"gap": STACK_MD}, w=w),
          vbox("MM-8 fail-closed", maint_content("fail_closed", control="t2", w=w), {"gap": STACK_MD}, w=w)]
    cols = [vbox(f"column-{i}", c, {"gap": STACK_LG}, w=w) for i, c in enumerate((c1, c2, c3, c4), 1)]
    return hbox("kit exercise", cols, {"gap": INSET_LG, "align": "start"})


def _token_table() -> dict[str, set[tuple[str, str]]]:
    """token-sync.json as {name: {(set, type)}}."""
    table: dict[str, set[tuple[str, str]]] = {}
    for st, n, ty, _v in json.loads(TOKENS_FILE.read_text()):
        table.setdefault(n, set()).add((st, ty))
    return table


def selftest() -> int:
    """Check the kit against the spec, the docs it quotes and token-sync.json; build board 02's AL-2 frame at both
    sizes (with a kit-exercise block beside it), write 00-selftest.json, validate it and check the output. 0 = pass."""
    fails: list[str] = []

    def check(ok: bool, what: str) -> None:
        """Print PASS or FAIL for one check and remember failures."""
        print(("PASS " if ok else "FAIL ") + what)
        if not ok:
            fails.append(what)

    reset_notes()
    md5 = hashlib.md5(SPEC.read_bytes()).hexdigest()
    print(("PASS " if md5 == SPEC_MD5 else "WARN ") + f"spec {md5[:8]} (L-numbers hold at {SPEC_MD5[:8]}, R-2 on the "
          f"board-cap restatement; read at the fold {SPEC_MD5_FOLD[:8]}; a WARN means re-run the line checks below)")
    table = _token_table()
    pat = r"(color|type|space|size|radius|elevation|opacity|border)\.[a-z0-9.\-]+"
    names = {v for kk, v in globals().items() if kk.isupper() and isinstance(v, str) and re.fullmatch(pat, v)}
    names |= {t for t in (TONES[x][0] for x in TONES)} | {TONES[x][2] for x in TONES} | {k.CANVAS, k.SCRIM,
                                                                                         k.FIELD_EDGE}
    missing = sorted(n for n in names if n not in table)
    check(not missing, f"all {len(names)} kit tokens exist in token-sync.json {missing or ''}")
    prims = sorted(n for n in names if n.startswith(("color.", "type.")) and {x for x, _ in table.get(n, set())} ==
                   {"primitives"})
    check(not prims, f"colour and typography tokens are semantic {prims or ''}")
    check("font.weight.semibold" in table and "motion.duration.normal" not in table,
          "font.weight.semibold exists (a primitive, not bindable on a text: FALLBACKS) and the motion tokens are "
          "code-only (§13 L647-648)")
    _spec_checks(check)
    reset_notes()
    _kit_checks(check)
    reset_notes()
    _instrument()
    reason("admin.live_gate")
    for kk in COPY:
        if kk.startswith("admin."):
            reason(kk)  # every T2 reason ≤ 60 characters with its full stop (raises otherwise)
    check(True, "every admin.* reason is one sentence of ≤ 60 characters (§14 L711; E09-D09 §3.1)")
    reset_notes()
    frames = [audit_page(px) for px in (1280, 2560)]
    exercise = _exercise()
    bad = _invented(frames)
    check(not bad, f"AL-2 frames: every text is a deck string or worked-example datum {bad[:5] or ''}")
    bad = _invented([exercise])
    check(not bad, f"exercise block: every text is a deck string or worked-example datum {bad[:5] or ''}")
    texts = [x["chars"] for f in frames[:1] for _p, x in k.walk(f) if x["t"] == "text"]
    need = [label("route.audit"), copy("audit.marker"), copy("audit.caption"), copy("tamper.page_passed"),
            copy("audit.append_only"), copy("admin.newest"), copy("admin.export_not_built"), label("signed_export"),
            label("newest"), label("newer"), label("older"), copy("audit.result_started"), copy("audit.result_intent"),
            label("sev.critical"), label("sev.error"), copy("strip.none"), copy("footer.area_entered")]
    gone = [n for n in need if n not in texts]
    check(not gone, f"frame-1280 draws AL-2's strings (L266) {gone or ''}")
    rules = [x for f in frames for _p, x in k.walk(f) if x["name"] == "high rule"]
    check(len(rules) == 4, f"AL-2's two high rows carry the 2 px rule in each frame ({len(rules)} of 4)")
    ann = annotations(0, {
        "source": SOURCE["SCR-135"],
        "state": "AL-2 populated, page checked (L266): chain_verified true; footer tamper.page_passed; on page 1 "
                 "Newest and Newer T2 admin.newest; one Started verify row, one Intent flag row",
        "decisions": "D2 severity words and the high rule, D3 outcome words, D4 keyset paging, D6 fixed order, D8 "
                     "reading recorded, D9 no mutation affordance, D12 export T2, D17 role not recorded",
        "roles": "Owner: everything; a Manager sees 'My activity' (AL-25); Viewer 403 (L305-307)",
        "keyboard": "Signed export → filters → the grid (one tab stop, roving) → paging → Run tamper check (L295-304)",
        "announcement": "none (AL-2)",
        "events": "admin.audit_read on the filter set's first read (D8; the marker line)",
        "Kit": "e42d04kit.py self-test, not a spec board: AL-2 at both sizes and a kit-exercise block",
    }, title_="00 kit self-test · SCR-135 AL-2 populated, page checked (both sizes) + kit exercise")
    secs = sections_for_board(frames, ann, extra=[exercise])
    big = max(len(json.dumps(x)) for x in secs)
    check(big <= SECTION_BUDGET, f"{len(secs)} sections, the largest {big} bytes (budget {SECTION_BUDGET})")
    w, h = root_size([*frames, exercise], ann)
    b = {"name": k.penpot_name(f"{PAGE} / 00 kit/selftest · {BOTH} · dark"), "w": w, "h": h, "x": 0,
         "y": -2 * PITCH_Y, "o": dict(k.ROOT_O)}  # above the grid's first row, clear of boards 01-05
    out = KIT_DIR / "00-selftest.json"
    try:
        check(True, "validator: " + write_sheet(out, b, secs, {"sources": ["e42d04kit.py self-test (not a board)"],
                                                               "spec_gaps": SPEC_GAPS},
                                                export=f"docs/design/E42/img/{PAGE}-00-selftest.png"))
    except RuntimeError as exc:
        print(exc)
        check(False, "validator exit 0")
        return 1
    sheet = json.loads(out.read_text(encoding="utf-8"))
    insts = [x for sec in sheet["sections"] for _p, x in k.walk(sec["node"]) if x["t"] == "inst"]
    check(bool(insts) and all(k._inst_check(x) in sheet["notes"]["live_checks"] for x in insts),
          f"{len(insts)} inst nodes listed in notes.live_checks")
    fr = [x["node"] for x in sheet["sections"] if x["into"] == "" and x["node"]["name"].startswith("frame-")]
    check([(f["w"], f["h"]) for f in fr] == [(1280, 800), (2560, 1440)], "frames 1280 × 800 and 2560 × 1440 at 1:1")
    bad = [x["into"] for x in sheet["sections"] if x["into"] and not x["into"].startswith(("frame-1280", "frame-2560",
                                                                                           "kit exercise",
                                                                                           "annotations"))]
    check(not bad, f"every section's into path starts at a root node {bad[:3] or ''}")
    check(not [ln for ln in sheet["notes"]["fallbacks"] if "E42-D03" not in ln and "§" in ln and "L" not in ln],
          "fallback lines carry their own line references")
    print(f"{out}: {'OK' if not fails else str(len(fails)) + ' failed'} ({len(sheet['sections'])} sections, "
          f"{len(json.dumps(sheet))} bytes; BOARDS {len(BOARDS)})")
    return 1 if fails else 0


if __name__ == "__main__":
    if sys.argv[1:] == ["selftest"]:
        sys.exit(selftest())
    print(__doc__)
    sys.exit(2)

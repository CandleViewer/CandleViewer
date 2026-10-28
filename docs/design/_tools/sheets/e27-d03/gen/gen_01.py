"""E27-D03 / 01 cmp-175-key-states (dark): frame 2 (the aggregate verdict line, all eight forms) plus the
CMP-175 key-scope variant set (badge and inline, both densities), the CMP-011 row chips of CMP-176's state slot and
CMP-034. gen_02 imports cells() for the light twin. Offline; stdlib only."""

from __future__ import annotations

import sys
from pathlib import Path

sys.dont_write_bytecode = True
KIT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT_DIR))
import e27d03kit as k

F2 = "Pattern / withdrawal verdict: dated, overdue, failed, unavailable, no keys"
DOC_IN = k.DOC_W - 2 * 24  # the doc frame's inner width (space.inset.xl padding)
SPEC_W = 1232  # the specimen cards' width (inner 1200)

# §2.1 L380-393: the form, its fills and the CMP-092 blocking row above a negated form (D02:212-230).
FORMS = (
    ("dated", {"n": 4, "hh_mm": "14:02"}, None),
    ("overdue", {"hh_mm": "13:47"}, "e27.shell.banner.key_stale"),
    ("failed", {}, "e27.shell.banner.key_failed"),
    ("unavailable", {}, "e27.shell.banner.key_unchecked"),
    ("read failed", {}, None),
    ("no keys", {}, None),
    ("loading", {}, None),
    ("cleared", {"n": 4, "hh_mm": "14:17"}, None),
)

# The thirteen variants (§2.1 L306-320) with their fills; the fixture times and day counts.
VFILLS = {"verified": {"hh_mm": "14:02"}, "expiring": {"n": 7}, "check overdue": {"hh_mm": "13:47"}}
NEVER_INLINE = (
    "withdrawal-detected (critical)",
)  # §2.1 L373-375: the critical state is always the badge
NEVER_BADGE = (
    "read-only (import)",
)  # §2.1 L310: CMP-027's refusal line on import, never a stored badge
ALLOWLIST = ("allowlist matches", "IP-mismatch", "IP-missing", "allowlist not checked")

# CMP-176's CMP-011 words (§2.2 L509-525), in the slot's precedence.
CHIP_WORDS = (
    ("Key refused by Bybit", {}),
    ("Down — order entry off for this account", {}),
    ("Off by policy", {}),
    ("Rotation overdue", {}),
    ("Degraded — REST only", {}),
    ("Rotation due in {n} d", {"n": 12}),
    ("No key — inactive", {}),
    ("Disabled", {}),
    ("OK", {}),
)


def _label(chars: str) -> k.Node:
    """A row label inside a card: a word the pinned spec writes (say), type.ui.caption color.text.secondary."""
    return k.text("row label", k.say(chars), k.CAPTION, k.TEXT_2)


def _row(name: str, kids: list[k.Node], w: int = SPEC_W - 32) -> k.Node:
    return k.hbox(name, kids, {"gap": k.INSET_SM, "wrap": "wrap", "align": "center"}, w=w)


def frame2() -> dict:
    """§2.6 L941: CMP-175 aggregate in its eight forms, each one 32 px line on color.surface.app under the h1; each
    negated form under CMP-092's blocking row with the server's sentence; loading a static skeleton, never OFF.
    """
    kids = []
    for form, fills, ban in FORMS:
        parts = [_label(form)]
        if ban:
            parts.append(k.banner(ban, w=DOC_IN - 32))
        parts.append(k.verdict_line(form, w=DOC_IN - 32, **fills))
        kids.append(
            k.vbox(
                f"form · {form}",
                parts,
                {"fill": k.APP, "pad": k.INSET_LG, "gap": k.STACK_SM, "radius": k.R_CARD},
                w=DOC_IN,
            )
        )
    return {"kids": kids}


def variant_set() -> k.Node:
    """The CMP-175 key scope (§2.1 L306-320, L370-378, L425-440): every variant as the badge at comfortable and
    at compact, as the inline form, and the four allowlist words with the lead dropped under a facet header.
    """
    rows = []
    for dn in ("comfortable", "compact"):
        with k.density(dn):
            badges = [
                k.cmp175(v, "badge", **VFILLS.get(v, {})) for v in k.CMP175 if v not in NEVER_BADGE
            ]
        rows.append(
            k.vbox(f"badges · {dn}", [_label(dn), _row("badges", badges)], {"gap": k.STACK_XS})
        )
    inline = [k.cmp175(v, "inline", **VFILLS.get(v, {})) for v in k.CMP175 if v not in NEVER_INLINE]
    rows.append(
        k.vbox("inline", [_label("inline"), _row("inline forms", inline)], {"gap": k.STACK_XS})
    )
    lead = [k.cmp175(v, "inline", lead=False) for v in ALLOWLIST]
    rows.append(
        k.vbox(
            "under the facet header",
            [
                k.text("header", k.say("IP allowlist"), k.LABEL, k.TEXT_2),
                _row("lead dropped", lead),
            ],
            {"gap": k.STACK_XS},
        )
    )
    return k.specimen(
        "CMP-175 key scope · the thirteen variants (badge, inline; comfortable, compact)",
        rows,
        w=SPEC_W,
        proposed=["HD1", "HD2", "BQ-5", "BQ-6", "D03-C3"],
        notes=[
            (
                "read-only (import) is CMP-027's refusal line on SCR-126, SCR-127 stage 3 and SCR-016 "
                "step 3, never a stored badge: drawn inline only (§2.1 L310)"
            ),
            "withdrawal-detected is never the inline form: drawn as the badge only (§2.1 L373-375)",
            "read-only (stored) is specified at component level only, no screen frame (D03-C3)",
        ],
    )


def row_chips() -> k.Node:
    """CMP-176's state slot (§2.2 L499-525): the CMP-011 chips, every non-key-verification word with its tone and
    glyph, at comfortable and at compact."""
    rows = []
    for dn in ("comfortable", "compact"):
        with k.density(dn):
            chips = [k.state_badge(w, **f) for w, f in CHIP_WORDS]
        rows.append(
            k.vbox(f"chips · {dn}", [_label(dn), _row("chips", chips)], {"gap": k.STACK_XS})
        )
    sp = k.specimen(
        "CMP-011 row chips · CMP-176's state slot",
        rows,
        w=SPEC_W,
        proposed=["HD3", "HD4"],
        notes=['CMP-011 has no success tone: "OK" is neutral with the check (§2.2 L527-528)'],
    )
    # specimen() takes no strips=: the G-12 strip goes on the cell's annotation layer by hand (board chrome, never
    # inside the specimen card); the board's Notes repeat it because the column lists frame strips only.
    layer = next(c for c in sp["kids"] if c["name"] == "annotation layer")
    layer["kids"].insert(0, k.not_served("G-12, #3657", '"Off by policy" (BQ-7), a target state'))
    return sp


def masked() -> k.Node:
    """CMP-034 MaskedValue, permanently masked (§2.3, BQ-8, HD5): text only, type.num.base, no box or control."""
    ids = [k.masked_id(i) for i in ("...a1b2", "...c3d4", "...e5f6")]
    return k.specimen(
        "CMP-034 MaskedValue · masked is its only state",
        [_row("masked ids", ids, w=400)],
        w=432,
        proposed=["HD5", "BQ-8"],
        notes=[
            (
                "its description is in the DOM at mount (e27.cmp034.description, §12.1 L2450); "
                "masked only: no toggle, no timer, no copy control (BQ-8)"
            )
        ],
    )


def cells() -> list[k.Node]:
    return [
        k.frame(
            F2,
            frame2,
            proposed=["HD1", "HD2"],
            notes=[
                "the cleared form announces once, politely, the server's notice e27.shell.banner.cleared",
                "the line reads the server's notices and computes no verdict of its own (D02:212-230)",
            ],
        ),
        variant_set(),
        row_chips(),
        masked(),
    ]


NOT_DRAWN = [
    (
        "the greyscale, deuteranopia and protanopia strips are the board's three cvd_sim.py renders at export "
        "(BQ-16, §9 L1756-1759), not hand-drawn colours: tokens bind by name only"
    )
]
NOTES = [
    'not yet served — G-12, #3657: the CMP-011 "Off by policy" chip (row chips cell; BQ-7)',
    (
        "light twin: board 02 (semantic-light; in light the octagon and the clock share one colour, so the shape "
        "and the words carry them, BQ-6)"
    ),
]
CHECKS = [
    "frame 2 draws the eight aggregate forms of §2.1 L386-393 from the deck (e27.scr125.verdict.*)",
    "the three negated forms sit under CMP-092's blocking row (key_stale, key_failed, key_unchecked)",
    "loading is a static skeleton with its words, never OFF",
    "the thirteen CMP-175 variants with their deck words; one glyph per class; the critical alone bold + 2 px",
    "the nine CMP-011 words of CMP-176's slot with their tones and glyphs",
    "CMP-034 is text only (type.num.base), fixture key ids",
]
LIVE = [
    "export -greyscale, -deuteranopia and -protanopia renders through docs/design/_tools/cvd_sim.py (BQ-16)"
]


def build(nn: int, cs: list[k.Node]) -> None:
    bd = k.board(
        nn,
        cs,
        source="E27-D03 §0 L218-219, §2.1 L295-464, §2.2 L496-528, §2.6 L941",
        cols=1,
        notes=NOTES,
        not_drawn=NOT_DRAWN,
    )
    path = k.KIT_DIR / f"{k.stem(nn)}.json"
    print(k.write_sheet(path, bd))
    print(k.compact_sheet(path))
    print(k.write_board_md(nn, bd, checks=CHECKS, live=LIVE))


if __name__ == "__main__":
    build(1, cells())

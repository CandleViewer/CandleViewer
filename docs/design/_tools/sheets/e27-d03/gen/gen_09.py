"""E27-D03 / 09 scr-079-drawer (dark): frames 62-71, SCR-079's drawer on SCR-010's compact host (§8 L1481-1565),
plus the one comfortable inset of `SCR-079 / healthy (owner)` (BQ-4) as a specimen cell.

Run: python3 -I -B gen/gen_09.py  (writes 09-scr-079-drawer.json / .md and the compacted copy in v4/).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.dont_write_bytecode = True
KIT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT_DIR))
import e27d03kit as k

NN = 9
L, ENV, KEY = "sub_001", "LIVE", "...c3d4"
BAL = (
    "51,234.91",
    "50,120.00",
    "41,000.25",
    "+1,114.91",
    "18.21",
    "+212.40",
    "4.10",
)  # E27-D02 §5.6 (D02:774-778)
RATE = (False, False, False, False, True, False, True)  # the two margin rates read in %


def iw() -> int:
    return k.DRAWER_W - 2 * k.PX[k.INSET_MD] - 8


def h2() -> str:
    return k.copy("e27.scr079.h2", label=L, ENV=ENV, kind=k.say("Sub-account"))


def h3(key: str, i: int = 0) -> Any:
    return k.text("h3", k.copy(key, i) if i else k.copy(key), k.HEADING_SM, k.TEXT_1)


# --- Blocks.
def balances(*, stale: bool = False) -> Any:
    """The caption (or the CMP-239 stale chip) and the two-column dl of CMP-036 rows (§8 Balances)."""
    if stale:
        cap = k.hbox(
            "CMP-239 chip · stale",
            [
                k.glyph("clock", "color.data-confidence.stale.indicator"),
                k.text(
                    "word",
                    k.copy("e27.scr079.stale", hh_mm_ss="10:31:11"),
                    k.CAPTION,
                    "color.data-confidence.stale.text",
                ),
            ],
            {
                "fill": "color.data-confidence.stale.surface",
                "radius": k.R_BADGE,
                "padX": k.INSET_SM,
                "padY": k.INSET_XS,
                "gap": k.INSET_XS,
            },
            note="the stale transition is polite once " "(e27.scr079.announce.stale)",
        )
    else:
        cap = k.text(
            "caption · CMP-036 freshness",
            k.copy("e27.scr079.balances.caption", hh_mm_ss="10:31:01"),
            k.CAPTION,
            k.TEXT_2,
        )
    labels = k.copies("e27.scr079.balances.labels")
    col_w = (iw() - 16) // 2
    rows = []
    for i, (lab, val) in enumerate(zip(labels, BAL)):
        v = (
            k.copy("e27.scr079.balances.units", 1, rate=val)
            if RATE[i]
            else k.copy("e27.scr079.balances.units", 0, amount=val)
        )
        rows.append(
            k.hbox(
                f"CMP-036 row · {lab}",
                [
                    k.text("term", lab, k.LABEL, k.TEXT_2, w=118),
                    k.text("value", v, k.NUM_BASE, k.TEXT_1),
                ],
                {"gap": k.INSET_XS},
                w=col_w,
                h=k.dens().control,
            )
        )
    dl = k.hbox(
        "dl · two columns",
        [k.vbox("column 1", rows[0::2], w=col_w), k.vbox("column 2", rows[1::2], w=col_w)],
        {"gap": k.INSET_LG, "align": "start"},
        w=iw(),
    )
    return k.vbox("Balances", [cap, dl], {"gap": k.STACK_XS}, w=iw())


def gated(label: str, *, look: str = "secondary") -> Any:
    """A write inside CMP-079 RbacGate whose reason is the drawer's one notice (aria-describedby points at it)."""
    return k.hbox(
        f"T2 · CMP-079 RbacGate · {label}",
        [k.button(label, look, "t2")],
        note="aria-describedby the drawer's one notice (BQ-9: one notice, many pointers)",
    )


def leverage(*, reason_key: str | None = None, via_notice: bool = False, **fills: Any) -> Any:
    lab = k.copy("e27.scr079.leverage")
    if via_notice:
        ctl = gated(lab)
    elif reason_key:
        ctl = k.t2_button(lab, reason_key, w=iw(), **fills)
    else:
        ctl = k.button(lab, "secondary")
    line = k.text(
        "line",
        k.copy("e27.scr079.positions.line", symbol="BTCUSDT", side="long", qty="0.250", n=10),
        k.NUM_BASE,
        k.TEXT_1,
    )
    return k.vbox(
        "Positions and leverage",
        [h3("e27.scr079.positions.h3"), line, ctl],
        {"gap": k.STACK_XS},
        w=iw(),
    )


def segmented(title: str, opts: list[str], selected: int) -> Any:
    """CMP-003 under CMP-079, T2 per §10.1: each segment keeps its role and full label, the lock leads it; the
    selected one keeps its check glyph and aria-checked."""
    segs = [
        k.hbox(
            f"T2 · segment · {o}",
            [
                k.lock(),
                k.glyph("check", k.TEXT_3) if i == selected else None,
                k.text("label", o, k.BODY, k.TEXT_3),
            ],
            {**k.T2_SHAPE, "padX": k.INSET_SM, "gap": k.INSET_XS, "radius": k.R_CONTROL},
            h=k.dens().control,
            note='aria-checked="true"' if i == selected else 'aria-disabled="true"',
        )
        for i, o in enumerate(opts)
    ]
    k._choice("t2")
    return k.vbox(
        f"CMP-003 · {title}",
        [k.text("label", title, k.LABEL, k.TEXT_2), k.hbox("segments", segs)],
        {"gap": k.STACK_XS},
    )


def settings(reason_key: str | None, **fills: Any) -> Any:
    """Account settings: the two mode controls, T2, and the reason under the pair (or the one notice's pointer)."""
    s = k.copies("e27.scr079.settings")
    pair = k.hbox(
        "modes",
        [segmented(s[1], [s[2], s[3]], 0), segmented(s[4], [s[5], s[6]], 0)],
        {"gap": k.INSET_LG, "align": "start"},
    )
    kids = [
        k.text("h3", s[0], k.HEADING_SM, k.TEXT_1),
        pair,
        k.t2_reason(k.reason(reason_key, **fills), w=iw()) if reason_key else None,
    ]
    return k.vbox("Account settings", kids, {"gap": k.STACK_XS}, w=iw())


def stmt(kind: str, colour: str, chars: str) -> Any:
    return k.hbox(
        f"statement · {chars[:24]}",
        [k.glyph(kind, colour), k.text("words", chars, k.BODY, k.TEXT_1, w=iw() - 20)],
        {"gap": k.INSET_XS, "align": "start"},
    )


OK_C, WARN_C, DANGER_C = (
    k.STATUS["success.strong"],
    k.STATUS["warning.strong"],
    k.STATUS["danger.strong"],
)


def health() -> Any:
    return k.hbox(
        "CMP-178 inline",
        [
            k.glyph("check", OK_C),
            k.text("words", k.copy("e27.scr079.health", state="healthy", n=2), k.BODY, k.TEXT_1),
        ],
        {"gap": k.INSET_XS},
    )


def key_owner(*, line: list[Any] | None = None, statements: list[Any] | None = None) -> Any:
    """Key and health — the Owner: the key line (CMP-034 inside it), the statements, CMP-178, the rate budget."""
    st = k.copies("e27.scr079.key.statements", hh_mm="14:02")
    kl = (
        line
        if line is not None
        else [
            k.text(
                "key line",
                k.copy(
                    "e27.scr079.key.line", 1, key_id_masked=KEY, status="active", date="2027-01-09"
                ),
                k.NUM_BASE,
                k.TEXT_1,
                w=iw(),
            )
        ]
    )
    sts = statements if statements is not None else [stmt("check", OK_C, x) for x in st]
    ul = k.vbox(
        "ul · statements",
        sts,
        {"gap": k.STACK_XS},
        note="a ul of plain statements (G-1 target state)",
    )
    rb = k.text("rate budget", k.copy("e27.scr079.rate_budget", n=72), k.BODY, k.TEXT_1)
    return k.vbox(
        "Key and health",
        [h3("e27.scr079.key.h3"), *kl, ul, health(), rb],
        {"gap": k.STACK_XS},
        w=iw(),
    )


def key_other() -> Any:
    """Key and health — any other role: the status and the health in words, nothing else of the key."""
    return k.vbox(
        "Key and health",
        [
            h3("e27.scr079.key.h3"),
            k.text("status", k.copy("e27.scr079.key.status", status="active"), k.BODY, k.TEXT_1),
            health(),
        ],
        {"gap": k.STACK_XS},
        w=iw(),
    )


def profile() -> Any:
    """CMP-106 and the two bare CMP-021 links (the Owner only; T3 for every other role)."""
    p = k.text(
        "CMP-106 profile",
        k.copy("e27.scr079.profile", name="BTC scalp", n=10, pct=2, qty="0.5", coin="BTC"),
        k.BODY,
        k.TEXT_1,
        w=iw(),
    )
    links = k.hbox(
        "links",
        [
            k.text(f"CMP-021 link · {i}", x, k.BODY, k.TEXT_LINK)
            for i, x in enumerate(k.copies("e27.scr079.links"), 1)
        ],
        {"gap": k.INSET_LG},
    )
    return k.vbox("Profile and links", [p, links], {"gap": k.STACK_XS}, w=iw())


def info_notice(chars: str) -> Any:
    """The drawer's one CMP-028 notice, tone info, silent (BQ-9): §9 c175-info-word / c175-info-glyph."""
    return k.hbox(
        "CMP-028 notice · info · the drawer's one notice",
        [
            k.glyph("info", k.STATUS["info.strong"]),
            k.text("words", chars, k.BODY, k.TEXT_1, w=iw() - 44),
        ],
        {
            "fill": k.STATUS["info.subtle"],
            "radius": k.R_CARD,
            "pad": k.INSET_SM,
            "gap": k.INSET_XS,
            "align": "start",
        },
        w=iw(),
        note="no live role; a stable id every gated write points at",
    )


def settings_gated() -> Any:
    """The mode controls gated by the one notice (no reason line of their own)."""
    s = k.copies("e27.scr079.settings")
    pair = k.hbox(
        "modes",
        [segmented(s[1], [s[2], s[3]], 0), segmented(s[4], [s[5], s[6]], 0)],
        {"gap": k.INSET_LG, "align": "start"},
        note="aria-describedby the drawer's one notice",
    )
    return k.vbox(
        "Account settings",
        [k.text("h3", s[0], k.HEADING_SM, k.TEXT_1), pair],
        {"gap": k.STACK_XS},
        w=iw(),
    )


def drawer(blocks: list[Any], *, focus: bool = True) -> dict[str, Any]:
    return {"overlays": [k.drawer(h2(), blocks, close_focused=focus)]}


def owner_blocks(**kw: Any) -> list[Any]:
    return [
        balances(stale=kw.get("stale", False)),
        leverage(),
        settings("accounts.mode_locked"),
        key_owner(line=kw.get("line"), statements=kw.get("statements")),
        profile(),
    ]


# --- Frames 62-71 and the comfortable inset.
def f63() -> dict[str, Any]:
    line = [
        k.masked_id(KEY),
        stmt("triangle", WARN_C, k.copy("e27.scr079.expiring.rotation", n=12, date="2026-11-04")),
        k.cmp175("expiring", "inline", n=9),
    ]
    return drawer(owner_blocks(line=line))


def f64() -> dict[str, Any]:
    nt = k.notice(
        [k.reason("accounts.key_rejected")],
        tone="danger",
        w=iw(),
        name="CMP-028 notice · danger · the " "drawer's one notice",
    )
    nxt = k.text(
        "owner next step",
        k.copy("e27.scr079.notice.owner_next"),
        k.BODY,
        k.TEXT_1,
        w=iw(),
        note="no control points at this node",
    )
    return drawer([nt, nxt, balances(), leverage(via_notice=True), settings_gated(), profile()])


def f65() -> dict[str, Any]:
    st = k.copies("e27.scr079.key.statements", hh_mm="14:02")
    other = k.copies("e27.scr079.key.statements.other", hh_mm="14:02")
    fix = k.vbox(
        "remediation (CD-3 rule form)",
        [
            k.text(
                "rule",
                k.say(
                    "CandleViewer accepts this key only if its IP allowlist holds exactly 203.0.113.10. Set "
                    "it in Bybit's dashboard"
                ),
                k.BODY,
                k.TEXT_1,
                w=iw() - 20,
            ),
            k.button(k.copy("e27.shared.copy"), "secondary", name="CMP-033 CopyButton · egress IP"),
            k.text(
                "then",
                k.say("then test it again in Admin → Accounts. It can't be set from here."),
                k.BODY,
                k.TEXT_1,
                w=iw() - 20,
            ),
        ],
        {"gap": k.STACK_XS, "padL": k.INSET_LG},
    )
    sts = [
        stmt("check", OK_C, st[0]),
        stmt("check", OK_C, st[1]),
        stmt("octagon", DANGER_C, other[2]),
        fix,
    ]
    return drawer(owner_blocks(statements=sts))


def f66() -> dict[str, Any]:
    return drawer(owner_blocks(stale=True))


def f67() -> dict[str, Any]:
    return drawer(
        [
            balances(),
            leverage(),
            settings("rbac.owner_only", verb="change account settings"),
            key_other(),
        ]
    )


def f68() -> dict[str, Any]:
    return drawer(
        [
            leverage(reason_key="rbac.permission", verb="change positions"),
            settings("rbac.owner_only", verb="change account settings"),
            key_other(),
        ]
    )


def f69() -> dict[str, Any]:
    return drawer(
        [
            info_notice(k.reason("rbac.view_as", user="alex")),
            balances(),
            leverage(via_notice=True),
            settings_gated(),
            key_other(),
        ]
    )


def f70() -> dict[str, Any]:
    return drawer(
        [
            info_notice(k.reason("accounts.disabled")),
            balances(),
            leverage(via_notice=True),
            settings_gated(),
            key_owner(),
        ]
    )


def f71() -> dict[str, Any]:
    kb = k.vbox(
        "Key and health",
        [
            h3("e27.scr079.key.h3"),
            k.text("48 h line", k.copy("e27.shared.first_key_48h"), k.BODY, k.TEXT_1, w=iw()),
        ],
        {"gap": k.STACK_XS},
        w=iw(),
    )
    return drawer(
        [
            info_notice(k.reason("accounts.no_key")),
            balances(),
            leverage(via_notice=True),
            settings_gated(),
            kb,
        ]
    )


def inset() -> Any:
    """SCR-079 / healthy (owner) once more at comfortable (BQ-4, HD12): the drawer panel alone."""
    with k.density("comfortable"):
        layer = k.drawer(h2(), owner_blocks(), close_focused=True)
    panel = {kk: v for kk, v in layer["kids"][-1].items() if kk not in ("x", "y")}
    return k.specimen(
        "SCR-079 / healthy (owner) · the comfortable inset",
        [panel],
        proposed=["HD12"],
        notes=[
            (
                "the same frame at size.control.comfortable / size.row.comfortable; density changes "
                "the spacing and nothing else (16:125)"
            )
        ],
        w=k.DRAWER_W + 32,
    )


G1 = ("G-1, #895 / #896", "the rights and allowlist statements")


def cells() -> list[Any]:
    t = k.BOARDS[NN].frames
    return [
        k.frame(
            t[0],
            lambda: drawer(owner_blocks()),
            strips=[G1],
            proposed=["HD10"],
            notes=[
                "BTCUSDT is open, so both mode controls are T2 accounts.mode_locked; focus on [Close]"
            ],
        ),
        k.frame(
            t[1],
            f63,
            strips=[G1],
            notes=[
                (
                    "the two clocks on two lines, each led by the triangle; the other "
                    "roles see no expiring state"
                )
            ],
        ),
        k.frame(
            t[2],
            f64,
            notes=[
                (
                    "every role: the one notice, danger; announced assertively once (D21); the key "
                    "block is unchanged and not redrawn here"
                )
            ],
        ),
        k.frame(
            t[3],
            f65,
            strips=[G1, ("D03-G1, #896", "the egress IP and its Copy")],
            proposed=["HD14"],
            notes=[
                "a non-owner sees the served health and the shell's read-only banner (D02:823-824)"
            ],
        ),
        k.frame(
            t[4],
            f66,
            strips=[G1],
            notes=[
                (
                    "not yet served — G-11 (the spec names no owner; the kit's strip refuses it): the chip's suffix "
                    "e27.scr079.stale.sizing waits for a field"
                ),
                "every value at full contrast (C-10)",
            ],
        ),
        k.frame(t[5], f67, notes=["Manager with the trade grant; no profile links (T3)"]),
        k.frame(
            t[6],
            f68,
            notes=[
                (
                    "not yet served — OQ-6 (no gap id in the spec): the balance block is not drawn "
                    "until 24 defines masked balances; never an invented masking"
                )
            ],
        ),
        k.frame(
            t[7],
            f69,
            notes=[
                (
                    "the view-as leg first; a forced write is refused view_as_read_only (T4) and "
                    "recorded admin.view_as_refused"
                )
            ],
        ),
        k.frame(
            t[8],
            f70,
            strips=[G1],
            notes=[
                (
                    "suspended by a failed check: no field carries it; the drawer learns "
                    "it only from E30-D02's refusal after a press (T4, "
                    "e27.scr079.refused.policy)"
                )
            ],
        ),
        k.frame(t[9], f71, notes=["the Owner's drawer adds the untimed 48 h line (D16)"]),
        inset(),
    ]


def build() -> dict[str, Any]:
    return k.board(
        NN,
        cells(),
        source="E27-D03 §0 L226 (board 09); §8 L1481-1565 (anatomy L1495-1506, hi-fi rows "
        "L1539-1548); §10.1 T2; §12.1 deck",
        cols=4,
        notes=[
            (
                "balance figures, BTCUSDT long 0.250 · 10x and the profile are E27-D02 §5.6's wire values "
                "(D02:774-788)"
            ),
            (
                "the key line's due date 2027-01-09 UTC is sub_001's (D02:784, D03 L1381); frame 63 keeps "
                "the spec's own 2026-11-04 UTC (L1540)"
            ),
            ("the selected modes (One-way, Cross) are a kit choice; the hi-fi rows " "name none"),
        ],
    )


def main() -> int:
    bd = build()
    path = k.KIT_DIR / f"{k.stem(NN)}.json"
    print(k.write_sheet(path, bd))
    print(k.compact_sheet(path))
    print(
        k.write_board_md(
            NN,
            bd,
            checks=[
                "10 frames, names as E27-D02 §7, every one shows T2 (the lock leading each full label)",
                "the compact host plus one comfortable inset (a specimen cell, not an 11th frame)",
                "stale at full contrast: the CMP-239 chip, values color.text.primary",
            ],
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

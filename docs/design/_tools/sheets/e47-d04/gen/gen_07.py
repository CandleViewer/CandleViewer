"""E47-D04 / 07 full-page-form: SCR-110 with SCR-117 (the page sequence, the h1 on entry) and the Manager's view
(a T2 control in the order, a T3 item absent: SCR-121's Admin entry) (§4, §10)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import k, mark  # noqa: E402

NN = 7
F_SEQ, F_T2T3 = k.frames_of(NN)
L10 = k.L("## 10. RBAC and the accessibility tree")
# `14` SCR-110 (L2371): the section nav; SCR-110's checklist: "the admin area is linked only for owners"
SECTIONS = ("Profile", "Security", "Appearance", "Hotkeys", "Trading defaults", "Notifications", "Data & performance",
            "Accessibility", "Help & about")
# `14` SCR-117 Type line (L2468): the boolean options drawn as CMP-004 toggles; W-7 / W-8 for the focus-ring one
OPTIONS = ("Reduced motion", "Disable canvas animation", "Always show data-table alternatives", "W-7",
           "Keyboard-only mode")
NAV_W2, PANE_X = 208, 232
T2_REASON = "Only the owner can flatten every account."  # E39-D03 §10 S4 (E09-D09 rbac.owner_only)


def settings_page(*, admin_link: bool, h1_focus: bool) -> tuple[k.Node, dict[str, tuple[int, int]]]:
    """SCR-110 hosting SCR-117 inside main (984 x 728); returns the page and marker spots (frame coords)."""
    items = [k.hbox(f"nav · {s}", [k.text("label", s, k.BODY, k.TEXT_1)],
                    {"padX": k.INSET_SM, "radius": k.R_CONTROL, **({"fill": k.SELECTED} if s == "Accessibility"
                                                                    else {})}, w=NAV_W2 - 16, h=k.ROW_H,
                    note='aria-current="page"' if s == "Accessibility" else None) for s in SECTIONS]
    if admin_link:
        items.append(k.hbox("nav · Admin", [k.text("label", "Admin", k.BODY, k.TEXT_1)], {"padX": k.INSET_SM},
                            w=NAV_W2 - 16, h=k.ROW_H, note="Owner only (SCR-110 checklist)"))
    nav = k.vbox("section nav · navigation Settings", [k.text("label", "Settings", k.LABEL, k.TEXT_2), *items],
                 {"gap": k.STACK_XS, "pad": k.INSET_SM, "fill": k.RAISED}, w=NAV_W2, h=k.BODY_H,
                 note='a second navigation named "Settings" (§2)')
    h1 = k.text("h1", "Settings", k.HEADING_LG, k.TEXT_1, w=160)
    h1b = k.hbox("h1 box", [h1], None, w=160, h=28, note='h1 tabindex="-1": focused on route entry')
    rows = []
    for o in OPTIONS:
        if o == "W-7":
            rows.append(k.toggle_row(k.w("W-7"), k.w("W-8")))
        else:
            rows.append(k.hbox(f"toggle · {o}", [k.switch(), k.vbox("text", [k.text("label", o, k.BODY_STRONG,
                                                                                    k.TEXT_1),
                                                                             k.placeholder("description", 280, 10)],
                                                                    {"gap": k.STACK_XS})],
                               {"gap": k.INSET_MD, "align": "start"}, w=560, note='role="switch"'))
    pane = k.vbox("pane", [k.focus_ring(h1b) if h1_focus else h1b,
                           k.text("h2", "Accessibility", k.HEADING_MD, k.TEXT_1), *rows],
                  {"gap": k.STACK_LG}, w=600, x=PANE_X, y=24)
    page = k.box("page · SCR-110", [dict(nav, x=0, y=0), pane], {"fill": k.APP}, w=k.MAIN_W, h=k.BODY_H)
    x0, y0 = k.NAV_W, k.TOP_H
    spots = {"section nav": (x0 + NAV_W2 - 28, y0 + 8), "h1": (x0 + PANE_X - 28, y0 + 28)}
    yy = y0 + 24 + 28 + (12 if h1_focus else 0) + 16 + 19 + 16
    for i, r in enumerate(rows, 1):
        spots[f"option {i}"] = (x0 + PANE_X - 28, yy)
        yy += round(k.est_height(r)) + 16
    return page, spots


def frame_seq() -> tuple[k.Node, tuple[str, list[str]]]:
    page, sp = settings_page(admin_link=True, h1_focus=True)
    order = [("skip link", (440, 4)), ("banner · TopBar", "topbar"), ("navigation · NavRail", "navrail"),
             ("navigation · Settings", sp["section nav"]), ("h1 (programmatic only)", sp["h1"])]
    order += [(f"option {i}", sp[f"option {i}"]) for i in range(1, len(OPTIONS) + 1)]
    order += [("contentinfo · StatusBar", "statusbar")]
    ov = [mark(i, wh, name=f"seq {i:02d} · {lab}") for i, (lab, wh) in enumerate(order, 1)]
    ov.append(k.tag("Owner session · route /settings, section Accessibility", 640, 760 - 20))
    fr = k.page_window(F_SEQ, page, admin=True, overlays=ov, note="route entry: focus on the page h1")
    lines = [k.arch("Tab sequence", "full-page form"), k.arch("Initial target", "full-page form"),
             "Stops drawn: " + ", ".join(f"{i} {lab}" for i, (lab, _w) in enumerate(order, 1)),
             "The h1 takes focus on route entry (tabindex -1, not a Tab stop); W-7 and W-8 (§15, verbatim) label "
             "the shipped thick-ring preference; the other SCR-117 options are `14`:2468's, descriptions as "
             "placeholders",
             k.arch("Restore on exit", "full-page form"), k.arch("Announcements", "full-page form")]
    return fr, k.frame_block(F_SEQ, lines, keyboard="Tab from the skip link through 1-11; the ring keys jump "
                                                    "banner → navigation → main → contentinfo")


def frame_t2t3() -> tuple[k.Node, tuple[str, list[str]]]:
    page, sp = settings_page(admin_link=False, h1_focus=False)
    k.copy_gap(f'T2 reason "{T2_REASON}": E39-D03 §10 S4 (the global FLATTEN ALL for a Manager; E09-D09 '
               "rbac.owner_only)")
    t2 = k.t2_button(k.FLATTEN, T2_REASON, focused="normal", w_=260, name="FLATTEN ALL · T2")
    t2 = dict(t2, h=46)
    fx = k.flatten_x(t2)
    # live check fold: as a column the ruled reason was clipped 8 px by the 48 px TopBar; the ring and the reason sit
    # in a row (centred, gap 8) and the reason hugs (218 px), so the end-justified group is 364 px wide, 104 more than
    # the column's 260, and its marker moves left with it
    t2["o"] = dict(t2["o"], dir="row", align="center", gap=k.INSET_SM)
    t2["kids"] = [t2["kids"][0], {key: v for key, v in t2["kids"][1].items() if key != "w"}]
    shift = 364 - 260
    ov = [mark(1, (440, 4), name="seq 01 · skip link"), mark(2, (fx - 24 - shift, 4), name="seq 02 · FLATTEN ALL T2"),
          mark(3, "navrail", name="seq 03 · NavRail"), mark(4, sp["section nav"], name="seq 04 · section nav"),
          k.tag("Admin entry: absent (T3) — not rendered, no ghost, no palette or search hit", 60, 330),
          k.tag("no Admin link in the section nav (T3)", k.NAV_W + 8, k.TOP_H + 10 * 28 + 30),
          k.callout("T2", ["FLATTEN ALL (all accounts) stays in the Tab order with its reason;",
                           "Enter changes nothing and re-shows the reason (§10)"], fx - 380, 70, 360),
          k.tag("Manager session · SCR-121 (Admin: users list) unreachable", 640, 740)]
    fr = k.page_window(F_T2T3, page, admin=False, flatten=t2, overlays=ov,
                       note="a Manager session: the T2 control focused in the banner; the admin affordances absent")
    lines = [f"§10 L{L10}: a T2 control keeps its native role and full label, aria-disabled (never disabled), stays "
             "in the Tab order and names its reason (aria-describedby); Enter changes nothing and re-shows it",
             "A T3 affordance (admin navigation for a session without admin:read) is absent: not rendered, not in "
             "the tree, not in the palette, not in search; nothing is merely dimmed",
             f"{k.rule('R-10')}",
             f"Drawn: the Manager's TopBar FLATTEN ALL (global scope, owner-only: E39-D03's RBAC matrix) as T2, "
             f"focused, reason \"{T2_REASON}\"; the NavRail without its Admin entry and the section nav without "
             "its Admin link, so SCR-121 has no route in",
             k.arch("Roles (T2 / T3)", "full-page form"),
             "The TopBar control's placement follows §9.2 (`14`:302); E39-D03 C6 places the panic buttons in the "
             "RightRail (recorded, not re-decided)"]
    return fr, k.frame_block(F_T2T3, lines, keyboard="Tab reaches the T2 control (2) before the rail (3); Enter on "
                                                     "it re-shows the reason")


def build(theme: str = "dark") -> None:
    del theme
    fr = [frame_seq(), frame_t2t3()]
    k.build_all(NN, [f for f, _b in fr], k.annotations(NN, [b for _f, b in fr]))


if __name__ == "__main__":
    build()

"""The kit pin 1ef40f20b (md5 29360883, 1,018 lines) -> the boards branch f4418e83b (md5 8168a304, 1,039 lines).

difflib on the two files (gen10/pin/E42-D04.md, gen10/pin/branch-f4418e83b.md): L1-689 keep their numbers (in-place
edits at L33-34, L92, L98, L157, L497-515, L549, L579-586, L590-601, L673-684); L690 splits into L690-691, L693 into
L694-695; L694-856 +2; the C-row block (R-2) inserts 19 lines after L856, so L857-937 +19; L938 splits into L957-959;
L939 on +21. Equal-size replaced blocks (table reflows) map row for row (checked: every row's first 25 characters
agree but L721 confirm row (R-2), L752, L905, L938, which the branch re-words in place).
"""


def new_line(n: int) -> int:
    if n <= 690:
        return n
    if n <= 692:
        return n + 1
    if n == 693:
        return 694
    if n <= 856:
        return n + 2
    if n <= 937:
        return n + 19
    if n == 938:
        return 957
    return n + 21


# The cap's lines f4418e83b re-words in place (difflib's replace blocks, cap numbering): a citation on one of them was
# re-read by content, never moved by the map alone.
R2_EDITED = frozenset({*range(33, 35), 92, 98, 157, *range(497, 516), 549, *range(579, 587), *range(590, 602),
                       *range(673, 685), 690, 693, *range(703, 725), *range(726, 733), 751, 752, 905, 934, 938,
                       *range(940, 971), *range(972, 990), 991})

# The fold 8a3bc3f2d's lines the cap (9ccf2790c, 1ef40f20b) re-words in place (no line moves; same numbering): a
# citation on one of them was re-read by content (computed from gen10/pin/fold-8a3bc3f2d.md vs gen10/pin/E42-D04.md).
CAP_EDITED = frozenset({4, 5, 32, 62, 67, 68, 69, 70, 71, 72, 73, 74, 76, 77, 78, 79, 80, 81, 88, 89, 159, 184, 193,
                        251, 253, 260, 500, 504, 506, 507, *range(546, 560), 669, 756, 757, 761, 762, 764, *range(766,
                        770), 771, *range(773, 789), 806, 808, 821, 822, *range(858, 895), 902, 914, 916, 917, 918, 923,
                        927})
EDITED = CAP_EDITED | R2_EDITED  # cap-numbered lines re-worded since the fold (the cap or f4418e83b)


# --- Fix pass 3 (2026-10-28): the boards branch f4418e83b (md5 8168a304, 1,039 lines) -> the restated text cbec19a92
# (md5 04dda6e1, 1,083 lines; gen10/pin/branch-cbec19a92.md): difflib on the two pins. L1-54 keep their numbers (in-place
# edits at L4-5, L32, L44); §0 is restated: L55-60 -> L55-66, L67-74 (the old board table) -> L73-76, L76-81 (Count,
# Themes) -> L78-110 have no line-for-line counterpart (a citation there is re-read by content: restated_line() raises);
# L61 -> L67; L62-66 +6; L75 -> L77; L82-870 +29 (the state tables' Board cells, §17's trace and the S line re-worded in
# place, row for row); the re-base C-row inserts 7 lines after L870, so L871-930 +36; §21's checklist gains two lines
# before L931, so L931-959 +38; the re-base note inserts 6 lines after L959, so L960 on +44.
RESTATED_S0 = frozenset({*range(55, 61), *range(67, 75), *range(76, 82)})


def restated_line(n: int) -> int:
    """f4418e83b's line n on cbec19a92 (raises for §0's restated lines: re-read those by content)."""
    if n in RESTATED_S0:
        raise ValueError(f"L{n}: §0's restated text has no line-for-line counterpart")
    if n <= 54:
        return n
    if n == 61:
        return 67
    if n <= 66:
        return n + 6
    if n == 75:
        return 77
    if n <= 870:
        return n + 29
    if n <= 930:
        return n + 36
    if n <= 959:
        return n + 38
    return n + 44


# f4418e83b's lines cbec19a92 re-words in place (difflib's equal-size replace blocks, branch numbering) or restates (§0):
# a citation on one of them is re-read by content, never moved by the map alone.
RESTATED_EDITED = frozenset({4, 5, 32, 44, *RESTATED_S0, 62, 63, 88, 89, 112, 159, 184, 193, 205, *range(234, 265),
                             *range(311, 321), 415, 490, *range(497, 516), *range(546, 560), 669, *range(728, 735),
                             758, 759, *range(761, 794), 810, 823, 824, *range(877, 914), 921, *range(931, 938), 942,
                             946})

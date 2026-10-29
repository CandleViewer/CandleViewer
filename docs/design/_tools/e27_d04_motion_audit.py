"""E27-D04 (#817) audit: the choreography table, the quotes, the danger rules, the cites, the boards.

Stdlib only, offline (`python3 -I -B`). It reads the spec from the working tree, and every cited
file and the token JSON AS TEXT at the pinned base with `git show`. Seven gates, each FAIL led by
its code, at most one FAIL per table row:

- [G1-TABLE] section 2 holds M-1 to M-11 in order, every cell filled; each Recipe cell names an
  E05-D03 section 2 row id that exists at the base, or "a cut"; a cut's timing cell is the instant
  triple and its reduce cell "identical (a cut)"; a recipe's timing and reduce cells name its rows.
- [G2-TOKEN] every dotted token name in the spec exists in the token JSON at the base; no easing
  token and no duration other than `motion.duration.instant` is restated in the table (E05-D03 is
  the one definition); every Stagger cell is `motion.duration.instant` (nothing staggers).
- [G3-QUOTES] Q-1 to Q-5 of section 3 stand byte for byte in `E27.json`:416 at the base (Q-5
  with its one bracketed word restored; the word is kept rot13-encoded here, as is the word list).
- [G4-DANGER] DZ-1 to DZ-3 stand with their pinned sentences and are applied on M-7, M-3 and M-5;
  A25 (M-8), A26 (M-1) and A27 are each stamped RULED in the ruled form.
- [G5-CITE] every `KEY`:line cite resolves to a declared key and an existing range at the base;
  each pinned cite still carries its words; E05-D03 at the base equals the BQ list's pin
  `bca5f0f1d` whenever that commit is readable (recorded in the numbers either way).
- [G6-HYGIENE] no local path, host, closing keyword, "approval pending", or a word or substring
  on the lane's public-text list.
- [G7-BOARDS] section 7: seven dark boards, no twins, names and exports in the ruled pattern,
  every board PENDING until PR 2.

`--json` prints the numbers and findings; `--check` exits 1 on any FAIL (0 FAIL, 0 WARN is the bar);
`--self-test` applies one mutation per gate (MUTATIONS) to an in-memory copy of the spec and passes
only when each adds exactly one new FAIL with its gate's code, a re-run on the unmutated text
reproduces the base result and no file on disk changed.

Usage: python3 -I -B docs/design/_tools/e27_d04_motion_audit.py [--check] [--json] [--self-test]
"""

from __future__ import annotations

import argparse
import codecs
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

ROOT = Path(__file__).resolve().parents[3]
SPEC = ROOT / "docs" / "design" / "E27" / "E27-D04.md"
BASE = "29fe3d5b2e"  # origin/main: the merge commit of E05-D03 (#4990); every cite is read here
PREV_PIN = "bca5f0f1d"  # #4990's head, where the BQ list read E05-D03 (R817 BQ-02)
KEYS = {
    "05": "docs/plan/05-accessibility-standard.md",
    "16": "docs/plan/16-design-system-brief.md",
    "22": "docs/plan/22-api-openapi.yaml",
    "D02": "docs/design/E27/E27-D02.md",
    "D03": "docs/design/E27/E27-D03.md",
    "D03H": "docs/design/E27/E27-D03-handoff.md",
    "memo": "docs/design/research/e27-key-custody.md",
    "E05-D03": "docs/design/E05/E05-D03.md",
    "E27.json": "docs/plan/backlog/E27.json",
}
TOKEN_FILES = (
    "packages/ui/tokens/primitives.tokens.json",
    "packages/ui/tokens/semantic-dark.tokens.json",
)
# key|line|words that must stand on that line at the base (the load-bearing cites)
CITE_PINS = """\
05|96|Focus is never silently stolen;16|198|per-panel / per-row stale;16|220|a stepper's step
16|222|safety banners;22|3342|operationId: testApiKey;D02|255|D18;D02|370|keys.kek_unavailable
D02|466|blocking error;D02|665|aria-current="step";D02|1204|withdrawal refusal
D02|1208|This can take up to 12 s.;D03|884|Rider to E27-D04;D03|1298|no colour change at any
D03|1586|Stale since 10:31:11 UTC;D03|2720|E27-D04 (#817), motion;D03H|33|any motion is E27-D04's
memo|412|AD-16;E05-D03|67|Dialog open / close;E05-D03|68|Drawer open / close
E05-D03|69|Value flash;E05-D03|74|Loading shimmer;E05-D03|75|Busy spinner
E05-D03|93|A mode flip mid-transition;E05-D03|117|MR-3;E27.json|416|Progressive verification"""
DZ_TEXT = {
    "DZ-1": "Nothing else on the screen starts motion in the frame a blocking error or a failed "
    "check appears.",
    "DZ-2": "Nothing about the countdown suggests more urgency than its copy.",
    "DZ-3": "Balances never tween.",
}
DZ_ON = {"DZ-1": "M-7", "DZ-2": "M-3", "DZ-3": "M-5"}
LEDGER_ON = {"A25": "M-8", "A26": "M-1", "A27": ""}
STAMP = "RULED (orchestrator, 2026-10-29, #2701 ledger addendum A row {row})"
CUT_TIMING = "`motion.duration.instant` · `—`"
INSTANT = "`motion.duration.instant`"
QUOTE_IDS = ("Q-1", "Q-2", "Q-3", "Q-4", "Q-5")
SHOWN = ("[shown]", codecs.decode("erirnyrq", "rot13"))  # Q-5's bracket and the word it stands for
BANNED_ROT13 = (
    "yrnx rkcbfrq olcnff rkcybvg nggnpx benpyr erirny haobhaqrq sybbq fgnyy QbF nqivfbel TUFN "
    "cer-nhgu"
)
BANNED = codecs.decode(BANNED_ROT13, "rot13").split()
BOARDS = 7


def git_show(rev: str, rel: str) -> str:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{rev}:{rel}"], capture_output=True, check=False
    )
    return out.stdout.decode("utf-8") if out.returncode == 0 else ""


def token_names(texts: list[str]) -> set[str]:
    names: set[str] = set()

    def walk(node: dict[str, Any], prefix: str) -> None:
        for k, v in node.items():
            if k.startswith("$") or not isinstance(v, dict):
                continue
            name = f"{prefix}.{k}" if prefix else k
            if "$value" in v:
                names.add(name)
            else:
                walk(v, name)

    for text in texts:
        if text:
            walk(json.loads(text), "")
    return names


class Ctx(NamedTuple):
    """The texts the gates read; the self-test swaps `spec` for a mutated copy."""

    spec: str
    base: dict[str, str]
    tokens: frozenset[str]
    prev_e05: str


class Result:
    def __init__(self) -> None:
        self.fails: list[str] = []
        self.warns: list[str] = []
        self.numbers: dict[str, object] = {}

    def fail(self, code: str, msg: str) -> None:
        self.fails.append(f"[{code}] {msg}")


def load_ctx() -> Ctx:
    base = {k: git_show(BASE, p) for k, p in KEYS.items()}
    tokens = frozenset(token_names([git_show(BASE, p) for p in TOKEN_FILES]))
    prev = git_show(PREV_PIN, KEYS["E05-D03"])
    return Ctx(SPEC.read_text(encoding="utf-8"), base, tokens, prev)


def section(spec: str, num: int) -> str:
    """Section `num` of the spec: from its `## n.` heading to the next one outside a fence."""
    out: list[str] = []
    fenced = inside = False
    for line in spec.splitlines(keepends=True):
        if line.startswith("```"):
            fenced = not fenced
        if not fenced and re.match(r"## \d+\. ", line):
            inside = line.startswith(f"## {num}. ")
        if inside:
            out.append(line)
    return "".join(out)


def rows(sec: str) -> list[list[str]]:
    out = []
    for line in sec.splitlines():
        if line.startswith("|") and not re.match(r"^\|[\s:|-]+\|$", line):
            out.append([c.strip() for c in line.strip().strip("|").split("|")])
    return out[1:]  # drop the header


COLS = (
    "m",
    "transition",
    "surfaces",
    "recipe",
    "timing",
    "stagger",
    "reduce",
    "carrier",
    "rules",
    "source",
)


def table(spec: str) -> list[dict[str, str]]:
    return [dict(zip(COLS, r, strict=False)) for r in rows(section(spec, 2))]


def e05_rows(ctx: Ctx) -> set[str]:
    return {r[0] for r in rows(section(ctx.base["E05-D03"], 2)) if r}


def recipe_ids(cell: str) -> list[str]:
    ids: list[str] = []
    for m in re.finditer(r"\brows? (\w+(?: and \w+)*)", cell):
        ids += m.group(1).split(" and ")
    return ids


# --- G1, G2: the table ------------------------------------------------------------------------
def row_problem(row: dict[str, str], known: set[str]) -> str:
    if len(row) != len(COLS) or not all(row.get(c) for c in COLS):
        return "a cell is missing or empty"
    ids, cut = recipe_ids(row["recipe"]), "a cut" in row["recipe"]
    if not ids and not cut:
        return f"Recipe {row['recipe']!r} names neither an E05-D03 row nor a cut"
    if unknown := [i for i in ids if i not in known]:
        return f"E05-D03 has no section 2 row {unknown}"
    if cut and not (
        row["timing"].startswith(CUT_TIMING) and row["reduce"].startswith("identical (a cut)")
    ):
        return "a cut's timing is not the instant triple or its reduce is not 'identical (a cut)'"
    for col in ("timing", "reduce"):
        if sorted(recipe_ids(row[col])) != sorted(ids):
            return f"the {col} cell names rows {recipe_ids(row[col])}, the Recipe {ids}"
    if not CITE.search(row["source"]):
        return "the Source cell holds no cite"
    return ""


def gate_table(ctx: Ctx, r: Result) -> None:
    rs, known = table(ctx.spec), e05_rows(ctx)
    if [x.get("m") for x in rs] != [f"M-{i}" for i in range(1, 12)]:
        r.fail("G1-TABLE", f"rows {[x.get('m') for x in rs]}, ruled M-1 to M-11 in order")
    for row in rs:
        if problem := row_problem(row, known):
            r.fail("G1-TABLE", f"{row.get('m')}: {problem}")
    r.numbers["rows"] = len(rs)
    r.numbers["cut_rows"] = sum("a cut" in x.get("recipe", "") for x in rs)
    r.numbers["recipe_rows"] = sorted({i for x in rs for i in recipe_ids(x.get("recipe", ""))})


TOKEN = re.compile(r"`([a-z]+(?:\.[a-z0-9_]+)+)`")


def gate_token(ctx: Ctx, r: Result) -> None:
    groups = {t.split(".")[0] for t in ctx.tokens}
    named = {t for t in TOKEN.findall(ctx.spec) if t.split(".")[0] in groups}
    if missing := sorted(named - ctx.tokens):
        r.fail("G2-TOKEN", f"token names not in the token JSON at the base: {missing}")
    for row in table(ctx.spec):
        cells = " ".join(v for k, v in row.items() if k not in ("transition", "surfaces"))
        restated = [t for t in TOKEN.findall(cells) if t.startswith("motion.")]
        if row.get("stagger") != INSTANT or set(restated) - {"motion.duration.instant"}:
            r.fail("G2-TOKEN", f"{row.get('m')}: a stagger or a restated recipe token")
    r.numbers["tokens_named"] = sorted(named)


# --- G3: the quotes ---------------------------------------------------------------------------
QUOTE = re.compile(r'^- (Q-\d) \([^)]*\): "(.+)"$', re.MULTILINE)


def gate_quotes(ctx: Ctx, r: Result) -> None:
    lines = ctx.base["E27.json"].splitlines()
    body = lines[415] if len(lines) > 415 else ""
    found = QUOTE.findall(section(ctx.spec, 3))
    if tuple(q for q, _ in found) != QUOTE_IDS:
        r.fail("G3-QUOTES", f"quotes {[q for q, _ in found]}, ruled {list(QUOTE_IDS)}")
    for qid, text in found:
        if (SHOWN[0] in text) != (qid == "Q-5"):
            r.fail("G3-QUOTES", f"{qid}: only Q-5 carries the bracketed word")
        elif text.replace(*SHOWN) not in body:
            r.fail("G3-QUOTES", f"{qid} is not byte for byte in `E27.json`:416 at {BASE}")
    r.numbers["quotes"] = len(found)


# --- G4: the danger rules and the ledger stamps -----------------------------------------------
def gate_danger(ctx: Ctx, r: Result) -> None:
    sec3, rs = section(ctx.spec, 3), {x.get("m"): x for x in table(ctx.spec)}
    for dz, text in DZ_TEXT.items():
        if f"**{dz}. {text}**" not in sec3:
            r.fail("G4-DANGER", f"{dz}'s pinned sentence is not in section 3")
        if dz not in rs.get(DZ_ON[dz], {}).get("rules", ""):
            r.fail("G4-DANGER", f"{dz} is not applied on {DZ_ON[dz]}")
    flat = " ".join(ctx.spec.split())
    for row, m in LEDGER_ON.items():
        if STAMP.format(row=row) not in flat:
            r.fail("G4-DANGER", f"{row} is not stamped in the ruled form")
        if m and row not in rs.get(m, {}).get("rules", ""):
            r.fail("G4-DANGER", f"{row} is not applied on {m}")


# --- G5: cites --------------------------------------------------------------------------------
CITE = re.compile(r"`([A-Za-z0-9.-]+)`((?::\d+(?:-\d+)?)(?:, :\d+(?:-\d+)?)*)")


def gate_cite(ctx: Ctx, r: Result) -> None:
    cited: list[tuple[str, int, int]] = []
    body = re.sub(r"```.*?```", "", ctx.spec, flags=re.DOTALL)
    for key, spans in CITE.findall(body):
        if key not in KEYS:
            r.fail("G5-CITE", f"`{key}`{spans}: an undeclared key")
            continue
        size = len(ctx.base[key].splitlines())
        for a, b in re.findall(r":(\d+)(?:-(\d+))?", spans):
            cited.append((key, int(a), int(b or a)))
            if not 0 < int(a) <= int(b or a) <= size:
                r.fail("G5-CITE", f"`{key}`:{a}{'-' + b if b else ''} is outside the file")
    for pin in CITE_PINS.replace("\n", ";").split(";"):
        key, line, words = pin.split("|", 2)
        lines = ctx.base[key].splitlines()
        if int(line) > len(lines) or words not in lines[int(line) - 1]:
            r.fail("G5-CITE", f"`{key}`:{line} no longer carries {words!r}")
        if not any(k == key and a <= int(line) <= b for k, a, b in cited):
            r.fail("G5-CITE", f"the pinned cite `{key}`:{line} is not in the spec")
    if ctx.prev_e05 and ctx.prev_e05 != ctx.base["E05-D03"]:
        r.fail("G5-CITE", f"E05-D03 at {BASE} differs from the BQ list's pin {PREV_PIN}")
    r.numbers["cites"] = len(cited)
    r.numbers["e05_pin_move"] = (
        f"{PREV_PIN} -> {BASE}: identical" if ctx.prev_e05 else f"{PREV_PIN} not readable here"
    )


# --- G6, G7: hygiene and boards ---------------------------------------------------------------
def gate_hygiene(ctx: Ctx, r: Result) -> None:
    for word in BANNED:
        mixed = word[:1].isupper() and not word.isupper()  # a mixed-case word matches its case
        hay, needle = (ctx.spec, word) if mixed else (ctx.spec.lower(), word.lower())
        if needle in hay:
            r.fail("G6-HYGIENE", f"a word or substring from the lane's public-text list: {word!r}")
    for pat, what in (
        (r"/home/|/tmp/|[A-Z]:\\\\", "a local path"),
        (r"https?://", "a host"),
        (r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?) #\d", "a closing keyword"),
        (r"approval pending", "approval pending"),
    ):
        if re.search(pat, ctx.spec, re.IGNORECASE):
            r.fail("G6-HYGIENE", what)


def gate_boards(ctx: Ctx, r: Result) -> None:
    bs = rows(section(ctx.spec, 7))
    for i, b in enumerate(bs, 1):
        m = re.fullmatch(r"`E27-D04 / (\d\d) ([a-z0-9-]+)`", b[1] if len(b) > 1 else "")
        exp = f"`docs/design/E27/img/E27-D04-{m.group(1)}-{m.group(2)}.png`" if m else ""
        ok = m and len(b) == 6 and b[0] == m.group(1) == f"{i:02d}" and b[2] == exp
        if not ok or b[3] != "dark" or b[5] != "PENDING (PR 2)":
            r.fail("G7-BOARDS", f"board row {b[:2]}: name, export, theme or status off the pattern")
    if len(bs) != BOARDS:
        r.fail("G7-BOARDS", f"{len(bs)} boards (ruled {BOARDS} dark, no twins)")
    r.numbers["boards"] = len(bs)


GATE_FNS: tuple[tuple[str, Callable[[Ctx, Result], None]], ...] = (
    ("G1-TABLE", gate_table),
    ("G2-TOKEN", gate_token),
    ("G3-QUOTES", gate_quotes),
    ("G4-DANGER", gate_danger),
    ("G5-CITE", gate_cite),
    ("G6-HYGIENE", gate_hygiene),
    ("G7-BOARDS", gate_boards),
)


def run(ctx: Ctx) -> Result:
    r = Result()
    for _, fn in GATE_FNS:
        fn(ctx, r)
    return r


# --- self-test --------------------------------------------------------------------------------
def sub(old: str, new: str) -> Callable[[Ctx], Ctx]:
    return lambda ctx: ctx._replace(spec=ctx.spec.replace(old, new, 1))


def regex(pattern: str, repl: str) -> Callable[[Ctx], Ctx]:
    return lambda ctx: ctx._replace(
        spec=re.sub(pattern, repl, ctx.spec, count=1, flags=re.MULTILINE)
    )


MUTATIONS: tuple[tuple[str, Callable[[Ctx], Ctx]], ...] = (
    ("G1-TABLE", regex(r"^(\| M-10 +\|[^|]+\|[^|]+\| )row 2b", r"\1row 2c")),
    (
        "G2-TOKEN",
        regex(
            r"^(\| M-3 +(?:\|[^|]+){4}\| )`motion\.duration\.instant`", r"\1`motion.duration.fast`"
        ),
    ),
    (
        "G3-QUOTES",
        sub("nothing about a blocking error is soft.", "nothing about a blocking error is gentle."),
    ),
    ("G4-DANGER", sub("than its copy.**", "than the copy.**")),
    ("G5-CITE", sub("`D03`:2018-2019", "`D03`:2018-9019")),
    (
        "G6-HYGIENE",
        sub("(a spec cannot split from its tool)", "(a spec cannot split from its tool, /tmp/x)"),
    ),
    ("G7-BOARDS", sub("`E27-D04 / 03 countdown`", "`E27-D04 / 03 Countdown`")),
)


def digests() -> dict[str, str]:
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in (SPEC, Path(__file__))}


def self_test(ctx: Ctx, base: Result) -> list[str]:
    bad: list[str] = []
    before, spec_sha = digests(), hashlib.sha256(ctx.spec.encode()).hexdigest()
    covered = {code for code, _ in MUTATIONS}
    bad += [f"self-test: gate {g} has no mutation" for g, _ in GATE_FNS if g not in covered]
    for code, fn in MUTATIONS:
        mutated = fn(ctx)
        if mutated.spec == ctx.spec:
            bad.append(f"self-test {code}: the mutation did not apply")
            continue
        new = sorted(set(run(mutated).fails) - set(base.fails))
        if len(new) != 1 or not new[0].startswith(f"[{code}]"):
            bad.append(f"self-test {code}: expected one new [{code}] FAIL, got {new[:3]}")
    again = run(ctx)
    if hashlib.sha256(ctx.spec.encode()).hexdigest() != spec_sha:
        bad.append("self-test: the spec text in memory changed")
    if again.fails != base.fails or again.numbers != base.numbers:
        bad.append("self-test: a re-run does not reproduce the base result")
    if digests() != before:
        bad.append("self-test: a file on disk changed")
    return bad


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 on any FAIL")
    ap.add_argument("--json", action="store_true", help="print the numbers and findings as JSON")
    ap.add_argument("--self-test", "--selftest", action="store_true", help="the mutation self-test")
    args = ap.parse_args(argv)
    ctx = load_ctx()
    if not all(ctx.base.values()) or not ctx.tokens:
        missing = [k for k, v in ctx.base.items() if not v]
        print(
            f"FAIL [G5-CITE] cannot read {missing or 'the tokens'} at {BASE} (fetch origin first)"
        )
        return 1
    res = run(ctx)
    st = self_test(ctx, res) if args.self_test else []
    if args.json:
        payload: dict[str, object] = {"numbers": res.numbers, "fails": res.fails}
        payload["warns"] = res.warns
        if args.self_test:
            payload["self_test"] = st
        print(json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True))
    else:
        out = [f"FAIL {line}" for line in res.fails] + [f"WARN {line}" for line in res.warns]
        n = res.numbers
        out.append(
            f"rows {n.get('rows')} (cuts {n.get('cut_rows')}, E05-D03 rows "
            f"{n.get('recipe_rows')}); quotes {n.get('quotes')}; cites {n.get('cites')}; "
            f"boards {n.get('boards')}; E05-D03 {n.get('e05_pin_move')}"
        )
        out.append(f"gates: {len(GATE_FNS)}; FAIL {len(res.fails)}, WARN {len(res.warns)}")
        if args.self_test:
            out += [f"FAIL {line}" for line in st]
            out.append(
                f"self-test: {'ok' if not st else 'FAILED'}: {len(MUTATIONS)} mutations (one per "
                "gate), each one new FAIL; a re-run reproduces the base result; files on disk "
                "unchanged"
            )
        print("\n".join(out))
    failed = bool(res.fails or st)
    return 1 if (failed and (args.check or args.self_test)) else 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))

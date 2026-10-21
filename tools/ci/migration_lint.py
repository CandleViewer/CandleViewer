#!/usr/bin/env python3
"""E03-T10: Alembic migration job checks — single-head, drift, expand/contract
lint, and `IF NOT EXISTS` ban.

`docs/plan/21-database-schema.md` §9 ("Single linear history on `main`", no
`IF NOT EXISTS` in migrations — Alembic owns state) and ADR-0013 rule 9
("Migrations ... must be backward-compatible for one release (expand/
contract), so a rollback never requires a down-migration") are the two
normative sources; this module is the mechanical enforcement of both plus
the security-sensitive-table carve-out from `02-definition-of-ready-done.md`
§4.1 (envelope encryption preserved on `api_keys`-touching migrations).

Error codes (ticket "Technical notes / design"):
    CI-MIG-001  multiple Alembic heads
    CI-MIG-002  schema drift between `models.py` and the migration chain
    CI-MIG-003  destructive operation without a `# cv:contract-phase:` annotation
    CI-MIG-004  upgrade-path (previous release) failure
    CI-MIG-005  `IF NOT EXISTS` used in a migration file
    CI-MIG-006  security-sensitive table touched (a `WARN` for the reviewer; never
                fails the job)

Stdlib only for the lint (`--check-if-not-exists`, `--check-destructive`);
the `alembic heads` / `alembic check` / `upgrade head` steps in
`.github/workflows/_job-migrations.yml` shell out to Alembic directly and
this module only assembles their exit codes into named error codes for the
job summary. No network access; no DB required for the static checks.
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# Destructive operations that need an explicit `# cv:contract-phase: <release>`
# justification per ADR-0013 rule 9 / expand-contract discipline.
_DESTRUCTIVE_OP_RE = re.compile(
    r"\bop\.(drop_column|drop_table|drop_index|drop_constraint)\s*\("
)
# `add_column` with `nullable=False` and no `server_default=` is destructive
# for existing rows (breaks expand/contract) unless annotated.
_ADD_COLUMN_RE = re.compile(r"\bop\.add_column\s*\(")
_NULLABLE_FALSE_RE = re.compile(r"nullable\s*=\s*False")
_SERVER_DEFAULT_RE = re.compile(r"server_default\s*=")
_ALTER_COLUMN_TYPE_RE = re.compile(r"\bop\.alter_column\s*\([^)]*type_\s*=")
_CONTRACT_PHASE_RE = re.compile(r"#\s*cv:contract-phase:\s*\S+")
_IF_NOT_EXISTS_RE = re.compile(r"\bIF\s+NOT\s+EXISTS\b", re.IGNORECASE)
# `CREATE EXTENSION IF NOT EXISTS` is exempt: extensions are cluster-level
# objects Alembic does not own (no downgrade drops them — other databases may
# depend on them) and the idempotent form is the documented Postgres idiom.
# The ban (21-database-schema.md §9) targets tables/indexes/columns, whose
# state Alembic *does* own.
_CREATE_EXTENSION_RE = re.compile(
    r"\bCREATE\s+EXTENSION\s+IF\s+NOT\s+EXISTS\b", re.IGNORECASE
)

# Tables that must never be a destructive-op target, contract-phase
# annotation or not (append-only audit, per ticket "Security notes").
# Names confirmed against `docs/plan/21-database-schema.md` §3.10
# (`audit_log`, `audit_checkpoints` — no `audit_entries` table exists).
_FORBIDDEN_DESTRUCTIVE_TABLES = frozenset({"audit_log", "audit_checkpoints"})

# Raw-SQL statements that mutate or reshape an audit table bypass the
# `op.drop_*`/`op.alter_column` AST-level checks above. Case-insensitive:
# DDL/DML keywords (and Postgres identifiers, since unquoted identifiers are
# folded to lower case) are not case-sensitive. Each pattern binds the
# keyword directly to the table name (rather than "keyword anywhere in the
# literal, table name anywhere in the literal") so prose — e.g. a module
# docstring that separately mentions `audit_log` in one sentence and
# `ALTER TABLE` in another about a different table — is never conflated with
# an actual SQL statement. `GRANT ALL` implicitly includes UPDATE/DELETE/
# TRUNCATE; a grant list may name a mutating verb alongside harmless
# privileges (e.g. `GRANT SELECT, DELETE ON ...`).
_TABLE_QUALIFIER = r"(?:\"?\w+\"?\.)?\"?'?"

# Sentinel substituted for an f-string placeholder whose value could not be
# resolved to a string constant at lint time. Never matches a real table name
# (NUL cannot appear in Python source), so it only trips the dedicated
# dynamic-table check below and never the static per-table patterns. NUL is not
# a word character, so the pattern ends in `(?!\w)` — a trailing `\b` would
# silently never match at end-of-string or before whitespace.
_UNRESOLVED_PLACEHOLDER = "\x00"
_DYNAMIC_MUTATION_RE = re.compile(
    rf"\b(?:DELETE\s+FROM|UPDATE|DROP\s+TABLE|TRUNCATE(?:\s+TABLE)?|ALTER\s+TABLE)"
    rf"\s+{_TABLE_QUALIFIER}{re.escape(_UNRESOLVED_PLACEHOLDER)}(?!\w)"
    rf"|\bGRANT\s+(?:ALL(?:\s+PRIVILEGES)?|[A-Za-z, ]*?\b(?:UPDATE|DELETE|TRUNCATE)\b[A-Za-z, ]*?)"
    rf"\s+ON\s+{_TABLE_QUALIFIER}{re.escape(_UNRESOLVED_PLACEHOLDER)}(?!\w)",
    re.IGNORECASE,
)


def _mutation_pattern_for(table: str) -> re.Pattern[str]:
    t = re.escape(table)
    q = _TABLE_QUALIFIER
    return re.compile(
        rf"\b(?:DELETE\s+FROM|UPDATE|DROP\s+TABLE|TRUNCATE(?:\s+TABLE)?|ALTER\s+TABLE)"
        rf"\s+{q}{t}\b"
        rf"|\bGRANT\s+(?:ALL(?:\s+PRIVILEGES)?|"
        rf"[A-Za-z, ]*?\b(?:UPDATE|DELETE|TRUNCATE)\b[A-Za-z, ]*?)"
        rf"\s+ON\s+{q}{t}\b",
        re.IGNORECASE,
    )


# There is deliberately no escape hatch for audit-table mutations: C-5.7
# forbids UPDATE/DELETE/DROP/TRUNCATE/ALTER/mutating GRANT on an audit table
# unconditionally, so no annotation (however spelled) may suppress a genuine
# finding. A previous `# cv:audit-exempt:` marker was removed because it was
# indistinguishable, at review time, from a bypass of a real mutation — see
# PR #1518 review history.
_CREATE_ONLY_RE = re.compile(r"^\s*CREATE\s+(TABLE|INDEX)\b", re.IGNORECASE)


def _resolve_simple_name_constants(tree: ast.AST) -> dict[str, str]:
    """Map `Name = Constant(str)` module/function-level assignments
    (`tbl = "audit_log"`) to their string value, so an f-string placeholder
    that is just a `Name` reference can be substituted before matching.
    Last assignment wins if a name is reassigned; conditional/loop-only
    assignments are still collected (fail-closed: over-resolving only ever
    adds table names to check, it never removes a real finding)."""
    values: dict[str, str] = {}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    values[target.id] = node.value.value
    return values


def _iter_string_literals(
    path: Path, source: str, skip_docstrings: bool = False
) -> list[tuple[int, str, bool]]:
    """Every string literal in the migration file, via the AST (so f-string
    parts and implicit concatenation are covered, not just single-line
    `op.execute("...")` calls). Returns `(1-based lineno of the literal's
    first line, normalised text, had_unresolved_interpolation)` triples.

    F-string interpolations that reference a simple `Name` bound to a string
    constant elsewhere in the module (`tbl = "audit_log"; f"...{tbl}..."`)
    are substituted with that value. Any other interpolation (attribute
    access, call, unresolved name, f-string format spec, etc.) is replaced
    with `_UNRESOLVED_PLACEHOLDER` and the triple's third element is `True`,
    so a dynamic table name in an audit-sensitive statement still trips a
    dedicated fail-closed finding even though the real name is unknown.

    `skip_docstrings` leaves out a string used as a statement (a module, class
    or function docstring): it is documentation and never executes."""
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []
    name_constants = _resolve_simple_name_constants(tree)
    docstrings: set[int] = set()
    if skip_docstrings:
        docstrings = {
            id(node.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        }
    literals: list[tuple[int, str, bool]] = []
    for node in ast.walk(tree):
        if id(node) in docstrings:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            literals.append((node.lineno, node.value, False))
        elif isinstance(node, ast.JoinedStr):
            parts: list[str] = []
            unresolved = False
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    parts.append(part.value)
                elif isinstance(part, ast.FormattedValue):
                    resolved = None
                    if isinstance(part.value, ast.Name):
                        resolved = name_constants.get(part.value.id)
                    if resolved is not None:
                        parts.append(resolved)
                    else:
                        parts.append(_UNRESOLVED_PLACEHOLDER)
                        unresolved = True
            text = "".join(parts)
            if text:
                literals.append((node.lineno, text, unresolved))
    return literals


def _normalise_sql(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _sql_statements(text: str) -> list[str]:
    """Split a (possibly multi-statement, possibly prose) literal into
    individual SQL-statement-sized chunks so a mutation keyword in one
    sentence/statement is never combined with an unrelated table name
    mentioned elsewhere in the same literal (e.g. a module docstring listing
    several tables in prose). Splits on `;` and on blank lines, which is
    conservative — a real single SQL statement never spans a blank line in
    this codebase's migrations."""
    chunks: list[str] = []
    for para in re.split(r"\n\s*\n", text):
        chunks.extend(part for part in para.split(";") if part.strip())
    return chunks or [text]


# CI-MIG-006 reads a revision for the identifiers it names, not for substrings:
# `orders`, `positions`, `executions` and `backups` are also plain words, and a
# table that only a comment or a message mentions is not touched. One scan, left
# to right, consumes whole whatever is not an identifier (comments, `'...'`
# literals) before it takes a name, so a `--` inside a literal or an apostrophe
# inside a comment can neither hide nor swallow a statement. A name is then
# either unquoted (Postgres folds it to lower case) or double-quoted (case kept,
# `""` is one `"`); in `public.orders`, `"public"."orders"` and `orders.id` each
# part is a name. A `$tag$ ... $tag$` body (a `DO` block, a trigger function) is
# code: it is consumed whole, so an apostrophe in it cannot pair with a quote
# outside it, and scanned on its own.
_SQL_TOKEN_RE = re.compile(
    r"--[^\n]*"  # line comment
    r"|/\*.*?\*/"  # block comment
    r"|(?P<estring>[eE]'(?:[^'\\]|\\.|'')*')"  # E'..': backslash escapes
    r"|(?P<string>'(?:[^']|'')*')"  # '..': a doubled quote is one quote
    r'|"(?P<quoted>(?:[^"]|"")+)"'  # "..": a quoted identifier
    r"|\$(?P<tag>(?:[^\W\d]\w*)?)\$(?P<body>.*?)\$(?P=tag)\$"  # $tag$..$tag$
    r"|\$(?:[^\W\d]\w*)?\$"  # a $tag$ delimiter with no partner
    r"|(?P<word>\w[\w$]*)",  # unquoted identifier, keyword or number
    re.DOTALL,
)

# A `'...'` literal is a value unless it is SQL, so its text is read only when it
# is dynamic SQL (it opens with one of `SQL_COMMANDS`, as in the `EXECUTE 'REVOKE
# DELETE ON t FROM cv_app'` these revisions write their grants as) or a bare,
# possibly qualified name (`'orders'::regclass`, the quoted form this rule has
# always matched). A `COMMENT ... IS` text, a `RAISE` message or a seed value such
# as 'orders:read' is prose and is skipped, unless it opens with a command word,
# when it is read as SQL (an extra flag, never a missed one); `$$` text is always
# read as code.
SQL_COMMANDS = (
    "ALTER", "ANALYZE", "BEGIN", "CALL", "CLUSTER", "COMMENT", "COPY", "CREATE",
    "DECLARE", "DELETE", "DO", "DROP", "EXECUTE", "GRANT", "INSERT", "LOCK", "MERGE",
    "REFRESH", "REINDEX", "REVOKE", "SELECT", "SET", "TABLE", "TRUNCATE", "UPDATE",
    "VACUUM", "WITH",
)  # fmt: skip
_SQL_COMMAND_RE = re.compile(r"\s*(?:" + "|".join(SQL_COMMANDS) + r")\b", re.IGNORECASE)
_WORD_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
_BARE_NAME_RE = re.compile(r'\s*[\w".]+\s*')


def _sql_identifiers(sql: str) -> set[str]:
    """Every name `sql` uses as an identifier, as Postgres reads it: an unquoted
    name folded to lower case, a double-quoted one exactly (`"ORDERS"` is not
    `orders`). Fail-closed: a column or alias that shares a table's name is read
    as the table, since no grammar is parsed."""
    names: set[str] = set()
    for token in _SQL_TOKEN_RE.finditer(sql):
        quoted, word, body = token["quoted"], token["word"], token["body"]
        literal = token["string"] or token["estring"]
        if body is not None:
            names |= _sql_identifiers(body)
        elif quoted is not None:
            names.add(quoted.replace('""', '"'))
        elif word is not None:
            names.add(word.lower())
        elif literal is not None:
            text = literal[literal.index("'") + 1 : -1].replace("''", "'")
            if _BARE_NAME_RE.fullmatch(text) or _SQL_COMMAND_RE.match(text):
                names |= _sql_identifiers(text)
    return names


# Populated from `tools/ci/security-sensitive-tables.txt` when present;
# migrations touching these need the `security-review` label (flagged, not
# blocked, by this tool — the label/reviewer gate is enforced elsewhere).
_DEFAULT_SECURITY_SENSITIVE_TABLES_PATH = Path(__file__).with_name(
    "security-sensitive-tables.txt"
)


@dataclass(frozen=True)
class LintFinding:
    code: str
    path: Path
    message: str

    def render(self) -> str:
        return f"{self.code}: {self.path}: {self.message}"


def _read_revision(path: Path) -> str:
    """A revision's text as Python reads it: a byte-order mark is not code."""
    return path.read_text(encoding="utf-8-sig")


def _read_sensitive_tables(path: Path) -> frozenset[str]:
    if not path.is_file():
        return frozenset()
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            names.add(stripped)
    return frozenset(names)


def _line_has_contract_phase_nearby(
    lines: list[str], idx: int, window: int = 3
) -> bool:
    """A `# cv:contract-phase:` comment on the same line or within `window`
    lines above/below the offending call counts as justification — matches
    how engineers naturally annotate a multi-line `op.*(...)` call."""
    lo = max(0, idx - window)
    hi = min(len(lines), idx + window + 1)
    return any(_CONTRACT_PHASE_RE.search(lines[i]) for i in range(lo, hi))


def check_if_not_exists(paths: list[Path]) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for path in paths:
        text = _read_revision(path)
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _IF_NOT_EXISTS_RE.search(line) and not _CREATE_EXTENSION_RE.search(line):
                findings.append(
                    LintFinding(
                        code="CI-MIG-005",
                        path=path,
                        message=(
                            f"line {lineno}: 'IF NOT EXISTS' is never used in "
                            "migrations — Alembic owns state (21-database-schema.md §9)"
                        ),
                    )
                )
    return findings


def _table_mentioned(line: str, tables: frozenset[str]) -> str | None:
    for table in tables:
        if re.search(rf"['\"]{re.escape(table)}['\"]", line):
            return table
    return None


def check_audit_table_integrity(
    paths: list[Path],
    forbidden_tables: frozenset[str] = _FORBIDDEN_DESTRUCTIVE_TABLES,
) -> list[LintFinding]:
    """C-5.7: audit tables are append-only — no `UPDATE`/`DELETE` grants, no
    dropping/mutating audit history, however the operation is spelled.

    Scans every string literal in the file (via `ast`, so multi-line
    `op.execute(\n "...")`, an indirected `SQL = "..."; op.execute(SQL)`, and
    f-string literal parts are all covered — not just a single-line
    `op.execute("...")` regex) for a mutation keyword co-occurring with an
    audit table name, both compared case-insensitively (Postgres folds
    unquoted identifiers to lower case). Also keeps the `op.alter_column` /
    `op.rename_table` line-level checks the AST-level destructive-op check
    above does not see.

    There is no escape hatch: a genuine `CREATE TABLE`/`CREATE INDEX` on an
    audit table is allowed through unconditionally (it never mutates
    existing rows), but any mutation keyword is always forbidden — no
    comment, marker or annotation of any kind suppresses a finding here."""
    findings: list[LintFinding] = []
    for path in paths:
        source = _read_revision(path)
        lines = source.splitlines()

        for lineno, literal, unresolved in _iter_string_literals(path, source):
            for statement in _sql_statements(literal):
                normalised = _normalise_sql(statement)
                if unresolved and _DYNAMIC_MUTATION_RE.search(normalised):
                    findings.append(
                        LintFinding(
                            code="CI-MIG-003",
                            path=path,
                            message=(
                                f"line {lineno}: dynamic table name in an "
                                "audit-sensitive statement (mutation keyword "
                                "with an unresolved interpolated target) — "
                                "forbidden, resolve to a literal table name "
                                "or refactor (C-5.7, ADR-0013 rule 9)"
                            ),
                        )
                    )
                    continue
                forbidden_hit = next(
                    (
                        table
                        for table in forbidden_tables
                        if _mutation_pattern_for(table).search(normalised)
                    ),
                    None,
                )
                if forbidden_hit is None:
                    continue
                if _CREATE_ONLY_RE.match(normalised):
                    continue
                findings.append(
                    LintFinding(
                        code="CI-MIG-003",
                        path=path,
                        message=(
                            f"line {lineno}: raw-SQL statement targets append-only "
                            f"table '{forbidden_hit}' — forbidden regardless of "
                            "annotation (C-5.7, ADR-0013 rule 9)"
                        ),
                    )
                )

        for idx, line in enumerate(lines):
            is_rename = bool(re.search(r"\bop\.rename_table\s*\(", line))
            is_alter_shape = bool(re.search(r"\bop\.alter_column\s*\(", line))
            if not (is_rename or is_alter_shape):
                continue
            forbidden_hit = _table_mentioned(line, forbidden_tables)
            if forbidden_hit is None:
                continue
            findings.append(
                LintFinding(
                    code="CI-MIG-003",
                    path=path,
                    message=(
                        f"line {idx + 1}: operation targets append-only "
                        f"table '{forbidden_hit}' — forbidden regardless of "
                        "annotation (C-5.7, ADR-0013 rule 9)"
                    ),
                )
            )
    return findings


def check_destructive_annotations(
    paths: list[Path],
    forbidden_tables: frozenset[str] = _FORBIDDEN_DESTRUCTIVE_TABLES,
) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for path in paths:
        lines = _read_revision(path).splitlines()
        for idx, line in enumerate(lines):
            is_destructive = bool(_DESTRUCTIVE_OP_RE.search(line))
            is_narrowing_type = bool(_ALTER_COLUMN_TYPE_RE.search(line))
            is_non_nullable_add = (
                bool(_ADD_COLUMN_RE.search(line))
                and _NULLABLE_FALSE_RE.search(line)
                and not _SERVER_DEFAULT_RE.search(line)
            )

            if not (is_destructive or is_narrowing_type or is_non_nullable_add):
                continue

            forbidden_hit = _table_mentioned(line, forbidden_tables)
            if is_destructive and forbidden_hit is not None:
                findings.append(
                    LintFinding(
                        code="CI-MIG-003",
                        path=path,
                        message=(
                            f"line {idx + 1}: destructive op targets append-only "
                            f"table '{forbidden_hit}' — forbidden regardless of "
                            "annotation (ADR-0013 rule 9, security notes)"
                        ),
                    )
                )
                continue

            if not _line_has_contract_phase_nearby(lines, idx):
                findings.append(
                    LintFinding(
                        code="CI-MIG-003",
                        path=path,
                        message=(
                            f"line {idx + 1}: destructive/non-additive operation "
                            "with no '# cv:contract-phase: <release>' annotation "
                            "(ADR-0013 rule 9)"
                        ),
                    )
                )
    return findings


def check_security_sensitive(
    paths: list[Path],
    sensitive_tables: frozenset[str] | None = None,
) -> list[LintFinding]:
    """Non-blocking flag (CI-MIG-006, informational): migrations touching
    security-sensitive tables need mandatory Security review per
    `02-definition-of-ready-done.md` §4.1. Returned as findings with code
    'CI-MIG-006' so the caller can choose to warn rather than fail.

    A revision touches a table when a string literal in it names the table as
    an identifier (see `_sql_identifiers`): in raw SQL, unquoted, double-quoted
    or schema-qualified (`CREATE TABLE account_profiles`), or as an Alembic
    argument (`op.add_column("orders", ...)`). A docstring, a Python or SQL
    comment, and a name that only the text of a `'...'` literal mentions are
    prose, not a touch, unless the literal opens with an SQL command: then it
    is read as SQL, so such prose can add a flag, never hide one; `$$` text is
    always read as code. A revision Python cannot parse has every word read as
    a name (fail-closed). One finding per table per file, ordered by table."""
    tables = sensitive_tables
    if tables is None:
        tables = _read_sensitive_tables(_DEFAULT_SECURITY_SENSITIVE_TABLES_PATH)
    if not tables:
        return []
    findings: list[LintFinding] = []
    for path in paths:
        source = _read_revision(path)
        try:
            ast.parse(source, filename=str(path))
        except SyntaxError:  # not Python: every word is a name, fail-closed
            names = {word.lower() for word in _WORD_RE.findall(source)}
        else:
            names = set()
            literals = _iter_string_literals(path, source, skip_docstrings=True)
            for _, literal, _ in literals:
                names |= _sql_identifiers(literal)
        for table in sorted(names & tables):
            findings.append(
                LintFinding(
                    code="CI-MIG-006",
                    path=path,
                    message=(
                        f"touches security-sensitive table '{table}' — "
                        "requires mandatory Security review (DoR §4.1)"
                    ),
                )
            )
    return findings


def _iter_migration_files(versions_dir: Path) -> list[Path]:
    return sorted(p for p in versions_dir.glob("*.py") if p.name != "__init__.py")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--versions-dir",
        type=Path,
        default=Path("candleviewer/migrations/versions"),
        help="Directory containing Alembic version files (default: %(default)s)",
    )
    args = parser.parse_args(argv)

    versions_dir: Path = args.versions_dir
    if not versions_dir.is_dir():
        print(f"CI-MIG-000: versions dir not found: {versions_dir}", file=sys.stderr)
        return 2

    paths = _iter_migration_files(versions_dir)
    findings: list[LintFinding] = []
    findings.extend(check_if_not_exists(paths))
    findings.extend(check_destructive_annotations(paths))
    findings.extend(check_audit_table_integrity(paths))
    security_findings = check_security_sensitive(paths)

    for finding in findings:
        print(finding.render(), file=sys.stderr)
    for finding in security_findings:
        print(f"WARN {finding.render()}", file=sys.stderr)

    if findings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

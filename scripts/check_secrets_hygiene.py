"""Credential-hygiene gate (E43-T06; SR-140, SR-141, SR-144, SR-145, SR-146).

Subcommands (all offline, deterministic, exit 1 on violation):

* ``fixtures``  - no fixture holds a real-looking exchange key without ``DUMMY_PREFIX`` (SR-145),
  and no file of the accounts fault-injection pack holds a bare key-shaped token (E27-Q01)
* ``dev-env``   - ``.env`` gitignored, ``.env.example`` free of secret values (SR-144)
* ``workflows`` - no command tracing (``set -x``, ``set -v``, a ``DEBUG`` trap) / environment dump
  in workflows or the repository shell scripts their steps run, directly or through other scripts
  (``workflow_scripts``; SR-146)
* ``inventory`` - a secret-name list (JSON array) holds no live key / KEK (SR-140)
* ``logs``      - scan log/artefact files for secret shapes (SR-146)

A failure that implicates a real credential refers to runbook IR-02 (rotate first, SR-143).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

#: Documented dummy prefix; the gitleaks allowlist and the fixture test both assert it.
DUMMY_PREFIX = "DUMMYKEY_"
IR02 = "IR-02: rotate the credential FIRST, investigate second (docs/ci-runbook.md, SR-143)"

#: Same shapes as the gitleaks exchange-key rules in .gitleaks.toml (controls must agree).
_KEY_FIELD = re.compile(
    r"""(?i)["']?(api[_-]?key|api[_-]?secret)["']?\s*[:=]\s*["']([A-Za-z0-9_]{16,})["']"""
)
_HEADER = re.compile(r"(?i)X-BAPI-(API-KEY|SIGN)\s*[:=]\s*[\"']?([A-Za-z0-9_]{16,})")
_SIGN = re.compile(r"""(?i)"sign(ature)?"\s*:\s*"([A-Fa-f0-9]{32,})\"""")
_PRIVATE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
_TOKEN = re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9]{20,})\b")
_REDACTED_MARKERS = ("REDACTED", "<redacted", "[redacted")

_FIXTURE_DIRS = ("services/api/tests/fixtures", "packages/fixtures", "tests/fixtures")

#: E27-Q01 (#833): an exchange API key is a bare 18-20 character alphanumeric token, a secret one of
#: 36. The accounts pack hyphenates every id by rule (``fixture-<scenario>-NNNN``), so in the pack
#: a bare token of that shape is a paste, whatever field or prose it sits in. The same rule as
#: ``packages/fixtures/scripts/accounts-pack.mjs`` (``findKeyShapedTokens``): a maximal run of
#: ``[A-Za-z0-9_-]`` that is purely alphanumeric counts when it holds a digit, or, letters only,
#: when it mixes at least ``_MIXED_CASE_MIN`` capitals and as many small letters. A tripwire for
#: accidental pastes, not a complete control.
_KEY_SHAPE_DIRS = ("packages/fixtures/accounts",)
_BARE_RUN = re.compile(r"[A-Za-z0-9_-]+")
_ALNUM = re.compile(r"[A-Za-z0-9]+")
_MIXED_CASE_MIN = 6
_TEXT_SUFFIXES = {
    ".json",
    ".jsonl",
    ".txt",
    ".md",
    ".yaml",
    ".yml",
    ".py",
    ".ts",
    ".mjs",
    ".csv",
}
_ENV_EXAMPLE_OK = re.compile(
    r"(?i)(KEY|SECRET|TOKEN|PASSWORD|KEK|DSN)[A-Z0-9_]*\s*=\s*(\S+)"
)


def _is_benign(value: str) -> bool:
    return value.startswith(DUMMY_PREFIX) or any(
        m.lower() in value.lower() for m in _REDACTED_MARKERS
    )


def scan_text(text: str) -> list[str]:
    """Return human descriptions of real-looking credentials found in ``text``."""
    hits: list[str] = []
    for rx in (_KEY_FIELD, _HEADER):
        for m in rx.finditer(text):
            if not _is_benign(m.group(2)):
                hits.append(f"exchange-key-shape ({m.group(1).lower()})")
    for m in _SIGN.finditer(text):
        hits.append("exchange-hmac-signature")
    if _PRIVATE.search(text):
        hits.append("private-key-block")
    for m in _TOKEN.finditer(text):
        if not _is_benign(m.group(0)):
            hits.append("token-shape")
    return hits


def _key_shape(length: int) -> str | None:
    if 18 <= length <= 20:
        return "api-key"
    if length == 36:
        return "api-secret"
    return None


def _looks_like_key(token: str) -> bool:
    if not _ALNUM.fullmatch(token) or not any(c.isalpha() for c in token):
        return False
    if any(c.isdigit() for c in token):
        return True
    capitals = sum(c.isupper() for c in token)
    return capitals >= _MIXED_CASE_MIN and len(token) - capitals >= _MIXED_CASE_MIN


def scan_key_shapes(text: str) -> list[str]:
    """Bare key- or secret-shaped tokens in ``text``: shape, length and offset, never the token."""
    hits: list[str] = []
    for m in _BARE_RUN.finditer(text):
        token = m.group(0)
        shape = _key_shape(len(token))
        if shape is not None and _looks_like_key(token):
            hits.append(f"bare {shape}-shaped token ({len(token)} chars at offset {m.start()})")
    return hits


def _check_key_shapes(root: Path) -> list[str]:
    """Every file of the accounts pack, whatever its suffix or name (plants live in tmp copies)."""
    errors: list[str] = []
    for d in _KEY_SHAPE_DIRS:
        base = root / d
        for path in sorted(base.rglob("*")) if base.is_dir() else []:
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            rel = path.relative_to(root).as_posix()
            for hit in scan_key_shapes(text):
                errors.append(f"{rel}: {hit}; the token is never printed (E27-Q01)")
    return errors


def check_fixtures(root: Path) -> list[str]:
    errors: list[str] = _check_key_shapes(root)
    for d in _FIXTURE_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.suffix not in _TEXT_SUFFIXES:
                continue
            rel = path.relative_to(root).as_posix()
            # Scanner self-tests plant fake keys on purpose (allowlisted in .gitleaks.toml).
            if (
                "/test/" in rel
                or ".test." in path.name
                or path.name.startswith("test_")
            ):
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for hit in scan_text(text):
                errors.append(
                    f"{path.relative_to(root).as_posix()}: {hit} without {DUMMY_PREFIX} prefix"
                )
    return errors


def check_dev_env(root: Path) -> list[str]:
    errors: list[str] = []
    gi = root / ".gitignore"
    lines = (
        [ln.strip() for ln in gi.read_text(encoding="utf-8").splitlines()]
        if gi.exists()
        else []
    )
    if ".env" not in lines:
        errors.append(".gitignore: '.env' is not ignored")
    ex = root / ".env.example"
    if not ex.exists():
        errors.append(".env.example is missing")
    else:
        for n, ln in enumerate(ex.read_text(encoding="utf-8").splitlines(), 1):
            if ln.lstrip().startswith("#"):
                continue
            m = _ENV_EXAMPLE_OK.search(ln)
            if (
                m
                and m.group(2).strip("\"'")
                and not _is_benign(m.group(2).strip("\"'"))
            ):
                errors.append(
                    f".env.example:{n}: secret-named setting has a non-empty value"
                )
            if scan_text(ln):
                errors.append(f".env.example:{n}: credential-shaped value")
    return errors


#: SR-146 tracing (#3294): the shell prints each command it runs with its values expanded. A
#: command word follows no word character, ``.``, ``/``, ``-`` or ``:`` (so not in ``reset``,
#: ``mybash``, ``ssh``, ``zap.sh``, ``tools/sh``, ``du -sh`` or a URL's last segment:
#: ``wget -O- https://example.com/sh -x``), but may follow a quote or a bracket:
#: ``bash -c "set -x; ..."``, ``eval 'set -x'``, ``(set -x)``. Quoted prose counts too.
_WORD_START = r"(?<![\w./:-])"


def _option_name(name: str) -> str:
    """Option ``name`` as zsh reads it, ending there (#3400): in any case and with ``_`` anywhere
    (``-o XTRACE``, ``x_trace``: zshoptions(1)), ``-`` between its letters or after it
    (``--x-trace``: zsh(1) INVOCATION reads it as ``_``). Not ``--xtrace-not`` or ``-o xtraced``,
    which name no option. Bash takes the exact name only, so it refuses the other spellings."""
    return r"(?i:_*" + "[-_]*".join(name) + r")(?![-_]*[a-zA-Z0-9])"


_XTRACE = _option_name("xtrace")
#: The options that echo commands: ``xtrace``, and ``verbose`` (#3400), which echoes each line as
#: the shell reads it: an ``eval`` string with its values in it (bash 5.3: ``X=s; eval "echo $X"``
#: prints ``echo s``), a step's script with its ``${{ secrets.* }}`` in it.
_TRACING = r"(?:" + _XTRACE + r"|" + _option_name("verbose") + r")"
#: zsh's inverted names: ``no`` before a name flips it (zshoptions(1)), so ``unsetopt noxtrace``
#: and ``set +o noxtrace`` turn tracing on.
_NO_TRACING = r"(?:" + _option_name("noxtrace") + r"|" + _option_name("noverbose") + r")"


def _turning_on(sets: str, unsets: str) -> str:
    """An option word turning tracing on, ``sets`` and ``unsets`` being the signs that set and
    unset an option: ``x`` or ``v`` in a ``sets`` group (``-x``, ``-ex``, ``-Eeuvo``), ``-o
    xtrace`` (``-eo verbose``) or ``+o noxtrace``."""
    setting = sets + r"[a-zA-Z]*(?:[xv]|o\s+" + _TRACING + r")"
    return setting + r"|" + unsets + r"[a-zA-Z]*o\s+" + _NO_TRACING


#: The tracing option word of ``set`` and a shell: ``_turning_on`` with ``-`` setting, or
#: ``--xtrace``, ``--verbose``; ``+x`` and ``+o xtrace`` turn tracing off.
_TRACE_WORD = r"(?:" + _turning_on("-", r"\+") + r"|--" + _TRACING + r")"
#: The option words before it: ``--norc``, ``-o name``, ``-eO name``, ``-e``, ``+u``. Any other
#: word ends them: ``set -- -x`` and ``set - -x`` (positional parameters), ``bash x.sh -x``. The
#: lookahead ends them at the tracing word.
_OPTION_WORDS = r"(?:(?!" + _TRACE_WORD + r")(?:--\w+|[-+][a-zA-Z]*[oO]\s+\w+|[-+][a-zA-Z]+)\s+)*"
#: Group ``on``: the tracing word after the option words, if any. Optional, so a rule matches a
#: command word with all its option words and ``finditer`` goes on after them, reading a line in
#: linear time. With the tracing word required, each ``sh`` in ``sh -o sh -o sh ...`` re-read the
#: rest of the line (quadratic: about 6 s at 48k characters).
_TRACE_ON = r"(?P<on>" + _TRACE_WORD + r")?"
#: ``set`` turning tracing on: ``set -x``, ``set -e -x``, ``set -o errexit -o xtrace``.
_SET_TRACE = re.compile(_WORD_START + r"set\s+" + _OPTION_WORDS + _TRACE_ON)
#: A path segment: word characters, ``.``, ``-`` and ``$NAME`` (``bash-5.2``, ``$TOOL``). A ``$``
#: counts only before a name: in ``/a$/a$/...`` each ``/`` after a ``$`` would start a rule that
#: re-reads the rest of the path.
_SEGMENT = r"(?:\$?[\w.-])*"
#: A shell's directory from ``/``, ``~``, ``~user``, ``$VAR`` or ``${VAR}``: ``/bin/``, ``//bin/``,
#: ``$HOME/bin/``, ``/opt/$TOOL/bin/``. A relative one (``tools/``, ``./``) holds a repository
#: file, which ``workflow_scripts`` follows if it is a shell script.
_SHELL_DIR = r"(?:[$~]" + _SEGMENT + r")?/(?:" + _SEGMENT + r"/)*"
#: A character of a word in the same command: not a space, a command separator, a bracket or a
#: backtick.
_IN_WORD = r"[^\s;&|()`]"
#: shellcheck's ``-s``/``--shell`` names the dialect it checks, a shell it does not run (#3400):
#: ``shellcheck -e SC1091 -s bash -x ci.sh``. Matched through that shell name, never ``on``. The
#: words before the option end at a word holding ``shellcheck`` (but ``.shellcheckrc``), where
#: another such match may start, so each word is read once.
_SHELLCHECK_DIALECT = (
    r"shellcheck(?:\s+(?!" + _IN_WORD + r"*(?<!\.)shellcheck|-s\s|--shell[\s=])" + _IN_WORD + r"+)*"
    r"\s+(?:-s|--shell)[\s=]\s*" + _IN_WORD + r"*"
)
#: A shell started with tracing on (``sh -x x.sh``, ``env bash -xc "..."``): sh, bash, rbash,
#: dash, ksh or zsh (all read ``-x``, ``-v`` and ``-o xtrace``), by name or from a ``_SHELL_DIR``.
_SHELL_ON = r"(?:r?ba|da|k|z)?sh\s+" + _OPTION_WORDS + _TRACE_ON
_SHELL_TRACE = re.compile(
    _WORD_START + r"(?:" + _SHELL_DIR + r")?(?:" + _SHELLCHECK_DIALECT + r"|" + _SHELL_ON + r")"
)
#: The long spelling anywhere on a line, also past an option's argument (``bash --rcfile x
#: --xtrace``). Always ``on``. Not ``--verbose``, which many tools take.
_LONG_XTRACE = re.compile(r"(?P<on>--" + _XTRACE + r")")


def _words(on: str) -> str:
    """The words to the end of a command, each read once: group ``on`` if one turns tracing on,
    an ``-o``/``+o`` taking the word after it."""
    return r"(?:\s+(?:(?P<on>" + on + r")|[-+][a-zA-Z]*o\s+" + _IN_WORD + r"+|" + _IN_WORD + r"+))*"


#: ``shopt`` setting ``set -o`` names, with ``-s`` and ``-o`` in its flags in any order (#3400):
#: ``shopt -so xtrace``, ``shopt -o -s errexit xtrace``. Not ``shopt -o xtrace`` (a query), ``-po``
#: (a listing) or ``-uo``. Each lookahead reads only the flags, which the match then takes.
_SHOPT_FLAGS = r"(?:\s+-[a-zA-Z-]*)*?\s+-[a-zA-Z-]*"
_SHOPT = re.compile(
    _WORD_START + r"shopt(?=" + _SHOPT_FLAGS + r"s)(?=" + _SHOPT_FLAGS + r"o)"
    r"(?:\s+-[a-zA-Z-]*)*" + _words(_TRACING)
)
#: zsh's ``setopt`` and ``unsetopt`` (#3400; zshbuiltins(1)): ``setopt xtrace``, ``setopt -x``,
#: ``unsetopt noxtrace``, ``unsetopt +o xtrace``: ``unsetopt`` flips each sign and each name
#: (``bin_setopt`` in zsh's Src/options.c).
_SETOPT = re.compile(_WORD_START + r"setopt" + _words(_turning_on("-", r"\+") + r"|" + _TRACING))
_UNSETOPT = re.compile(
    _WORD_START + r"unsetopt" + _words(_turning_on(r"\+", "-") + r"|" + _NO_TRACING)
)
#: ``SHELLOPTS`` listing xtrace or verbose (#3400): bash turns on each option it lists when it
#: starts (``env SHELLOPTS=xtrace bash x.sh``; a job's or a step's ``env:``, ``SHELLOPTS:
#: xtrace``). Bash refuses to assign it (readonly), dash exports it (``export
#: SHELLOPTS=errexit:xtrace``).
_SHELLOPTS = re.compile(
    _WORD_START + r"SHELLOPTS[\"']?\s*(?:\+?=|:)\s*[\"']?(?:[\w${}-]*:)*?(?P<on>" + _TRACING + r")"
)
#: A ``DEBUG`` trap, run before each command (#3400): ``trap 'echo "$BASH_COMMAND"' DEBUG`` prints
#: each command as ``set -v`` does, so any action counts (the scan cannot tell what it prints).
#: Not ``trap - DEBUG`` or ``trap DEBUG`` (a reset), ``trap -p DEBUG`` (a listing) or ``trap ''
#: DEBUG`` (no action). The action is one word with its quotes; a quote is read to its end.
_TRAP_ACTION = r"(?:'[^']*'|\"(?:[^\"\\]|\\.)*\"|\\.|[^\s'\"\\;&|()`])+"
_DEBUG_SIGNAL = r"[\"']?(?i:debug)[\"']?(?!" + _IN_WORD + r")"
_TRAP_DEBUG = re.compile(
    _WORD_START + r"trap\s+(?:--\s+)?(?!-|(?:''|\"\")\s)" + _TRAP_ACTION + _words(_DEBUG_SIGNAL)
)
#: zsh's ``TRAPDEBUG`` function is a ``DEBUG`` trap (zshmisc(1), Trap Functions).
_TRAPDEBUG = re.compile(_WORD_START + r"(?P<on>TRAPDEBUG)(?![\w-])")
#: The rules reported as ``'set -x' tracing``: a match with an ``on`` group. Not reported:
#: - quoted option words: ``set "-x"``, ``bash "-x"``, ``set -o "xtrace"``
#: - options built by expansion: ``set -e${DEBUG:+x}``, ``SHELLOPTS=$OPTS``
#: - a shell named through a variable (``"$BASH" -x``, ``$SHELL -x``) or quoted (``"bash" -x``)
#: - a long option's argument before it: ``bash --rcfile x.rc -x``
#: - a shell path segment with another character: ``/opt/bash@5/bin/bash -x``
#: - an ``ERR``, ``EXIT`` or ``RETURN`` trap: it runs once, on its event, not before each command
#:   (one printing ``$BASH_COMMAND`` shows the failing command's line)
#: Reported though not tracing: a shell name as another tool's option argument (``tmux new -s sh
#: -x 80``: a session named sh, 80 columns wide), ``set`` as another tool's word (``gh secret set
#: -v all X``: gh's ``--visibility``).
_SET_X = (
    _SET_TRACE,
    _SHELL_TRACE,
    _LONG_XTRACE,
    _SHOPT,
    _SETOPT,
    _UNSETOPT,
    _SHELLOPTS,
    _TRAP_DEBUG,
    _TRAPDEBUG,
)
_ENV_DUMP = re.compile(
    r"(^|[;&|]\s*|^\s*-?\s*(run:\s*)?)(printenv|env|export\s+-p|set)\s*(\||$|>)"
)
_SKIP_ALLOW = "# secrets-hygiene: allow"

_RUN_KEY = re.compile(r"^(\s*(?:-\s+)?)run:(.*)$")
_WORKDIR = re.compile(r"^\s*(?:-\s+)?working-directory:\s*[\"']?([\w./-]+)", re.MULTILINE)
#: The repository root in CI, wherever a workflow or a script it runs names it.
_WORKSPACE = re.compile(r"([\"']?)\$(?:\{?GITHUB_WORKSPACE\}?|\{\{ *github\.workspace *\}\})\1/")
#: (interpreter, path) of a command in command position, past `VAR=x`, keywords, wrappers with
#: their dash options and numeric arguments, and `bash|sh -c` (the string is a command line, a path
#: in it counting only as a direct script); `workflow_scripts` says which.
_OPTS = r"--\S*\s+|[-+][abd-zA-Z]*o\s+\w+\s+|[-+][abd-zA-Z]+\s+"
_INVOKES = re.compile(
    r"(?:^|[;&|(){`])\s*(?:(?:if|then|elif|else|do|while|until|!|exec|time|command"
    r"|(?:/usr/bin/)?env|sudo|nohup|nice|stdbuf|timeout|xvfb-run|uv\s+run)(?:\s+(?:-\S+|\d\S*))*\s+"
    r"|\w+=\S*\s+|(?:/(?:usr/)?bin/)?(?:ba)?sh\s+(?:" + _OPTS + r")*-[abd-zA-Z]*c[a-zA-Z]*\s+"
    r"(?:--\s+)?[\"']?)*"
    r"(?:(?:/(?:usr/)?bin/)?(bash|sh|source|\.)\s+(?:" + _OPTS + r")*)?[\"']?([\w.][\w./-]*)"
)
_SHEBANG = re.compile(r"#!.*\b(?:ba)?sh\b")
#: A shebang whose options trace (``#!/bin/sh -ex``, ``#!/usr/bin/env -S bash -o xtrace``,
#: ``#!/usr/bin/env -S zsh --xtrace``): line 1 of a scanned script, unless it carries the allow
#: marker (#3400; ``#!/usr/bin/env -S bash -x # secrets-hygiene: allow``: ``env -S`` reads a word
#: starting with ``#`` as a comment).
_SHEBANG_X = re.compile(r"#!.*\s" + _TRACE_WORD)
#: Suffixes never sourced as shell: ``source|.`` follows any other repository file.
_NOT_SHELL = re.compile(
    r"\.(?:md|markdown|txt|rst|py|json|ya?ml|toml|[cm]?js|tsx?|css|html|xml|csv|lock|cfg|ini|sql)"
)


def _sr146_hits(text: str) -> list[tuple[int, str]]:
    """The SR-146 line rules: (line, finding) per hit; comment and allow-marked lines skip."""
    hits: list[tuple[int, str]] = []
    for n, ln in enumerate(text.splitlines(), 1):
        if _SKIP_ALLOW in ln or ln.lstrip().startswith("#"):
            continue
        body = ln.strip().removeprefix("- run:").removeprefix("run:").strip()
        if any(m["on"] for rule in _SET_X for m in rule.finditer(body)):
            hits.append((n, "'set -x' tracing"))
        if _ENV_DUMP.search(body):
            hits.append((n, "environment dump"))
    return hits


def _code(line: str) -> str:
    """``line`` up to its comment: a ``#`` that starts a word outside quotes."""
    quote, escaped = "", False
    for i, c in enumerate(line):
        if escaped or (c == "\\" and quote != "'"):
            escaped = not escaped
        elif c == quote or (not quote and c in "\"'"):
            quote = "" if quote else c
        elif not quote and c == "#" and (i == 0 or line[i - 1].isspace()):
            return line[:i]
    return line


def _run_lines(text: str) -> list[str]:
    """The shell lines of every `run:` value in a workflow (inline or block), comments dropped."""
    lines: list[str] = []
    key_col = -1
    for ln in text.splitlines():
        if key_col >= 0 and (not ln.strip() or len(ln) - len(ln.lstrip()) > key_col):
            lines.append(_code(ln.strip()))
            continue
        m = _RUN_KEY.match(ln)
        key_col = len(m.group(1)) if m else -1
        if m and not m.group(2).strip().startswith(("|", ">")):
            value = _code(m.group(2)).strip()
            lines.append(value[1:-1] if value[:1] in "\"'" and value[-1:] == value[:1] else value)
    return lines


def _read(path: Path, size: int = -1) -> str | None:
    """``path``'s first ``size`` characters (all by default), or None if it cannot be read."""
    try:
        with path.open(encoding="utf-8", errors="replace") as f:
            return f.read(size)
    except OSError:
        return None


def _repo_file(root: Path, rel: PurePosixPath) -> Path | None:
    """``rel`` from ``root`` as a file resolving (symlinks, ``..``) inside ``root``, else None; one
    that cannot be resolved (a symlink loop) is kept, so that reading it fails the scan. Not
    ``Path.resolve``: it raises RuntimeError on a symlink loop up to Python 3.12."""
    path = Path(os.path.realpath(root / rel))
    try:
        regular = stat.S_ISREG(path.stat().st_mode)
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError:
        regular = True
    return path if path.is_relative_to(root) and regular else None


def _is_shell(path: Path, interpreter: str) -> bool:
    """Run by ``bash|sh``: any file; by ``source|.``: any without a ``_NOT_SHELL`` suffix; run
    directly: a ``.sh``/``.bash`` file or one with a sh/bash shebang (an unreadable one counts)."""
    if interpreter:
        return interpreter in ("bash", "sh") or not _NOT_SHELL.fullmatch(path.suffix)
    head = _read(path, 256)
    return path.suffix in (".sh", ".bash") or head is None or bool(_SHEBANG.match(head))


def _invoked(root: Path, bases: list[PurePosixPath], line: str) -> Iterator[str]:
    """The root-relative repository shell scripts that ``line`` runs or sources."""
    for interpreter, rel in _INVOKES.findall(line):
        if not interpreter and "/" not in rel:
            continue  # a bare command name is a PATH lookup, not a repository file
        for base in bases:
            script = _repo_file(root, base / rel)
            if script and _is_shell(script, interpreter):
                yield script.relative_to(root).as_posix()


def workflow_scripts(root: Path) -> dict[str, set[str]]:
    """Each repository shell script a workflow step runs, directly or through the scripts it runs
    (root-relative) -> its runners: ``w.yml``, or ``w.yml via <the script that runs it>`` (#3274).

    A command counts at a line start or after ``;``, ``&``, ``|``, ``(``, ``)``, ``{`` or a
    backtick, past ``VAR=x``, ``!``, ``if then elif else do while until`` and the wrappers ``exec
    time command env /usr/bin/env sudo nohup nice stdbuf timeout xvfb-run`` and ``uv run`` with
    their dash options and numeric arguments: ``bash|sh [options] <path>`` (also from ``/bin/``
    or ``/usr/bin/``) runs any file, ``source|. <path>`` any file without a ``_NOT_SHELL``
    suffix, a direct ``<dir>/<file>`` only a shell script (``.sh``/``.bash`` or a sh/bash
    shebang). Shell scripts only: SR-146's rules are shell rules, which would neither catch a
    Python leak nor stay quiet on Python text quoting them. A ``#`` starting a word outside
    quotes ends a line. Paths are tried from the root and each ``working-directory:`` of the
    workflow, in nested scripts too (errs toward scanning), a ``$GITHUB_WORKSPACE/``,
    ``${GITHUB_WORKSPACE}/``, ``"$GITHUB_WORKSPACE"/`` or ``${{ github.workspace }}/`` prefix
    being the root, and a ``bash|sh -c`` string read as a command line; one resolving
    outside the root (``..``, a symlink, absolute) is refused, a missing one skipped, one that
    cannot be read (a loop) fails the scan. Not followed: ``make``/``pnpm`` targets, ``pnpm exec
    bash``, ``npx bash``, ``eval``, paths built from any other ``$VAR`` or ``$(...)``, a
    non-script command in a ``bash -c`` string (judged as a direct command), ``cd <dir> &&
    ./x.sh`` (not tried from ``<dir>``), stdin and pipes (``cat x | bash``, ``bash < x``,
    ``xargs bash x``), a wrapper option taking a word (``timeout -s KILL``), other interpreters.
    """
    root = root.resolve()
    found: dict[str, set[str]] = {}
    wf = root / ".github" / "workflows"
    for path in sorted(wf.glob("*.y*ml")) if wf.is_dir() else []:
        text = _WORKSPACE.sub("", path.read_text(encoding="utf-8"))
        bases = [PurePosixPath(), *map(PurePosixPath, _WORKDIR.findall(text))]
        todo = [(path.name, line) for line in _run_lines(text)]
        seen: set[str] = set()
        while todo:
            runner, line = todo.pop()
            for key in _invoked(root, bases, line):
                found.setdefault(key, set()).add(runner)
                if key not in seen:
                    seen.add(key)
                    nested = _WORKSPACE.sub("", _read(root / key) or "").splitlines()
                    todo += [(f"{path.name} via {key}", _code(ln)) for ln in nested]
    return found


def check_workflows(root: Path) -> list[str]:
    errors: list[str] = []
    wf = root / ".github" / "workflows"
    for path in sorted(wf.glob("*.y*ml")) if wf.is_dir() else []:
        for n, what in _sr146_hits(path.read_text(encoding="utf-8")):
            errors.append(f"{path.name}:{n}: {what} (SR-146)")
    for rel, runners in sorted(workflow_scripts(root).items()):
        by = f"run by {', '.join(sorted(runners))}"
        text = _read(root / rel)
        if text is None:
            errors.append(f"{rel}: unreadable script (SR-146 scan); {by}")
        line1 = (text or "").partition("\n")[0]
        if _SHEBANG_X.match(line1) and _SKIP_ALLOW not in line1:
            errors.append(f"{rel}:1: 'set -x' tracing (SR-146); {by}")
        for n, what in _sr146_hits(text or ""):
            errors.append(f"{rel}:{n}: {what} (SR-146); {by}")
    return errors


_FORBIDDEN_SECRET = re.compile(
    r"(?i)(LIVE.*(API[_-]?(KEY|SECRET))|(API[_-]?(KEY|SECRET)).*(LIVE|PROD)|"
    r"(PROD|PRODUCTION).*KEK|KEK.*(PROD|PRODUCTION)|FUNDED)"
)
_LONG_LIVED = re.compile(
    r"(?i)(AWS_SECRET_ACCESS_KEY|GCP_SA_KEY|AZURE_CLIENT_SECRET|_PAT$)"
)


def check_inventory(
    names: list[str], release_bearing_protected: dict[str, bool] | None = None
) -> list[str]:
    errors: list[str] = []
    for name in names:
        if _FORBIDDEN_SECRET.search(name):
            errors.append(
                f"secret '{name}': production exchange credential / KEK in CI (SR-140); {IR02}"
            )
        if _LONG_LIVED.search(name):
            errors.append(f"secret '{name}': long-lived token; prefer OIDC (SR-141)")
    for name, ok in (release_bearing_protected or {}).items():
        if not ok:
            errors.append(
                f"secret '{name}': release-bearing but not environment-scoped with reviewers (SR-141)"
            )
    return errors


def check_logs(paths: list[Path]) -> list[str]:
    errors: list[str] = []
    for p in paths:
        files = [f for f in p.rglob("*") if f.is_file()] if p.is_dir() else [p]
        for f in files:
            text = f.read_text(encoding="utf-8", errors="replace")
            for hit in scan_text(text):
                errors.append(f"{f.as_posix()}: {hit} in log/artefact (SR-146); {IR02}")
    return errors


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "check",
        choices=["fixtures", "dev-env", "workflows", "inventory", "logs", "all"],
    )
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--root", default=".")
    ns = ap.parse_args(argv)
    root = Path(ns.root).resolve()
    errors: list[str] = []
    if ns.check in ("fixtures", "all"):
        errors += check_fixtures(root)
    if ns.check in ("dev-env", "all"):
        errors += check_dev_env(root)
    if ns.check in ("workflows", "all"):
        errors += check_workflows(root)
    if ns.check == "inventory":
        errors += check_inventory(
            json.loads(Path(ns.paths[0]).read_text(encoding="utf-8"))
        )
    if ns.check == "logs":
        errors += check_logs([Path(p) for p in ns.paths])
    for e in errors:
        print(f"FAIL {e}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())

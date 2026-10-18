"""Assertion library for the `electron-hardening` gate (E10-X02, SR-110..SR-119, SR-174).

All checks are pure functions over already-read text/facts so the broken-fixture
meta-tests can drive each one directly. See `electron_hardening_gate.py` for the CLI.
"""

from __future__ import annotations

import itertools
import posixpath
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SEC_DOC = "docs/plan/04-security-program.md"
ROW = f"{SEC_DOC} section 6.11"
# SR-173..SR-182 live in section 6.11a (E10 threat model controls).
ROW_6_11A = f"{SEC_DOC} section 6.11a"
SR_IN_6_11A = frozenset({"SR-174"})

# SR-110: the exact, closed webPreferences set (enableRemoteModule must be ABSENT).
SR110_REQUIRED: dict[str, bool] = {
    "contextIsolation": True,
    "nodeIntegration": False,
    "nodeIntegrationInWorker": False,
    "nodeIntegrationInSubFrames": False,
    "sandbox": True,
    "webSecurity": True,
    "allowRunningInsecureContent": False,
    "experimentalFeatures": False,
}

# Electron omits these from getLastWebPreferences() when they hold the (secure) default, so a
# missing key is compliant for the *live* check; an explicit insecure value still fails. The
# explicit literal is asserted statically by check_declared_prefs().
ABSENT_MEANS_DEFAULT = frozenset({"nodeIntegrationInWorker"})

# SR-174: the closed privilege set of the shell's app:// scheme (APP_SCHEME_PRIVILEGES in
# apps/desktop/src/main/appProtocol.ts, declared once with Object.freeze). Widening it is a
# deliberate change made here, in review.
APP_SCHEME_PRIVILEGES: dict[str, bool] = {"standard": True, "secure": True}

# SR-174: the one origin the app:// handler serves (APP_SCHEME and APP_HOST in appProtocol.ts).
APP_ORIGIN = "app://candleviewer"

# SR-112: the app:// handler responses collect-hardening-facts.mjs fetches from the packaged
# main process (same list there), with the status each must get: the page, a missing asset and
# an /api path (the SPA fallback leaves both 404), a non-GET method (405) and a client route
# with no extension, which the SPA fallback answers with index.html (200).
APP_PROBES: dict[tuple[str, str], int] = {
    ("GET", f"{APP_ORIGIN}/"): 200,
    ("GET", f"{APP_ORIGIN}/assets/cv-hardening-probe.js"): 404,
    ("GET", f"{APP_ORIGIN}/api/cv-hardening-probe"): 404,
    ("POST", f"{APP_ORIGIN}/"): 405,
    ("GET", f"{APP_ORIGIN}/login"): 200,
}

# SR-114: the top-level entries of apps/desktop/dist the build emits; the scans below cover both.
DIST_DIRS = frozenset({"main", "preload"})

# SR-112: directives whose value must match verbatim (connect-src handled separately).
SR112_EXACT: dict[str, str] = {
    "default-src": "'self'",
    "script-src": "'self'",
    "style-src": "'self' 'unsafe-inline'",
    "img-src": "'self' data: blob:",
    "worker-src": "'self' blob:",
    "object-src": "'none'",
    "frame-ancestors": "'none'",
    "base-uri": "'none'",
    "form-action": "'none'",
}

# SR-119: any exchange host (both vendor domains), incl. regional and stream* subdomains.
BYBIT_HOST_RE = re.compile(
    # nosemgrep: cv-adapter-isolation reason=B5-b owner=@CandleViewer/security review=2026-12-31
    r"(?i)[a-z0-9*.-]*\b(?:bybit|bytick)[a-z0-9-]*(?:\.[a-z]{2,})+"
)

# SR-114 / SR-116: affordances that must never appear in a release build.
DEV_AFFORDANCES: tuple[tuple[str, str], ...] = (
    (r"\bopenDevTools\s*\(", "devtools auto-open (openDevTools)"),
    (r"devTools\s*:\s*(?:true|!0)", "devTools enabled in webPreferences"),
    (r"remote-debugging-(?:port|pipe)", "remote debugging port/pipe switch"),
    (r"--inspect(?:-brk)?\b", "node inspector switch"),
    (
        r"__CV_TEST_HOOK__|CV_TEST_HOOK|CV_E2E_HOOK|__cvTestHook",
        "test-only main-process hook",
    ),
    (r"unsafe-eval", "relaxed dev CSP token (unsafe-eval)"),
    (r"webSecurity\s*:\s*(?:false|!1)", "webSecurity disabled"),
)


@dataclass(frozen=True)
class Violation:
    sr: str
    subject: str
    message: str

    def render(self) -> str:
        row = ROW_6_11A if self.sr in SR_IN_6_11A else ROW
        return f"{self.sr} violated by {self.subject}: {self.message} [see {row}, {self.sr}]"


def parse_csp(csp: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in csp.split(";"):
        part = part.strip()
        if not part:
            continue
        name, _, value = part.partition(" ")
        out[name.strip().lower()] = " ".join(value.split())
    return out


def check_webprefs(window: str, prefs: dict[str, Any]) -> list[Violation]:
    """SR-110 over one window's live/declared webPreferences."""
    vs: list[Violation] = []
    for key, want in SR110_REQUIRED.items():
        got = prefs.get(key)
        if got is None and key in ABSENT_MEANS_DEFAULT:
            continue
        if got is not want:
            vs.append(
                Violation(
                    "SR-110",
                    f"window '{window}'",
                    f"webPreferences.{key} is {got!r}, SR-110 requires {want!r}",
                )
            )
    if "enableRemoteModule" in prefs:
        vs.append(
            Violation(
                "SR-110",
                f"window '{window}'",
                "webPreferences.enableRemoteModule must be absent, never set",
            )
        )
    return vs


def check_declared_prefs(shell_port_js: str) -> list[Violation]:
    """SR-110 static: the compiled HARDENED_WEB_PREFERENCES sets every flag explicitly."""
    m = re.search(r"HARDENED_WEB_PREFERENCES\s*=\s*\{(.*?)\}", shell_port_js, re.DOTALL)
    if m is None:
        return [
            Violation("SR-110", "main shellPort", "HARDENED_WEB_PREFERENCES not found")
        ]
    declared = dict(re.findall(r"([A-Za-z]+)\s*:\s*(true|false)", m.group(1)))
    vs: list[Violation] = []
    for key, want in SR110_REQUIRED.items():
        if declared.get(key) != ("true" if want else "false"):
            vs.append(
                Violation(
                    "SR-110",
                    "main shellPort",
                    f"declared {key} is {declared.get(key)!r}, SR-110 requires {str(want).lower()}",
                )
            )
    return vs


def _call_args(js: str, name: str) -> list[str]:
    """The argument text of every `x.name(...)` or `x["name"](...)` call, by balanced parens."""
    found: list[str] = []
    for m in re.finditer(r"\b" + re.escape(name) + r"(?:[\"'`]\s*\])?\s*\(", js):
        depth, i = 1, m.end()
        while i < len(js) and depth:
            depth += {"(": 1, ")": -1}.get(js[i], 0)
            i += 1
        found.append(js[m.end() : i - 1])
    return found


# An assignment operator (`=`, `+=`, `||=`, ...), not a comparison (`==`, `<=`) or an arrow.
_ASSIGN = r"\s*(?:\*\*|\?\?|\|\||&&|<<|>>>?|[-+*/%&|^])?=(?![=>])"


def check_app_scheme(main_js: str) -> list[Violation]:
    """SR-112 + SR-174: the web app is served over the scoped app:// handler, under the CSP.

    No privileged scheme may bypass the CSP. The app scheme keeps its closed privilege set,
    declared once with Object.freeze and never written to, and is the only scheme registered
    (one call, passing the constant itself, not a copy or a spread). No window loads from a
    file: URL (a file: page is outside the handler's asset root).
    These are text heuristics over the compiled main process, comments included, so a comment
    that names a checked call or `loadFile` can turn the gate red. `loadURL` and
    `registerSchemesAsPrivileged` may appear only as direct calls, so an alias,
    bind/call/apply or an optional call fails. The file: check sees any `loadFile` and a
    quoted `file:` literal or `pathToFileURL` anywhere in a `loadURL` argument. It does not
    see a file: URL built elsewhere and passed in a variable, a name or literal assembled
    from parts (`win["load" + "URL"]`, `"fi" + "le:"`), or a write through Object.assign or
    defineProperty, which the freeze makes throw. The unit tests in apps/desktop/test pin
    the real call arguments and that the constant is frozen.
    """
    vs: list[Violation] = []
    if re.search(r"\bbypassCSP(?:[\"'`]\s*\]?)?\s*:\s*(?:true|!0)", main_js):
        vs.append(
            Violation(
                "SR-112",
                "main privileged scheme",
                "a privileged scheme sets bypassCSP; every app page must stay under the CSP",
            )
        )
    decls = [
        m.end() for m in re.finditer(r"\bAPP_SCHEME_PRIVILEGES" + _ASSIGN, main_js)
    ]
    m = (
        re.match(
            r"\s*Object\.freeze\(\s*\{(.*?)\}\s*\)", main_js[decls[0] :], re.DOTALL
        )
        if len(decls) == 1
        else None
    )
    pair = r"([A-Za-z]+)\s*:\s*(true|false|!0|!1)"
    declared = (
        {key: value in {"true", "!0"} for key, value in re.findall(pair, m.group(1))}
        if m and not re.sub(pair, "", m.group(1)).replace(",", "").strip()
        else None
    )
    if declared != APP_SCHEME_PRIVILEGES:
        vs.append(
            Violation(
                "SR-174",
                "main appProtocol",
                f"declare APP_SCHEME_PRIVILEGES once, as Object.freeze of the allowed set "
                f"{APP_SCHEME_PRIVILEGES!r}; found {len(decls)} declaration(s), "
                f"privileges {declared!r}",
            )
        )
    member = r"\s*(?:\.\s*[\w$]+|\[[^\]]*\])"
    if re.search(r"\bAPP_SCHEME_PRIVILEGES" + member + _ASSIGN, main_js):
        vs.append(
            Violation(
                "SR-174",
                "main appProtocol",
                "code writes to APP_SCHEME_PRIVILEGES; the set is fixed where it is declared",
            )
        )
    calls = [
        # Whitespace and trailing commas are formatting, so a reflowed call still matches.
        re.sub(r",(?=[\]}])", "", re.sub(r"\s+", "", a))
        for a in _call_args(main_js, "registerSchemesAsPrivileged")
    ]
    if calls != ["[{scheme:APP_SCHEME,privileges:APP_SCHEME_PRIVILEGES}]"]:
        vs.append(
            Violation(
                "SR-174",
                "main registerSchemesAsPrivileged",
                f"expected one call registering only APP_SCHEME with APP_SCHEME_PRIVILEGES, "
                f"found {len(calls)} call(s)",
            )
        )
    loads = _call_args(main_js, "loadURL")
    if re.search(r"\bloadFile\b", main_js) or any(
        re.search(r"[\"'`]file:", a, re.IGNORECASE) or "pathToFileURL" in a
        for a in loads
    ):
        vs.append(
            Violation(
                "SR-174",
                "main window load",
                "a window loads a file: URL; serve the web app through the app:// handler",
            )
        )
    for name, subject in (
        ("registerSchemesAsPrivileged", "main registerSchemesAsPrivileged"),
        ("loadURL", "main window load"),
    ):
        # Not followed by `(` or `"](`: the checks above only read direct calls.
        if re.search(r"\b" + name + r"\b(?!\s*\(|[\"'`]\s*\]\s*\()", main_js):
            vs.append(
                Violation(
                    "SR-174",
                    subject,
                    f"{name} is used other than by a direct call (an alias, "
                    f"bind/call/apply or an optional call); call it directly so its "
                    f"arguments are checked",
                )
            )
    return vs


def check_csp(source: str, csp: str) -> list[Violation]:
    """SR-112 (verbatim directives, no unsafe-eval) + SR-119 (no exchange host)."""
    vs: list[Violation] = []
    d = parse_csp(csp)
    for name, want in SR112_EXACT.items():
        if name not in d:
            vs.append(
                Violation(
                    "SR-112", source, f"directive '{name}' is missing; need '{want}'"
                )
            )
        elif d[name] != want:
            vs.append(
                Violation(
                    "SR-112",
                    source,
                    f"directive '{name}' is '{d[name]}', need '{want}'",
                )
            )
    if "unsafe-eval" in csp:
        vs.append(Violation("SR-112", source, "CSP contains 'unsafe-eval' (forbidden)"))
    connect = d.get("connect-src")
    if connect is None:
        vs.append(Violation("SR-112", source, "directive 'connect-src' is missing"))
    else:
        toks = connect.split()
        if not toks or toks[0] != "'self'":
            vs.append(Violation("SR-112", source, "connect-src must start with 'self'"))
        for tok in toks[1:]:
            if (
                tok == "*"
                or tok.startswith("*.")
                or tok in {"http:", "https:", "ws:", "wss:"}
            ):
                vs.append(
                    Violation(
                        "SR-112", source, f"connect-src wildcard/scheme-only '{tok}'"
                    )
                )
    for m in BYBIT_HOST_RE.finditer(csp):
        vs.append(
            Violation(
                "SR-119",
                source,
                f"Exchange host '{m.group(0)}' in CSP; all exchange traffic is backend-only "
                "(single chokepoint: credentials, per-UID rate tracker, env capability record)",
            )
        )
    return vs


FORBIDDEN_BRIDGE_KEYS = frozenset(
    {
        "invoke",
        "send",
        "sendSync",
        "sendTo",
        "on",
        "once",
        "postMessage",
        "ipcRenderer",
        "ipc",
    }
)
CHANNEL_RE = re.compile(r"[\"'](cv:[A-Za-z0-9:_.-]+)[\"']")


def check_dev_affordances(subject: str, text: str) -> list[Violation]:
    """SR-114/SR-116 (STRIDE E4/E6): nothing dev-only may ship in a release build."""
    vs: list[Violation] = []
    for pattern, label in DEV_AFFORDANCES:
        if re.search(pattern, text):
            vs.append(Violation("SR-114", subject, f"release build contains {label}"))
    return vs


def check_bundle_hosts(subject: str, text: str) -> list[Violation]:
    """SR-119: no exchange host in renderer-bundled code (string scan)."""
    seen: set[str] = set()
    vs: list[Violation] = []
    for m in BYBIT_HOST_RE.finditer(text):
        host = m.group(0).lower()
        if host not in seen:
            seen.add(host)
            vs.append(
                Violation(
                    "SR-119",
                    subject,
                    f"Exchange host '{host}' in bundled code; exchange traffic is backend-only",
                )
            )
    return vs


def check_auto_update(web_bundle: str, updates_js: str) -> list[Violation]:
    """SR-115: capabilities.autoUpdate === false while signing is not operational."""
    vs: list[Violation] = []
    if re.search(r"autoUpdate\s*:\s*(?:!0|true)", web_bundle):
        vs.append(
            Violation(
                "SR-115",
                "renderer bundle",
                "a capabilities object sets autoUpdate: true; must be false until code signing "
                "(R5/E48) is operational",
            )
        )
    m = re.search(
        r"function\s+isAutoUpdateEnabled\s*\(\s*\)\s*\{(.*?)\}", updates_js, re.DOTALL
    )
    if m is None or not re.fullmatch(r"\s*return\s+false\s*;?\s*", m.group(1)):
        vs.append(
            Violation(
                "SR-115",
                "main updateChannel",
                "isAutoUpdateEnabled() must be a constant `return false`",
            )
        )
    return vs


def check_preload(preload_js: str, allow_list_js: str, main_js: str) -> list[Violation]:
    """SR-111 structural: no generic invoke/ipcRenderer passthrough; channel table is closed."""
    vs: list[Violation] = []
    subject = "preload bundle"
    exposed = re.findall(
        r"exposeInMainWorld\(\s*[\"']([^\"']+)[\"']\s*,\s*([A-Za-z_$][\w$]*)",
        preload_js,
    )
    if [n for n, _ in exposed] != ["cv"]:
        vs.append(
            Violation(
                "SR-111",
                subject,
                f"must expose exactly one namespace 'cv', got {exposed}",
            )
        )
    for _, ident in exposed:
        if ident == "ipcRenderer":
            vs.append(Violation("SR-111", subject, "exposes ipcRenderer directly"))
    if re.search(
        r"ipcRenderer\s*\.\s*(?:send|sendSync|sendTo|on|once|postMessage)\b", preload_js
    ):
        vs.append(Violation("SR-111", subject, "uses a non-invoke ipcRenderer method"))
    for m in re.finditer(r"ipcRenderer\s*\.\s*invoke\s*\(\s*([^,)]+)", preload_js):
        arg = m.group(1).strip()
        if arg == "channel":
            # the single guarded helper; it must re-check the allow-list first
            if "isChannelAllowed" not in preload_js:
                vs.append(
                    Violation(
                        "SR-111", subject, "dynamic channel without allow-list check"
                    )
                )
        elif not CHANNEL_RE.fullmatch(arg):
            vs.append(
                Violation(
                    "SR-111", subject, f"invoke() with non-literal channel '{arg}'"
                )
            )
    cv_obj = re.search(r"Object\.freeze\(\{(.*?)\}\)", preload_js, re.DOTALL)
    if cv_obj:
        for key in re.findall(r"(?:^|[,{\s])([A-Za-z_$][\w$]*)\s*:", cv_obj.group(1)):
            if key in FORBIDDEN_BRIDGE_KEYS:
                vs.append(
                    Violation("SR-111", subject, f"bridge exposes generic key '{key}'")
                )
    table = set(CHANNEL_RE.findall(allow_list_js))
    used = set(CHANNEL_RE.findall(preload_js)) - table
    if used:
        vs.append(
            Violation(
                "SR-111", subject, f"channels not in allow-list table: {sorted(used)}"
            )
        )
    handled = set(
        re.findall(r"ipcMain\s*\.\s*handle\(\s*[\"'](cv:[^\"']+)[\"']", main_js)
    )
    if handled != table:
        vs.append(
            Violation(
                "SR-111",
                "main ipcMain handlers",
                f"handlers {sorted(handled)} differ from allow-list table {sorted(table)}",
            )
        )
    return vs


# SR-116 / SR-174: electron-builder's packaging lists, the pattern that keeps source maps out,
# and where the packaged main process reads the web app (index.ts resolves
# dist/main/../../../web/dist from inside app.asar, which is <resources>/web/dist).
PACKAGING_KEYS = ("files", "extraResources", "extraFiles")
MAP_EXCLUSION = "!**/*.map"
WEB_DIST_TO = "web/dist"
_ITEM = re.compile(r"( *)- +(.*)")
_FIELD = re.compile(r"( *)(\w+):(?: +(.*))?")
# Plain scalars YAML does not read as a string: a boolean, null, number, date or mapping.
_NOT_STRING = re.compile(
    r"(?i)true|false|yes|no|on|off|null|\.?\d.*|\.inf|\.nan|.*:(\s.*)?"
)


def _uncomment(text: str) -> str:
    return re.sub(r"(?:^|\s)#.*", "", text).strip()


def _scalar(text: str) -> str | None:
    """One plain or quoted YAML string; None for anything else (escapes, flow, anchors)."""
    m = re.fullmatch(r"\"([^\"\\]*)\"|'([^']*)'|([\w./$][^#]*)", _uncomment(text))
    if m is None or _NOT_STRING.fullmatch(m[3] or ""):
        return None
    return next(g for g in m.groups() if g is not None)


def _block_list(lines: list[str]) -> list[Any] | str:
    """A block list of patterns and of {from, to, filter} entries, or why it is unreadable."""
    items: list[Any] = []
    top = len(lines[0]) - len(lines[0].lstrip(" ")) if lines else 0
    key_col, in_filter = -1, False
    for line in lines:
        col, item = len(line) - len(line.lstrip(" ")), _ITEM.fullmatch(line)
        if item and col == top:
            rest = item.group(2)
            if _FIELD.fullmatch(rest) is None:
                if (value := _scalar(rest)) is None:
                    return f"unreadable item {rest.strip()!r}"
                items.append(value)
                key_col = -1
                continue
            items.append({})
            key_col = col = len(line) - len(rest)
            line, item = " " * col + rest, None
        entry = items[-1] if items and isinstance(items[-1], dict) else None
        field = _FIELD.fullmatch(line)
        if entry is not None and field and col == key_col:
            key, raw = field.group(2), _uncomment(field.group(3) or "")
            if key not in ("from", "to", "filter") or key in entry:
                return f"unexpected field {key!r}"
            in_filter = key == "filter" and raw == ""
            val = list[str]() if in_filter or raw == "[]" else _scalar(raw)
            if val is None:
                return f"unreadable {key} value {raw!r}"
            entry[key] = [val] if key == "filter" and isinstance(val, str) else val
        elif entry is not None and item and in_filter and col >= key_col:
            if (value := _scalar(item.group(2))) is None:
                return f"unreadable filter pattern {item.group(2).strip()!r}"
            entry["filter"].append(value)
        else:
            return f"unreadable line {line.strip()!r}"
    return items


def _packaging_lists(text: str) -> dict[str, list[Any] | str]:
    """The top-level PACKAGING_KEYS of electron-builder.yml, each as its list or as the
    reason it cannot be read."""
    lines = [ln for ln in text.splitlines() if ln.strip() and ln.lstrip()[0] != "#"]
    out: dict[str, list[Any] | str] = {}
    for i, line in enumerate(lines):
        m = re.fullmatch(r"(files|extraResources|extraFiles):(?:\s(.*))?", line)
        if m is None:
            continue
        key, value = m.group(1), _uncomment(m.group(2) or "")
        block = list(itertools.takewhile(lambda ln: ln[0] in " \t-", lines[i + 1 :]))
        if key in out or (value and block):
            out[key] = "declared twice" if key in out else "a value and a block"
        elif re.fullmatch(r"\[\s*\]", value):
            out[key] = []
        elif value:
            scalar = _scalar(value)
            out[key] = [scalar] if scalar is not None else f"unreadable value {value!r}"
        else:
            out[key] = _block_list(block)
    return out


def _excludes_maps(patterns: list[str]) -> bool:
    """True when ordered patterns leave out every .map file. electron-builder applies them in
    order (minimatch: an odd count of leading '!' excludes) and an include re-adds what it
    matches, so after the last MAP_EXCLUSION only exclusions may follow."""
    if MAP_EXCLUSION not in patterns:
        return False
    tail = patterns[len(patterns) - patterns[::-1].index(MAP_EXCLUSION) :]
    return all((len(p) - len(p.lstrip("!"))) % 2 == 1 for p in tail)


def check_packaging(text: str, config_dir: Path, web_dist: Path) -> list[Violation]:
    """SR-116: no source map is packaged. SR-174: the web dist is the packaged asset root.

    Reads the top-level files, extraResources and extraFiles of electron-builder.yml as a
    small YAML subset (block lists of plain or escape-free quoted patterns and of
    {from, to, filter} entries, or `[]`); any other form fails closed, as do these keys
    anywhere else (a platform section adds to them). A list's patterns and each entry's
    filter must leave out every .map file (_excludes_maps); no filter, or no `files`,
    packages everything. One extraResources entry must copy the web dist this gate scanned
    to web/dist, the root the packaged app:// handler serves; `from` resolves against the
    config's directory, the project directory of build:installer. Not seen: `extends`,
    another entry writing under web/dist, and files a build hook copies.
    """
    subject = "electron-builder.yml"
    vs: list[Violation] = []
    body = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
    keys = r"(files|extraResources|extraFiles)[\"']?[ \t]*:"
    nested = re.findall(r"(?m)(?:^[ \t]+[\"']?|^[\"']|[{,][ \t]*[\"']?)" + keys, body)
    if nested:
        msg = (
            f"{sorted(set(nested))} outside the top level (a platform section, a flow "
            "mapping or a quoted key) is not checked; declare it at the top level"
        )
        vs.append(Violation("SR-116", subject, msg))
    lists = _packaging_lists(text)
    for key in PACKAGING_KEYS:
        items = lists.get(key, ["**/*"] if key == "files" else [])
        if isinstance(items, str):
            msg = f"cannot read {key}: {items}; use a block list (see check_packaging)"
            vs.append(Violation("SR-116", subject, msg))
            continue
        patterns = [p for p in items if isinstance(p, str)]
        sets = [(f"{key} patterns", patterns)] if patterns else []
        sets += [
            (f"{key} entry from {e.get('from')!r}", e.get("filter", []))
            for e in items
            if isinstance(e, dict)
        ]
        for label, pats in sets:
            if not _excludes_maps(pats):
                msg = (
                    f"{label} could package source maps: end its patterns with "
                    f"'{MAP_EXCLUSION}' and add no include after it"
                )
                vs.append(Violation("SR-116", subject, msg))
    resources = lists.get("extraResources", [])
    if isinstance(resources, list) and not any(
        isinstance(e, dict)
        and isinstance(e.get("from"), str)
        and isinstance(e.get("to"), str)
        and (config_dir / e["from"]).resolve() == web_dist.resolve()
        and posixpath.normpath(e["to"]) == WEB_DIST_TO
        for e in resources
    ):
        msg = (
            f"extraResources must copy the web dist this gate scanned ({web_dist}) to "
            f"'{WEB_DIST_TO}', the asset root the packaged app:// handler serves"
        )
        vs.append(Violation("SR-174", subject, msg))
    return vs


def extract_meta_csp(html: str) -> str | None:
    m = re.search(
        r"<meta[^>]+http-equiv=[\"']Content-Security-Policy[\"'][^>]*content=\"([^\"]*)\"",
        html,
        re.IGNORECASE | re.DOTALL,
    )
    return m.group(1) if m else None


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def _mistyped_fields(p: dict[str, Any]) -> list[str]:
    """The fields of one collected app:// response that have the wrong JSON type. A null status
    or csp is allowed: the collector writes it when a fetch fails or the header is absent, and
    check_app_responses() reports that by name."""
    status, csp = p.get("status"), p.get("csp")
    ok = {
        "method": isinstance(p.get("method"), str),
        "url": isinstance(p.get("url"), str),
        # A JSON number: bool is an int subclass, so true and false must not pass.
        "status": status is None or type(status) is int,
        "csp": csp is None or isinstance(csp, str),
    }
    return [field for field, good in ok.items() if not good]


def check_app_responses(probes: Any, header_csp: Any, require: bool) -> list[Violation]:
    """SR-112: the app:// handler's responses, 404 and 405 included, carry the main-process CSP.

    The status shows which handler path answered. The header must hold the main-process CSP's
    tokens in the same order: comparing parse_csp() dicts would miss a repeated directive, which
    the browser enforces by its first occurrence. Absent facts fail only under --require-runtime.
    A mistyped entry, or a second response for the same request, is a violation too, so every
    collected response is judged; the first copy of a request is the one checked below.
    """
    if probes is None and not require:
        return []
    vs: list[Violation] = []
    got: dict[tuple[str, str], dict[str, Any]] = {}
    for i, p in enumerate(probes if isinstance(probes, list) else []):
        where = f"facts appProbes[{i}]"
        if not isinstance(p, dict):
            vs.append(Violation("SR-112", where, "is not an object"))
            continue
        bad = _mistyped_fields(p)
        if bad:
            need = "method and url strings, status an integer or null, csp a string or null"
            msg = f"wrong type for {', '.join(bad)} (need {need})"
            vs.append(Violation("SR-112", where, msg))
            continue
        key = (p["method"], p["url"])
        if key in got:
            subject = f"app:// handler {key[0]} {key[1]}"
            vs.append(Violation("SR-112", subject, "collected more than once"))
            continue
        got[key] = p
    for (method, url), status in APP_PROBES.items():
        subject = f"app:// handler {method} {url}"
        p = got.get((method, url))
        if p is None:
            vs.append(Violation("SR-112", subject, "no response collected"))
            continue
        if p.get("status") != status:
            msg = f"status is {p.get('status')!r}, need {status}"
            vs.append(Violation("SR-112", subject, msg))
        csp = p.get("csp")
        if not isinstance(csp, str):
            vs.append(Violation("SR-112", subject, "no Content-Security-Policy header"))
        elif not isinstance(header_csp, str) or csp.split() != header_csp.split():
            msg = "CSP header differs from the main-process CSP"
            vs.append(Violation("SR-112", subject, msg))
    return vs


def check_window_url(window: str, url: Any) -> list[Violation]:
    """SR-174: a window shows the web app from the app:// handler's one origin.

    A prefix match on the URL the window reports, so the scheme is app and the host exactly
    candleviewer: no file: page, userinfo, port or look-alike host.
    """
    if isinstance(url, str) and url.startswith(f"{APP_ORIGIN}/"):
        return []
    return [
        Violation(
            "SR-174",
            f"window '{window}'",
            f"shows {url!r}; a window must show the web app from {APP_ORIGIN}/",
        )
    ]


def check_runtime_facts(
    facts: dict[str, Any], meta_csp: str | None, require: bool
) -> list[Violation]:
    """Live facts from the packaged app: the CSP header, the app:// handler's responses and
    every window's webPreferences and URL."""
    vs: list[Violation] = []
    header_csp = facts.get("cspHeader")
    if isinstance(header_csp, str):
        vs += check_csp("main-process CSP header", header_csp)
        if meta_csp is not None and parse_csp(meta_csp) != parse_csp(header_csp):
            vs.append(
                Violation("SR-112", "CSP header vs <meta>", "header and <meta> differ")
            )
    elif require:
        vs.append(Violation("SR-112", "facts", "no CSP header fact collected"))
    windows = facts.get("windows")
    if isinstance(windows, list) and windows:
        for w in windows:
            name = str(w.get("name", "?"))
            vs += check_webprefs(name, dict(w.get("webPreferences", {})))
            if require or "url" in w:
                vs += check_window_url(name, w.get("url"))
            # Env word in the title is an a11y disclosure; enforced once the env badge
            # ticket lands it (collector sets requireEnvTitle).
            if facts.get("requireEnvTitle") and not re.search(
                r"(?i)\b(demo|live|testnet)\b", str(w.get("title", ""))
            ):
                vs.append(
                    Violation(
                        "SR-110", f"window '{name}'", "title must include the env word"
                    )
                )
    elif require:
        vs.append(
            Violation("SR-110", "facts", "no live window webPreferences collected")
        )
    vs += check_app_responses(facts.get("appProbes"), header_csp, require)
    return vs


def run_all_checks(
    *,
    desktop_dist: Path,
    web_dist: Path,
    builder_config: Path,
    facts: dict[str, Any],
    require_runtime: bool = False,
) -> list[Violation]:
    # Recursive, so a module in a sub-directory of main/ or preload/ is scanned too.
    main_files = sorted((desktop_dist / "main").rglob("*.js"))
    preload_files = sorted((desktop_dist / "preload").rglob("*.js"))
    if not main_files or not preload_files:
        return [
            Violation(
                "SR-114", str(desktop_dist), "packaged main/preload output not found"
            )
        ]
    vs: list[Violation] = []
    # electron-builder packages all of dist/ but the scans read only main/ and preload/.
    unscanned = sorted({p.name for p in desktop_dist.iterdir()} - DIST_DIRS)
    if unscanned:
        msg = (
            f"top-level {unscanned} would be packaged but is not scanned; build into "
            "main/ or preload/, or extend the gate's scans"
        )
        vs.append(Violation("SR-114", str(desktop_dist), msg))
    main_js = "\n".join(_read(p) for p in main_files)
    for p in main_files + preload_files:
        vs += check_dev_affordances(p.relative_to(desktop_dist).as_posix(), _read(p))
    bundle_files = (
        sorted((web_dist / "assets").glob("*.js")) if web_dist.is_dir() else []
    )
    html = _read(web_dist / "index.html")
    if not bundle_files or not html:
        vs.append(
            Violation("SR-114", str(web_dist), "renderer bundle/index.html not found")
        )
    web_js = "\n".join(_read(p) for p in bundle_files)
    for p in bundle_files:
        vs += check_bundle_hosts(f"renderer bundle {p.name}", _read(p))
        vs += check_dev_affordances(f"renderer bundle {p.name}", _read(p))
    meta = extract_meta_csp(html)
    if meta is None:
        vs.append(Violation("SR-112", "index.html", "CSP <meta> fallback is missing"))
    else:
        vs += check_csp("index.html <meta> CSP", meta)
    vs += check_declared_prefs(_read(desktop_dist / "main" / "shellPort.js"))
    vs += check_app_scheme(main_js)
    vs += check_runtime_facts(facts, meta, require_runtime)
    vs += check_auto_update(web_js, _read(desktop_dist / "main" / "updateChannel.js"))
    vs += check_preload(
        _read(desktop_dist / "preload" / "index.js"),
        _read(desktop_dist / "preload" / "allowList.js"),
        main_js,
    )
    vs += check_packaging(_read(builder_config), builder_config.parent, web_dist)
    return vs

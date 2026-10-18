"""Assertion library for the `electron-hardening` gate (E10-X02, SR-110..SR-119).

All checks are pure functions over already-read text/facts so the broken-fixture
meta-tests can drive each one directly. See `electron_hardening_gate.py` for the CLI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SEC_DOC = "docs/plan/04-security-program.md"
ROW = f"{SEC_DOC} section 6.11"

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
        return f"{self.sr} violated by {self.subject}: {self.message} [see {ROW}, {self.sr}]"


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


def check_packaging(builder_config_text: str) -> list[Violation]:
    """SR-116: source maps are not shipped to production users."""
    if re.search(
        r"^\s*-\s*[\"']?!\*\*/\*\.map[\"']?\s*$", builder_config_text, re.MULTILINE
    ):
        return []
    return [
        Violation(
            "SR-116",
            "electron-builder.yml",
            "files must exclude source maps ('!**/*.map') from the packaged artefact",
        )
    ]


def extract_meta_csp(html: str) -> str | None:
    m = re.search(
        r"<meta[^>]+http-equiv=[\"']Content-Security-Policy[\"'][^>]*content=\"([^\"]*)\"",
        html,
        re.IGNORECASE | re.DOTALL,
    )
    return m.group(1) if m else None


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8") if p.is_file() else ""


def check_runtime_facts(
    facts: dict[str, Any], meta_csp: str | None, require: bool
) -> list[Violation]:
    """Live facts from the packaged app: CSP header + every window's webPreferences."""
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
    return vs


def run_all_checks(
    *,
    desktop_dist: Path,
    web_dist: Path,
    builder_config: Path,
    facts: dict[str, Any],
    require_runtime: bool = False,
) -> list[Violation]:
    main_files = sorted((desktop_dist / "main").glob("*.js"))
    preload_files = sorted((desktop_dist / "preload").glob("*.js"))
    if not main_files or not preload_files:
        return [
            Violation(
                "SR-114", str(desktop_dist), "packaged main/preload output not found"
            )
        ]
    vs: list[Violation] = []
    main_js = "\n".join(_read(p) for p in main_files)
    for p in main_files + preload_files:
        vs += check_dev_affordances(f"{p.parent.name}/{p.name}", _read(p))
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
    vs += check_runtime_facts(facts, meta, require_runtime)
    vs += check_auto_update(web_js, _read(desktop_dist / "main" / "updateChannel.js"))
    vs += check_preload(
        _read(desktop_dist / "preload" / "index.js"),
        _read(desktop_dist / "preload" / "allowList.js"),
        main_js,
    )
    vs += check_packaging(_read(builder_config))
    return vs

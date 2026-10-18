"""Meta-tests for the electron-hardening gate (E10-X02).

A gate that has only ever passed is unproven: each test below builds a minimal *good* artefact
tree, proves the gate is clean, then applies ONE deliberate break and proves the gate fails
naming the right SR requirement. Offline, stdlib only.
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.electron_hardening_checks import (
    APP_PROBES,
    SR110_REQUIRED,
    SR112_EXACT,
    parse_csp,
    run_all_checks,
)
from tools.ci.electron_hardening_gate import main as gate_main

GOOD_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "connect-src 'self' http://127.0.0.1:8000 ws://127.0.0.1:8000; "
    "img-src 'self' data: blob:; worker-src 'self' blob:; object-src 'none'; "
    "frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)
GOOD_PRELOAD = """
const { contextBridge, ipcRenderer } = require("electron");
function invokeAllowed(channel, ...args) {
  if (!isChannelAllowed(channel, ALLOWED_IPC_CHANNELS)) throw new Error("no");
  return ipcRenderer.invoke(channel, ...args);
}
var ALLOWED_IPC_CHANNELS = ["cv:gpu:info"];
var cv = Object.freeze({
  gpuInfo: () => invokeAllowed("cv:gpu:info"),
});
contextBridge.exposeInMainWorld("cv", cv);
"""
GOOD_ALLOW = 'export const ALLOWED_IPC_CHANNELS = ["cv:gpu:info"];\n'
GOOD_MAIN = (
    'ipcMain.handle("cv:gpu:info", () => 1);\n'
    "protocol.registerSchemesAsPrivileged("
    "[{ scheme: APP_SCHEME, privileges: APP_SCHEME_PRIVILEGES }]);\n"
    "void win.loadURL(APP_ENTRY_URL);\n"
)
GOOD_APP_PROTOCOL = (
    "export const APP_SCHEME_PRIVILEGES = "
    "Object.freeze({ standard: true, secure: true });\n"
)
GOOD_SHELLPORT = (
    "export const HARDENED_WEB_PREFERENCES = {\n"
    + "".join(f"  {k}: {str(v).lower()},\n" for k, v in SR110_REQUIRED.items())
    + "};\n"
)
GOOD_UPDATE = "export function isAutoUpdateEnabled() {\n    return false;\n}\n"
GOOD_BUILDER = 'files:\n  - dist/**/*\n  - "!**/*.map"\n'
GOOD_WINDOWS: list[dict[str, object]] = [
    {
        "name": "window-0",
        "title": "CandleViewer",
        "url": "app://candleviewer/",
        "webPreferences": dict(SR110_REQUIRED),
    },
    {
        "name": "popout-1",
        "title": "CandleViewer",
        "url": "app://candleviewer/popout/chart?id=1",
        "webPreferences": dict(SR110_REQUIRED),
    },
]
# The app:// handler responses collect-hardening-facts.mjs fetches, pinned here as literals:
# the page, a missing asset and an /api path (both 404, no SPA fallback) and a non-GET (405).
GOOD_PROBES: list[dict[str, object]] = [
    {
        "method": method,
        "url": f"app://candleviewer{path}",
        "status": status,
        "csp": GOOD_CSP,
    }
    for method, path, status in (
        ("GET", "/", 200),
        ("GET", "/assets/cv-hardening-probe.js", 404),
        ("GET", "/api/cv-hardening-probe", 404),
        ("POST", "/", 405),
    )
]


class Tree:
    """A minimal packaged-artefact tree plus facts, mutable per test."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.files = {
            "desktop/main/index.js": GOOD_MAIN,
            "desktop/main/appProtocol.js": GOOD_APP_PROTOCOL,
            "desktop/main/shellPort.js": GOOD_SHELLPORT,
            "desktop/main/updateChannel.js": GOOD_UPDATE,
            "desktop/preload/index.js": GOOD_PRELOAD,
            "desktop/preload/allowList.js": GOOD_ALLOW,
            "web/assets/index-abc.js": "var caps={autoUpdate:!1};console.log('hi')",
            "web/index.html": (
                f'<html><head><meta http-equiv="Content-Security-Policy" content="{GOOD_CSP}" />'
                "</head></html>"
            ),
            "electron-builder.yml": GOOD_BUILDER,
        }
        self.windows = copy.deepcopy(GOOD_WINDOWS)
        self.probes = copy.deepcopy(GOOD_PROBES)
        self.facts: dict[str, object] = {
            "cspHeader": GOOD_CSP,
            "windows": self.windows,
            "appProbes": self.probes,
        }

    def violations(self, require: bool = True) -> list:  # type: ignore[type-arg]
        for rel, text in self.files.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        return run_all_checks(
            desktop_dist=self.root / "desktop",
            web_dist=self.root / "web",
            builder_config=self.root / "electron-builder.yml",
            facts=self.facts,
            require_runtime=require,
        )


@pytest.fixture
def tree(tmp_path: Path) -> Tree:
    return Tree(tmp_path)


def srs(vs: list) -> set[str]:  # type: ignore[type-arg]
    return {v.sr for v in vs}


def test_good_tree_is_clean(tree: Tree) -> None:
    assert tree.violations() == []


@pytest.mark.parametrize("flag", sorted(SR110_REQUIRED))
def test_flipping_any_hardening_flag_on_a_popout_fails_sr110(
    tree: Tree, flag: str
) -> None:
    tree.facts["windows"][1]["webPreferences"][flag] = not SR110_REQUIRED[flag]  # type: ignore[index]
    vs = tree.violations()
    assert srs(vs) == {"SR-110"}
    assert "popout-1" in vs[0].render() and flag in vs[0].render()


def test_enable_remote_module_present_fails_sr110(tree: Tree) -> None:
    tree.facts["windows"][0]["webPreferences"]["enableRemoteModule"] = False  # type: ignore[index]
    assert srs(tree.violations()) == {"SR-110"}


def test_declared_flag_flipped_in_shellport_fails_sr110(tree: Tree) -> None:
    tree.files["desktop/main/shellPort.js"] = GOOD_SHELLPORT.replace(
        "sandbox: true", "sandbox: false"
    )
    vs = tree.violations()
    assert srs(vs) == {"SR-110"} and "sandbox" in vs[0].render()


def test_missing_nodeintegrationinworker_in_live_prefs_is_default_compliant(
    tree: Tree,
) -> None:
    del tree.facts["windows"][0]["webPreferences"]["nodeIntegrationInWorker"]  # type: ignore[attr-defined]
    assert tree.violations() == []


def test_no_windows_collected_fails_closed_in_runtime_mode(tree: Tree) -> None:
    tree.facts["windows"] = []
    assert srs(tree.violations()) == {"SR-110"}


@pytest.mark.parametrize("directive", sorted(SR112_EXACT))
def test_removing_any_csp_directive_fails_sr112(tree: Tree, directive: str) -> None:
    weak = "; ".join(
        p for p in GOOD_CSP.split("; ") if not p.startswith(directive + " ")
    )
    tree.facts["cspHeader"] = weak
    vs = tree.violations()
    assert "SR-112" in srs(vs)
    assert any(directive in v.render() for v in vs)


def test_unsafe_eval_in_csp_fails_sr112(tree: Tree) -> None:
    tree.facts["cspHeader"] = GOOD_CSP.replace(
        "script-src 'self'", "script-src 'self' 'unsafe-eval'"
    )
    assert "SR-112" in srs(tree.violations())


def test_frame_ancestors_weakened_in_meta_fails_sr112(tree: Tree) -> None:
    weak = GOOD_CSP.replace("frame-ancestors 'none'", "frame-ancestors *")
    tree.files["web/index.html"] = (
        f'<meta http-equiv="Content-Security-Policy" content="{weak}" />'
    )
    vs = tree.violations()
    assert "SR-112" in srs(vs) and any("frame-ancestors" in v.render() for v in vs)


def test_missing_meta_fallback_fails_sr112(tree: Tree) -> None:
    tree.files["web/index.html"] = "<html></html>"
    assert "SR-112" in srs(tree.violations())


def test_connect_src_wildcard_fails_sr112(tree: Tree) -> None:
    tree.facts["cspHeader"] = GOOD_CSP.replace("ws://127.0.0.1:8000", "wss:")
    assert "SR-112" in srs(tree.violations())


@pytest.mark.parametrize(
    "host",
    [
        "wss://stream.bybit.com",
        "https://api.bybit.com",
        "https://api-demo.bybit.com",
        "https://api.bytick.com",
        "wss://stream-testnet.bybit.com",
        "https://api.bybit.nl",
    ],
)
def test_bybit_host_in_csp_fails_sr119(tree: Tree, host: str) -> None:
    tree.facts["cspHeader"] = GOOD_CSP.replace(
        "ws://127.0.0.1:8000", f"ws://127.0.0.1:8000 {host}"
    )
    vs = tree.violations()
    assert "SR-119" in srs(vs)
    assert any("backend-only" in v.render() for v in vs if v.sr == "SR-119")


def test_bybit_host_in_renderer_bundle_fails_sr119(tree: Tree) -> None:
    tree.files["web/assets/index-abc.js"] = (
        "fetch('https://api.bybit.com/v5/market/time')"
    )
    assert srs(tree.violations()) == {"SR-119"}


@pytest.mark.parametrize(
    "main_js",
    [
        "win.webContents.openDevTools();",
        "new BrowserWindow({webPreferences:{devTools:true}})",
        'app.commandLine.appendSwitch("remote-debugging-port","9222")',
        "globalThis.__CV_TEST_HOOK__ = () => 1;",
    ],
)
def test_dev_affordance_in_main_fails_sr114(tree: Tree, main_js: str) -> None:
    tree.files["desktop/main/index.js"] = GOOD_MAIN + main_js
    assert "SR-114" in srs(tree.violations())


def test_relaxed_dev_csp_in_main_fails_sr114(tree: Tree) -> None:
    tree.files["desktop/main/csp.js"] = (
        "const dev = \"script-src 'self' 'unsafe-eval'\";"
    )
    assert "SR-114" in srs(tree.violations())


def test_bypass_csp_on_any_privileged_scheme_fails_sr112(tree: Tree) -> None:
    tree.files["desktop/main/index.js"] = (
        GOOD_MAIN
        + 'protocol.registerSchemesAsPrivileged([{scheme:"x",privileges:{bypassCSP:!0}}]);'
    )
    vs = tree.violations()
    # The second registration also breaks the one-call rule (SR-174).
    assert srs(vs) == {"SR-112", "SR-174"} and "bypassCSP" in vs[0].render()


@pytest.mark.parametrize("key", ['"bypassCSP"', "'bypassCSP'", '["bypassCSP"]'])
def test_bypass_csp_under_a_quoted_key_fails_sr112(tree: Tree, key: str) -> None:
    tree.files["desktop/main/csp.js"] = f"const extra = {{ {key}: !0 }};\n"
    assert srs(tree.violations()) == {"SR-112"}


@pytest.mark.parametrize(
    "privileges",
    [
        "standard: true, secure: true, supportFetchAPI: true",
        "standard: true, secure: true, corsEnabled: !0",
        "standard: true, secure: true, allowServiceWorkers: true",
        "standard: true, secure: false",
        "standard: true",
        "standard: true, secure: true, ...EXTRA",
    ],
)
def test_app_scheme_privileges_outside_the_closed_set_fail_sr174(
    tree: Tree, privileges: str
) -> None:
    tree.files["desktop/main/appProtocol.js"] = (
        f"export const APP_SCHEME_PRIVILEGES = Object.freeze({{ {privileges} }});\n"
    )
    vs = tree.violations()
    assert srs(vs) == {"SR-174"}
    assert "section 6.11a, SR-174" in vs[0].render()


def test_bypass_csp_in_the_app_scheme_privileges_fails_sr112_and_sr174(
    tree: Tree,
) -> None:
    tree.files["desktop/main/appProtocol.js"] = (
        "export const APP_SCHEME_PRIVILEGES = "
        "Object.freeze({ standard: true, secure: true, bypassCSP: true });\n"
    )
    assert srs(tree.violations()) == {"SR-112", "SR-174"}


@pytest.mark.parametrize(
    "app_protocol",
    [
        # Not frozen, so a later write could widen the set at runtime.
        "export const APP_SCHEME_PRIVILEGES = { standard: true, secure: true };\n",
        # Writes to the constant after its declaration.
        GOOD_APP_PROTOCOL + 'APP_SCHEME_PRIVILEGES["bypass" + "CSP"] = true;\n',
        GOOD_APP_PROTOCOL + "APP_SCHEME_PRIVILEGES.supportFetchAPI = !0;\n",
        GOOD_APP_PROTOCOL + "APP_SCHEME_PRIVILEGES . corsEnabled ||= true;\n",
    ],
)
def test_app_scheme_privileges_not_frozen_or_written_fails_sr174(
    tree: Tree, app_protocol: str
) -> None:
    tree.files["desktop/main/appProtocol.js"] = app_protocol
    vs = tree.violations()
    assert srs(vs) == {"SR-174"} and "APP_SCHEME_PRIVILEGES" in vs[0].render()


def test_a_second_app_scheme_privileges_declaration_fails_sr174(tree: Tree) -> None:
    # A shadowing declaration with a wider set in another main-process file.
    tree.files["desktop/main/index.js"] = GOOD_MAIN + (
        "const APP_SCHEME_PRIVILEGES = "
        "Object.freeze({ standard: true, secure: true, supportFetchAPI: true });\n"
    )
    vs = tree.violations()
    assert srs(vs) == {"SR-174"} and "2 declaration(s)" in vs[0].render()


def test_reading_the_app_scheme_privileges_passes(tree: Tree) -> None:
    tree.files["desktop/main/index.js"] = GOOD_MAIN + (
        "if (APP_SCHEME_PRIVILEGES.secure === true && APP_SCHEME_PRIVILEGES['standard'] == !0) {}\n"
    )
    assert tree.violations() == []


REGISTRATION = (
    "protocol.registerSchemesAsPrivileged("
    "[{ scheme: APP_SCHEME, privileges: APP_SCHEME_PRIVILEGES }]);\n"
)


@pytest.mark.parametrize(
    "registration",
    [
        "privileges: { standard: true, secure: true, supportFetchAPI: true }",
        "privileges: { ...APP_SCHEME_PRIVILEGES, corsEnabled: true }",
        "privileges: OTHER_PRIVILEGES",
        "privileges: APP_SCHEME_PRIVILEGES }, { scheme: 'x', privileges: APP_SCHEME_PRIVILEGES",
        None,
    ],
)
def test_app_scheme_registration_other_than_the_constant_fails_sr174(
    tree: Tree, registration: str | None
) -> None:
    replacement = (
        ""
        if registration is None
        else REGISTRATION.replace("privileges: APP_SCHEME_PRIVILEGES", registration)
    )
    assert REGISTRATION in GOOD_MAIN
    tree.files["desktop/main/index.js"] = GOOD_MAIN.replace(REGISTRATION, replacement)
    vs = tree.violations()
    assert srs(vs) == {"SR-174"} and "registerSchemesAsPrivileged" in vs[0].render()


def test_a_second_registration_by_bracket_access_fails_sr174(tree: Tree) -> None:
    tree.files["desktop/main/index.js"] = GOOD_MAIN + (
        'protocol["registerSchemesAsPrivileged"]([{ scheme: "x", privileges: {} }]);\n'
    )
    vs = tree.violations()
    assert srs(vs) == {"SR-174"} and "found 2 call(s)" in vs[0].render()


def test_app_scheme_registration_reflowed_with_trailing_commas_passes(
    tree: Tree,
) -> None:
    tree.files["desktop/main/index.js"] = GOOD_MAIN.replace(
        REGISTRATION,
        "protocol.registerSchemesAsPrivileged([\n"
        "    { scheme: APP_SCHEME, privileges: APP_SCHEME_PRIVILEGES, },\n"
        "]);\n",
    )
    assert tree.violations() == []


def test_missing_app_scheme_privileges_fails_sr174(tree: Tree) -> None:
    tree.files["desktop/main/appProtocol.js"] = "export const APP_SCHEME = 'app';\n"
    assert srs(tree.violations()) == {"SR-174"}


@pytest.mark.parametrize(
    "load",
    [
        'void win.loadFile(path.join(__dirname, "../../../web/dist/index.html"));',
        'void win.loadURL("file:///opt/app/web/dist/index.html");',
        "void win.loadURL(`file://${indexPath}`);",
        'void win.loadURL("FILE:///opt/app/web/dist/index.html");',
        "void win.loadURL(pathToFileURL(indexPath).href);",
        "void win.loadURL(url.pathToFileURL(path.join(root, 'index.html')).href);",
        "void win . loadFile (indexPath);",
        # A file: literal anywhere in the argument, and loadFile bound or indexed.
        'void win.loadURL(new URL("file:///opt/app/web/dist/index.html").href);',
        "void win.loadURL(String('file:///opt/app/web/dist/index.html'));",
        'void win["loadURL"]("file:///opt/app/web/dist/index.html");',
        'void win["loadFile"](indexPath);',
        "const load = win.loadFile.bind(win);",
    ],
)
def test_window_loading_a_file_url_fails_sr174(tree: Tree, load: str) -> None:
    tree.files["desktop/main/index.js"] = GOOD_MAIN + load
    vs = tree.violations()
    assert srs(vs) == {"SR-174"} and "file: URL" in vs[0].render()


@pytest.mark.parametrize(
    ("name", "use"),
    [
        (
            "loadURL",
            'const load = win.loadURL.bind(win);\nvoid load("file:///x.html");',
        ),
        ("loadURL", 'void win.loadURL.call(win, "file:///x.html");'),
        ("loadURL", 'void Reflect.apply(win.loadURL, win, ["file:///x.html"]);'),
        ("loadURL", 'void win.loadURL?.("file:///x.html");'),
        ("loadURL", "const { loadURL } = win;"),
        (
            "registerSchemesAsPrivileged",
            (
                "const reg = protocol.registerSchemesAsPrivileged.bind(protocol);\n"
                'reg([{ scheme: "x", privileges: { supportFetchAPI: true } }]);'
            ),
        ),
    ],
)
def test_a_checked_call_used_other_than_directly_fails_sr174(
    tree: Tree, name: str, use: str
) -> None:
    tree.files["desktop/main/index.js"] = GOOD_MAIN + use
    vs = tree.violations()
    assert srs(vs) == {"SR-174"}
    assert f"{name} is used other than by a direct call" in vs[0].render()


def test_direct_calls_spelled_with_brackets_or_spaces_pass(tree: Tree) -> None:
    tree.files["desktop/main/index.js"] = GOOD_MAIN + (
        'void win["loadURL"](APP_ENTRY_URL);\n'
        "void win.webContents.loadURL (APP_ENTRY_URL);\n"
    )
    assert tree.violations() == []


@pytest.mark.parametrize(
    ("rel", "js", "sr", "subject"),
    [
        (
            "main/windows/help.js",
            'void win.loadFile("help.html");',
            "SR-174",
            "main window load",
        ),
        (
            "main/windows/help.js",
            "win.webContents.openDevTools();",
            "SR-114",
            "main/windows/help.js",
        ),
        (
            "preload/extra/a.js",
            "win.webContents.openDevTools();",
            "SR-114",
            "preload/extra/a.js",
        ),
    ],
)
def test_a_module_in_a_sub_directory_is_scanned(
    tree: Tree, rel: str, js: str, sr: str, subject: str
) -> None:
    tree.files[f"desktop/{rel}"] = js
    vs = tree.violations()
    assert srs(vs) == {sr} and f"violated by {subject}:" in vs[0].render()


@pytest.mark.parametrize("i", [1, 2])
def test_a_404_without_the_csp_header_fails_sr112(tree: Tree, i: int) -> None:
    tree.probes[i]["csp"] = None
    vs = tree.violations()
    assert srs(vs) == {"SR-112"} and str(tree.probes[i]["url"]) in vs[0].render()


@pytest.mark.parametrize(
    "csp",
    [
        GOOD_CSP.replace("frame-ancestors 'none'", "frame-ancestors *"),
        # A repeated directive is enforced by its first occurrence; parse_csp keeps the last.
        "default-src *; " + GOOD_CSP,
        "",
    ],
    ids=["frame-ancestors-relaxed", "repeated-default-src", "empty"],
)
def test_a_405_with_a_different_csp_header_fails_sr112(tree: Tree, csp: str) -> None:
    tree.probes[3]["csp"] = csp
    assert srs(tree.violations()) == {"SR-112"}


@pytest.mark.parametrize(
    ("i", "status"),
    [(0, 404), (1, 200), (2, 200), (3, 200), (3, None)],
    ids=[
        "page-404",
        "missing-asset-200",
        "api-spa-fallback-200",
        "post-200",
        "no-status",
    ],
)
def test_a_handler_response_with_the_wrong_status_fails_sr112(
    tree: Tree, i: int, status: int | None
) -> None:
    tree.probes[i]["status"] = status
    assert srs(tree.violations()) == {"SR-112"}


@pytest.mark.parametrize("i", range(len(GOOD_PROBES)))
def test_a_missing_handler_response_fails_closed_in_runtime_mode(
    tree: Tree, i: int
) -> None:
    del tree.probes[i]
    assert srs(tree.violations()) == {"SR-112"}


@pytest.mark.parametrize("probes", [None, {"GET": 200}, []])
def test_absent_or_malformed_handler_responses_fail_closed_in_runtime_mode(
    tree: Tree, probes: object
) -> None:
    tree.facts["appProbes"] = probes
    if probes is None:
        del tree.facts["appProbes"]
    vs = tree.violations()
    assert srs(vs) == {"SR-112"} and len(vs) == len(GOOD_PROBES)


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ("not-a-probe", "is not an object"),
        ({**GOOD_PROBES[0], "method": ["GET"]}, "wrong type for method"),
        ({**GOOD_PROBES[0], "url": {"path": "/"}}, "wrong type for url"),
        ({**GOOD_PROBES[0], "status": "200"}, "wrong type for status"),
        ({**GOOD_PROBES[0], "status": True}, "wrong type for status"),
        ({**GOOD_PROBES[0], "csp": [GOOD_CSP]}, "wrong type for csp"),
    ],
    ids=[
        "not-an-object",
        "method-list",
        "url-object",
        "status-text",
        "status-bool",
        "csp-list",
    ],
)
def test_a_handler_response_with_a_mistyped_field_fails_sr112(
    tree: Tree, entry: object, message: str
) -> None:
    tree.probes.append(copy.deepcopy(entry))
    vs = tree.violations()
    assert len(vs) == 1 and vs[0].sr == "SR-112"
    assert f"facts appProbes[{len(GOOD_PROBES)}]: {message}" in vs[0].render()


@pytest.mark.parametrize(
    "first_status", [404, 200], ids=["failing-then-passing", "twice"]
)
def test_a_handler_response_collected_twice_fails_sr112(
    tree: Tree, first_status: int
) -> None:
    tree.probes[0]["status"] = first_status
    tree.probes.append(copy.deepcopy(GOOD_PROBES[0]))
    vs = tree.violations()
    assert srs(vs) == {"SR-112"}
    assert any(
        "app:// handler GET app://candleviewer/: collected more than once" in v.render()
        for v in vs
    )


COLLECTOR = (
    Path(__file__).resolve().parents[2]
    / "apps/desktop/scripts/collect-hardening-facts.mjs"
)


def collector_probes() -> list[tuple[str, str]]:
    """The collector's PROBES literal: the text from `const PROBES = [` to the next `];`, read
    as JSON once the trailing comma prettier leaves after the last pair is dropped."""
    text = COLLECTOR.read_text(encoding="utf-8")
    start = text.index("const PROBES = [") + len("const PROBES = ")
    body = text[start : text.index("];", start)].rstrip().removesuffix(",")
    return [(method, url) for method, url in json.loads(body + "]")]


def test_the_collector_fetches_the_requests_the_gate_judges() -> None:
    # Drift would otherwise show only in CI's packaged-build job, as a missing response.
    assert collector_probes() == list(APP_PROBES)


@pytest.mark.parametrize(
    "url",
    [
        "file:///opt/CandleViewer/resources/web/dist/index.html",
        "app://other/",
        "app://candleviewer.evil/",
        "app://candleviewer@evil/",
        "app://user@candleviewer/",
        "app://candleviewer:8443/",
        "http://127.0.0.1:5173/",
        "about:blank",
        "",
        None,
    ],
)
def test_a_window_off_the_app_origin_fails_sr174(tree: Tree, url: str | None) -> None:
    tree.windows[1]["url"] = url
    vs = tree.violations()
    assert srs(vs) == {"SR-174"} and "window 'popout-1'" in vs[0].render()


def test_a_window_without_a_url_fails_closed_in_runtime_mode(tree: Tree) -> None:
    del tree.windows[0]["url"]
    assert srs(tree.violations()) == {"SR-174"}


def test_handler_responses_and_window_urls_stay_optional_without_require_runtime(
    tree: Tree,
) -> None:
    del tree.facts["appProbes"]
    for w in tree.windows:
        del w["url"]
    assert tree.violations(require=False) == []
    tree.windows[0]["url"] = "file:///index.html"
    assert srs(tree.violations(require=False)) == {"SR-174"}


@pytest.mark.parametrize(
    ("rel", "entry"), [("shared/util.js", "shared"), ("index.js", "index.js")]
)
def test_an_unscanned_top_level_entry_in_the_desktop_dist_fails_sr114(
    tree: Tree, rel: str, entry: str
) -> None:
    tree.files[f"desktop/{rel}"] = "export const x = 1;\n"
    vs = tree.violations()
    assert srs(vs) == {"SR-114"} and f"['{entry}'] would be packaged" in vs[0].message


def test_autoupdate_true_in_renderer_fails_sr115(tree: Tree) -> None:
    tree.files["web/assets/index-abc.js"] = "var caps={autoUpdate:!0}"
    assert srs(tree.violations()) == {"SR-115"}


def test_autoupdate_enabled_in_main_fails_sr115(tree: Tree) -> None:
    tree.files["desktop/main/updateChannel.js"] = (
        "export function isAutoUpdateEnabled() { return process.env.X === '1'; }"
    )
    assert srs(tree.violations()) == {"SR-115"}


def test_sourcemaps_shipped_fails_sr116(tree: Tree) -> None:
    tree.files["electron-builder.yml"] = "files:\n  - dist/**/*\n"
    assert srs(tree.violations()) == {"SR-116"}


def test_ipcrenderer_exposed_directly_fails_sr111(tree: Tree) -> None:
    tree.files["desktop/preload/index.js"] = (
        GOOD_PRELOAD + '\ncontextBridge.exposeInMainWorld("raw", ipcRenderer);'
    )
    assert srs(tree.violations()) == {"SR-111"}


def test_generic_invoke_on_bridge_fails_sr111(tree: Tree) -> None:
    tree.files["desktop/preload/index.js"] = GOOD_PRELOAD.replace(
        "gpuInfo: () =>", "invoke: (c) => ipcRenderer.invoke(c),\n  gpuInfo: () =>"
    )
    vs = tree.violations()
    assert srs(vs) == {"SR-111"}


def test_channel_missing_from_allowlist_table_fails_sr111(tree: Tree) -> None:
    tree.files["desktop/preload/index.js"] = GOOD_PRELOAD.replace(
        'gpuInfo: () => invokeAllowed("cv:gpu:info"),',
        'gpuInfo: () => invokeAllowed("cv:gpu:info"), x: () => ipcRenderer.invoke("cv:evil"),',
    )
    assert "SR-111" in srs(tree.violations())


def test_main_handler_outside_table_fails_sr111(tree: Tree) -> None:
    tree.files["desktop/main/index.js"] = (
        GOOD_MAIN + 'ipcMain.handle("cv:shell:run", () => 1);'
    )
    assert srs(tree.violations()) == {"SR-111"}


def test_missing_artefacts_fail_closed(tmp_path: Path) -> None:
    vs = run_all_checks(
        desktop_dist=tmp_path / "nope",
        web_dist=tmp_path / "nope2",
        builder_config=tmp_path / "x.yml",
        facts={},
    )
    assert srs(vs) == {"SR-114"}


def test_parse_csp_normalises_whitespace() -> None:
    assert parse_csp("a  'self' ;b 'none'") == {"a": "'self'", "b": "'none'"}


def test_cli_exit_codes_and_annotation(
    tree: Tree, capsys: pytest.CaptureFixture[str]
) -> None:
    assert tree.violations() == []
    facts = tree.root / "facts.json"
    facts.write_text(json.dumps(tree.facts), encoding="utf-8")
    argv = [
        "--desktop-dist", str(tree.root / "desktop"),
        "--web-dist", str(tree.root / "web"),
        "--builder-config", str(tree.root / "electron-builder.yml"),
        "--facts", str(facts), "--require-runtime",
    ]  # fmt: skip
    assert gate_main(argv) == 0
    tree.facts["windows"][0]["webPreferences"]["sandbox"] = False  # type: ignore[index]
    facts.write_text(json.dumps(tree.facts), encoding="utf-8")
    assert gate_main(argv) == 1
    out = capsys.readouterr()
    assert "::error title=electron-hardening SR-110::" in out.out
    assert "section 6.11" in out.err

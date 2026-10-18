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
GOOD_MAIN = 'ipcMain.handle("cv:gpu:info", () => 1);\n'
GOOD_SHELLPORT = (
    "export const HARDENED_WEB_PREFERENCES = {\n"
    + "".join(f"  {k}: {str(v).lower()},\n" for k, v in SR110_REQUIRED.items())
    + "};\n"
)
GOOD_UPDATE = "export function isAutoUpdateEnabled() {\n    return false;\n}\n"
GOOD_BUILDER = 'files:\n  - dist/**/*\n  - "!**/*.map"\n'
GOOD_WINDOWS = [
    {
        "name": "window-0",
        "title": "CandleViewer",
        "webPreferences": dict(SR110_REQUIRED),
    },
    {
        "name": "popout-1",
        "title": "CandleViewer",
        "webPreferences": dict(SR110_REQUIRED),
    },
]


class Tree:
    """A minimal packaged-artefact tree plus facts, mutable per test."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.files = {
            "desktop/main/index.js": GOOD_MAIN,
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
        self.facts: dict[str, object] = {
            "cspHeader": GOOD_CSP,
            "windows": copy.deepcopy(GOOD_WINDOWS),
        }

    def violations(self) -> list:  # type: ignore[type-arg]
        for rel, text in self.files.items():
            p = self.root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        return run_all_checks(
            desktop_dist=self.root / "desktop",
            web_dist=self.root / "web",
            builder_config=self.root / "electron-builder.yml",
            facts=self.facts,
            require_runtime=True,
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

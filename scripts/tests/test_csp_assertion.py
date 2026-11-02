"""Meta-tests for `tools/ci/csp_assertion.py` (E43-T01, SR-112 / SR-114 / SR-119): a good tree is
clean against the committed golden policy and the real API builder, and each single break (a drifted
meta, header or API policy, an `unsafe-inline`, a missing fact, an exchange host in any web `*.js`)
fails naming its requirement. Offline, stdlib only."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.ci.csp_assertion import API_CSP, GOLDEN, main, run_csp_assertion

GOLD = json.loads(GOLDEN.read_text(encoding="utf-8"))


def _meta_html(policy: str) -> str:
    return f'<html><head><meta http-equiv="Content-Security-Policy" content="{policy}" /></head></html>'


@pytest.fixture
def web(tmp_path: Path) -> Path:
    dist = tmp_path / "web"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text(_meta_html(GOLD["meta"]), encoding="utf-8")
    (dist / "assets" / "index-abc.js").write_text("console.log('hi')", encoding="utf-8")
    return dist


def _run(web: Path, facts: dict[str, object] | None = None, **kw: object) -> list:  # type: ignore[type-arg]
    facts = {"cspHeader": GOLD["header"]} if facts is None else facts
    return run_csp_assertion(web_dist=web, facts=facts, **kw)  # type: ignore[arg-type]


def test_a_good_tree_is_clean(web: Path) -> None:
    assert _run(web) == []


def test_the_golden_policy_has_no_unsafe_source() -> None:
    assert "unsafe-" not in GOLD["header"] and "unsafe-" not in GOLD["meta"]


def test_a_missing_meta_fails_sr112(web: Path) -> None:
    (web / "index.html").write_text("<html></html>", encoding="utf-8")
    assert {v.sr for v in _run(web)} == {"SR-112"}


@pytest.mark.parametrize(
    "policy",
    [
        GOLD["meta"].replace("style-src 'self'", "style-src 'self' 'unsafe-inline'"),
        GOLD["meta"].replace("script-src 'self'", "script-src 'self' 'unsafe-eval'"),
        GOLD["meta"].replace(
            "ws://127.0.0.1:8000", "ws://127.0.0.1:8000 wss://box.ts.net"
        ),
        GOLD["meta"] + "; frame-ancestors 'none'",
    ],
    ids=["unsafe-inline", "unsafe-eval", "extra-connect", "header-only-in-meta"],
)
def test_a_drifted_meta_fails_sr112(web: Path, policy: str) -> None:
    (web / "index.html").write_text(_meta_html(policy), encoding="utf-8")
    assert "SR-112" in {v.sr for v in _run(web)}


def test_a_drifted_electron_header_fails_sr112(web: Path) -> None:
    drifted = GOLD["header"].replace(
        "style-src 'self'", "style-src 'self' 'unsafe-inline'"
    )
    assert "SR-112" in {v.sr for v in _run(web, {"cspHeader": drifted})}


def test_a_tailnet_header_is_a_valid_policy_but_not_the_golden_default(
    web: Path,
) -> None:
    vs = _run(web, {"cspHeader": GOLD["tailnet"]})
    assert [v.subject for v in vs] == ["Electron CSP header"]
    assert "not the golden one" in vs[0].message


def test_a_missing_header_fact_fails_unless_not_required(web: Path) -> None:
    assert "SR-112" in {v.sr for v in _run(web, {})}
    assert _run(web, {}, require_header_fact=False) == []


def test_a_drifted_api_policy_fails_sr112(web: Path, tmp_path: Path) -> None:
    api = tmp_path / "csp.py"
    api.write_text(
        API_CSP.read_text(encoding="utf-8").replace(
            "\"style-src 'self'\"", "\"style-src 'self' 'unsafe-inline'\""
        ),
        encoding="utf-8",
    )
    vs = _run(web, api_csp_path=api)
    assert any(v.subject == "FastAPI CSP header" for v in vs)


def test_an_api_builder_that_does_not_load_fails_sr112(
    web: Path, tmp_path: Path
) -> None:
    api = tmp_path / "csp.py"
    api.write_text("raise RuntimeError('boom')\n", encoding="utf-8")
    assert any("does not load" in v.message for v in _run(web, api_csp_path=api))
    assert any(
        "does not load" in v.message
        for v in _run(web, api_csp_path=tmp_path / "none.py")
    )


@pytest.mark.parametrize(
    "rel",
    ["assets/index-abc.js", "assets/chunks/vendor.js", "worker.js", "assets/w/x/y.js"],
)
def test_a_bybit_host_in_any_web_js_fails_sr119(web: Path, rel: str) -> None:
    target = web / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('fetch("https://api.bybit.com/v5/market/time")', encoding="utf-8")
    vs = _run(web)
    assert {v.sr for v in vs} == {"SR-119"}
    assert any(Path(rel).name in v.subject for v in vs)


def test_a_web_dist_without_scripts_fails_sr114(tmp_path: Path) -> None:
    dist = tmp_path / "web"
    dist.mkdir()
    (dist / "index.html").write_text(_meta_html(GOLD["meta"]), encoding="utf-8")
    assert {v.sr for v in _run(dist)} == {"SR-114"}


def test_the_cli_exit_codes(
    web: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    facts = tmp_path / "facts.json"
    facts.write_text(json.dumps({"cspHeader": GOLD["header"]}), encoding="utf-8")
    assert main(["--web-dist", str(web), "--facts", str(facts)]) == 0
    assert "csp-assertion: clean" in capsys.readouterr().out
    (web / "index.html").write_text(_meta_html("default-src *"), encoding="utf-8")
    assert main(["--web-dist", str(web), "--facts", str(facts)]) == 1
    assert "violation(s)" in capsys.readouterr().err

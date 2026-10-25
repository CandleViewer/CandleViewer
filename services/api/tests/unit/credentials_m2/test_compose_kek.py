"""e27-kek.md §9 interim control: the KEK never reaches a compose `environment:` (C5, rejected).

#3180 narrows "no `CV_KEK*` name at all" to what the control protects. The demo-host overlay
configures a file KEK through e27-kek.md §4's settings, so a name holding `KEK` must be one of
them, with a value that cannot hold key material; the key itself reaches cv-api only as the
`cv_kek` file secret mounted at `CV_KEK_HANDLE`. `.env.example` names the file and the version,
never the key. Every guard has a negative control.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from candleviewer.settings import Settings

_INFRA = Path(__file__).resolve().parents[5] / "infra"
_DEMO_HOST = _INFRA / "compose" / "docker-compose.demo-host.yml"
#: e27-kek.md §4's settings a compose environment may carry, and each value's shape: a source, a
#: compose secret's mount, a version (a number, or the operator's variable).
_SETTINGS = {
    "CV_KEK_SOURCE": re.compile(r"file|handle"),
    "CV_KEK_HANDLE": re.compile(r"/run/secrets/[a-z0-9_]+"),
    "CV_KEK_VERSION": re.compile(r"[1-9][0-9]{0,5}|\$\{CV_KEK_VERSION(?::\?[^}]*)?\}"),
}
_MOUNT = {"source": "cv_kek", "target": "cv_kek", "uid": "10001", "gid": "10001", "mode": 0o400}


def _files() -> list[Path]:
    return sorted(_INFRA.rglob("docker-compose*.yml"))


def _env(service: dict[str, Any]) -> dict[str, str]:
    raw = service.get("environment") or {}
    if isinstance(raw, dict):
        return {str(k): "" if v is None else str(v) for k, v in raw.items()}
    return {k: v for k, _, v in (str(item).partition("=") for item in raw)}


def kek_problems(doc: dict[str, Any]) -> list[str]:
    """Each environment entry that could carry the KEK, by name (never by value)."""
    problems: list[str] = []
    for name, svc in (doc.get("services") or {}).items():
        for key, value in _env(svc or {}).items():
            shape = _SETTINGS.get(key.upper())
            if "KEK" in key.upper() and shape is None:
                problems.append(f"{name} exposes {key} via environment:")
            elif shape is not None and not shape.fullmatch(value):
                problems.append(f"{name} sets {key} to a value outside its shape")
    return problems


def test_compose_files_found() -> None:
    assert _DEMO_HOST in _files()


def test_no_kek_in_compose_environment() -> None:
    for f in _files():
        doc = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
        assert kek_problems(doc) == [], f.name


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("CV_KEK_VALUE", "${CV_KEK_VALUE:?x}"),
        ("CV_KEK", "${CV_KEK:?x}"),
        ("cv_kek_b64", "${CV_KEK_B64:?x}"),
        ("KEK_HEX", "${KEK_HEX:?x}"),
        ("CV_KEK_HANDLE", "a" * 64),
        ("CV_KEK_HANDLE", "/tmp/cv_kek"),
        ("CV_KEK_SOURCE", "${CV_KEK_SOURCE:?x}"),
        ("CV_KEK_VERSION", "${CV_KEK_VALUE:?x}"),
    ],
    ids=["value-name", "bare-name", "lowercase", "other-prefix", "handle-is-key-material",
         "handle-outside-secrets", "source-from-env", "version-names-the-key"],
)  # fmt: skip
@pytest.mark.parametrize("form", ["mapping", "list"])
def test_negative_control_the_environment_guard_catches(key: str, value: str, form: str) -> None:
    doc = copy.deepcopy(yaml.safe_load(_DEMO_HOST.read_text(encoding="utf-8")))
    env = {**_env(doc["services"]["api"]), key: value}
    doc["services"]["api"]["environment"] = env if form == "mapping" else [
        f"{k}={v}" for k, v in env.items()
    ]
    assert len(kek_problems(doc)) == 1


def test_the_demo_host_overlay_hands_the_kek_over_as_a_file_secret_at_the_handle() -> None:
    doc = yaml.safe_load(_DEMO_HOST.read_text(encoding="utf-8"))
    api = doc["services"]["api"]
    env = _env(api)
    assert (env["CV_KEK_SOURCE"], env["CV_KEK_HANDLE"]) == ("file", "/run/secrets/cv_kek")
    assert env["CV_KEK_HANDLE"] == Settings.model_fields["kek_handle"].default
    assert set(doc["secrets"]["cv_kek"]) == {"file"}  # a host file, never `environment:`
    assert re.fullmatch(r"\$\{CV_KEK_FILE:\?[^}]+\}", doc["secrets"]["cv_kek"]["file"])
    mounts = [m for m in api["secrets"] if isinstance(m, dict) and m["source"] == "cv_kek"]
    assert mounts == [_MOUNT]


def test_env_example_names_the_kek_file_and_its_version_never_the_key() -> None:
    example = (_INFRA / "compose" / ".env.example").read_text(encoding="utf-8")
    pairs = [line.partition("=") for line in example.splitlines() if not line.startswith("#")]
    kek = {name: value for name, sep, value in pairs if sep and "KEK" in name.upper()}
    assert kek == {"CV_KEK_FILE": "", "CV_KEK_VERSION": "1"}  # a blank path, a number

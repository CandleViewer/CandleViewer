"""e27-kek.md §9 interim control: the KEK never reaches a compose `environment:` (C5, rejected).

#3180 narrows "no `CV_KEK*` name at all" to what the control protects. The demo-host overlay
configures a file KEK through e27-kek.md §4's settings, so a name holding `KEK` must be one of
them, with a value that cannot hold key material; the key itself reaches cv-api only as the
`cv_kek` file secret mounted at `CV_KEK_HANDLE`, never as a secret from the environment. The guard
is rule 5 of infra/scripts/lint_compose.py, kept in one place (C-16.5): this module runs it over
every compose file under infra/. `.env.example` names the file and the version, never the key, and
the demo-host runbook's check value is the one the loader enrols. Every guard has a negative
control.
"""

from __future__ import annotations

import copy
import hashlib
import hmac
import importlib
import re
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from candleviewer.secrets._kek import LoadedKek
from candleviewer.settings import Settings

_INFRA = Path(__file__).resolve().parents[5] / "infra"
_RUNBOOK = _INFRA.parent / "docs" / "ops" / "runbooks" / "demo-host.md"
_DEMO_HOST = _INFRA / "compose" / "docker-compose.demo-host.yml"
_MOUNT = {"source": "cv_kek", "target": "cv_kek", "uid": "10001", "gid": "10001", "mode": 0o400}
#: A compose secret sourced from the operator's environment, named for the KEK (M1, probe b).
_ENV_KEK = {"cv_kek_hex": {"environment": "CV_KEK_HEX"}}
sys.path.insert(0, str(_INFRA / "scripts"))
_LINT = importlib.import_module("lint_compose")


def _files() -> list[Path]:
    return sorted(_INFRA.rglob("docker-compose*.yml"))


def _env(service: dict[str, Any]) -> dict[str, str]:
    raw = service.get("environment") or {}
    if isinstance(raw, dict):
        return {str(k): "" if v is None else str(v) for k, v in raw.items()}
    return {k: v for k, _, v in (str(item).partition("=") for item in raw)}


def kek_problems(doc: dict[str, Any]) -> list[str]:
    """Everything that could carry the KEK, by name (never by value): the lint's rule 5."""
    problems: list[str] = _LINT.check_no_kek_in_environment(doc)
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
        ("CV_KEK_HANDLE", "/run/secrets/" + "a" * 64),
        ("CV_KEK_HANDLE", "/var/lib/candleviewer/cv_kek"),
        ("CV_KEK_SOURCE", "${CV_KEK_SOURCE:?x}"),
        ("CV_KEK_VERSION", "${CV_KEK_VALUE:?x}"),
    ],
    ids=["value-name", "bare-name", "lowercase", "other-prefix", "handle-is-key-material",
         "handle-of-key-material", "handle-outside-secrets", "source-from-env",
         "version-names-the-key"],
)  # fmt: skip
@pytest.mark.parametrize("form", ["mapping", "list"])
def test_negative_control_the_environment_guard_catches(key: str, value: str, form: str) -> None:
    doc = copy.deepcopy(yaml.safe_load(_DEMO_HOST.read_text(encoding="utf-8")))
    env = {**_env(doc["services"]["api"]), key: value}
    doc["services"]["api"]["environment"] = (
        env if form == "mapping" else [f"{k}={v}" for k, v in env.items()]
    )
    problems = kek_problems(doc)
    assert problems != [] and not any(value in problem for problem in problems)


@pytest.mark.parametrize(
    ("declared", "mount", "environment"),
    [
        (_ENV_KEK, "cv_kek_hex", {}),
        (_ENV_KEK, {"source": "cv_kek_hex", "target": "cv_kek"}, {}),
        ({"master": {"environment": "CV_MASTER"}}, "master",
         {"CV_KEK_HANDLE": "/run/secrets/master"}),
    ],
    ids=["kek-named-secret", "onto-the-handle", "neutral-secret-at-the-handle"],
)  # fmt: skip
def test_negative_control_the_guard_catches_a_kek_secret_from_the_environment(
    declared: dict[str, Any], mount: object, environment: dict[str, str]
) -> None:
    """M1: a compose secret sourced from the environment holds the KEK in `.env` as surely as
    `environment:` does, whether its name says so or it is mounted where the KEK is read."""
    doc = copy.deepcopy(yaml.safe_load(_DEMO_HOST.read_text(encoding="utf-8")))
    doc["secrets"] |= declared
    api = doc["services"]["api"]
    api["secrets"] = [*api["secrets"], mount]
    api["environment"] = {**_env(api), **environment}
    assert kek_problems(doc) != []


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


def test_the_demo_host_runbook_computes_the_check_value_the_loader_enrols() -> None:
    """demo-host.md step 5 holds the KCV in `security.kek_enrolled` against one it computes from
    the KEK file and the offline copy: the loader's derivation, or the check proves nothing."""
    formula = 'hmac.new(k, b"cv-kek-kcv-v1", hashlib.sha256).hexdigest()[:16]'
    assert formula in _RUNBOOK.read_text(encoding="utf-8")
    key = bytes(range(32))  # a fixed test vector, never a key
    shown = hmac.new(key, b"cv-kek-kcv-v1", hashlib.sha256).hexdigest()[:16]
    assert LoadedKek(bytearray(key), 1, env_name="demo").kcv().hex() == shown

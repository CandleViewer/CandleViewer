"""e27-kek.md §9 interim control: no compose file passes CV_KEK* via `environment:`."""

from __future__ import annotations

from pathlib import Path

import yaml

_INFRA = Path(__file__).resolve().parents[5] / "infra"


def _files() -> list[Path]:
    return sorted(_INFRA.rglob("docker-compose*.yml"))


def test_compose_files_found() -> None:
    assert _files()


def test_no_kek_in_compose_environment() -> None:
    for f in _files():
        doc = yaml.safe_load(f.read_text()) or {}
        for name, svc in (doc.get("services") or {}).items():
            envs = svc.get("environment") or {}
            keys = envs if isinstance(envs, dict) else [e.split("=", 1)[0] for e in envs]
            bad = [k for k in keys if str(k).upper().startswith("CV_KEK")]
            assert not bad, f"{f.name}:{name} exposes {bad} via environment:"

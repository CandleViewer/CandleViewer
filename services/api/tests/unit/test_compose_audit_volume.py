"""The base compose file's `api`: its audit files on one named volume (#3285 item 3, compose half)
and the audit lane's key a file secret, off that volume (ADR-0037 decision 6, #3009).

Pure unit tests over the YAML, beside `test_settings_stop_budget.py`: no docker, no network.
Without Swarm, compose bind-mounts a file secret as it is and ignores `mode`, `uid` and `gid`, so
here those are proven as declared and tied to the image's user; at boot the loader refuses any other
mode or owner (`test_audit_lane_wiring.py`), and CI's image step loads a key provisioned as the
compose file says (`_job-security.yml`). Every guard has a negative control per failure it catches.
"""

from __future__ import annotations

import copy
import posixpath
import re
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

import pytest
import yaml

from candleviewer.audit_lane_wiring import ENVIRONMENT_FORMS
from candleviewer.settings import Settings

_INFRA = Path(__file__).resolve().parents[4] / "infra"
_BASE = _INFRA / "compose" / "docker-compose.yml"
_ENV_EXAMPLE = _INFRA / "compose" / ".env.example"
_COMPOSE_FILES = sorted((_INFRA / "compose").glob("docker-compose*.yml"))
_KEY = "cv_audit_lane_key"
_VOLUME = "/var/lib/candleviewer/audit"  # the audit volume's target in the base file
_TMP = "/tmp"  # noqa: S108 - the api's tmpfs mount point, compared, never written
#: `${VAR:-/dev/null}`: a fresh checkout's `docker compose up` mounts /dev/null, which the fake
#: backend never reads and a real backend refuses (not a regular file).
_SOURCE = re.compile(r"\$\{([A-Z][A-Z0-9_]*):-/dev/null\}")
#: `dast-auth-zap.yml` gives every `.env.example` name matching this a random value.
_DAST_REPLACED = re.compile(r"PASSWORD|SECRET|KEY")

Change = Callable[[dict[str, Any]], None]


def _doc(path: Path = _BASE) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _api(doc: dict[str, Any]) -> dict[str, Any]:
    api: dict[str, Any] = (doc.get("services") or {}).get("api") or {}
    return api


def _env(service: dict[str, Any]) -> dict[str, str]:
    raw = service.get("environment") or {}
    if isinstance(raw, dict):
        return {str(k): "" if v is None else str(v) for k, v in raw.items()}
    return {k: v for k, _, v in (str(item).partition("=") for item in raw)}


def _target(entry: str | dict[str, Any]) -> PurePosixPath:
    """Where compose mounts a service's secret: under `/run/secrets/`, or an absolute target,
    with every `..` resolved."""
    name = entry if isinstance(entry, str) else str(entry.get("target") or entry["source"])
    return PurePosixPath(posixpath.normpath(PurePosixPath("/run/secrets", name)))


def _mount(entry: str | dict[str, Any]) -> tuple[str, str, str]:
    """A `volumes:` entry, short or long syntax, as (type, source, target)."""
    if isinstance(entry, dict):
        return str(entry.get("type", "volume")), str(entry.get("source", "")), entry["target"]
    if ":" not in entry:
        return "volume", "", entry  # anonymous
    source, _, rest = entry.partition(":")
    kind = "bind" if source.startswith(("/", ".", "~", "$")) else "volume"
    return kind, source, rest.partition(":")[0]


def _image_user() -> tuple[str, str]:
    """The runtime uid and gid of `Dockerfile.api`, its last `USER`."""
    dockerfile = (_INFRA / "images" / "Dockerfile.api").read_text(encoding="utf-8")
    uid, _, gid = re.findall(r"^USER\s+(\S+)", dockerfile, re.MULTILINE)[-1].partition(":")
    return uid, gid


def _set(path: str, value: object) -> Change:
    """Set (or with None, delete) the node at a dotted path of a compose document."""

    def change(doc: dict[str, Any]) -> None:
        *parents, leaf = path.split(".")
        for name in parents:
            doc = doc[name]
        if value is None:
            del doc[leaf]
        else:
            doc[leaf] = value

    return change


# --- #3285 item 3: the audit files sit on one named volume ------------------------------------


def audit_volume_problems(doc: dict[str, Any]) -> list[str]:
    api, problems = _api(doc), list[str]()
    if api.get("read_only") is not True:
        problems.append("api.read_only is not true")
    tmpfs = api.get("tmpfs")
    if (tmpfs if isinstance(tmpfs, list) else [tmpfs]) != [_TMP]:
        problems.append(f"api.tmpfs is {tmpfs!r}, not {_TMP} alone")
    volumes, declared = api.get("volumes") or [], doc.get("volumes") or {}
    named = [m for m in map(_mount, volumes) if m[0] == "volume" and m[1] in declared]
    if len(volumes) != 1 or len(named) != 1:
        problems.append(f"api's mounts are not one named volume and no bind: {volumes!r}")
    wal = PurePosixPath(_env(api).get("CV_AUDIT_WAL_PATH", ""))
    if not wal.is_absolute() or ".." in wal.parts:
        return [*problems, f"CV_AUDIT_WAL_PATH {str(wal)!r} is not absolute and free of '..'"]
    if named and wal.parent != PurePosixPath(named[0][2]):
        problems.append(f"CV_AUDIT_WAL_PATH's directory is not the volume's target {named[0][2]}")
    for entry in api.get("secrets") or []:
        if _target(entry).is_relative_to(wal.parent):
            problems.append(f"secret {entry!r} is mounted on the audit volume")
    return problems


def test_the_base_compose_file_keeps_the_audit_files_on_one_named_volume() -> None:
    assert audit_volume_problems(_doc()) == []


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        (_set("services.api.volumes", None), "not one named volume"),
        (_set("services.api.environment.CV_AUDIT_WAL_PATH", "var/audit/audit.wal"), "absolute"),
        (_set("services.api.environment.CV_AUDIT_WAL_PATH", "/var/x/../audit.wal"), "absolute"),
        (_set("services.api.read_only", False), "read_only"),
        (_set("services.api.volumes", [f"./audit:{_VOLUME}"]), "no bind"),
        (_set("services.api.volumes", [f"cv-audit-data:{_VOLUME}", "/x:/y"]), "no bind"),
        (_set("services.api.tmpfs", [_TMP, "/var"]), "tmpfs"),
        (_set("services.api.environment.CV_AUDIT_WAL_PATH", "/var/lib/other/audit.wal"),
         "the volume's target"),
        (_set("services.api.secrets", [{"source": _KEY, "target": f"{_VOLUME}/k"}]),
         "on the audit volume"),
        (_set("services.api.secrets", [{"source": _KEY, "target": f"../..{_VOLUME}/k"}]),
         "on the audit volume"),
    ],
    ids=["no-volume", "relative", "dot-dot", "not-read-only", "bind", "extra-bind", "tmpfs",
         "other-directory", "secret-on-the-volume", "secret-dot-dot"],
)  # fmt: skip
def test_negative_control_the_volume_guard_catches(change: Change, fragment: str) -> None:
    doc = copy.deepcopy(_doc())
    change(doc)
    assert any(fragment in p for p in audit_volume_problems(doc))


# --- ADR-0037 decision 6: the lane key is a file secret, off the environment and the volume ------


def lane_key_problems(doc: dict[str, Any], env_example: str) -> list[str]:
    problems: list[str] = []
    secret = (doc.get("secrets") or {}).get(_KEY) or {}
    source = _SOURCE.fullmatch(str(secret.get("file", "")))
    if set(secret) != {"file"} or source is None:
        problems.append(f"secret {_KEY} is not a file secret defaulting to /dev/null: {secret!r}")
    elif _DAST_REPLACED.search(source[1]):
        problems.append(f"{source[1]} would get a random value from dast-auth-zap.yml")
    elif f"\n{source[1]}=\n" not in f"\n{env_example}":
        problems.append(f".env.example has no empty placeholder line {source[1]}=")
    mounts = [e for e in _api(doc).get("secrets") or [] if isinstance(e, dict)]
    mounts = [e for e in mounts if e.get("source") == _KEY]
    if len(mounts) != 1:
        return [*problems, f"api does not mount {_KEY} once"]
    (uid, gid), entry = _image_user(), mounts[0]
    default = Settings.model_fields["audit_lane_mac_file"].default  # not the ambient environment
    want = {"target": PurePosixPath(default), "mode": 0o400, "uid": uid, "gid": gid}
    got = {"target": _target(entry), "mode": entry.get("mode"), "uid": str(entry.get("uid")),
           "gid": str(entry.get("gid"))}  # fmt: skip
    wrong = [k for k in want if got[k] != want[k]]
    return problems + [f"api's {_KEY} {k} is {got[k]!r}, not {want[k]!r}" for k in wrong]


def test_the_lane_key_is_a_file_secret_at_the_loaders_path_and_the_images_user() -> None:
    assert lane_key_problems(_doc(), _ENV_EXAMPLE.read_text(encoding="utf-8")) == []


_ENTRY: dict[str, Any] = {"source": _KEY, "target": _KEY, "uid": "10001", "gid": "10001",
                          "mode": 0o400}  # fmt: skip


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        (_set(f"secrets.{_KEY}", {"environment": "CV_AUDIT_LANE_KEY_HEX"}), "not a file secret"),
        (_set(f"secrets.{_KEY}", {"file": "./secrets/cv_audit_lane_key"}), "defaulting"),
        (_set(f"secrets.{_KEY}", {"file": "${CV_AUDIT_LANE_KEY_FILE:-/dev/null}"}), "dast-auth"),
        (_set(f"secrets.{_KEY}", {"file": "${CV_AUDIT_LANE_HMAC_PATH:-/dev/null}"}), "placeholder"),
        (_set("services.api.secrets", None), "once"),
        (_set("services.api.secrets", [_ENTRY | {"target": "/run/secrets/other"}]), "target"),
        (_set("services.api.secrets", [_ENTRY | {"mode": 0o444}]), "mode"),
        (_set("services.api.secrets", [_ENTRY | {"uid": "0"}]), "uid"),
        (_set("services.api.secrets", [_ENTRY | {"gid": "0"}]), "gid"),
    ],
    ids=["environment-secret", "no-default", "dast-name", "no-placeholder", "not-mounted",
         "other-target", "mode-0444", "uid-0", "gid-0"],
)  # fmt: skip
def test_negative_control_the_lane_key_guard_catches(change: Change, fragment: str) -> None:
    doc = copy.deepcopy(_doc())
    change(doc)
    example = _ENV_EXAMPLE.read_text(encoding="utf-8")
    assert any(fragment in p for p in lane_key_problems(doc, example))


def environment_form_problems(doc: dict[str, Any]) -> list[str]:
    """The keys have no environment form: a service that sets one refuses boot (S2b-1)."""
    return [
        f"service {name!r} sets {form}"
        for name, service in (doc.get("services") or {}).items()
        for form in sorted({k.upper() for k in _env(service)} & ENVIRONMENT_FORMS)
    ]


@pytest.mark.parametrize("path", _COMPOSE_FILES, ids=lambda p: p.name)
def test_no_compose_file_gives_a_service_the_lane_keys_environment_form(path: Path) -> None:
    assert environment_form_problems(_doc(path)) == []


@pytest.mark.parametrize("form", sorted(ENVIRONMENT_FORMS))
def test_negative_control_the_environment_guard_catches(form: str) -> None:
    doc = copy.deepcopy(_doc())
    _api(doc)["environment"][form.lower()] = ""
    assert environment_form_problems(doc) == [f"service 'api' sets {form}"]

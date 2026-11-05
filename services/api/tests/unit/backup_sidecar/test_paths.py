"""#3319 B1b (ADR-0041 section 3): the sidecar's confinement on the backup volume, a mirror of the
API's `storage/backup_artefacts.py` walk: absolute and canonical below the root or refused before
any I/O, `O_NOFOLLOW` at every component, regular single-link files on the root's device only;
a quarantine name is never replaced; errors carry a code, never a path."""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from pathlib import Path

import pytest

from cvbackup.paths import QUARANTINE_DIR, PathFault, Root, components


def _root(tmp_path: Path) -> Root:
    root = Root(str(tmp_path / "backups"))
    (tmp_path / "backups").mkdir()
    root.ensure((QUARANTINE_DIR, "pg_dump"))
    return root


def _location(root: Root) -> str:
    return f"{root.path}/pg_dump/{uuid.uuid4()}.age"


def _name() -> str:
    return f"{uuid.uuid4()}.age"


def _code(call: Callable[..., object], *args: str) -> str:
    with pytest.raises(PathFault) as fault:
        call(*args)
    assert str(fault.value) == fault.value.code  # a code, never a path
    return fault.value.code


@pytest.mark.parametrize("path", ["", "/", "relative/x", "/a//b", "/a/./b", "/a/../b", "/a\x00b"])
def test_only_absolute_canonical_paths_have_components(path: str) -> None:
    assert components(path) is None or path == "/"
    if path in ("", "/"):
        with pytest.raises(ValueError, match="canonical form, not /"):
            Root(path)


def test_a_location_outside_the_root_is_refused_before_any_io(tmp_path: Path) -> None:
    root = _root(tmp_path)
    outside = f"{tmp_path}/elsewhere/pg_dump/{uuid.uuid4()}.age"
    assert root.relative(outside) is None and root.relative(root.path) is None
    for method in (root.open_artefact, root.exists):
        assert _code(method, outside) == "artefact_missing"
    assert _code(root.quarantine, outside, _name()) == "artefact_missing"


def test_only_a_regular_single_link_file_opens(tmp_path: Path) -> None:
    root = _root(tmp_path)
    directory, linked = _location(root), _location(root)
    os.mkdir(directory)
    Path(linked).write_bytes(b"x")
    os.link(linked, f"{root.path}/pg_dump/second-name")
    assert _code(root.open_artefact, directory) == "artefact_missing"
    assert _code(root.open_artefact, linked) == "artefact_missing"
    assert _code(root.open_artefact, f"{tmp_path}/backups/nodir/x.age") == "artefact_missing"


def test_a_symlinked_directory_on_the_way_is_refused(tmp_path: Path) -> None:
    root = _root(tmp_path)
    (tmp_path / "other").mkdir()
    os.symlink(tmp_path / "other", f"{root.path}/linked")
    assert _code(root.exists, f"{root.path}/linked/{uuid.uuid4()}.age") == "artefact_missing"


def test_a_quarantine_name_is_never_replaced_and_a_purge_tolerates_absence(tmp_path: Path) -> None:
    root = _root(tmp_path)
    first, second, kept = _location(root), _location(root), _name()
    Path(first).write_bytes(b"first")
    Path(second).write_bytes(b"second")
    assert root.quarantine(first, kept) is True
    assert _code(root.quarantine, second, kept) == "volume_unavailable"
    assert Path(second).read_bytes() == b"second"  # untouched
    assert (tmp_path / "backups" / QUARANTINE_DIR / kept).read_bytes() == b"first"
    assert root.quarantine(first, _name()) is False  # nothing left at the location
    root.purge(kept)
    root.purge(kept)  # already gone: purged
    assert not (tmp_path / "backups" / QUARANTINE_DIR / kept).exists()


def test_a_directory_at_a_location_is_never_quarantined(tmp_path: Path) -> None:
    root = _root(tmp_path)
    directory = _location(root)
    os.mkdir(directory)
    assert _code(root.quarantine, directory, _name()) == "artefact_missing"
    assert os.path.isdir(directory)


@pytest.mark.parametrize("name", ["../pg_dump/{u}.age", "pg_dump/{u}.age", ".", "..", "", "x.age",
                                  "{u}.age/", ".{u}.age", "{u}"])  # fmt: skip
def test_quarantine_and_purge_refuse_a_name_that_is_not_one_artefact_name(
    tmp_path: Path, name: str
) -> None:
    root = _root(tmp_path)
    victim, location = _location(root), _location(root)
    Path(victim).write_bytes(b"victim")
    Path(location).write_bytes(b"artefact")
    name = name.format(u=Path(victim).stem)
    assert _code(root.purge, name) == "artefact_missing"
    assert _code(root.quarantine, location, name) == "artefact_missing"
    assert Path(victim).read_bytes() == b"victim" and Path(location).read_bytes() == b"artefact"
    assert os.listdir(f"{root.path}/{QUARANTINE_DIR}") == []


def test_a_location_is_exactly_a_kind_and_a_name_below_the_root(tmp_path: Path) -> None:
    root = _root(tmp_path)
    location = _location(root)
    assert root.artefact(location) == ("pg_dump", Path(location).name)
    os.makedirs(f"{root.path}/{QUARANTINE_DIR}/pg_dump")
    deeper = f"{root.path}/{QUARANTINE_DIR}/pg_dump/{_name()}"
    Path(deeper).write_bytes(b"kept")
    hidden = f"{root.path}/{QUARANTINE_DIR}/{_name()}"
    Path(hidden).write_bytes(b"kept")
    for refused in (deeper, hidden, f"{root.path}/{_name()}", f"{root.path}/pg_dump/x.age"):
        for method in (root.artefact, root.open_artefact, root.exists):
            assert _code(method, refused) == "artefact_missing"
        assert _code(root.quarantine, refused, _name()) == "artefact_missing"
    assert Path(deeper).read_bytes() == b"kept" and Path(hidden).read_bytes() == b"kept"

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
    assert _code(root.quarantine, outside, "x.age") == "artefact_missing"


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
    first, second = _location(root), _location(root)
    Path(first).write_bytes(b"first")
    Path(second).write_bytes(b"second")
    assert root.quarantine(first, "kept.age") is True
    assert _code(root.quarantine, second, "kept.age") == "volume_unavailable"
    assert Path(second).read_bytes() == b"second"  # untouched
    assert (tmp_path / "backups" / QUARANTINE_DIR / "kept.age").read_bytes() == b"first"
    assert root.quarantine(first, "again.age") is False  # nothing left at the location
    root.purge("kept.age")
    root.purge("kept.age")  # already gone: purged
    assert not (tmp_path / "backups" / QUARANTINE_DIR / "kept.age").exists()


def test_a_directory_at_a_location_is_never_quarantined(tmp_path: Path) -> None:
    root = _root(tmp_path)
    directory = _location(root)
    os.mkdir(directory)
    assert _code(root.quarantine, directory, "d.age") == "artefact_missing"
    assert os.path.isdir(directory)

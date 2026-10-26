"""Fixtures for cv-recorder-no-path-delete (E16-X02, ADR-0003: the recorder module owns no path)."""
import os
import shutil
from pathlib import Path


def planted(key, root):
    (Path(root) / key).unlink()  # ruleid: cv-recorder-no-path-delete
    os.remove(root)  # ruleid: cv-recorder-no-path-delete
    shutil.rmtree(root)  # ruleid: cv-recorder-no-path-delete
    os.replace(root, root + ".old")  # ruleid: cv-recorder-no-path-delete
    os.removedirs(root)  # ruleid: cv-recorder-no-path-delete


def planted_typed(part: Path, target: Path):
    part.rename(target)  # ruleid: cv-recorder-no-path-delete
    part.replace(target)  # ruleid: cv-recorder-no-path-delete


async def good(cold, symbol, stream, key):
    return await cold.delete(symbol, stream, key)  # ok: cv-recorder-no-path-delete


def good_untyped_replace(name: str, record):
    label = name.replace("-", "_")  # ok: cv-recorder-no-path-delete
    return label, record.replace(name=label)  # ok: cv-recorder-no-path-delete

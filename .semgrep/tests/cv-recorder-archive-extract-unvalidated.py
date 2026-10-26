"""Fixtures for cv-recorder-archive-extract-unvalidated (E16-X02, SR-097)."""
import shutil
import tarfile
import zipfile


def planted(archive, dest):
    tarfile.open(archive).extractall(dest)  # ruleid: cv-recorder-archive-extract-unvalidated
    with tarfile.open(archive) as tf:
        tf.extractall(dest)  # ruleid: cv-recorder-archive-extract-unvalidated
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(dest)  # ruleid: cv-recorder-archive-extract-unvalidated
        for member in zf.infolist():
            zf.extract(member, dest)  # ruleid: cv-recorder-archive-extract-unvalidated
    shutil.unpack_archive(archive, dest)  # ruleid: cv-recorder-archive-extract-unvalidated


def planted_class_open(archive, dest):
    tarfile.TarFile.open(archive).extractall(dest)  # ruleid: cv-recorder-archive-extract-unvalidated
    tarfile.TarFile(archive).extract("member", dest)  # ruleid: cv-recorder-archive-extract-unvalidated
    with tarfile.TarFile.open(archive) as tf:
        tf.extractall(dest)  # ruleid: cv-recorder-archive-extract-unvalidated
    tar = tarfile.TarFile.open(archive)
    tar.extract("member", dest)  # ruleid: cv-recorder-archive-extract-unvalidated


def planted_typed(tf: tarfile.TarFile, zf: zipfile.ZipFile, dest):
    tf.extractall(dest)  # ruleid: cv-recorder-archive-extract-unvalidated
    tf.extract("member", dest)  # ruleid: cv-recorder-archive-extract-unvalidated
    zf.extractall(dest)  # ruleid: cv-recorder-archive-extract-unvalidated
    zf.extract("member", dest)  # ruleid: cv-recorder-archive-extract-unvalidated


def good(archive, dest, paths):
    with tarfile.open(archive) as tf:
        tf.extractall(dest, filter="data")  # ok: cv-recorder-archive-extract-unvalidated
    with zipfile.ZipFile(archive) as zf:
        with zf.open("BTCUSDT2026-06-05.csv") as fh:  # ok: cv-recorder-archive-extract-unvalidated
            (paths.partition_dir / "part-0000.csv").write_bytes(fh.read())  # ok: cv-recorder-archive-extract-unvalidated


def good_typed(tf: tarfile.TarFile, zf: zipfile.ZipFile, dest):
    tf.extractall(dest, filter="data")  # ok: cv-recorder-archive-extract-unvalidated
    return zf.read("member")  # ok: cv-recorder-archive-extract-unvalidated

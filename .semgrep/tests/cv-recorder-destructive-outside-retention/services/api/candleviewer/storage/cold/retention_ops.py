"""The allow-listed site: the reaper's cold delete (excluded by path)."""
import shutil


def _delete_sync(partition_dir):
    shutil.rmtree(partition_dir)  # ok: cv-recorder-destructive-outside-retention

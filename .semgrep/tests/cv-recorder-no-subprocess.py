"""Fixtures for cv-recorder-no-subprocess (E16-X02, SR-096)."""
import asyncio
import os
import shutil
import subprocess  # ruleid: cv-recorder-no-subprocess


def planted(root):
    subprocess.run(["du", "-s", root])  # ruleid: cv-recorder-no-subprocess
    os.system(f"rm -rf {root}")  # ruleid: cv-recorder-no-subprocess
    os.popen("df -k")  # ruleid: cv-recorder-no-subprocess
    os.execvp("du", ["du", root])  # ruleid: cv-recorder-no-subprocess


async def planted_async(root):
    await asyncio.create_subprocess_exec("du", root)  # ruleid: cv-recorder-no-subprocess
    await asyncio.create_subprocess_shell(f"df {root}")  # ruleid: cv-recorder-no-subprocess


def good(root):
    os.makedirs(root, exist_ok=True)  # ok: cv-recorder-no-subprocess
    return shutil.disk_usage(root)  # ok: cv-recorder-no-subprocess

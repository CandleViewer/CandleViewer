"""E42-Q03 (#1216): the perf API's port is its own, and the API that answers is the one started.

    python3 -I bench/admin/api_up.py free --port PORT
    python3 -I bench/admin/api_up.py wait --port PORT --pid PID [--tries 60] [--interval 2]

`free` exits 1 when anything listens on PORT, on any address: the run never starts beside a stack
that holds its port. `wait` polls `http://127.0.0.1:PORT/healthz`; after a 200 it requires PID
alive and every listener on PORT held by PID or a descendant (`uv run` starts the server as its
child). A listener whose owner cannot be read (another user's) is not ours: it fails closed. So
the run's k6, its sign-ins and their audit rows never reach another stack's API (C-5.7).
Exit 0 when the started API answers; 1 otherwise. Linux `/proc`, stdlib only.
"""

from __future__ import annotations

import argparse
import http.client
import os
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

PROC = Path("/proc")
LISTEN = "0A"


def listening_inodes(port: int) -> set[int]:
    """The socket inodes listening on `port`, IPv4 and IPv6, any address."""
    inodes: set[int] = set()
    for table in ("tcp", "tcp6"):
        path = PROC / "net" / table
        if not path.exists():
            continue
        for line in path.read_text().splitlines()[1:]:
            cols = line.split()
            if len(cols) > 9 and cols[3] == LISTEN and int(cols[1].rsplit(":", 1)[1], 16) == port:
                inodes.add(int(cols[9]))
    return inodes


def owners(inodes: set[int]) -> dict[int, set[int]]:
    """The PIDs holding each inode, of the processes this user may read."""
    found: dict[int, set[int]] = {inode: set() for inode in inodes}
    links = {f"socket:[{inode}]": inode for inode in inodes}
    for proc in PROC.iterdir():
        if not proc.name.isdigit():
            continue
        try:
            for fd in (proc / "fd").iterdir():
                inode = links.get(os.readlink(fd))
                if inode is not None:
                    found[inode].add(int(proc.name))
        except OSError:  # gone, or another user's: its sockets stay unowned (fail closed)
            continue
    return found


def descends(pid: int, root: int) -> bool:
    while pid > 1:
        if pid == root:
            return True
        try:
            status = (PROC / str(pid) / "status").read_text()
        except OSError:
            return False
        pid = int(next(ln.split()[1] for ln in status.splitlines() if ln.startswith("PPid:")))
    return pid == root


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def owned_by(port: int, pid: int) -> bool:
    """Something listens on `port`, and every listener is `pid`'s or a descendant's."""
    held = owners(listening_inodes(port))
    return bool(held) and all(p and all(descends(o, pid) for o in p) for p in held.values())


def healthy(port: int) -> bool:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)  # no proxy, loopback only
    try:
        conn.request("GET", "/healthz")
        return conn.getresponse().status == 200
    except OSError:
        return False
    finally:
        conn.close()


def wait(
    port: int,
    pid: int,
    tries: int,
    interval: float,
    probe: Callable[[int], bool] = healthy,
    sleep: Callable[[float], None] = time.sleep,
) -> int:
    for _ in range(tries):
        if not alive(pid):
            print("api_up: the started API exited", file=sys.stderr)
            return 1
        if probe(port):
            if owned_by(port, pid):
                return 0
            print(f"api_up: port {port} answers, but not from the started API", file=sys.stderr)
            return 1
        sleep(interval)
    print(f"api_up: no answer on port {port}", file=sys.stderr)
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="The perf API's port (E42-Q03).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    free = sub.add_parser("free")
    free.add_argument("--port", type=int, required=True)
    up = sub.add_parser("wait")
    up.add_argument("--port", type=int, required=True)
    up.add_argument("--pid", type=int, required=True)
    up.add_argument("--tries", type=int, default=60)
    up.add_argument("--interval", type=float, default=2.0)
    args = parser.parse_args(argv)
    if args.cmd == "free":
        if listening_inodes(args.port):
            print(f"api_up: port {args.port} is already in use: refusing", file=sys.stderr)
            return 1
        return 0
    return wait(args.port, args.pid, args.tries, args.interval)


if __name__ == "__main__":
    sys.exit(main())

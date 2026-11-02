"""Real, host-wide listening-socket enumerator for the composition root.

`binding_check.enumerator_from_sockets` only sees the sockets `uvicorn`
itself created; it cannot see a Windows-side `portproxy` leak on WSL (the
exact hazard `20-architecture.md` "WSL hazards" names) because that traffic
never touches a Python-owned socket object. This module enumerates the
*entire host's* listening sockets via `psutil.net_connections()` (which reads
`/proc/net/tcp*` on Linux/WSL and the OS-wide socket table on Windows) plus,
on Windows/WSL, the `netsh interface portproxy` table, which is the mechanism
that creates a leak `psutil` itself cannot see (a `portproxy` rule forwards a
Windows-side listening address to a WSL IP without there being a
Windows-owned listening socket that shares the WSL process's identity).

Fail-closed:
- `OSError`/`psutil.Error` propagate to the caller so `BindingSelfCheck.run()`
  treats an unreadable socket table as unsafe, per its own docstring.
- An enumeration that comes back *empty* is itself treated as unsafe: a
  process that binds to anything at all should always show at least one
  listening socket, so an empty result means the enumeration mechanism is
  broken (wrong permissions, wrong process scope, sandboxed/isolated netns)
  rather than that the host has no listeners. Silently reporting "OK" from a
  broken enumerator is exactly the failure mode this module exists to avoid.
"""

from __future__ import annotations

import re
import shutil
import subprocess  # nosec B404 - fixed argv, no shell, used to read a local netsh table only
import sys

import psutil

from .binding_check import SocketAddressEnumerator

_PORTPROXY_LINE = re.compile(
    r"^\s*(?P<listen_addr>\S+)\s+(?P<listen_port>\d+)\s+(?P<connect_addr>\S+)\s+(?P<connect_port>\d+)\s*$"
)


def _format(host: str, port: int | str) -> str:
    if ":" in host:
        return f"[{host}]:{port}"
    return f"{host}:{port}"


def _enumerate_psutil_listening_sockets() -> list[str]:
    """Enumerate every listening socket on the host via `psutil`.

    Unlike `psutil.Process().net_connections()` (which is scoped to the
    calling process and therefore blind to sockets owned by any other
    process, e.g. a `portproxy`-fed listener or another service sharing the
    host), `psutil.net_connections()` walks the whole host's socket table.
    """
    try:
        connections = psutil.net_connections(kind="inet")
    except psutil.Error as exc:  # pragma: no cover - platform/permission dependent
        raise OSError(str(exc)) from exc

    result: list[str] = []
    for conn in connections:
        if conn.status != psutil.CONN_LISTEN:
            continue
        # psutil types `laddr` as `addr | tuple[()]`: a listener with no local
        # address has nothing to report, and the empty tuple cannot be unpacked.
        laddr = conn.laddr
        if not laddr or len(laddr) < 2:
            continue
        host, port = laddr[0], laddr[1]
        result.append(_format(host, port))
    return result


def _enumerate_windows_portproxy_sockets() -> list[str]:
    """Best-effort enumeration of Windows `netsh interface portproxy` rules.

    Only meaningful on Windows (including the Windows side consulted from a
    WSL host, when `netsh.exe` is reachable). Returns `[]` when `netsh` is
    unavailable (e.g. plain Linux CI) rather than failing the whole check —
    the portproxy table is an *additional* leak surface, not the primary
    enumeration, so its absence is not itself evidence of a broken check.
    """
    if sys.platform != "win32":
        return []
    netsh = shutil.which("netsh")
    if netsh is None:  # pragma: no cover - environment dependent
        return []
    try:
        proc = subprocess.run(  # noqa: S603  # nosec B603 - fixed argv, no shell, local read-only query
            [netsh, "interface", "portproxy", "show", "all"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):  # pragma: no cover - environment dependent
        return []

    result: list[str] = []
    for line in proc.stdout.splitlines():
        match = _PORTPROXY_LINE.fullmatch(line)
        if not match:
            continue
        result.append(_format(match["listen_addr"], match["listen_port"]))
    return result


def enumerate_host_listening_sockets() -> list[str]:
    """Enumerate every listening socket on this host.

    Combines the host-wide `psutil` socket table with the Windows
    `portproxy` forwarding table (when present) so a `portproxy` rule that
    forwards a Windows-side address into WSL is caught even though no single
    process on either side owns a socket object naming both ends.

    Raises `OSError` (fail-closed) when the underlying `psutil` read fails,
    or when the combined result is empty: a listening process (this one, at
    minimum) always has at least one bound socket, so an empty result means
    the enumeration itself is broken, not that nothing is listening.
    """
    result = _enumerate_psutil_listening_sockets()
    result.extend(_enumerate_windows_portproxy_sockets())

    if not result:
        raise OSError(
            "enumerate_host_listening_sockets() returned no listening sockets at all; "
            "treating this as a broken enumeration (fail-closed) rather than a host with "
            "no listeners."
        )
    return result


def real_socket_enumerator() -> SocketAddressEnumerator:
    """Return the enumerator the composition root wires into `BindingSelfCheck`."""
    return enumerate_host_listening_sockets

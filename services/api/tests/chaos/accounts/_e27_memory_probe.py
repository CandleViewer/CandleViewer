"""E27-Q03 (#892): the credential-memory walk, run in a fresh interpreter.

`test_e27_kek_and_memory.py` starts this module as `python -m tests.chaos.accounts._e27_memory_probe
<mode>`. A fresh process holds only what this module imports, so a walk over every object the
collector tracks is bounded by that, never by what an earlier module of the same lane left alive
(the db-chaos lane runs all of `tests/integration` first). It prints one JSON line: the type names
of the live objects holding the marker's text.

Modes: `control`, the positive control (a marker held in a dict the collector does not track must
be found); `signing`, the criterion (after a signing call returns, no live object holds the
marker). The marker is a fixed prefix and random hex made here at run time, never a real key, and
it never leaves this process: only type names are printed.

Exit hygiene (#5325 delta look 6557442583): the probe shuts its loop's default executor down
within `EXECUTOR_GRACE_S`, writes the names of the threads still alive to stderr before it returns,
and arms `faulthandler` to write every thread's stack to stderr at `STACK_DUMP_S`, before the
parent's `PROBE_TIMEOUT_S` kill, so a child that does not exit says where it waits.
"""

from __future__ import annotations

import asyncio
import faulthandler
import gc
import json
import os
import sys
import threading
from typing import Any

from candleviewer.secrets import KEY_ID_SLOT
from candleviewer.secrets.secret import Secret
from candleviewer.secrets.service import SecretsService, mint_borrower
from tests.unit.credentials_m2._service_fakes import _ctx, _Src, _svc
from tests.unit.credentials_m2._vectors import ACCOUNT, KEK_V1, SNAPSHOT

#: Fixture-only marker: a fixed prefix and random hex made per run, so no copy sits in the source.
MARK_PREFIX = "e27q03-marker-"
#: Seconds the default executor gets to join its workers once the service has stopped.
EXECUTOR_GRACE_S = 10.0
#: Seconds after start when `faulthandler` writes every thread's stack to stderr (no exit): well
#: inside the parent's 60 s `PROBE_TIMEOUT_S`, so the parent reads the stacks before it kills.
STACK_DUMP_S = 45.0


def _marked() -> tuple[str, Secret[str]]:
    """The needle and the secret, as two distinct objects of equal text: the walk skips the needle
    by identity only, so a reference to the secret's own object is never hidden."""
    text = MARK_PREFIX + os.urandom(12).hex()
    return "".join(list(text)), Secret(text)


def holders(needle: str) -> list[str]:
    """Type names of live objects holding `needle`'s text in a str, bytes or bytearray. Starts at
    every object the collector tracks and descends into the containers it does not track (a dict
    or tuple of strings only), so a string is found wherever a reachable container holds it."""
    raw = needle.encode()
    found: list[str] = []
    seen: set[int] = set()
    stack: list[Any] = gc.get_objects()
    while stack:
        obj = stack.pop()
        if id(obj) in seen:
            continue
        seen.add(id(obj))
        for ref in gc.get_referents(obj):
            if ref is needle or ref is raw:
                continue
            if isinstance(ref, str):
                hit = needle in ref
            elif isinstance(ref, bytes | bytearray):
                hit = raw in ref
            else:
                hit = False
                if not gc.is_tracked(ref) and isinstance(ref, dict | tuple | list | frozenset):
                    stack.append(ref)
            if hit:
                found.append(type(obj).__name__)
    return found


def control() -> list[str]:
    """A marker held in a dict of strings only (not tracked by gc), kept by a tracked list."""
    needle, kept = _marked()
    holder = {"held": "".join(list(needle))}
    box = [holder]
    assert not gc.is_tracked(holder) and gc.is_tracked(box)
    found = holders(needle)
    del box, holder, kept
    return found


async def signing() -> list[str]:
    """Store the marker as a key's secret, sign once, drop every reference here, then walk."""
    svc: SecretsService = _svc(_Src(KEK_V1, 1))
    await svc.start(_ctx())
    try:
        needle, secret = _marked()
        broker = svc._require()
        meta = await broker.store("demo", ACCOUNT, "m", Secret("ABCD1234"), secret, SNAPSHOT)
        broker._store.activate(meta.key_id)  # type: ignore[attr-defined]  # in-memory fake helper
        del secret
        signed = await mint_borrower(svc, "exchange_adapter").sign(
            meta.key_id, (KEY_ID_SLOT,), purpose="sign_rest"
        )
        assert signed.signature  # the call returned a MAC
        del signed
        gc.collect()
        return holders(needle)
    finally:
        await svc.stop(0)
        # `asyncio.run` would also join these workers, with no bound of ours: here a stuck one fails
        # the probe with a reason instead of keeping the process alive.
        async with asyncio.timeout(EXECUTOR_GRACE_S):
            await asyncio.get_running_loop().shutdown_default_executor()


def threads_alive() -> list[str]:
    """Name and daemon flag of every thread the `threading` module still knows of."""
    return [f"{t.name} daemon={t.daemon}" for t in threading.enumerate()]


def main(argv: list[str]) -> int:
    faulthandler.dump_traceback_later(STACK_DUMP_S, exit=False)
    if argv == ["control"]:
        found = control()
    elif argv == ["signing"]:
        found = asyncio.run(signing())
    else:
        print("usage: _e27_memory_probe control|signing", file=sys.stderr)
        return 2
    print("threads alive at return: " + json.dumps(threads_alive()), file=sys.stderr, flush=True)
    print(json.dumps(found), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

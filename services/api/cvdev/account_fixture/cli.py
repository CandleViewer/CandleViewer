"""#2893 S14: the switch CLI, the command line over `control` that a fixture stack runs.

    python -m cvdev.account_fixture.cli clock set 2026-10-05T12:00:00+00:00
    python -m cvdev.account_fixture.cli clock advance 3600
    python -m cvdev.account_fixture.cli switch fixture-compliant-0001 [--to S] [--overlay O ...]

On a stack it runs in the api container (`docker compose exec api ...`, with the fixture compose
override, `infra/compose/docker-compose.account-fixture.yml`), on the same `CV_ACCOUNT_FIXTURE_DIR`
and pack (`pack.PACK_ROOT`, under the working directory) as the stack's transport. `clock` sets or
advances the fixture clock (`FixtureClock`: scenario time, exchange time and the request log's
`ts`; signing keeps the real clock). `switch` calls `KeyStates.switch`: the key answers as `--to`
(by default its stored scenario's `switch_to`) with the overlays named, and its scenario time
restarts at the switch; one `switch` line goes to the request log.

It refuses, changing nothing, unless the fixture is armed in a non-live environment: the settings
load (their own dev/test gate) with `CV_ACCOUNT_FIXTURE` and `CV_ACCOUNT_FIXTURE_DIR` set, and
`Settings.account_fixture_refusal` is None (demo, the synthetic feed, no `CV_BYBIT_API_*`, no test
clock). Every failure prints one fixed line, never a path, a value, a key's secret or a traceback,
and exits 2. Nothing here imports `candleviewer.secrets` or `candleviewer.audit`.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Final

from candleviewer.settings import Environment, Settings
from cvdev.account_fixture.control import FixtureClock, KeyStateError, KeyStates
from cvdev.account_fixture.pack import PACK_ROOT, Pack, fixture_key_ids
from cvdev.account_fixture.requestlog import RequestLog

PROG: Final = "python -m cvdev.account_fixture.cli"
DESCRIPTION: Final = "Set the account fixture clock or switch a pack key, on an armed demo stack."
EXIT_REFUSED: Final = 2
NOT_ARMED: Final = "the account fixture is not armed: CV_ACCOUNT_FIXTURE is unset"
NO_DIR: Final = "the account fixture is armed without CV_ACCOUNT_FIXTURE_DIR"
LIVE: Final = "the account fixture CLI never runs in a live environment"
OUT_OF_RANGE: Final = "the fixture clock cannot move that far"
STATE_FAILED: Final = "the fixture state directory or the account pack could not be used"


class CliRefused(Exception):
    """A fixed message, printed as the CLI's one line; it never names a path, value or secret."""


def _seconds(text: str) -> timedelta:
    try:
        seconds = Decimal(text)
    except InvalidOperation:
        raise argparse.ArgumentTypeError("seconds must be a signed decimal") from None
    try:
        if seconds.is_finite():
            return timedelta(microseconds=int(seconds * 1_000_000))
    except OverflowError:
        pass
    raise argparse.ArgumentTypeError("seconds must be a signed decimal within timedelta's range")


def _moment(text: str) -> datetime:
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError("the moment must be ISO 8601 with an offset") from None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=PROG, description=DESCRIPTION)
    commands = parser.add_subparsers(dest="command", required=True)
    clock = commands.add_parser("clock", help="set or advance the fixture clock")
    moves = clock.add_subparsers(dest="move", required=True)
    moves.add_parser("set", help="the clock reads MOMENT now").add_argument("moment", type=_moment)
    advance = moves.add_parser("advance", help="move the clock by SECONDS (may be negative)")
    advance.add_argument("seconds", type=_seconds)
    switch = commands.add_parser("switch", help="switch a pack key's scenario at runtime")
    switch.add_argument("key_id", help="a pack key id, fixture-<scenario>-NNNN")
    switch.add_argument("--to", dest="scenario", help="a key scenario (default: its switch_to)")
    switch.add_argument("--overlay", dest="overlays", action="append", default=[])
    return parser


def armed(settings: Settings) -> str:
    """`CV_ACCOUNT_FIXTURE_DIR`, or `CliRefused` unless the fixture is armed off live."""
    if settings.environment is Environment.LIVE:
        raise CliRefused(LIVE)
    if settings.account_fixture is None:
        raise CliRefused(NOT_ARMED)
    refusal = settings.account_fixture_refusal()
    if refusal is not None:
        raise CliRefused(refusal)  # Settings' fixed messages: a switch and a rule, never a value
    if settings.account_fixture_dir is None:
        raise CliRefused(NO_DIR)
    return settings.account_fixture_dir


def run(args: argparse.Namespace, settings: Settings, pack: Pack | None = None) -> str:
    """Do what `args` asks on the armed stack's state; the line to print. Raises `CliRefused`."""
    directory = armed(settings)
    try:
        clock = FixtureClock(directory)
        if args.command == "clock":
            if args.move == "set":
                clock.set(args.moment)
            else:
                clock.advance(args.seconds)
            return f"fixture clock now reads {clock().isoformat()}"
        pack = pack or Pack(PACK_ROOT)
        env = settings.environment
        with RequestLog(
            directory, process_env=env, clock=clock, pack_key_ids=fixture_key_ids(pack)
        ) as log:
            keys = KeyStates(directory, pack, log=log, clock=clock)
            state = keys.switch(args.key_id, args.scenario, overlays=args.overlays)
    except (KeyStateError, ValueError) as exc:
        if isinstance(exc, KeyStateError) or str(exc).startswith("the fixture clock"):
            raise CliRefused(str(exc)) from None  # the control surface's fixed rule messages
        raise CliRefused(STATE_FAILED) from None  # a pack or log message may name a path
    except OverflowError:
        raise CliRefused(OUT_OF_RANGE) from None
    except (OSError, RuntimeError, KeyError):
        raise CliRefused(STATE_FAILED) from None
    overlays = ", ".join(state.overlays) or "none"
    started = state.started.isoformat()
    return f"{args.key_id} answers as {state.scenario} (overlays: {overlays}) from {started}"


def main(
    argv: Sequence[str] | None = None, *, settings: Settings | None = None, pack: Pack | None = None
) -> int:
    args = _parser().parse_args(argv)
    try:
        try:
            resolved = settings or Settings()
        except ValueError:  # a pydantic ValidationError: its text may hold an input value
            raise CliRefused("invalid settings; nothing changed") from None
        line = run(args, resolved, pack)
    except CliRefused as refused:
        sys.stderr.write(f"account-fixture: refused: {refused}\n")
        return EXIT_REFUSED
    except Exception:  # nothing unexpected may print a traceback, path or value
        sys.stderr.write(f"account-fixture: refused: {STATE_FAILED}\n")
        return EXIT_REFUSED
    sys.stdout.write(f"account-fixture: {line}\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - `python -m`; `main` is tested in process
    raise SystemExit(main())

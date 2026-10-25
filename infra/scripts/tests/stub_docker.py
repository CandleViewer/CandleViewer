"""A stand-in for `docker` in `test_demo_host_owner_first_run.py` (#3180). Not collected by pytest.

The first run calls `docker compose ... stop api`, then `... run --rm --no-deps bootstrap-owner
--owner <email>` (#4479's CLI, which prints the Owner's invite token once on its TTY), then `...
up -d --wait api`. This stub records its arguments to `docker.jsonl` and the call to the shared
`sequence.log`, and never reads stdin: the Owner retypes the CLI's phrase into the CLI's own TTY,
so the script's answers are no business of docker's. It exits with the scenario's status for its
subcommand (`docker` in `scenario.json`, 0 by default) and, for `run`, prints the scenario's
`docker_print` line where the CLI prints the token, to show where that output goes.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

#: The global options of `docker compose` that take a value, before the subcommand.
_TAKES_VALUE = frozenset({"-p", "--project-name", "-f", "--file", "--profile", "--env-file"})


def main() -> int:
    stub = Path(os.environ["CV_STUB_DIR"])
    args = sys.argv[1:]
    with (stub / "docker.jsonl").open("a", encoding="utf-8") as log:
        log.write(json.dumps(args) + "\n")
    words = args[1:] if args[:1] == ["compose"] else args
    at = 0
    while at < len(words) and words[at].startswith("-"):
        at += 2 if words[at] in _TAKES_VALUE else 1
    command = words[at] if at < len(words) else ""
    with (stub / "sequence.log").open("a", encoding="utf-8") as log:
        log.write(f"docker {command}\n")
    scenario = json.loads((stub / "scenario.json").read_text(encoding="utf-8"))
    if command == "run":
        print(scenario.get("docker_print", ""), flush=True)
    return int(scenario.get("docker", {}).get(command, 0))


if __name__ == "__main__":
    raise SystemExit(main())

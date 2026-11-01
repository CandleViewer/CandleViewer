"""The gate of the real-QuestDB leg (`test_s05b`): when may a test stop the compose QuestDB?

It stops and starts that container, so it must only ever do so on a stack the job owns. On this
host a self-hosted runner (`cv-bench-01`) sets `GITHUB_ACTIONS` beside a demo QuestDB, so that
variable alone proves nothing: a GitHub-hosted runner is `RUNNER_ENVIRONMENT=github-hosted`, and
both it and a local run must name the chaos compose project.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Mapping, Sequence

#: The compose project of the chaos stack, the single source. `_job-integration.yml` sets
#: `COMPOSE_PROJECT_NAME` to it on every storage chaos step (stack up, pytest, repeat, down), and
#: `_stack.py`'s `docker compose` calls inherit it from the environment; a local run pins it too.
CHAOS_PROJECT = "cv-chaos"


def stack_skip_reason(env: Mapping[str, str]) -> str | None:
    """Why the container test must not run in this environment, or `None` when it may."""
    if env.get("GITHUB_ACTIONS"):
        if env.get("RUNNER_ENVIRONMENT") != "github-hosted":
            return "GITHUB_ACTIONS without a github-hosted runner: the stack may not be ours"
        if env.get("COMPOSE_PROJECT_NAME") != CHAOS_PROJECT:
            return f"a hosted run needs COMPOSE_PROJECT_NAME={CHAOS_PROJECT} (the job pins it)"
        return None
    if env.get("CV_CHAOS_STACK") == "1":
        if env.get("COMPOSE_PROJECT_NAME") == CHAOS_PROJECT:
            return None
        return f"CV_CHAOS_STACK=1 needs COMPOSE_PROJECT_NAME={CHAOS_PROJECT}"
    return "stops the compose QuestDB: github-hosted CI, or a pinned local chaos stack only"


#: Finds the container publishing a host port: its `docker inspect` document, or `None`.
Finder = Callable[[int], Mapping[str, object] | None]


def _docker(*args: str) -> subprocess.CompletedProcess[str]:
    argv = ["docker", *args]
    return subprocess.run(  # noqa: S603 - fixed argv, no shell
        argv, capture_output=True, text=True, errors="replace", timeout=20, check=False
    )


def docker_find(port: int) -> Mapping[str, object] | None:
    """The real finder: `docker ps` for the publisher of `port`, then `docker inspect` of it."""
    ps = _docker("ps", "-q", "--filter", f"publish={port}")
    ids = ps.stdout.split()
    if ps.returncode != 0 or len(ids) != 1:
        return None
    out = _docker("inspect", ids[0])
    docs = json.loads(out.stdout) if out.returncode == 0 and out.stdout.strip() else []
    return docs[0] if len(docs) == 1 and isinstance(docs[0], dict) else None


def questdb_ownership_skip(
    ports: Sequence[int], find: Finder = docker_find, project: str = CHAOS_PROJECT
) -> str | None:
    """The harness guard (the k6 host guard's twin): refuse any QuestDB we cannot prove is ours.

    Every port the leg talks to must be published by a compose container of `project` whose
    service is `questdb`. A port with no such container (a demo stack, a bare process, an
    unknown host) is never used: the test skips."""
    for port in ports:
        found = find(port)
        if found is None:
            return f"nothing identifiable publishes port {port}: not a container we own"
        config = found.get("Config")
        labels = config.get("Labels") if isinstance(config, Mapping) else None
        labels = labels if isinstance(labels, Mapping) else {}
        if labels.get("com.docker.compose.project") != project:
            return f"port {port} is published by a container outside compose project {project}"
        if labels.get("com.docker.compose.service") != "questdb":
            return f"port {port} is not published by the questdb service"
    return None

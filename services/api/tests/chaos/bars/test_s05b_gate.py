"""The s05b gate, without a container: it opens only on a stack the job owns (E12-Q06, #529)."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from tests.chaos.bars._gate import CHAOS_PROJECT, questdb_ownership_skip, stack_skip_reason

pytestmark = pytest.mark.chaos

HOSTED = {
    "GITHUB_ACTIONS": "true",
    "RUNNER_ENVIRONMENT": "github-hosted",
    "COMPOSE_PROJECT_NAME": CHAOS_PROJECT,
}


def test_gate_opens_on_a_github_hosted_runner() -> None:
    assert stack_skip_reason(HOSTED) is None
    assert (
        questdb_ownership_skip(
            [8812, 9009], lambda port: _container(HOSTED["COMPOSE_PROJECT_NAME"])
        )
        is None
    )


def test_gate_stays_shut_on_a_hosted_run_that_did_not_pin_the_project() -> None:
    unpinned = {k: v for k, v in HOSTED.items() if k != "COMPOSE_PROJECT_NAME"}
    assert stack_skip_reason(unpinned)
    assert stack_skip_reason({**unpinned, "COMPOSE_PROJECT_NAME": "compose"})


def test_gate_stays_shut_on_a_self_hosted_runner_beside_a_demo_stack() -> None:
    assert stack_skip_reason({"GITHUB_ACTIONS": "true", "RUNNER_ENVIRONMENT": "self-hosted"})
    assert stack_skip_reason({"GITHUB_ACTIONS": "true"})  # variable absent: not proven hosted


def test_gate_opens_locally_only_for_the_pinned_chaos_project() -> None:
    assert stack_skip_reason({"CV_CHAOS_STACK": "1", "COMPOSE_PROJECT_NAME": CHAOS_PROJECT}) is None
    assert stack_skip_reason({"CV_CHAOS_STACK": "1"})
    assert stack_skip_reason({"CV_CHAOS_STACK": "1", "COMPOSE_PROJECT_NAME": "candleviewer"})


def test_gate_is_shut_by_default_and_a_self_hosted_runner_cannot_use_the_local_flag() -> None:
    assert stack_skip_reason({})
    assert stack_skip_reason({"GITHUB_ACTIONS": "true", "CV_CHAOS_STACK": "1",
                              "COMPOSE_PROJECT_NAME": CHAOS_PROJECT})  # fmt: skip


def test_gate_reads_the_real_environment_through_the_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os

    for name in ("GITHUB_ACTIONS", "RUNNER_ENVIRONMENT", "CV_CHAOS_STACK", "COMPOSE_PROJECT_NAME"):
        monkeypatch.delenv(name, raising=False)
    assert stack_skip_reason(os.environ)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "github-hosted")
    assert stack_skip_reason(os.environ)  # not pinned yet
    monkeypatch.setenv("COMPOSE_PROJECT_NAME", CHAOS_PROJECT)
    assert stack_skip_reason(os.environ) is None


def _container(project: str, service: str = "questdb") -> Mapping[str, object]:
    labels = {"com.docker.compose.project": project, "com.docker.compose.service": service}
    return {"Id": "abc123", "Config": {"Labels": labels}}


def test_guard_accepts_ports_published_by_our_questdb_container() -> None:
    assert questdb_ownership_skip([8812, 9009], lambda port: _container(CHAOS_PROJECT)) is None


def test_guard_refuses_a_port_nothing_identifiable_publishes() -> None:
    reason = questdb_ownership_skip([8812], lambda port: None)
    assert reason and "8812" in reason


def test_guard_refuses_a_demo_stack_in_another_compose_project() -> None:
    assert questdb_ownership_skip([8812], lambda port: _container("candleviewer-demo"))


def test_guard_refuses_a_container_that_is_not_the_questdb_service() -> None:
    assert questdb_ownership_skip([8812], lambda port: _container(CHAOS_PROJECT, "postgres"))


def test_guard_refuses_when_any_one_port_is_foreign() -> None:
    def find(port: int) -> Mapping[str, object] | None:
        return _container(CHAOS_PROJECT) if port == 8812 else _container("other")

    assert questdb_ownership_skip([8812, 9009], find)


def test_guard_refuses_a_container_document_without_labels() -> None:
    assert questdb_ownership_skip([8812], lambda port: {"Id": "x", "Config": {}})

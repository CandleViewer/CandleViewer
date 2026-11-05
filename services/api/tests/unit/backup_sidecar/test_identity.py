"""#3319 B1b (ADR-0041 section 4; AD-SC04, AD-SC06): an age identity is held only bound to one
job and one digest, in a buffer wiped when the job ends, fails, is cancelled or passes its
deadline, and it never shows: not in `repr`, `str`, a format, a log line, an exception, a pickle
or a copy. Identity material is generated per test (random bytes; no key is ever real)."""

from __future__ import annotations

import asyncio
import contextlib
import copy
import logging
import os
import pickle
from collections.abc import Callable

import pytest

from cvbackup.identity import BoundIdentity, IdentityRefused, IdentitySlots

JOB, OTHER_JOB = "job-a", "job-b"
DIGEST = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"


class Ticks:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _material() -> bytearray:
    """Marker-prefixed random material, so a leak is searchable."""
    return bytearray(b"CVBTESTIDENTITY-" + os.urandom(16).hex().encode())


def _bound(clock: Ticks, deadline: float = 200.0) -> tuple[BoundIdentity, bytes]:
    material = _material()
    kept = bytes(material)
    return BoundIdentity(JOB, DIGEST, material, deadline=deadline, clock=clock), kept


def test_bound_identity_takes_the_material_over_and_wipes_the_callers_buffer() -> None:
    material = _material()
    kept = bytes(material)
    identity = BoundIdentity(JOB, DIGEST, material, deadline=200.0, clock=Ticks())
    assert not any(material)
    assert bytes(identity.reveal(JOB, DIGEST)) == kept


def test_bound_identity_repr_and_str_never_show_material(
    caplog: pytest.LogCaptureFixture,
) -> None:
    identity, kept = _bound(Ticks())
    rendered = [repr(identity), str(identity), f"{identity}", f"{identity!r}", format(identity, "")]
    with caplog.at_level(logging.DEBUG):
        logging.getLogger("cvbackup").info("identity %s %r", identity, identity)
        logging.getLogger("cvbackup").error("in a list %s", [identity])
    rendered += [caplog.text]
    for text in rendered:
        assert "CVBTESTIDENTITY" not in text and kept.decode() not in text
    assert not hasattr(identity, "__dict__")


@pytest.mark.parametrize(
    "leak",
    [
        pytest.param(lambda i: pickle.dumps(i), id="pickle"),
        pytest.param(lambda i: copy.copy(i), id="copy"),
        pytest.param(lambda i: copy.deepcopy(i), id="deepcopy"),
        pytest.param(lambda i: bytes(i), id="bytes"),
        pytest.param(lambda i: i.__getstate__(), id="getstate"),
        pytest.param(lambda i: i.__reduce__(), id="reduce"),
    ],
)
def test_bound_identity_refuses_pickle_copy_and_serialisation(
    leak: Callable[[BoundIdentity], object],
) -> None:
    identity, _ = _bound(Ticks())
    with pytest.raises(IdentityRefused) as refused:
        leak(identity)
    assert "CVBTESTIDENTITY" not in str(refused.value) and refused.value.__cause__ is None


def test_bound_identity_for_other_job_or_digest_is_refused() -> None:
    identity, _ = _bound(Ticks())
    with pytest.raises(IdentityRefused, match="not_bound"):
        identity.reveal(OTHER_JOB, DIGEST)
    with pytest.raises(IdentityRefused, match="not_bound"):
        identity.reveal(JOB, "0" * 64)
    assert not identity.wiped


def test_bound_identity_after_deadline_is_refused_and_wiped() -> None:
    clock = Ticks()
    identity, _ = _bound(clock, deadline=150.0)
    clock.now = 150.0
    with pytest.raises(IdentityRefused, match="deadline"):
        identity.reveal(JOB, DIGEST)
    assert identity.wiped
    with pytest.raises(IdentityRefused, match="wiped"):
        identity.reveal(JOB, DIGEST)


def _held_slots(clock: Ticks) -> IdentitySlots:
    slots = IdentitySlots(clock)
    slots.expect(JOB, DIGEST, deadline=200.0)
    slots.deliver(JOB, DIGEST, _material())
    return slots


@pytest.mark.parametrize(
    "ending",
    [
        pytest.param(None, id="end"),
        pytest.param(RuntimeError("the job failed"), id="fail"),
        pytest.param(asyncio.CancelledError(), id="cancel"),
    ],
)
def test_bound_identity_wipe_zeroes_buffer_on_end_fail_cancel(
    ending: BaseException | None,
) -> None:
    slots, seen = _held_slots(Ticks()), list[BoundIdentity]()
    with contextlib.suppress(*(() if ending is None else (type(ending),))):
        with slots.held(JOB) as identity:
            seen.append(identity)
            assert not identity.wiped
            if ending is not None:
                raise ending
    assert seen[0].wiped
    with pytest.raises(IdentityRefused, match="not_held"), slots.held(JOB):
        pass


def test_bound_identity_wipe_zeroes_buffer_on_deadline() -> None:
    clock = Ticks()
    slots = _held_slots(clock)
    with slots.held(JOB) as identity:
        clock.now = 250.0
        assert slots.expire() == 1
        assert identity.wiped


def test_bound_identity_second_for_same_job_is_refused() -> None:
    slots = IdentitySlots(Ticks())
    slots.expect(JOB, DIGEST, deadline=200.0)
    slots.deliver(JOB, DIGEST, _material())
    second = _material()
    with pytest.raises(IdentityRefused, match="second_identity"):
        slots.deliver(JOB, DIGEST, second)
    assert not any(second)
    with pytest.raises(IdentityRefused, match="job_known"):
        slots.expect(JOB, DIGEST, deadline=300.0)


@pytest.mark.parametrize(
    ("job", "digest", "now", "reason"),
    [
        (OTHER_JOB, DIGEST, 100.0, "not_waiting"),
        (JOB, "0" * 64, 100.0, "not_bound"),
        (JOB, DIGEST, 200.0, "deadline"),
    ],
)
def test_an_identity_for_no_waiting_job_another_digest_or_late_is_refused_and_wiped(
    job: str, digest: str, now: float, reason: str
) -> None:
    clock = Ticks()
    slots = IdentitySlots(clock)
    slots.expect(JOB, DIGEST, deadline=200.0)
    clock.now = now
    material = _material()
    with pytest.raises(IdentityRefused, match=reason):
        slots.deliver(job, digest, material)
    assert not any(material)


def test_expire_drops_a_wait_past_its_deadline() -> None:
    clock = Ticks()
    slots = IdentitySlots(clock)
    slots.expect(JOB, DIGEST, deadline=150.0)
    clock.now = 160.0
    assert slots.expire() == 1
    with pytest.raises(IdentityRefused, match="not_waiting"):
        slots.deliver(JOB, DIGEST, _material())

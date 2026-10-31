"""C-13.6 #13 on a real filesystem (E16-Q04; BQ-5 as re-ruled on #5259): the nightly's leg.

`chaos-recorder-nightly.yml` mounts a 64 MiB ext4 loopback image and sets `CV_CHAOS_LOOPBACK=1`;
everywhere else the two real-filesystem tests skip (`_loopback.loopback_dir`). The guard tests
run in every lane: a non-loopback directory is refused (a failure, never a skip).
- The ladder over the image: 76 -> 81 -> 91 -> 96 % reach NORMAL, WARN, AUTOSTOP and HALT as the
  kernel reports free space, the pinned bytes never change, and at 96 % the open position keeps
  writing while the non-pinned auto symbol is gated, every row accounted for.
- The WAL on a full image: QuestDB down, the WAL's write is refused with a real `ENOSPC`
  (`writer._drain_spill_buf`'s `OSError` branch): the rows become `backpressure_drop` gaps, none is
  lost silently, and once space is back the writer recovers and writes again.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from candleviewer.recorder.models import DiskPressureLevel as L
from candleviewer.recorder.writer import GAP_CAUSE, STREAMS
from tests.chaos.recorder._ladder import AUTO, PINNED, LadderRig
from tests.chaos.recorder._loopback import (
    DEFAULT_DIR,
    DIR_ENV,
    ENABLE_ENV,
    LOOP_MAX_BYTES,
    LoopbackVolume,
    check_loopback,
    fill_completely,
    loopback_dir,
    mount_source,
    scratch,
)
from tests.chaos.recorder.test_questdb_down import Outage

pytestmark = pytest.mark.chaos
NIGHTLY = (
    Path(__file__).resolve().parents[5] / ".github" / "workflows" / "chaos-recorder-nightly.yml"
)
MNT = Path("/mnt/cv-chaos-recorder")
LOOP = f"36 25 7:3 / {MNT} rw,relatime shared:200 - ext4 /dev/loop3 rw\n"
DISK = f"36 25 8:1 / {MNT} rw,relatime shared:1 - ext4 /dev/sda1 rw,errors=remount-ro\n"
ROOT = "22 1 8:1 / / rw,relatime shared:1 - ext4 /dev/sda1 rw\n"


def test_loopback_guard_accepts_a_small_loop_mount() -> None:
    check_loopback(MNT, mountinfo=ROOT + LOOP, total_bytes=LOOP_MAX_BYTES)
    spaced = "37 25 7:4 / /mnt/a\\040b rw - ext4 /dev/loop4 rw\n"
    assert mount_source(Path("/mnt/a b"), spaced) == "/dev/loop4"


@pytest.mark.parametrize(
    ("mountinfo", "total", "why"),
    [
        (ROOT + DISK, 1 << 20, "not a loopback mount"),
        (ROOT, 1 << 20, "not a loopback mount"),  # a plain directory on the root disk
        (ROOT + LOOP, LOOP_MAX_BYTES + 1, "not the chaos loopback image"),
        (ROOT + LOOP + DISK, 1 << 20, "not a loopback mount"),  # a disk mounted over the image
    ],
)
def test_loopback_guard_refuses_anything_else(mountinfo: str, total: int, why: str) -> None:
    with pytest.raises(RuntimeError, match=why):
        check_loopback(MNT, mountinfo=mountinfo, total_bytes=total)


def test_nightly_runs_the_loopback_leg_on_a_mounted_image() -> None:
    """The gate: the nightly mounts the image before the suite, runs the suite with the leg on
    (so it never skips there), and unmounts on every exit path."""
    flow: dict[str, Any] = yaml.safe_load(NIGHTLY.read_text(encoding="utf-8"))
    steps: list[dict[str, Any]] = flow["jobs"]["chaos-recorder"]["steps"]
    names = [str(s.get("name", s.get("uses", ""))) for s in steps]
    mount = next(i for i, n in enumerate(names) if n.startswith("Loopback image"))
    suite = next(i for i, n in enumerate(names) if n.startswith("Recorder chaos suite"))
    umount = next(i for i, n in enumerate(names) if n.startswith("Unmount"))
    assert mount < suite < umount
    assert "sudo mount -o loop" in steps[mount]["run"] and str(DEFAULT_DIR) in steps[mount]["run"]
    assert steps[suite]["env"] == {ENABLE_ENV: "1", DIR_ENV: str(DEFAULT_DIR)}
    assert "tests/chaos/recorder" in steps[suite]["run"]
    assert steps[umount]["if"] == "always()" and str(DEFAULT_DIR) in steps[umount]["run"]


def test_loopback_leg_skips_unless_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENABLE_ENV, raising=False)
    with pytest.raises(pytest.skip.Exception, match=ENABLE_ENV):
        loopback_dir()


async def test_loopback_ladder_on_a_real_filesystem(tmp_path: Path) -> None:
    mount = loopback_dir()
    with scratch(mount) as root:
        rig = LadderRig(tmp_path, LoopbackVolume(root / "recording", mount=mount))
        await rig.start()
        try:
            for pct, level in ((76, L.NORMAL), (81, L.WARN), (91, L.AUTOSTOP), (96, L.HALT)):
                await rig.at(pct)
                assert rig.budget.level is level, f"{pct} % used: {rig.volume.free_pct():.1f} free"
                rig.assert_pins_intact()
            assert rig.retention.paused == [AUTO], "pinned symbols are never paused"
            await rig.feed(300)
            assert rig.written(AUTO) == 0 and rig.written(PINNED) > 0, "INV-B11-a"
            assert {g["cause"] for g in rig.store.gaps} == {GAP_CAUSE}
            produced = sum(rig.mix.produced_rows.values())
            assert produced == rig.written() + rig.dropped(), "INVARIANT: no silent loss"
        finally:
            await rig.stop()


async def test_wal_enospc_on_a_full_filesystem_becomes_gaps_then_recovers() -> None:
    mount = loopback_dir()
    with scratch(mount) as root:
        o = Outage(root)  # its WAL on the image
        try:
            await o.writer.open()
            o.writer.seed(["BTCUSDT", "ETHUSDT"])
            await o.step()  # healthy
            assert fill_completely(root / "fill.bin") > 0
            o.sink.down.add("*")  # QuestDB down: the writer spills, the image refuses
            for _ in range(5):
                await o.step()
            assert o.writer.spill_bytes == 0, "nothing reached the full image"
            (root / "fill.bin").unlink()  # space is back, and so is QuestDB
            o.sink.down.clear()
            await o.writer.recover()
            before = len(o.rows())
            await o.step()
            for stream in STREAMS:
                await o.writer.pump(stream)
            await o.writer.flush_gaps()
            await o.writer.flush_counters()
            assert len(o.rows()) > before, "the writer writes again after ENOSPC"
            assert o.dropped() > 0 and o.store.gaps, "ENOSPC drops into gaps"
            assert {g["cause"] for g in o.store.gaps} == {GAP_CAUSE}
            assert len(o.rows()) + o.dropped() == o.produced(), "INVARIANT: no silent loss"
        finally:
            await o.writer.stop()

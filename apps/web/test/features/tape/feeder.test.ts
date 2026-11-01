// E22-S01 (#714) BQ-215: the harness feeder: seeded, a 200-print snapshot, then one structured `d`
// per 100 ms window whose counts add up to the rate exactly.
import { describe, expect, it } from "vitest";
import { SNAPSHOT_PRINTS, createFeeder, seeded } from "../../../src/features/tape/harness/feeder";
import type { TopicFrame } from "../../../src/lib/ws/api";

const count = (frames: readonly TopicFrame[]): number =>
  frames.reduce((n, f) => {
    if (f.kind === "reset") return n;
    const body = f.kind === "snap" ? f.bodies[0] : f.body;
    const p = body.e === "j" ? (body.p as { trades: unknown[] }) : { trades: [] };
    return n + p.trades.length;
  }, 0);

describe("tape harness feeder", () => {
  it("is deterministic for a seed", () => {
    const a = seeded(577);
    const b = seeded(577);
    expect([a(), a(), a()]).toEqual([b(), b(), b()]);
    expect(seeded(1)()).not.toBe(seeded(2)());
  });

  it("sends the snapshot, then exactly `rate` prints a second in 100 ms windows", () => {
    let now = 0;
    const feeder = createFeeder({
      symbol: "BTCUSDT",
      rate: 2_000,
      seed: 577,
      now: () => now,
      startTsMs: 0,
    });
    const handle = feeder.client.consume({ ch: "trades.BTCUSDT", paneId: "p", priority: "other" });
    expect(handle.status).toBe("pending");
    const first = handle.read();
    expect(first[0]?.kind).toBe("snap");
    expect(count(first)).toBe(SNAPSHOT_PRINTS);
    expect(handle.status).toBe("live");
    let total = 0;
    for (let frame = 1; frame <= 50; frame += 1) {
      now = frame * 20;
      total += count(handle.read());
    }
    expect(total).toBe(2_000);
    expect(feeder.injected()).toBe(2_000 + SNAPSHOT_PRINTS);
    handle.release();
    expect(handle.status).toBe("pending");
    feeder.client.setPane("p", "visible");
  });
});

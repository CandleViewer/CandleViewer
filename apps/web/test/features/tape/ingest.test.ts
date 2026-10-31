// E22-S01 (#714) PR-A: ingest of `trades.{symbol}` frames (AC1, AC2, AC4; C-68, C-78, BQ-209).
import { describe, expect, it } from "vitest";
import type { TopicFrame } from "../../../src/lib/ws/api";
import { TapeIngest } from "../../../src/features/tape/model/ingest";
import {
  FLAG_BIG,
  FLAG_BLOCK,
  FLAG_LIQUIDATION,
  FLAG_SEAM,
  SIDE_BUY,
  SIDE_SELL,
  TapeRing,
} from "../../../src/features/tape/model/ring";
import { delta, item, items, reset, snap } from "./frames";

const setup = (capacity = 10_000) => {
  const ring = new TapeRing(capacity);
  return { ring, ingest: new TapeIngest(ring, "BTCUSDT") };
};

const heldIds = (ring: TapeRing): (string | undefined)[] => {
  const ids: (string | undefined)[] = [];
  for (let seq = ring.oldestSeq; seq < ring.nextSeq; seq += 1) ids.push(ring.id(seq));
  return ids;
};

describe("tape ingest", () => {
  it("appends a snapshot oldest first, then deltas, with the side from the feed (AC1)", () => {
    const { ring, ingest } = setup();
    const appended = ingest.apply([
      snap([item(1, { side: "sell" }), item(2, { side: "buy" })]),
      delta([item(3, { side: "sell" })]),
    ]);
    expect(appended).toBe(3);
    expect(heldIds(ring)).toEqual(["t1", "t2", "t3"]);
    expect([0, 1, 2].map((seq) => ring.side[ring.slot(seq)])).toEqual([
      SIDE_SELL,
      SIDE_BUY,
      SIDE_SELL,
    ]);
    expect(ingest.lastPrintTsMs).toBe(item(3).ts_ms);
    expect(ingest.counters.frames).toBe(2);
  });

  it("reads the server's flags and cluster size, never recomputing the threshold (BQ-210)", () => {
    const { ring, ingest } = setup();
    ingest.apply([
      snap(
        [
          item(1, { is_big_trade: true, size: "0.001" }), // flagged although tiny: the server decides
          item(2, { is_block_trade: true, is_liquidation: true, cluster_size: 4 }),
          item(3, { size: "999" }), // huge but unflagged stays tier 0
        ],
        { big_trade_threshold: "1000000" },
      ),
    ]);
    expect(ring.flags[ring.slot(0)]).toBe(FLAG_BIG);
    expect(ring.flags[ring.slot(1)]).toBe(FLAG_BLOCK | FLAG_LIQUIDATION);
    expect(ring.clusterSize[ring.slot(1)]).toBe(4);
    expect(ring.flags[ring.slot(2)]).toBe(0);
    expect(ingest.threshold).toBe("1000000");
  });

  it("reseeds after a reconnect without duplicating rows and keeps last-good rows under a seam (AC4, C-78)", () => {
    const { ring, ingest } = setup();
    ingest.apply([snap(items(1, 5))]);
    ingest.apply([reset("reconnect"), snap(items(3, 8), {}, 9)]);
    expect(heldIds(ring)).toEqual(["t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8"]);
    expect(ingest.counters.duplicates).toBe(3);
    expect(ingest.seams).toBe(1);
    expect(ring.flags[ring.slot(5)]).toBe(FLAG_SEAM); // above t6, the first new print
    expect(ring.flags[ring.slot(4)]).toBe(0);
    expect([ingest.lastReset, ingest.counters.resets]).toEqual(["reconnect", 1]);
  });

  it("puts no seam on a reset that comes before any row, and one seam for several resets", () => {
    const { ring, ingest } = setup();
    ingest.apply([reset("gap"), snap(items(1, 2))]);
    expect(ingest.seams).toBe(0);
    ingest.apply([reset("gap"), reset("resnapshot"), delta([item(3)])]);
    expect(ingest.seams).toBe(1);
    expect(ring.flags[ring.slot(2)]).toBe(FLAG_SEAM);
  });

  it("accounts for the server's dropped and coalesced counts (BQ-209)", () => {
    const { ingest } = setup();
    ingest.apply([
      delta([item(1)], { dropped: 4, coalesced: true, coalesced_count: 3 }),
      delta([item(2)], { dropped: 1, coalesced: true }),
      delta([item(3)], { coalesced: false, coalesced_count: 9 }),
    ]);
    const c = ingest.counters;
    expect([c.serverDropped, c.coalescedFrames, c.coalescedCount]).toEqual([5, 2, 3]);
  });

  it("rejects a binary body, another symbol's batch and a payload that is not a batch", () => {
    const { ring, ingest } = setup();
    const binary: TopicFrame = {
      kind: "d",
      seq: 1,
      ts: 0,
      sp: undefined,
      decodeMs: 0,
      size: 0,
      meta: undefined,
      body: { e: "b64", bytes: new ArrayBuffer(8) },
    };
    ingest.apply([binary, delta([item(1)], { symbol: "ETHUSDT" }), delta(null as never)]);
    expect([ring.length, ingest.counters.rejectedBodies]).toEqual([0, 3]);
  });

  it("skips and counts an item that fails the §14.2 shape", () => {
    const { ring, ingest } = setup();
    ingest.apply([
      delta([
        null,
        { ...item(1), side: "long" },
        { ...item(2), price: "abc" },
        { ...item(3), ts_ms: Number.NaN },
        { ...item(4), id: "" },
        { ...item(5), size: 7 },
        item(6),
      ]),
    ]);
    expect([ring.length, ingest.counters.malformed]).toEqual([1, 6]);
  });

  it("appends an item without an id with no dedupe", () => {
    const { ring, ingest } = setup();
    const noId = item(1);
    delete noId.id;
    ingest.apply([delta([noId, noId])]);
    expect([ring.length, ingest.counters.duplicates]).toEqual([2, 0]);
  });

  it("counts a print a full ring refused because its oldest row is pinned (S22)", () => {
    const { ring, ingest } = setup(2);
    ingest.apply([snap(items(1, 2))]);
    ring.pin(0);
    ingest.apply([delta([item(3)])]);
    expect([ingest.counters.notKept, ring.notKept, ring.length]).toEqual([1, 1, 2]);
  });

  it("never loses a print silently: appended + duplicates + not kept + malformed = received", () => {
    let state = 0x5eed;
    const rand = (n: number): number => {
      state = (state * 1_103_515_245 + 12_345) % 2 ** 31; // seeded LCG: deterministic
      return state % n;
    };
    const { ring, ingest } = setup(64);
    for (let round = 0; round < 400; round += 1) {
      const from = rand(500);
      const batchItems: unknown[] = items(from, from + rand(40));
      if (rand(10) === 0) batchItems.push({ bad: true });
      const r = rand(20);
      if (r === 0) ingest.apply([reset("gap")]);
      else if (r === 1) ring.pin(ring.oldestSeq);
      else if (r === 2) ring.unpin(ring.oldestSeq);
      ingest.apply([rand(4) === 0 ? snap(batchItems) : delta(batchItems)]);
    }
    const c = ingest.counters;
    expect(c.received).toBeGreaterThan(0);
    expect(c.appended + c.duplicates + c.notKept + c.malformed).toBe(c.received);
    expect(ring.length).toBeLessThanOrEqual(64);
    expect(new Set(heldIds(ring)).size).toBe(ring.length); // no duplicated row
  });
});

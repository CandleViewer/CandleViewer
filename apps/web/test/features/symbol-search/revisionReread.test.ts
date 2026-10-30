/**
 * E08-S09 (#4703, E08-D05 §3): an `instrument_revision` snapshot (23 §7.4) re-reads the instrument list, once per
 * burst, while the index runs, and once more when the list that landed was fetched before the burst. Fake timers: a
 * burst is a run of frames each inside the quiet of the one before.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { apiFetch } = vi.hoisted(() => ({
  apiFetch: vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(),
}));
vi.mock("../../../src/lib/http/csrfFetch", () => ({ apiFetch }));

import {
  createInstrumentIndex,
  type IndexSnapshot,
  type InstrumentIndex,
} from "../../../src/features/symbol-search/instrumentIndex";
import { toEntry, type Instrument } from "../../../src/features/symbol-search/ranking";
import {
  REVISION_QUIET_MS,
  createRevisionReread,
  type RevisionReread,
} from "../../../src/features/symbol-search/revisionReread";

const HOUR = 3_600_000;
const QUIET_S = REVISION_QUIET_MS / 1000;
const entry = (symbol: string, status: NonNullable<Instrument["status"]> = "Trading") =>
  toEntry({ symbol, category: "linear", status, tick_size: "0.1", qty_step: "1" });
/** Holds BTCUSDT and ETHUSDT (Trading), LUNAUSDT (a looked-up Closed one) and GONEUSDT (a cached 404). */
const READY: IndexSnapshot = {
  phase: "ready",
  entries: [entry("BTCUSDT"), entry("ETHUSDT")],
  known: [entry("LUNAUSDT", "Closed")],
  unlisted: ["GONEUSDT"],
  loadedAt: 0,
  cacheAgeS: null,
  staleSince: null,
  refreshing: false,
  retryAt: null,
  failure: null,
};

/**
 * A running fake index. `land` is a read's answer arriving: the list in memory moves on and the index tells its
 * subscribers. `stopIndex` stops it (what `useRunningIndex` then reads: nothing).
 */
function rig() {
  let snap = READY;
  const told = new Set<() => void>();
  const reread = vi.fn();
  const index: InstrumentIndex = {
    subscribe: (fn) => (told.add(fn), () => void told.delete(fn)),
    getSnapshot: () => snap,
    start: vi.fn(),
    stop: vi.fn(),
    reread,
    learn: vi.fn(),
  };
  let running: InstrumentIndex | null = index;
  const seam = createRevisionReread(() => running);
  return {
    seam,
    reread,
    subscribers: (): number => told.size,
    stopIndex: (): void => {
      running = null;
    },
    land: (patch: Partial<IndexSnapshot>): void => {
      snap = { ...snap, ...patch };
      for (const fn of [...told]) fn();
    },
  };
}
/** The answer of a read made now, of a snapshot the server fetched `agoS` seconds ago (`meta.cache_age_s`). */
const answer = (
  agoS: number | null,
  over: Partial<IndexSnapshot> = {},
): Partial<IndexSnapshot> => ({
  loadedAt: Date.now(),
  cacheAgeS: agoS,
  staleSince: null,
  ...over,
});
/** The snapshot of the burst's own refresh: fetched just before its first frame, so a quiet and a little older when read. */
const FRESH_S = QUIET_S + 0.5;
/** The snapshot the server served before it swapped: fetched hours earlier. */
const OLD_S = 7_200;
/** One frame, and the quiet that ends its burst: the read is made, and its answer is awaited. */
const readOnce = (seam: RevisionReread): void => {
  seam.note("book.BTCUSDT.50");
  vi.advanceTimersByTime(REVISION_QUIET_MS);
};

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(Date.UTC(2026, 9, 30, 12));
});
afterEach(() => {
  vi.useRealTimers();
  apiFetch.mockReset();
});

describe("the burst", () => {
  it("reads once for however many frames came", () => {
    const { seam, reread } = rig();
    for (const channel of ["book.BTCUSDT.50", "bars.BTCUSDT.time.1", "trades.BTCUSDT"]) {
      seam.note(channel);
    }
    vi.advanceTimersByTime(10 * REVISION_QUIET_MS);
    expect(reread).toHaveBeenCalledTimes(1);
  });

  it("reads one quiet after the last frame, not the first: a frame inside the quiet moves the read back", () => {
    const { seam, reread } = rig();
    seam.note("book.BTCUSDT.50");
    vi.advanceTimersByTime(REVISION_QUIET_MS - 1_000);
    seam.note("bars.BTCUSDT.time.1"); // a window from the first frame would end 1 s from here
    vi.advanceTimersByTime(REVISION_QUIET_MS - 1);
    expect(reread).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(reread).toHaveBeenCalledTimes(1);
  });

  it("leaves no timer once it has read", () => {
    const { seam } = rig();
    readOnce(seam);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("reads again for a frame after the quiet: a new burst", () => {
    const { seam, reread } = rig();
    readOnce(seam);
    expect(reread).toHaveBeenCalledTimes(1);
    seam.note("book.ETHUSDT.50");
    vi.advanceTimersByTime(REVISION_QUIET_MS - 1);
    expect(reread).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(1);
    expect(reread).toHaveBeenCalledTimes(2);
  });
});

describe("the server's order (instruments_refresh.py:709 to :725)", () => {
  it("waits out the swap lag: nothing is read inside the 15 s risk-limit budget (:107) and the upsert's margin", () => {
    const { seam, reread } = rig();
    seam.note("book.BTCUSDT.50"); // the revisions go out first; the snapshot GET /instruments serves swaps later
    vi.advanceTimersByTime(15_000 + 4_999); // the risk-limit fetches and 5 s for the upsert, less a millisecond
    expect(reread).not.toHaveBeenCalled();
  });
});

describe("a list that landed before the burst", () => {
  it("schedules one more read, a quiet later, when the answer was fetched before the burst: the swap had not happened", () => {
    const { seam, reread, land } = rig();
    readOnce(seam);
    land(answer(OLD_S));
    vi.advanceTimersByTime(REVISION_QUIET_MS - 1);
    expect(reread).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(1);
    expect(reread).toHaveBeenCalledTimes(2);
  });

  it("schedules none when the answer was fetched with the burst: the list is the burst's own", () => {
    const { seam, reread, land } = rig();
    readOnce(seam);
    land(answer(FRESH_S));
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(10 * REVISION_QUIET_MS);
    expect(reread).toHaveBeenCalledTimes(1);
  });

  it("does not judge the one more read: its answer, old again, schedules nothing, never a loop", () => {
    const { seam, reread, land } = rig();
    readOnce(seam);
    land(answer(OLD_S));
    vi.advanceTimersByTime(REVISION_QUIET_MS);
    land(answer(OLD_S));
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(10 * REVISION_QUIET_MS);
    expect(reread).toHaveBeenCalledTimes(2);
  });

  it("judges the list against the burst's first frame, not its last: a long burst's own list is not old", () => {
    const { seam, reread, land } = rig();
    const gap = REVISION_QUIET_MS - 1_000;
    seam.note("book.BTCUSDT.50"); // the first frame; the refresh fetched its list just before it
    vi.advanceTimersByTime(gap);
    seam.note("bars.BTCUSDT.time.1"); // frames kept coming, each inside the quiet of the one before
    vi.advanceTimersByTime(gap);
    seam.note("trades.BTCUSDT");
    vi.advanceTimersByTime(REVISION_QUIET_MS);
    expect(reread).toHaveBeenCalledTimes(1);
    land(answer((2 * gap + REVISION_QUIET_MS + 500) / 1000)); // fetched half a second before the first frame
    expect(vi.getTimerCount()).toBe(0);
  });

  it("schedules the one more read for an answer the server marks stale", () => {
    const { seam, reread, land } = rig();
    readOnce(seam);
    land(answer(FRESH_S, { staleSince: "2026-10-30T11:59:00Z" }));
    vi.advanceTimersByTime(REVISION_QUIET_MS);
    expect(reread).toHaveBeenCalledTimes(2);
  });

  it("schedules the one more read for an answer that does not say its age: freshness is not shown", () => {
    const { seam, reread, land } = rig();
    readOnce(seam);
    land(answer(null));
    vi.advanceTimersByTime(REVISION_QUIET_MS);
    expect(reread).toHaveBeenCalledTimes(2);
  });

  it("ignores a change of the list that is no answer: the read's own has not landed", () => {
    const { seam, reread, land } = rig();
    readOnce(seam);
    land({ refreshing: true }); // the index says it is slow; no list landed
    vi.advanceTimersByTime(10 * REVISION_QUIET_MS);
    expect(reread).toHaveBeenCalledTimes(1);
    land(answer(OLD_S)); // and the answer that does land is still judged
    vi.advanceTimersByTime(REVISION_QUIET_MS);
    expect(reread).toHaveBeenCalledTimes(2);
  });

  it("starts the next burst for a frame that comes while the answer is awaited: that answer is not judged", () => {
    const { seam, reread, land } = rig();
    readOnce(seam);
    vi.advanceTimersByTime(5_000);
    seam.note("book.BTCUSDT.50");
    land(answer(OLD_S)); // the earlier read's answer, late: the new burst's read comes instead
    vi.advanceTimersByTime(REVISION_QUIET_MS - 1);
    expect(reread).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(1);
    expect(reread).toHaveBeenCalledTimes(2);
  });

  it("replaces the one more read with the next burst's own, which reads once", () => {
    const { seam, reread, land } = rig();
    readOnce(seam);
    land(answer(OLD_S)); // the one more read waits, a quiet from now
    vi.advanceTimersByTime(10_000);
    seam.note("book.ETHUSDT.50");
    vi.advanceTimersByTime(REVISION_QUIET_MS - 1);
    expect(reread).toHaveBeenCalledTimes(1);
    vi.advanceTimersByTime(1);
    expect(reread).toHaveBeenCalledTimes(2);
    vi.advanceTimersByTime(10 * REVISION_QUIET_MS);
    expect(reread).toHaveBeenCalledTimes(2);
  });

  it("judges the next burst's read as any other, after it replaced the one more read", () => {
    const { seam, reread, land } = rig();
    readOnce(seam);
    land(answer(OLD_S)); // the one more read waits
    seam.note("book.ETHUSDT.50"); // the next burst takes its place
    vi.advanceTimersByTime(REVISION_QUIET_MS);
    land(answer(OLD_S)); // and its read is judged: the swap still has not happened
    vi.advanceTimersByTime(REVISION_QUIET_MS);
    expect(reread).toHaveBeenCalledTimes(3);
  });

  it("is not told by an index that stopped before its answer landed", () => {
    const { seam, reread, land, stopIndex } = rig();
    readOnce(seam);
    stopIndex();
    land(answer(OLD_S));
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(10 * REVISION_QUIET_MS);
    expect(reread).toHaveBeenCalledTimes(1);
  });
});

describe("while the index is not running", () => {
  it("a frame arms nothing: no timer, no read", () => {
    const { seam, reread, stopIndex } = rig();
    stopIndex();
    seam.note("book.BTCUSDT.50");
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(10 * REVISION_QUIET_MS);
    expect(reread).not.toHaveBeenCalled();
  });

  it("a read that waits is not made when the index stops inside the quiet", () => {
    const { seam, reread, stopIndex } = rig();
    seam.note("book.BTCUSDT.50");
    vi.advanceTimersByTime(REVISION_QUIET_MS - 1);
    stopIndex();
    vi.advanceTimersByTime(1);
    expect(reread).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("the symbol a frame names", () => {
  it.each([
    ["a Trading symbol", "book.BTCUSDT.50"],
    ["a looked-up symbol that does not trade", "ticker.LUNAUSDT"],
    ["a symbol cached as unlisted", "trades.GONEUSDT"],
    ["a bar series", "bars.ETHUSDT.time.1"],
  ])("reads for %s the index holds", (_what, channel) => {
    const { seam, reread } = rig();
    seam.note(channel);
    vi.advanceTimersByTime(REVISION_QUIET_MS);
    expect(reread).toHaveBeenCalledTimes(1);
  });

  it("reads for a topic that names none: a batched ticker's symbols are in its options (23 §6.1)", () => {
    const { seam, reread } = rig();
    seam.note("ticker");
    vi.advanceTimersByTime(REVISION_QUIET_MS);
    expect(reread).toHaveBeenCalledTimes(1);
  });

  it("starts no read for a symbol the index does not hold", () => {
    const { seam, reread } = rig();
    seam.note("book.DOGEUSDT.50");
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(10 * REVISION_QUIET_MS);
    expect(reread).not.toHaveBeenCalled();
  });

  it("does not move back a read that waits, for a symbol the index does not hold", () => {
    const { seam, reread } = rig();
    seam.note("book.BTCUSDT.50");
    vi.advanceTimersByTime(REVISION_QUIET_MS - 100);
    seam.note("book.DOGEUSDT.50"); // not the burst's: the read stays where the held symbol put it
    vi.advanceTimersByTime(100);
    expect(reread).toHaveBeenCalledTimes(1);
  });
});

describe("stop()", () => {
  it("drops the read that waits and leaves no timer", () => {
    const { seam, reread } = rig();
    seam.note("book.BTCUSDT.50");
    expect(vi.getTimerCount()).toBe(1);
    seam.stop();
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(10 * REVISION_QUIET_MS);
    expect(reread).not.toHaveBeenCalled();
  });

  it("stops listening to the index while its answer is awaited, and judges no answer after", () => {
    const { seam, reread, land, subscribers } = rig();
    readOnce(seam);
    expect(subscribers()).toBe(1);
    seam.stop();
    expect(subscribers()).toBe(0);
    land(answer(OLD_S));
    vi.advanceTimersByTime(10 * REVISION_QUIET_MS);
    expect(reread).toHaveBeenCalledTimes(1);
  });

  it("drops the one more read that waits", () => {
    const { seam, reread, land } = rig();
    readOnce(seam);
    land(answer(OLD_S));
    expect(vi.getTimerCount()).toBe(1);
    seam.stop();
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(10 * REVISION_QUIET_MS);
    expect(reread).toHaveBeenCalledTimes(1);
  });

  it("with nothing waiting is not an error", () => {
    const { seam } = rig();
    expect(() => {
      seam.stop();
      seam.stop();
    }).not.toThrow();
  });
});

describe("with the real index", () => {
  const instrument = (symbol: string) => ({
    symbol,
    category: "linear",
    status: "Trading",
    tick_size: "0.1",
    qty_step: "1",
  });
  /** `GET /instruments` of a catalogue the server fetched `agoS` seconds ago. */
  const listed = (agoS: number): Response =>
    new Response(
      JSON.stringify({
        items: ["BTCUSDT", "ETHUSDT"].map(instrument),
        meta: {
          next_cursor: null,
          has_more: false,
          count: 2,
          cache_age_s: agoS,
          stale_since: null,
        },
      }),
      { status: 200 },
    );
  const flush = (ms = 0) => vi.advanceTimersByTimeAsync(ms);

  it("a revision read replaces the hourly timer, and does not add a second: the next read is an hour from it", async () => {
    apiFetch
      .mockImplementationOnce(async () => listed(0))
      .mockImplementation(async () => listed(FRESH_S));
    const index = createInstrumentIndex();
    index.start();
    await flush();
    expect(vi.getTimerCount()).toBe(1); // the hourly read, an hour from the first
    const seam = createRevisionReread(() => index);
    seam.note("book.BTCUSDT.50");
    await flush(REVISION_QUIET_MS);
    expect(apiFetch).toHaveBeenCalledTimes(2); // the revision read, and its own list is the burst's
    expect(vi.getTimerCount()).toBe(1); // the hourly timer, replaced
    await flush(HOUR - REVISION_QUIET_MS); // where the first hourly read would have been
    expect(apiFetch).toHaveBeenCalledTimes(2);
    await flush(REVISION_QUIET_MS); // an hour from the revision read
    expect(apiFetch).toHaveBeenCalledTimes(3);
    index.stop();
  });

  it("re-reads once more for an old answer, and once only: the one more is not judged", async () => {
    apiFetch
      .mockImplementationOnce(async () => listed(0))
      .mockImplementation(async () => listed(OLD_S));
    const index = createInstrumentIndex();
    index.start();
    await flush();
    const seam = createRevisionReread(() => index);
    seam.note("book.BTCUSDT.50");
    await flush(REVISION_QUIET_MS); // the revision read: the server has not swapped yet
    expect(apiFetch).toHaveBeenCalledTimes(2);
    await flush(REVISION_QUIET_MS); // the one more
    expect(apiFetch).toHaveBeenCalledTimes(3);
    await flush(10 * REVISION_QUIET_MS); // its answer is old too, and nothing follows
    expect(apiFetch).toHaveBeenCalledTimes(3);
    index.stop();
    seam.stop();
  });
});

// E17-T04 S3 (23 8.5, C7): the outbound pacer keeps the client far enough under the gateway's 30
// frames/s and 300/min that jitter cannot push it over. Frames queued in one task leave at its end
// and 40 ms apart, so every check awaits the clock first.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  chunkTopics,
  createOutboundPacer,
  type OutboundPacer,
} from "../../../src/lib/ws/policy/outboundPacer";
import * as F from "../../../src/lib/ws/protocol/frames";
import { validateClientFrame } from "./support/schemaHarness";

const BOOK = "book.BTCUSDT.50";
let sent: F.ClientFrame[];
let times: number[]; // the clock at each send, from the start of the test
let nextId: () => string;
let pacer: ReturnType<typeof createOutboundPacer>;

beforeEach(() => {
  vi.useFakeTimers();
  const start = performance.now();
  sent = [];
  times = [];
  nextId = F.createIdSource();
  pacer = createOutboundPacer({
    send: (frame) => {
      sent.push(frame);
      times.push(performance.now() - start);
    },
  });
});
afterEach(() => vi.useRealTimers());

/** Moves the fake clock, running the pacer's end-of-task flush and its wake-up timers on the way. */
const advance = (ms = 0) => vi.advanceTimersByTimeAsync(ms);
const queue = (n: number, make: (id: string) => F.ClientFrame) => {
  for (let i = 0; i < n; i += 1) pacer.enqueue(make(nextId()));
};
const resyncs = (n: number) => queue(n, (id) => F.resync(id, BOOK, { reason: "manual" }));
const pongs = (n: number) => queue(n, (id) => F.pong(id, 0));
const ping = () => pacer.enqueue(F.ping(nextId(), 0));
/** Timers as strict as a worker's: `clearTimeout` takes only a handle `setTimeout` returned, and `queueMicrotask` defers until `flush()`. */
const strictTimers = (now: () => number) => {
  const microtasks: (() => void)[] = [];
  return {
    now,
    setTimeout: vi.fn(() => 7),
    clearTimeout: vi.fn((handle: unknown) => {
      if (handle === undefined) throw new Error("clearTimeout(undefined)");
    }),
    queueMicrotask: (callback: () => void) => void microtasks.push(callback),
    flush: () => {
      for (const callback of microtasks.splice(0)) callback();
    },
  };
};
/** What a careless caller could pass: JSON drops `undefined` and turns `NaN` into `null`. */
const junk = (p: object) => F.ctl(nextId(), BOOK, p as F.CtlPayload);

describe("spacing and windows", () => {
  it("sends 40 ms apart and defers the 28th frame in 1 250 ms until the first is that old, in order", async () => {
    resyncs(28);
    expect(sent).toEqual([]); // queued in this task, sent at its end
    await advance(1249);
    expect(times).toEqual(Array.from({ length: 27 }, (_, i) => i * 40));
    expect(pacer.size).toBe(1);
    await advance(1);
    expect(times[27]).toBe(1250);
    expect(sent.map((f) => f.id)).toEqual(Array.from({ length: 28 }, (_, i) => `c-${i + 1}`));
  });

  it("defers the 264th frame in 65 s until the first is that old (270 less the ping reserve)", async () => {
    resyncs(264);
    await advance(64_999);
    expect(sent).toHaveLength(263);
    await advance(1);
    expect(times[263]).toBe(65_000);
  });

  it("keeps slots for the client ping: it goes first, and a full long window never starves it", async () => {
    resyncs(264);
    await advance(13_000); // 263 sent, the 264th waits for the window
    expect(ping()).toBe(true);
    await advance(40);
    expect(sent.at(-1)).toMatchObject({ t: "ping" });
    expect([sent.length, pacer.size]).toEqual([264, 1]);
  });

  it("never lets the gateway see 30 frames in its second or 300 in its minute, whatever the jitter", async () => {
    resyncs(700);
    await advance(150_000);
    expect(sent).toHaveLength(700);
    // the gateway's limiter (lifecycle.py InboundRateLimiter), fed the arrival times, which cannot overtake
    const denied = (arrivals: number[]): number => {
      const stamps: number[] = [];
      return arrivals.filter((now) => {
        while (stamps.length > 0 && now - (stamps[0] ?? 0) >= 60_000) stamps.shift();
        const full = stamps.filter((t) => now - t < 1000).length >= 30 || stamps.length >= 300;
        if (!full) stamps.push(now);
        return full;
      }).length;
    };
    const seeded = (seed: number) => () =>
      (seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0) / 2 ** 32;
    const jittered = (amp: number, seed: number) => {
      const random = seeded(seed);
      let last = -Infinity;
      return times.map((t) => (last = Math.max(last, t + (random() * 2 - 1) * amp)));
    };
    for (const amp of [20, 100]) {
      for (let seed = 1; seed <= 20; seed += 1) expect(denied(jittered(amp, seed))).toBe(0);
    }
    expect(denied(times.map((t, i) => (i < 27 ? t + 5 : t)))).toBe(0); // the first burst 5 ms late
    // control: 27 at once and 27 more 1 000 ms later, the first 2 ms late, is what 27/s used to allow
    expect(denied([...Array<number>(27).fill(2), ...Array<number>(27).fill(1000)])).toBeGreaterThan(
      0,
    );
  });

  it("reset() starts a connection from nothing: the queue, the windows and the exemption", async () => {
    pacer.markAuthenticated();
    resyncs(30);
    await advance(1045); // 27 sent by 1 040, 3 waiting
    pacer.reset(); // the old stamps would still fill the short window
    expect(pacer.size).toBe(0);
    pongs(28); // counted again, with the whole budget
    await advance(1040);
    expect(sent).toHaveLength(27 + 27);
    expect(pacer.size).toBe(1);
    await advance(1000);
    expect(sent).toHaveLength(27 + 28); // the 3 frames that were waiting died with the old connection
  });
});

describe("send errors", () => {
  it("keeps a frame that send threw on, in order, and retries it 1 s later with the rest", async () => {
    const errors: unknown[] = [];
    let calls = 0;
    const flaky = createOutboundPacer({
      send: (frame) => {
        calls += 1;
        if (calls === 3) throw new Error("socket not ready");
        sent.push(frame);
      },
      onError: (error) => {
        errors.push(error);
        throw new Error("a faulty handler"); // must not stop the retry
      },
    });
    for (let i = 0; i < 5; i += 1) flaky.enqueue(F.resync(nextId(), BOOK, { reason: "manual" }));
    await advance(80); // the third attempt, at 80 ms, threw
    expect(sent.map((f) => f.id)).toEqual(["c-1", "c-2"]);
    expect([errors.length, flaky.size]).toEqual([1, 3]);
    await advance(999); // nothing leaves before the retry timer
    expect(sent).toHaveLength(2);
    await advance(1); // 1 000 ms after the throw: the retry
    expect(sent.map((f) => f.id)).toEqual(["c-1", "c-2", "c-3"]);
    await advance(80); // then the two behind it, 40 ms apart
    expect(sent.map((f) => f.id)).toEqual(["c-1", "c-2", "c-3", "c-4", "c-5"]);
    expect(flaky.size).toBe(0);
  });

  it("does not spend a window slot on a throw, and any enqueue retries at once (1 s is an upper bound)", async () => {
    let attempts = 0;
    const flaky = createOutboundPacer({
      send: (frame) => {
        attempts += 1;
        if (attempts === 27) throw new Error("socket not ready"); // at 1 040 ms, with 26 frames in the window
        sent.push(frame);
      },
    });
    for (let i = 0; i < 27; i += 1) flaky.enqueue(F.resync(nextId(), BOOK, { reason: "manual" }));
    await advance(1040);
    expect([sent.length, flaky.size]).toEqual([26, 1]);
    flaky.enqueue(F.resync(nextId(), BOOK, { reason: "manual" }));
    await advance(); // the thrown frame goes first, at once: a counted throw would make it wait
    expect(sent).toHaveLength(27);
  });

  it("is not undone when onError resets the pacer, and leaves no stale stamp when send does", async () => {
    const later: string[] = [];
    let calls = 0;
    const own: OutboundPacer = createOutboundPacer({
      send: (frame) => {
        calls += 1;
        if (calls === 1) throw new Error("socket closed");
        later.push(frame.id);
        if (calls === 2) {
          own.reset(); // send closes the connection and starts the next one
          own.enqueue(F.resync("c-z", BOOK, { reason: "manual" }));
        }
      },
      onError: () => own.reset(), // the handler closes the connection
    });
    own.enqueue(F.resync("c-1", BOOK, { reason: "manual" }));
    own.enqueue(F.resync("c-2", BOOK, { reason: "manual" }));
    await advance(2000);
    expect([later, own.size, vi.getTimerCount()]).toEqual([[], 0, 0]); // neither came back, no retry waits
    own.enqueue(F.resync("c-3", BOOK, { reason: "manual" }));
    await advance(); // c-3 and, in the same flush, c-z: the reset left no stamp to wait for
    expect(later).toEqual(["c-3", "c-z"]);
  });

  it("does not throw out of a pong whose send throws", () => {
    const flaky = createOutboundPacer({
      send: () => {
        throw new Error("socket not ready");
      },
    });
    flaky.markAuthenticated();
    expect(flaky.enqueue(F.pong("c-p", 0))).toBe(true);
  });
});

describe("pong accounting (8.5)", () => {
  it("counts a pong before auth_ok like any other frame", async () => {
    pongs(28);
    await advance(1249);
    expect([sent.length, pacer.size]).toEqual([27, 1]);
  });

  it("exempts a pong after auth_ok: sent at once, ahead of the queue, spending no budget", async () => {
    pacer.markAuthenticated();
    resyncs(30);
    pacer.enqueue(F.pong("c-pong", 0));
    expect(sent.map((f) => f.t)).toEqual(["pong"]); // not even waiting for the end of the task
    await advance(1249);
    expect(sent).toHaveLength(1 + 27);
    pongs(100);
    expect([sent.length, pacer.size]).toEqual([1 + 27 + 100, 3]);
    await advance(81); // the 28th to 30th resync leave at 1 250, 1 290 and 1 330: the pongs cost them nothing
    expect([sent.length, pacer.size]).toEqual([1 + 27 + 100 + 3, 0]);
  });
});

describe("ctl coalescing", () => {
  it("merges 40 ctl for one ch into one frame, the latest value of each option winning", async () => {
    pacer.enqueue(F.ctl(nextId(), BOOK, { throttle_ms: 50, coalesce: true }));
    queue(39, (id) => F.ctl(id, BOOK, { throttle_ms: 100 + Number(id.slice(2)) }));
    await advance(500);
    expect(sent).toHaveLength(1);
    expect(sent[0]).toMatchObject({ t: "ctl", ch: BOOK, p: { throttle_ms: 140, coalesce: true } });
    expect(sent.flatMap(validateClientFrame)).toEqual([]);
  });

  it("keeps an earlier value when a later ctl carries it as undefined or NaN", async () => {
    pacer.enqueue(F.ctl(nextId(), BOOK, { throttle_ms: 100, depth: 50 }));
    pacer.enqueue(junk({ throttle_ms: undefined, coalesce: true }));
    pacer.enqueue(junk({ depth: Number.NaN })); // nothing left of it: refused, the waiting ctl untouched
    await advance(500);
    expect(sent).toHaveLength(1);
    expect(sent[0]).toMatchObject({ p: { throttle_ms: 100, depth: 50, coalesce: true } });
  });

  it("merges past a ctl of another ch, but never across a sub, unsub or resync of its own", async () => {
    pacer.enqueue(F.ctl(nextId(), BOOK, { throttle_ms: 100 }));
    pacer.enqueue(F.ctl(nextId(), "trades.BTCUSDT", { throttle_ms: 100 }));
    pacer.enqueue(F.ctl(nextId(), BOOK, { depth: 200 }));
    await advance(500);
    expect(sent.map((f) => f.t === "ctl" && f.ch)).toEqual([BOOK, "trades.BTCUSDT"]);
    expect(sent[0]).toMatchObject({ p: { throttle_ms: 100, depth: 200 } });

    for (const between of [
      F.unsub(nextId(), [BOOK]),
      F.sub(nextId(), { topics: [{ ch: BOOK }] }),
      F.resync(nextId(), BOOK, { reason: "manual" }),
    ]) {
      sent.length = 0;
      pacer.enqueue(F.ctl(nextId(), BOOK, { throttle_ms: 100 }));
      pacer.enqueue(between);
      pacer.enqueue(F.ctl(nextId(), BOOK, { throttle_ms: 200 }));
      await advance(500);
      expect(sent.map((f) => f.t)).toEqual(["ctl", between.t, "ctl"]);
    }
  });

  it("never emits an empty ctl: the generated type admits {} but the schema needs a property (#572)", async () => {
    const empty = junk({}); // {} is a type error once CtlPayload needs a property, but a caller can still send it
    expect(validateClientFrame(empty).join()).toMatch(/fewer than 1 properties/);
    pacer.enqueue(F.ctl(nextId(), BOOK, { throttle_ms: 250 }));
    const refused = [empty, junk({ throttle_ms: undefined }), junk({ throttle_ms: Number.NaN })];
    expect(refused.map(pacer.enqueue)).toEqual([false, false, false]);
    await advance(5000);
    expect(sent).toHaveLength(1); // only the real one, untouched by the refused ones
    expect(JSON.parse(JSON.stringify(sent[0]))).toHaveProperty("p.throttle_ms", 250);
  });
});

describe("chunkTopics", () => {
  it("sends 120 topics as 3 valid sub frames of 50, 50 and 20", async () => {
    const topics = Array.from({ length: 120 }, (_, i) => ({ ch: `trades.SYM${i}` }));
    for (const chunk of chunkTopics(topics, 50)) pacer.enqueue(F.sub(nextId(), { topics: chunk }));
    await advance(500);
    const sizes = sent.map((f) => (f.t === "sub" ? f.p.topics.length : -1));
    expect(sizes).toEqual([50, 50, 20]);
    expect(sent.flatMap(validateClientFrame)).toEqual([]);
  });

  it("follows welcome.limits.max_topics_per_request, never above 50, and keeps the order", () => {
    const many = Array.from({ length: 120 }, (_, i) => i);
    expect(chunkTopics([1, 2, 3, 4, 5], 2)).toEqual([[1, 2], [3, 4], [5]]);
    expect(chunkTopics(many, 500).map((c) => c.length)).toEqual([50, 50, 20]);
    expect(chunkTopics([], 50)).toEqual([]);
    expect(chunkTopics([1, 2], Number.NaN)).toEqual([[1], [2]]); // an unusable limit: one topic per frame
  });
});

describe("injected timers", () => {
  it("run on the timers it is given, never the platform's", () => {
    let clock = 0;
    const timers = strictTimers(() => clock);
    const injected = createOutboundPacer({ send: (f) => sent.push(f), timers });
    injected.enqueue(F.resync("c-a", BOOK, { reason: "manual" }));
    expect(sent).toEqual([]); // the injected microtask has not run, so nothing has left
    timers.flush();
    injected.enqueue(F.resync("c-b", BOOK, { reason: "manual" })); // too soon after it: the 40 ms spacing
    timers.flush();
    expect(sent).toHaveLength(1);
    expect(timers.setTimeout).toHaveBeenCalledWith(expect.any(Function), 40);
    expect(vi.getTimerCount()).toBe(0); // nothing reached the platform's timers
    clock = 40; // the injected clock moves, and the waiting frame is let go by the next flush
    injected.enqueue(F.resync("c-c", BOOK, { reason: "manual" }));
    timers.flush();
    expect(sent.map((f) => f.id)).toEqual(["c-a", "c-b"]);
    timers.clearTimeout.mockClear(); // the flushes above clear it too: only reset() counts from here
    injected.reset();
    expect(timers.clearTimeout).toHaveBeenCalledWith(7);
  });

  it("counts stamps from the future as now when the clock steps back: a stall of one window, not of the step", () => {
    let clock = 10_000;
    const timers = strictTimers(() => clock);
    const stepped = createOutboundPacer({ send: (f) => sent.push(f), timers });
    for (let i = 0; i < 27; i += 1) {
      stepped.enqueue(F.resync(nextId(), BOOK, { reason: "manual" }));
      timers.flush();
      clock += 40;
    }
    expect(sent).toHaveLength(27);
    clock = 3000; // an injected, skew-corrected clock steps back 8 s
    stepped.enqueue(F.resync(nextId(), BOOK, { reason: "manual" }));
    timers.flush();
    expect(timers.setTimeout).toHaveBeenLastCalledWith(expect.any(Function), 1250);
  });
});

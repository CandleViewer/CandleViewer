// E17-T04 S5 (23 5.4, 8.5; SR-193): a `ctl` that would re-snapshot draws on the gateway's rebuild budget. A
// refusal changes nothing there, so the engine must not go on believing the bucket was applied, and must
// not ask again at once: it waits, twice as long after each refusal, and never retries in a loop.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { REFUSED_BACKOFF_MAX_MS, REFUSED_BACKOFF_MS } from "../../../src/lib/ws/core/flowControl";
import { CTL_DEBOUNCE_MS } from "../../../src/lib/ws/policy/ctlDebouncer";
import { engineHarness, spec } from "./support/engineHarness";
import type { Json } from "./support/fakeGateway";

beforeEach(() => {
  // `resync_rate_limited` has no 10.3 treatment yet (#3149): the error handler reads it as a client bug
  vi.spyOn(console, "error").mockImplementation(() => undefined);
});
afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
});

const HEATMAP = "heatmap.BTCUSDT";
const size = (cssWidth: number) =>
  ({ visibility: "visible", tabHidden: false, size: { cssWidth, dpr: 1 } }) as const;
/** The buckets the client asked for with a `ctl` (a throttle ctl asks for none). */
const bucketCtls = (t: ReturnType<typeof engineHarness>) =>
  t.gateway.latest
    .of("ctl")
    .map((f) => (f["p"] as Json)["time_bucket_ms"])
    .filter((bucket) => bucket !== undefined);

/** A heatmap whose pane is 1 190 px wide (1 000 ms) and is then made 601 px wide: 5 000 ms is wanted. */
async function narrowed() {
  const t = engineHarness();
  t.engine.setPane("p1", size(1190));
  const handle = t.engine.consume(spec(HEATMAP));
  await t.start();
  return { t, handle };
}

/** How long it takes, in steps of `STEP_MS`, for the number of bucket `ctl`s to reach `count`. */
const STEP_MS = 100;
async function until(t: ReturnType<typeof engineHarness>, count: number): Promise<number> {
  let waited = 0;
  while (bucketCtls(t).length < count && waited < 400_000) {
    await t.advance(STEP_MS);
    waited += STEP_MS;
  }
  return waited;
}

describe("a bucket ctl the rebuild budget refused (SR-193)", () => {
  it("is undone and asked for again after a back-off, not at once", async () => {
    const { t, handle } = await narrowed();
    t.gateway.refuseRebuilds(1);
    t.engine.setPane("p1", size(601));
    await t.advance(CTL_DEBOUNCE_MS); // the ctl leaves after its debounce and is refused
    expect(bucketCtls(t)).toEqual([5_000]);
    expect(handle.effective["time_bucket_ms"]).toBe(1_000); // C4: what the server runs, not what was asked
    await t.advance(REFUSED_BACKOFF_MS + CTL_DEBOUNCE_MS - 1);
    expect(bucketCtls(t)).toEqual([5_000]); // still waiting
    await t.advance(1);
    expect(bucketCtls(t)).toEqual([5_000, 5_000]); // asked for again, from the geometry of that moment
    expect(handle.effective["time_bucket_ms"]).toBe(5_000);
    expect(t.gateway.latest.of("ctl")).toHaveLength(2); // and nothing in between
  });

  it("drops the bucket it took for applied: a resize back to what the server holds sends nothing", async () => {
    const { t } = await narrowed();
    t.gateway.refuseRebuilds(1);
    t.engine.setPane("p1", size(601));
    await t.advance(CTL_DEBOUNCE_MS);
    t.engine.setPane("p1", size(1190)); // the 1 000 ms the server still runs
    await t.advance(REFUSED_BACKOFF_MS + 10_000);
    expect(bucketCtls(t)).toEqual([5_000]); // no ctl back to 1 000 ms: it was never left
  });

  it("derives the bucket from the geometry of the moment the wait ends, not the one that was refused", async () => {
    const { t, handle } = await narrowed();
    t.gateway.refuseRebuilds(1);
    t.engine.setPane("p1", size(601));
    await t.advance(CTL_DEBOUNCE_MS);
    t.engine.setPane("p1", size(12_000)); // 250 ms is wanted by now
    await t.advance(REFUSED_BACKOFF_MS + CTL_DEBOUNCE_MS);
    expect(bucketCtls(t)).toEqual([5_000, 250]);
    expect(handle.effective["time_bucket_ms"]).toBe(250);
  });

  it("waits twice as long after each refusal, up to the window the budget counts over, and starts again once a bucket was applied", async () => {
    const { t } = await narrowed();
    t.gateway.refuseRebuilds(5);
    t.engine.setPane("p1", size(601));
    expect(await until(t, 1)).toBe(CTL_DEBOUNCE_MS);
    const waits: number[] = [];
    for (let count = 2; count <= 6; count += 1) waits.push(await until(t, count));
    // 5 s, 10 s, 20 s, 40 s, then the 60 s cap (not 80 s); each plus the debounce, to the step of the clock
    const expected = [5_000, 10_000, 20_000, 40_000, REFUSED_BACKOFF_MAX_MS];
    waits.forEach((waited, i) => {
      const exact = (expected[i] ?? 0) + CTL_DEBOUNCE_MS;
      expect(waited).toBeGreaterThanOrEqual(exact);
      expect(waited).toBeLessThan(exact + STEP_MS);
    });
    // the sixth was accepted: the next refusal starts from the first wait again
    t.gateway.refuseRebuilds(1);
    t.engine.setPane("p1", size(1190));
    expect(await until(t, 7)).toBe(CTL_DEBOUNCE_MS);
    const again = await until(t, 8);
    expect(again).toBeGreaterThanOrEqual(REFUSED_BACKOFF_MS + CTL_DEBOUNCE_MS);
    expect(again).toBeLessThan(REFUSED_BACKOFF_MS + CTL_DEBOUNCE_MS + STEP_MS);
  });

  it("is forgotten with the stream: a heatmap let go during the wait is never asked for again", async () => {
    const { t } = await narrowed();
    t.gateway.refuseRebuilds(1);
    t.engine.setPane("p1", size(601));
    await t.advance(CTL_DEBOUNCE_MS);
    t.engine.setPane("p1", { visibility: "collapsed", tabHidden: false });
    await t.advance(REFUSED_BACKOFF_MAX_MS * 2);
    expect(bucketCtls(t)).toEqual([5_000]);
    expect(t.gateway.latest.of("unsub")).toHaveLength(1);
  });

  it("a refusal that arrives after the stream was let go starts no wait", async () => {
    const t = engineHarness({ hold: ["ctl_ok"] }); // the refusal of the ctl is held back with its ctl_ok
    t.engine.setPane("p1", size(1190));
    t.engine.consume(spec(HEATMAP));
    await t.start();
    t.gateway.refuseRebuilds(1);
    t.engine.setPane("p1", size(601));
    await t.advance(CTL_DEBOUNCE_MS); // the ctl is out, and the refusal is on its way
    t.engine.setPane("p1", { visibility: "collapsed", tabHidden: false });
    await t.advance(300); // the unsub goes out
    const timers = vi.getTimerCount();
    t.gateway.latest.releaseHeld(); // the refusal arrives
    expect(vi.getTimerCount()).toBe(timers);
    await t.advance(REFUSED_BACKOFF_MAX_MS * 2);
    expect(bucketCtls(t)).toEqual([5_000]);
  });

  it("is forgotten with the connection: the next one subscribes with the bucket the pane wants", async () => {
    const { t, handle } = await narrowed();
    t.gateway.refuseRebuilds(1);
    t.engine.setPane("p1", size(601));
    await t.advance(CTL_DEBOUNCE_MS);
    t.gateway.latest.close(1011);
    await t.advance(REFUSED_BACKOFF_MAX_MS * 2); // the wait of the lost connection is over, and sends nothing
    expect(t.gateway.latest.of("ctl")).toEqual([]);
    expect(t.gateway.latest.of("sub")[0]).toMatchObject({
      p: { topics: [{ ch: HEATMAP, opts: { time_bucket_ms: 5_000 } }] },
    });
    expect(handle.effective["time_bucket_ms"]).toBe(5_000);
  });
});

describe("a ctl refused while others are in flight, and a throttle ctl (SR-193)", () => {
  it("a resize that settles after the ctl left, before its refusal arrives, sends nothing inside the wait", async () => {
    const t = engineHarness({ hold: ["ctl_ok"] });
    t.engine.setPane("p1", size(1190));
    t.engine.consume(spec(HEATMAP));
    await t.start();
    t.gateway.refuseRebuilds(1);
    t.engine.setPane("p1", size(601)); // 5 000 ms wanted
    await t.advance(CTL_DEBOUNCE_MS); // the ctl leaves, its refusal is held
    t.engine.setPane("p1", size(12_000)); // 250 ms wanted: a debounce is running
    await t.advance(100);
    t.gateway.latest.releaseHeld(); // the refusal arrives inside the debounce
    await t.advance(CTL_DEBOUNCE_MS); // when the debounce would have fired
    expect(bucketCtls(t)).toEqual([5_000]);
    await t.advance(REFUSED_BACKOFF_MS + 100); // the wait is over: asked from the geometry of this moment
    expect(bucketCtls(t)).toEqual([5_000, 250]);
  });

  it("a second refusal while the first wait runs replaces it: nothing is asked until the longer wait is over", async () => {
    const t = engineHarness({ hold: ["ctl_ok"] });
    t.engine.setPane("p1", size(1190));
    t.engine.consume(spec(HEATMAP));
    await t.start();
    t.gateway.refuseRebuilds(2);
    t.engine.setPane("p1", size(601)); // 5 000 ms wanted
    await t.advance(CTL_DEBOUNCE_MS); // ctl A leaves, its refusal is held
    t.engine.setPane("p1", size(12_000)); // 250 ms wanted
    await t.advance(CTL_DEBOUNCE_MS); // ctl B leaves, its refusal is held
    expect(bucketCtls(t)).toEqual([5_000, 250]);
    t.gateway.latest.releaseHeld(); // both refused: a wait of 5 s, then one of 10 s
    await t.advance(REFUSED_BACKOFF_MS + CTL_DEBOUNCE_MS + 100); // the first wait is over, the second is not
    expect(bucketCtls(t)).toEqual([5_000, 250]);
    await t.advance(REFUSED_BACKOFF_MS + CTL_DEBOUNCE_MS); // the longer wait is over
    expect(bucketCtls(t)).toEqual([5_000, 250, 250]);
  });

  it("the back-off starts again from its first wait only when a bucket was applied, not on any other reply", async () => {
    const t = engineHarness({ hold: ["ctl_ok"] });
    t.engine.setPane("p1", size(12_000)); // 250 ms: a hidden tab changes its throttle (1 000 ms)
    t.engine.consume(spec(HEATMAP));
    await t.start();
    t.gateway.refuseRebuilds(2);
    t.engine.setPane("p1", size(601));
    await t.advance(CTL_DEBOUNCE_MS); // the bucket ctl leaves, its refusal is held
    t.engine.setPane("p1", {
      visibility: "visible",
      tabHidden: true,
      size: { cssWidth: 601, dpr: 1 },
    });
    await t.advance(50); // the throttle ctl leaves behind it, its reply held
    t.gateway.latest.releaseHeld(); // the refusal first (a wait of 5 s), then the throttle's ctl_ok: a reply that applied no bucket
    await t.advance(REFUSED_BACKOFF_MS + CTL_DEBOUNCE_MS + 100); // the first wait is over: the bucket is asked for again
    expect(bucketCtls(t)).toEqual([5_000, 5_000]);
    t.gateway.latest.releaseHeld(); // refused again: the second wait is twice the first
    await t.advance(REFUSED_BACKOFF_MS + CTL_DEBOUNCE_MS + 100);
    expect(bucketCtls(t)).toEqual([5_000, 5_000]); // not after one more first wait
    await t.advance(REFUSED_BACKOFF_MS);
    expect(bucketCtls(t)).toEqual([5_000, 5_000, 5_000]);
  });

  it("a throttle ctl refused the same way waits like a bucket ctl: not asked again at once", async () => {
    const t = engineHarness();
    const handle = t.engine.consume(spec("trades.BTCUSDT"));
    await t.start();
    t.gateway.refuseCtls(1);
    t.engine.setPane("p1", { visibility: "offscreen", tabHidden: false });
    await t.advance(300);
    const throttles = () => t.gateway.latest.of("ctl").length;
    expect(throttles()).toBe(1);
    expect(handle.effective["throttle_ms"]).toBe(100); // refused: what the server runs
    t.engine.setPane("p1", { visibility: "offscreen", tabHidden: false }); // a new pass, inside the wait
    await t.advance(REFUSED_BACKOFF_MS - 301);
    expect(throttles()).toBe(1); // still waiting
    await t.advance(400);
    expect(throttles()).toBe(2); // asked again, and applied
    expect(handle.effective["throttle_ms"]).toBe(1_000);
  });
});

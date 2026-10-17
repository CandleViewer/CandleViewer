// E17-T04 S3 (23 8.5, C8): what the throttle policy wants of each visual topic, from who is looking at it.
import { describe, expect, it } from "vitest";
import {
  desiredThrottles,
  isVisualTopic,
  type ThrottleConsumer,
} from "../../../src/lib/ws/policy/throttlePolicy";

const MIN = 50; // welcome.limits.min_throttle_ms
const BOOK = "book.BTCUSDT.50";
/** One topic of each visual family (6.1) at its default throttle: the reference workspace and the rest. */
const DEFAULTS: readonly (readonly [string, number])[] = [
  [BOOK, 50],
  ["trades.BTCUSDT", 100],
  ["bars.BTCUSDT.time.1", 250],
  ["footprint.BTCUSDT.time.5", 250],
  ["heatmap.BTCUSDT", 500],
  ["profile.BTCUSDT.volume", 1000],
  ["metrics.BTCUSDT", 250],
  ["ticker.BTCUSDT", 250],
  ["liquidations.BTCUSDT", 500],
];
const PRIVATE = ["orders", "positions", "executions", "wallet", "trade_groups", "rules"];
const NOT_VISUAL = [...PRIVATE, "alerts", "recorder", "machines.order.state", "system"];

const consumer = (ch: string, over: Partial<ThrottleConsumer> = {}): ThrottleConsumer => ({
  ch,
  visibility: "visible",
  tabHidden: false,
  requestedMs: 50,
  ...over,
});
const workspace = (over: Partial<ThrottleConsumer> = {}): ThrottleConsumer[] => {
  return DEFAULTS.map(([ch, requestedMs]) => consumer(ch, { requestedMs, ...over }));
};
const throttle = (throttleMs: number) => ({ kind: "throttle", throttleMs });

describe("throttle policy (C8)", () => {
  it("four panes hidden: every visual topic is at least 1 000 ms and none is released", () => {
    const desired = desiredThrottles(workspace({ tabHidden: true }), MIN);
    expect([...desired.keys()]).toEqual(DEFAULTS.map(([ch]) => ch));
    expect([...desired.values()]).toEqual(DEFAULTS.map(() => throttle(1000)));
    // hidden never speeds a slow topic up: a pane that asked for 2 000 ms keeps it
    const slow = consumer("ticker.BTCUSDT", { tabHidden: true, requestedMs: 2000 });
    expect(desiredThrottles([slow], MIN).get("ticker.BTCUSDT")).toEqual(throttle(2000));
  });

  it("never touches private topics or system, hidden, off-screen or collapsed", () => {
    expect(NOT_VISUAL.some(isVisualTopic)).toBe(false);
    expect(DEFAULTS.every(([ch]) => isVisualTopic(ch))).toBe(true);
    const everything = NOT_VISUAL.flatMap((ch) => {
      return (["visible", "offscreen", "collapsed"] as const).map((visibility) => {
        return consumer(ch, { visibility, tabHidden: true, requestedMs: 0 });
      });
    });
    expect(desiredThrottles(everything, MIN).size).toBe(0);
  });

  it("restore (tab visible again): the requested value, floored at min_throttle_ms", () => {
    const asked = [...workspace(), consumer("ticker.ETHUSDT", { requestedMs: 20 })];
    const expected = [...DEFAULTS, ["ticker.ETHUSDT", MIN]] as const;
    const restored = [...desiredThrottles(asked, MIN)];
    expect(restored).toEqual(expected.map(([ch, ms]) => [ch, throttle(ms)]));
  });

  it("an off-screen pane goes to 1 000 ms and the others keep their own", () => {
    const list = workspace().map((c) =>
      c.ch === BOOK ? { ...c, visibility: "offscreen" as const } : c,
    );
    const desired = desiredThrottles(list, MIN);
    expect(desired.get(BOOK)).toEqual(throttle(1000));
    expect(desired.get("trades.BTCUSDT")).toEqual(throttle(100));
  });

  it("a collapsed pane is released only when it is the topic's last consumer (refcount 0)", () => {
    const collapsed = consumer(BOOK, { visibility: "collapsed" });
    const live = consumer(BOOK, { requestedMs: 100 });
    const released = desiredThrottles([collapsed], MIN).get(BOOK);
    expect(released).toEqual({ kind: "release" });
    expect(Object.isFrozen(released)).toBe(true); // one value shared by every call: nobody may edit it
    // the collapsed pane's own 50 ms does not drag the topic down, whichever comes first
    expect(desiredThrottles([collapsed, live], MIN).get(BOOK)).toEqual(throttle(100));
    expect(desiredThrottles([live, collapsed], MIN).get(BOOK)).toEqual(throttle(100));
  });

  it("sanitises requestedMs: clamped to the ctl range, and NaN never poisons the minimum", () => {
    const asks = (...requestedMs: number[]) => {
      const consumers = requestedMs.map((ms) => consumer(BOOK, { requestedMs: ms }));
      return desiredThrottles(consumers, MIN).get(BOOK);
    };
    expect(asks(1e9)).toEqual(throttle(60_000)); // the top of the ctl range (13.6)
    expect(asks(-5)).toEqual(throttle(MIN)); // and never under what the server allows
    // the schema takes an integer, and the server refuses a ctl with 100.5 whole: round up, never faster than asked
    expect([asks(100.5), asks(333.33), asks(100)]).toEqual([
      throttle(101),
      throttle(334),
      throttle(100),
    ]);
    // not a finite number: counts as the fastest allowed, so a bug shows as traffic, never as NaN
    for (const bad of [Number.NaN, Infinity]) {
      expect([asks(bad), asks(bad, 200), asks(200, bad)]).toEqual([
        throttle(MIN),
        throttle(MIN),
        throttle(MIN),
      ]);
    }
  });

  it("floors at the protocol's 50 ms until welcome has said what this server's minimum is", () => {
    const fast = [consumer(BOOK, { requestedMs: 20 })];
    const floors = [undefined, Number.NaN, Infinity].map((min) =>
      desiredThrottles(fast, min).get(BOOK),
    );
    expect(floors).toEqual([throttle(50), throttle(50), throttle(50)]);
    expect(desiredThrottles(fast, 100).get(BOOK)).toEqual(throttle(100)); // a real minimum still wins
  });

  it("a topic runs at the fastest of its consumers in every tab", () => {
    const hiddenTab = consumer(BOOK, { tabHidden: true });
    const visibleTab = consumer(BOOK, { requestedMs: 100 });
    expect(desiredThrottles([hiddenTab, visibleTab], MIN).get(BOOK)).toEqual(throttle(100));
    const bothHidden = { ...visibleTab, tabHidden: true };
    expect(desiredThrottles([hiddenTab, bothHidden], MIN).get(BOOK)).toEqual(throttle(1000));
    const offscreen = { ...visibleTab, visibility: "offscreen" as const };
    expect(desiredThrottles([hiddenTab, offscreen], MIN).get(BOOK)).toEqual(throttle(1000));
  });
});

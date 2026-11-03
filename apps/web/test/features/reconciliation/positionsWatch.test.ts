/**
 * E29-S07 (#1028) review fold M1: the reassurance drop watches the `positions` topic with a
 * consumer of its own (E29-S01's feed untouched); a delta drops its accounts, a reset every one.
 */
import { describe, expect, it, vi } from "vitest";
import {
  MAX_WATCHED,
  movedAccounts,
  watchPositionDeltas,
  type WatchTimers,
} from "../../../src/features/reconciliation/positionsWatch";
import type { ConsumerSpec, TopicFrame, TopicHandle } from "../../../src/lib/ws/api";

const A = "a1000000-0000-4000-8000-00000000000A";
const B = "a1000000-0000-4000-8000-00000000000b";
const stamp = { seq: 1, ts: 1, sp: undefined, decodeMs: 0, size: 1, meta: undefined };
const delta = (...ids: string[]): TopicFrame => ({
  ...stamp,
  kind: "d",
  body: { e: "j", p: { positions: ids.map((id) => ({ exchange_account_id: id })) } },
});

function fakeClient() {
  let queue: TopicFrame[] = [];
  const release = vi.fn();
  const specs: ConsumerSpec[] = [];
  const client = {
    consume: (spec: ConsumerSpec): TopicHandle => {
      specs.push(spec);
      return {
        ch: spec.ch,
        read: () => {
          const out = queue;
          queue = [];
          return out;
        },
        effective: {},
        status: "live",
        source: "live",
        rs: undefined,
        release,
      };
    },
  };
  return { client, push: (f: TopicFrame) => queue.push(f), release, specs };
}
function fakeTimers(): WatchTimers & { tick(): void; cleared: boolean } {
  let fn: () => void = () => undefined;
  const t = {
    cleared: false,
    setInterval: (f: () => void) => ((fn = f), 1),
    clearInterval: () => void (t.cleared = true),
    tick: () => fn(),
  };
  return t;
}

describe("movedAccounts", () => {
  it("a delta names its accounts (lower-cased); a reset or an unreadable delta all", () => {
    expect(movedAccounts(delta(A, B))).toEqual([A.toLowerCase(), B]);
    expect(movedAccounts({ kind: "reset", reason: "gap" })).toBe("all");
    expect(movedAccounts({ ...stamp, kind: "d", body: { e: "j", p: { other: 1 } } })).toBe("all");
  });

  it("the handle's first snap moves nothing; any later snap moves every account", () => {
    const snap: TopicFrame = { ...stamp, kind: "snap", bodies: [{ e: "j", p: {} }] };
    expect(movedAccounts(snap, true)).toEqual([]);
    expect(movedAccounts(snap)).toBe("all");
  });

  it("a body that is not JSON, or has no record payload, moves every account (fail closed)", () => {
    const binary: TopicFrame = {
      ...stamp,
      kind: "d",
      body: { e: "b64", bytes: new ArrayBuffer(1) },
    };
    expect(movedAccounts(binary)).toBe("all");
    expect(movedAccounts({ ...stamp, kind: "d", body: { e: "j", p: [] } })).toBe("all");
    expect(movedAccounts({ ...stamp, kind: "d", body: { e: "j", p: null } })).toBe("all");
  });
});

describe("watchPositionDeltas", () => {
  it("drains on its timer, drops each moved account, and lets go on stop (teardown)", () => {
    const { client, push, release, specs } = fakeClient();
    const timers = fakeTimers();
    const onMoved = vi.fn();
    const stop = watchPositionDeltas(client, [A, B], onMoved, timers);
    expect(specs[0]).toEqual({
      ch: "positions",
      opts: { exchange_account_ids: [A.toLowerCase(), B] },
      paneId: "reconciliation",
      priority: "private",
    });
    push(delta(B));
    expect(onMoved).not.toHaveBeenCalled(); // never per arrival
    timers.tick();
    expect(onMoved).toHaveBeenCalledWith(B);
    push({ kind: "reset", reason: "resnapshot" });
    timers.tick();
    expect(onMoved).toHaveBeenCalledWith(A.toLowerCase());
    onMoved.mockClear();
    push({ ...stamp, kind: "snap", bodies: [{ e: "j", p: {} }] }); // the handle's first snap
    timers.tick();
    expect(onMoved).not.toHaveBeenCalled();
    push({ ...stamp, kind: "snap", bodies: [{ e: "j", p: {} }] }); // a mid-session resnapshot
    timers.tick();
    expect(onMoved.mock.calls.map(([id]) => id)).toEqual([A.toLowerCase(), B]);
    stop();
    expect(release).toHaveBeenCalledTimes(1);
    expect(timers.cleared).toBe(true);
  });

  it("a stop applies the frames still buffered first: a delta pending at stop still drops its account", () => {
    const { client, push, release } = fakeClient();
    const timers = fakeTimers();
    const onMoved = vi.fn();
    const stop = watchPositionDeltas(client, [A, B], onMoved, timers);
    push(delta(B)); // arrived since the last tick; no tick has run
    expect(onMoved).not.toHaveBeenCalled();
    stop();
    expect(onMoved).toHaveBeenCalledWith(B);
    expect(release).toHaveBeenCalledTimes(1);
  });

  it("the first snap drops nothing but touches every watched account's generation", () => {
    const { client, push } = fakeClient();
    const timers = fakeTimers();
    const onMoved = vi.fn();
    const onTouched = vi.fn();
    watchPositionDeltas(client, [A, B], onMoved, timers, onTouched);
    push({ ...stamp, kind: "snap", bodies: [{ e: "j", p: {} }] });
    timers.tick();
    expect(onMoved).not.toHaveBeenCalled();
    expect(onTouched.mock.calls.map(([id]) => id)).toEqual([A.toLowerCase(), B]);
    push({ ...stamp, kind: "snap", bodies: [{ e: "j", p: {} }] });
    timers.tick();
    expect(onMoved).toHaveBeenCalledTimes(2); // a later snap drops (and so touches) them all
    expect(onTouched).toHaveBeenCalledTimes(2);
  });

  it("watches at most one request's accounts, and nothing for none", () => {
    const { client, specs } = fakeClient();
    const ids = Array.from({ length: 30 }, (_, i) => `id-${i}`);
    watchPositionDeltas(client, ids, vi.fn(), fakeTimers())();
    expect(specs[0]?.opts?.exchange_account_ids).toHaveLength(MAX_WATCHED);
    watchPositionDeltas(client, [], vi.fn(), fakeTimers())();
    expect(specs).toHaveLength(1);
  });
});

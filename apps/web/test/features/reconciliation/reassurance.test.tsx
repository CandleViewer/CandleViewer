/**
 * E29-S07 (#1028) the reassurance gate (BQ-11 of 6575172489; BQ-6 and BQ-7 ruled (6610918411)):
 * "Your exchange-side stop-losses are unaffected." only when the REST read shows it true, never a
 * time clause, dropped at the next delta; E17's stops clause only while every account in scope
 * is synced and passed.
 */
import { act, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Position } from "../../../src/features/positions/api";
import {
  clearReassurance,
  dropReassurance,
  getReassurance,
  judge,
  readReassurance,
  reassuranceLine,
  stopsClauseHolds,
  touchReassurance,
  useReassuranceLine,
} from "../../../src/features/reconciliation/reassurance";
import { connectionRegion, regionAnnouncement } from "../../../src/lib/ws/state/connectionRegion";
import { INITIAL_WS_STATE, reduce } from "../../../src/lib/ws/state/reducer";
import type { EngineEvent, WsState } from "../../../src/lib/ws/state/types";
import { createAccountSignals } from "../../../src/shell/accountState";
import { streamReady } from "../../../src/features/reconciliation/reassurance";
import type { SystemUpdate } from "../../../src/lib/ws/protocol/frames";
import { OFF, authOk, connecting, shutdown, stream } from "../../lib/ws/support/engineEvents";

const A = "a1000000-0000-4000-8000-00000000000a";
const B = "a1000000-0000-4000-8000-00000000000b";
const pos = (symbol: string, over: Partial<Position> = {}): Position =>
  ({
    exchange_account_id: A,
    symbol,
    size: "0.250",
    native_stop_present: true,
    tpsl_mode: "Full",
    ...over,
  }) as Position;
/** A position whose read carries no `native_stop_present` at all. */
const unstamped = (symbol: string): Position =>
  Object.fromEntries(
    Object.entries(pos(symbol)).filter(([k]) => k !== "native_stop_present"),
  ) as Position;
const ok = (items: Position[]) => ({ kind: "ok" as const, items, aggregates: [] });

afterEach(() => clearReassurance());

describe("The reassurance must be true", () => {
  it("an open position found without a native stop: the line is not shown, the false line names it", () => {
    const verdict = judge(A, [pos("BTCUSDT"), pos("SOLUSDT", { native_stop_present: false })]);
    expect(reassuranceLine(verdict)).toEqual({
      key: "acct.reassure.false",
      text: "1 open position has no confirmed exchange-side stop: SOLUSDT.",
    });
  });

  it("every open position confirmed: the true line, its first sentence only (no time clause)", () => {
    expect(reassuranceLine(judge(A, [pos("BTCUSDT")]))).toEqual({
      key: "acct.reassure.true",
      text: "Your exchange-side stop-losses are unaffected.",
    });
  });

  it("a Partial-mode stop is never confirmed; flat positions and other accounts do not count", () => {
    const verdict = judge(A, [
      pos("BTCUSDT", { tpsl_mode: "Partial" }),
      pos("ETHUSDT", { native_stop_present: false, size: "0" }),
      pos("XRPUSDT", { native_stop_present: false, exchange_account_id: B }),
      unstamped("ADAUSDT"),
    ]);
    expect(reassuranceLine(verdict)?.text).toBe(
      "2 open positions have no confirmed exchange-side stop: ADAUSDT, BTCUSDT.",
    );
  });

  it("unread claims nothing", () => {
    expect(reassuranceLine({ kind: "unread" })).toBeNull();
  });
});

describe("the read and the drop", () => {
  it("reads each account, chunked at 25; a failed read leaves the accounts unread", async () => {
    const ids = Array.from(
      { length: 26 },
      (_, i) => `a1000000-0000-4000-8000-${String(i).padStart(12, "0")}`,
    );
    const listPositions = vi
      .fn()
      .mockResolvedValueOnce(ok([]))
      .mockResolvedValueOnce({ kind: "unavailable" });
    await readReassurance(ids, { listPositions });
    expect(listPositions).toHaveBeenCalledTimes(2);
    expect(listPositions.mock.calls[0]?.[0]).toEqual({ accountIds: ids.slice(0, 25) });
    expect(getReassurance().get(ids[0] ?? "")?.kind).toBe("true");
    expect(getReassurance().get(ids[25] ?? "")?.kind).toBe("unread");
  });

  it("the account's next positions delta drops the verdict until the next read", async () => {
    await readReassurance([A], { listPositions: async () => ok([pos("BTCUSDT")]) });
    function Line(): React.JSX.Element {
      return <p>{useReassuranceLine(A)?.text ?? "none"}</p>;
    }
    const view = render(<Line />);
    expect(view.container).toHaveTextContent("Your exchange-side stop-losses are unaffected.");
    act(() => dropReassurance(A));
    expect(view.container).toHaveTextContent("none");
    act(() => dropReassurance(A)); // idempotent
  });

  it("an aborted read stores nothing", async () => {
    const abort = new AbortController();
    abort.abort();
    await readReassurance([A], { listPositions: async () => ok([]) }, abort.signal);
    expect(getReassurance().size).toBe(0);
  });
});

describe("staleness (review fold M1, OM-T08): a delta drops the verdict, a read never revives it", () => {
  const deferred = () => {
    let release: (value: ReturnType<typeof ok>) => void = () => undefined;
    const promise = new Promise<ReturnType<typeof ok>>((r) => (release = r));
    return { promise, release };
  };

  it("a delta clears a true verdict until the next read", async () => {
    await readReassurance([A], { listPositions: async () => ok([pos("BTCUSDT")]) });
    expect(getReassurance().get(A)?.kind).toBe("true");
    dropReassurance(A);
    expect(getReassurance().get(A)).toBeUndefined();
  });

  /** `listPositions` answering each call with the next deferred, recording the accounts asked. */
  const answers = (count: number) => {
    const list = Array.from({ length: count }, () => deferred());
    const asked: (readonly string[] | undefined)[] = [];
    let n = 0;
    const api = {
      listPositions: (q?: { readonly accountIds?: readonly string[] }) => {
        asked.push(q?.accountIds);
        const next = list[n];
        n += 1;
        return next === undefined ? Promise.resolve(ok([])) : next.promise;
      },
    };
    return { list, asked, api };
  };
  const settleReads = async (): Promise<void> => {
    for (let i = 0; i < 5; i += 1) await Promise.resolve();
  };

  it("the first snap before the answer: the moved account is read again and ends true", async () => {
    const { list, asked, api } = answers(2);
    const reading = readReassurance([A, B], api);
    touchReassurance(A); // the subscription's first snap beats the REST answer
    list[0]?.release(ok([pos("BTCUSDT"), pos("ETHUSDT", { exchange_account_id: B })]));
    await settleReads();
    expect(getReassurance().get(A)).toBeUndefined(); // the crossed answer is not published
    expect(getReassurance().get(B)?.kind).toBe("true");
    expect(asked).toEqual([[A, B], [A]]); // the retry asks for the moved account only
    list[1]?.release(ok([pos("BTCUSDT")]));
    await reading;
    expect(getReassurance().get(A)?.kind).toBe("true");
  });

  it("a delta during the retry too leaves the account unread: no stale true, at most two reads", async () => {
    const { list, asked, api } = answers(2);
    const reading = readReassurance([A], api);
    dropReassurance(A);
    list[0]?.release(ok([pos("BTCUSDT")]));
    await settleReads();
    dropReassurance(A); // a later delta lands while the retry is on the wire
    list[1]?.release(ok([pos("BTCUSDT")]));
    await reading;
    expect(getReassurance().get(A)).toBeUndefined();
    expect(asked).toHaveLength(2);
  });

  it("a verdict held before a snap stands while the retry is on the wire", async () => {
    await readReassurance([B], { listPositions: async () => ok([]) });
    touchReassurance(B);
    expect(getReassurance().get(B)?.kind).toBe("true");
  });

  it("a clear during a read voids it", async () => {
    const answer = deferred();
    const reading = readReassurance([A], { listPositions: () => answer.promise });
    clearReassurance();
    answer.release(ok([pos("BTCUSDT")]));
    await reading;
    expect(getReassurance().size).toBe(0);
  });

  it("the next read after a drop stores its verdict again", async () => {
    dropReassurance(A);
    await readReassurance([A], { listPositions: async () => ok([pos("BTCUSDT")]) });
    expect(getReassurance().get(A)?.kind).toBe("true");
  });
});

describe("E17's stops clause (BQ-7 ruled)", () => {
  const signals = createAccountSignals();
  const notice = (reason: string): SystemUpdate =>
    ({
      kind: "account_notice",
      severity: "warning",
      reason,
      message: "m",
      exchange_account_ids: [A],
    }) as SystemUpdate;

  it("holds only while every account in scope is synced and passed", async () => {
    await readReassurance([A, B], {
      listPositions: async () => ok([pos("BTCUSDT"), pos("ETHUSDT", { exchange_account_id: B })]),
    });
    expect(stopsClauseHolds([A, B], signals.getSnapshot(), getReassurance())).toBe(true);
    expect(
      stopsClauseHolds(
        [A, B, "a1000000-0000-4000-8000-0000000000cc"],
        signals.getSnapshot(),
        getReassurance(),
      ),
    ).toBe(false);
    signals.applyNotice(notice("oms.account_desync"), 1);
    expect(stopsClauseHolds([A, B], signals.getSnapshot(), getReassurance())).toBe(false);
    signals.applyNotice(notice("oms.account_synced"), 2);
    // L3: an unknown or empty account list is unread (fail closed)
    expect(stopsClauseHolds([], signals.getSnapshot(), new Map())).toBe(false);
    expect(stopsClauseHolds(undefined, signals.getSnapshot(), getReassurance())).toBe(false);
  });

  const run = (...events: EngineEvent[]): WsState => events.reduce(reduce, INITIAL_WS_STATE);
  const UP = run(connecting, authOk(OFF), stream("live"));
  const DROPPED = reduce(UP, {
    type: "reconnecting",
    attempt: 1,
    nextAttemptAtMs: 4_000,
    lost: { sinceMs: 0, lastDataMs: null },
  });

  it("a region drawn without it never says it either", () => {
    const view = connectionRegion(DROPPED, 1_000, { stopsConfirmed: false });
    expect(view?.lines.join(" ")).not.toMatch(/stops/i);
    expect(view?.lines).toContain("App-managed rules are paused.");
    expect(regionAnnouncement(null, view)?.text).toBe(
      "Disconnected. New orders off. Cancel and close still work, confirmed over the server.",
    );
    const kept = connectionRegion(DROPPED, 1_000, { stopsConfirmed: true });
    expect(regionAnnouncement(null, kept)?.text).toMatch(/Exchange-side stops still protect/);
  });

  it("every variant that carried it drops it: offline, session ended, the shutdown read-only line", () => {
    const fatal = (closeCode: number) =>
      reduce(UP, {
        type: "offline",
        cause: "fatal",
        closeCode,
        lost: { sinceMs: 0, lastDataMs: 0 },
      });
    for (const ws of [fatal(1002), fatal(4403), reduce(UP, shutdown)]) {
      const view = connectionRegion(ws, 1_000, { stopsConfirmed: false });
      expect(view?.lines.join(" ")).not.toMatch(/stops/i);
      expect(view?.lines.join(" ")).toMatch(/[Aa]pp-managed rules are paused/);
    }
  });
});

describe("the clause fails closed (E29-S07 review)", () => {
  it("an overflowed account store reads as unread, as new exposure does", () => {
    const signals = createAccountSignals();
    const id = (i: number) => `a1000000-0000-4000-8000-${String(i).padStart(12, "0")}`;
    for (let i = 0; i < 257; i += 1)
      signals.applyNotice(
        {
          kind: "account_notice",
          severity: "warning",
          reason: "oms.account_desync",
          message: "m",
          exchange_account_ids: [id(i)],
          changed_at_ms: 1,
        } as SystemUpdate,
        1,
      );
    expect(signals.getSnapshot().overflowed).toBe(true);
    expect(
      stopsClauseHolds([A], signals.getSnapshot(), new Map([[A, { kind: "true" as const }]])),
    ).toBe(false);
  });

  it("streamReady needs the link up, no outage, a live system stream and the private feed", () => {
    const live = [connecting, authOk(OFF), stream("live")].reduce(reduce, INITIAL_WS_STATE);
    expect(streamReady(live, false)).toBe(true);
    expect(streamReady(live, true)).toBe(false);
    expect(streamReady(reduce(live, stream("resyncing")), false)).toBe(false);
    expect(streamReady(INITIAL_WS_STATE, false)).toBe(false);
  });
});

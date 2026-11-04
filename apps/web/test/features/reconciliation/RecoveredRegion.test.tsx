// E29-S07 (#1028) SCR-152's `recovered` region (E17-D02 §6, §10 B7; E29-D03 §4.6; E08-D14 DF-17):
// the summary after a reconnect, SR-03 said once, FM-24's focus on dismissal. Fake timers, fake
// reads (no network), the WS state from the reducer.
import { createRequire } from "node:module";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ShellAnnouncer, clearAnnouncements } from "../../../src/features/app-shell/announcer";
import type { ReconciliationReads } from "../../../src/features/reconciliation/digest";
import {
  RecoveredRegionSlot,
  summaryAccounts,
} from "../../../src/features/reconciliation/RecoveredRegion";
import { INITIAL_WS_STATE, reduce } from "../../../src/lib/ws/state/reducer";
import type { EngineEvent, WsState } from "../../../src/lib/ws/state/types";
import { shellAccountSignals } from "../../../src/shell/accountState";
import {
  getReassurance,
  readReassurance,
  stopsClauseHolds,
} from "../../../src/features/reconciliation/reassurance";
import {
  applySystemUpdate,
  resetShellState,
  setShellState,
  type Me,
} from "../../../src/shell/bootstrap/store";
import type { SystemUpdate } from "../../../src/lib/ws/protocol/frames";
import { OFF, ON, authOk, connecting, killSwitch, stream } from "../../lib/ws/support/engineEvents";
import { A, digest } from "./support/digests";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };
const seriousAxe = async (el: Element): Promise<unknown[]> =>
  (await axe.run(el, { rules: { "color-contrast": { enabled: false } } })).violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );

const T0 = Date.UTC(2026, 10, 3, 14, 1, 30);
const run = (...events: EngineEvent[]): WsState => events.reduce(reduce, INITIAL_WS_STATE);
const UP = run(connecting, authOk(OFF), stream("live"));
const DROPPED = reduce(UP, {
  type: "reconnecting",
  attempt: 1,
  nextAttemptAtMs: T0 + 4_000,
  lost: { sinceMs: T0, lastDataMs: T0 - 1_000 },
});
const BACK = [connecting, authOk(OFF), stream("live")].reduce(reduce, DROPPED);

function fakeReads(over: Partial<ReconciliationReads> = {}): ReconciliationReads & {
  signals: AbortSignal[];
} {
  const signals: AbortSignal[] = [];
  return {
    signals,
    getDigest: vi.fn(async (_id: string, signal?: AbortSignal) => {
      if (signal !== undefined) signals.push(signal);
      return { kind: "ok" as const, digest: digest({ corrected: ["l-1"] }) };
    }),
    offlineFills: vi.fn(async () => [{ accountId: A, orderId: "o-1", filled: true }]),
    ...over,
  };
}

const ME = {
  accounts: [{ exchange_account_id: A, label: "Sub-1", environment: "live", mode: "trade" }],
} as unknown as Me;

/** The reassurance gate's read: every open position confirmed (no network). */
const positions = {
  listPositions: vi.fn(async () => ({ kind: "ok" as const, items: [], aggregates: [] })),
};

/** The reassurance drop's watch: the test moves an account with `moved(id)`. */
let moved: (id: string) => void = () => undefined;
type Watch = (
  ids: readonly string[],
  onMoved: (id: string) => void,
  onTouched: (id: string) => void,
) => () => void;
const watch = vi.fn<Watch>((_ids, onMoved) => {
  moved = onMoved;
  return () => {
    moved = () => undefined;
  };
});

function Harness(props: {
  ws: WsState;
  reads: ReconciliationReads;
  privateFeedDown?: boolean;
  visible?: boolean;
  last?: boolean;
}): React.JSX.Element {
  return (
    <>
      <RecoveredRegionSlot
        ws={props.ws}
        privateFeedDown={props.privateFeedDown ?? false}
        visible={props.visible ?? true}
        reads={props.reads}
        positions={positions}
        watch={watch}
        now={() => Date.now()}
      />
      {props.last === true ? null : <button type="button">Next stop</button>}
      <main>Workspace</main>
      <ShellAnnouncer />
    </>
  );
}

const flush = async (): Promise<void> => {
  await act(async () => {
    await vi.runAllTimersAsync();
  });
};
const region = (): HTMLElement | null => screen.queryByRole("region", { name: "Connection" });
const assertive = (): HTMLElement => {
  const el = [...document.querySelectorAll<HTMLElement>('[aria-live="assertive"]')].at(-1);
  if (el === undefined) throw new Error("no assertive region");
  return el;
};

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(T0);
  act(() => setShellState({ me: ME }));
});
afterEach(() => {
  act(() => {
    resetShellState();
    clearAnnouncements();
  });
  vi.useRealTimers();
});

describe("Reconnect with a correction", () => {
  it("after the drop and the snapshots, the summary lists the fill with a link to its row", async () => {
    const reads = fakeReads();
    const view = render(<Harness ws={UP} reads={reads} />);
    view.rerender(<Harness ws={DROPPED} reads={reads} />);
    await flush();
    expect(region()).toBeNull();
    vi.setSystemTime(T0 + 41_000);
    view.rerender(<Harness ws={BACK} reads={reads} />);
    await flush();
    const r = region();
    expect(r).not.toBeNull();
    expect(r).toHaveAttribute("data-state", "recovered");
    expect(r).toHaveTextContent("Reconnected");
    expect(r).toHaveTextContent("While you were offline: 1 order filled.");
    expect(within(r as HTMLElement).getByRole("link", { name: "1 order filled" })).toHaveAttribute(
      "href",
      "/positions/order/o-1",
    );
    expect(r).toHaveTextContent(
      "Offline 14:01:30–14:02:11 UTC · Sub-1: 1 change — review them in Positions.",
    );
    expect(reads.offlineFills).toHaveBeenCalledWith(
      [A],
      { fromMs: T0, toMs: T0 + 41_000 },
      expect.anything(),
    );
    expect(assertive()).toHaveTextContent("Reconnected. 1 order filled while offline.");
  });
});

describe("the recovered region", () => {
  it("shows nothing at a session start (no outage), and holds until the snapshots are in", async () => {
    const reads = fakeReads();
    const view = render(<Harness ws={run(connecting)} reads={reads} />);
    view.rerender(<Harness ws={UP} reads={reads} />);
    await flush();
    expect(region()).toBeNull();
    view.rerender(<Harness ws={DROPPED} reads={reads} />);
    view.rerender(<Harness ws={BACK} reads={reads} privateFeedDown />);
    await flush();
    expect(region()).toBeNull();
    expect(reads.getDigest).not.toHaveBeenCalled();
    view.rerender(<Harness ws={BACK} reads={reads} />);
    await flush();
    expect(region()).not.toBeNull();
  });

  it("is never auto-hidden: it holds past 10 s until dismissed", async () => {
    const reads = fakeReads();
    const view = render(<Harness ws={DROPPED} reads={reads} />);
    view.rerender(<Harness ws={BACK} reads={reads} />);
    await flush();
    act(() => vi.advanceTimersByTime(60_000));
    expect(region()).not.toBeNull();
  });

  it("SR-03 is said once per episode exit, and a new outage drops the summary", async () => {
    const reads = fakeReads();
    const view = render(<Harness ws={DROPPED} reads={reads} />);
    view.rerender(<Harness ws={BACK} reads={reads} />);
    await flush();
    const said = assertive().textContent;
    view.rerender(<Harness ws={{ ...BACK }} reads={reads} />);
    await flush();
    expect(assertive().textContent).toBe(said);
    expect(reads.getDigest).toHaveBeenCalledTimes(1);
    view.rerender(<Harness ws={DROPPED} reads={reads} />);
    await flush();
    expect(region()).toBeNull();
  });

  it("FM-24: Dismiss returns focus to the slot's next Tab stop; Esc dismisses too", async () => {
    const reads = fakeReads();
    const view = render(<Harness ws={DROPPED} reads={reads} />);
    view.rerender(<Harness ws={BACK} reads={reads} />);
    await flush();
    const dismiss = screen.getByRole("button", { name: "Dismiss" });
    dismiss.focus();
    fireEvent.click(dismiss);
    expect(region()).toBeNull();
    expect(screen.getByRole("button", { name: "Next stop" })).toHaveFocus();

    view.rerender(<Harness ws={DROPPED} reads={reads} />);
    view.rerender(<Harness ws={BACK} reads={reads} />);
    await flush();
    const link = within(region() as HTMLElement).getByRole("link", { name: "1 order filled" });
    link.focus();
    fireEvent.keyDown(link, { key: "Escape" });
    expect(region()).toBeNull();
    expect(screen.getByRole("button", { name: "Next stop" })).toHaveFocus();
  });

  it("with no digest and no fills, it reads Reconnected and summary.interim", async () => {
    const reads = fakeReads({
      getDigest: vi.fn(async () => ({ kind: "none" as const })),
      offlineFills: vi.fn(async () => null),
    });
    const view = render(<Harness ws={DROPPED} reads={reads} />);
    view.rerender(<Harness ws={BACK} reads={reads} />);
    await flush();
    expect(region()).toHaveTextContent(
      "ReconnectedOffline 14:01:30–14:01:30 UTC. Rule actions are not listed here yet — check your stops.",
    );
    expect(assertive()).toHaveTextContent(/^Reconnected\.$/);
  });

  it("teardown: unmounting mid-read aborts it, and nothing renders or speaks after", async () => {
    let release: (() => void) | undefined;
    const reads = fakeReads({
      offlineFills: vi.fn(() => new Promise<null>((resolve) => (release = () => resolve(null)))),
    });
    const view = render(<Harness ws={DROPPED} reads={reads} />);
    view.rerender(<Harness ws={BACK} reads={reads} />);
    await act(async () => Promise.resolve());
    view.unmount();
    expect(reads.signals.every((s) => s.aborted)).toBe(true);
    await act(async () => release?.());
    expect(document.querySelector('[data-state="recovered"]')).toBeNull();
  });

  it("follows the client's kill switch into the shell's account states", () => {
    const reads = fakeReads();
    render(<Harness ws={reduce(UP, killSwitch(ON))} reads={reads} />);
    expect(shellAccountSignals.getSnapshot().killSwitch.view.state).toBe("engaged");
  });

  it("the reassurance gate reads at each connect and again when an account's lock begins", async () => {
    positions.listPositions.mockClear();
    const reads = fakeReads();
    render(<Harness ws={UP} reads={reads} />);
    await flush();
    expect(positions.listPositions).toHaveBeenCalledTimes(1);
    expect(positions.listPositions.mock.calls[0]).toEqual([{ accountIds: [A] }, expect.anything()]);
    act(() =>
      applySystemUpdate({
        kind: "account_notice",
        severity: "critical",
        reason: "oms.account_stale",
        message: "m",
        exchange_account_ids: [A],
        changed_at_ms: 5,
      } as SystemUpdate),
    );
    await flush();
    expect(positions.listPositions).toHaveBeenCalledTimes(2);
  });

  it("a positions delta drops the account's verdict until the next read (review fold M1)", async () => {
    positions.listPositions.mockResolvedValue({ kind: "ok", items: [], aggregates: [] });
    render(<Harness ws={UP} reads={fakeReads()} />);
    await flush();
    expect(getReassurance().get(A)?.kind).toBe("true");
    expect(watch).toHaveBeenLastCalledWith([A], expect.any(Function), expect.any(Function));
    act(() => moved(A));
    expect(getReassurance().get(A)).toBeUndefined();
  });

  it("every connect drops the last verdicts first, before its own read answers", async () => {
    await readReassurance([A], positions); // a verdict from an earlier session
    expect(getReassurance().get(A)?.kind).toBe("true");
    let answer: (v: { kind: "ok"; items: never[]; aggregates: never[] }) => void = () => undefined;
    positions.listPositions.mockImplementationOnce(
      () => new Promise((resolve) => (answer = resolve as typeof answer)),
    );
    render(<Harness ws={UP} reads={fakeReads()} />);
    await flush();
    expect(getReassurance().get(A)).toBeUndefined(); // cleared at the connect, the read still out
    await act(async () => answer({ kind: "ok", items: [], aggregates: [] }));
    expect(getReassurance().get(A)?.kind).toBe("true");
  });

  it("the watch runs while the link is up: `ready` falling with the link up keeps it, and a delta drops the verdict (BQ-11)", async () => {
    positions.listPositions.mockResolvedValue({ kind: "ok", items: [], aggregates: [] });
    watch.mockClear();
    const view = render(<Harness ws={UP} reads={fakeReads()} />);
    await flush();
    expect(getReassurance().get(A)?.kind).toBe("true");
    const resyncing = reduce(UP, stream("resyncing")); // link still up, `ready` false
    expect(resyncing.link.kind).toBe("up");
    view.rerender(<Harness ws={resyncing} reads={fakeReads()} />);
    await flush();
    expect(watch).toHaveBeenCalledTimes(1); // not torn down, not restarted
    act(() => moved(A)); // a delta received while `ready` is false
    expect(getReassurance().get(A)).toBeUndefined();
    view.rerender(<Harness ws={DROPPED} reads={fakeReads()} />); // then the link drops
    await flush();
    const signals = shellAccountSignals.getSnapshot();
    expect(stopsClauseHolds([A], signals, getReassurance())).toBe(false); // the claim is not made
  });

  it("the link dropping stops the watch but keeps the last verdict; unmounting clears it", async () => {
    positions.listPositions.mockResolvedValue({ kind: "ok", items: [], aggregates: [] });
    const stopped = vi.fn();
    const mine = vi.fn<Watch>(() => stopped);
    const render1 = (ws: WsState) => (
      <RecoveredRegionSlot
        ws={ws}
        privateFeedDown={false}
        visible
        reads={fakeReads()}
        positions={positions}
        watch={mine}
        now={() => Date.now()}
      />
    );
    const view = render(render1(UP));
    await flush();
    expect(getReassurance().get(A)?.kind).toBe("true");
    view.rerender(render1(DROPPED));
    await flush();
    expect(stopped).toHaveBeenCalledTimes(1); // the watch stops with the link (it drains first)
    expect(getReassurance().get(A)?.kind).toBe("true"); // nothing can arrive to move it: the last read stands
    view.unmount();
    expect(getReassurance().size).toBe(0); // nothing watches after unmount: no verdict is kept
  });

  it("the shell's stop clears the verdicts (resetShellState)", async () => {
    await readReassurance([A], positions);
    expect(getReassurance().get(A)?.kind).toBe("true");
    act(() => resetShellState());
    expect(getReassurance().size).toBe(0);
  });

  it("a lock past the watched accounts, or with no watch running, is not read", async () => {
    positions.listPositions.mockClear();
    const view = render(<Harness ws={DROPPED} reads={fakeReads()} />); // the link is down: no watch
    act(() =>
      applySystemUpdate({
        kind: "account_notice",
        severity: "critical",
        reason: "oms.account_stale",
        message: "m",
        exchange_account_ids: [A],
        changed_at_ms: 7,
      } as SystemUpdate),
    );
    await flush();
    expect(positions.listPositions).not.toHaveBeenCalled();
    view.unmount();
  });

  it("a lock on an account past the watched 25 is not read (it stays unread)", async () => {
    const id = (i: number) => `a1000000-0000-4000-8000-${String(i).padStart(12, "0")}`;
    const many = {
      accounts: Array.from({ length: 26 }, (_, i) => ({
        exchange_account_id: id(i),
        label: `Sub-${i}`,
        environment: "live",
        mode: "trade",
      })),
    } as unknown as Me;
    act(() => setShellState({ me: many }));
    positions.listPositions.mockClear();
    const view = render(<Harness ws={UP} reads={fakeReads()} />);
    await flush();
    positions.listPositions.mockClear(); // the connect read of the first 25
    act(() =>
      applySystemUpdate({
        kind: "account_notice",
        severity: "critical",
        reason: "oms.account_stale",
        message: "m",
        exchange_account_ids: [id(25)],
        changed_at_ms: 9,
      } as SystemUpdate),
    );
    await flush();
    expect(positions.listPositions).not.toHaveBeenCalled();
    expect(getReassurance().has(id(25))).toBe(false);
    view.unmount();
  });

  it("SR-03 waits until the region shows (a11y m2)", async () => {
    const reads = fakeReads();
    const view = render(<Harness ws={DROPPED} reads={reads} visible={false} />);
    view.rerender(<Harness ws={BACK} reads={reads} visible={false} />);
    await flush();
    expect(assertive()).toBeEmptyDOMElement();
    view.rerender(<Harness ws={BACK} reads={reads} />);
    await flush();
    expect(assertive()).toHaveTextContent("Reconnected. 1 order filled while offline.");
  });

  it("FM-24: with no stop after it, Dismiss hands focus to main; focus elsewhere stays", async () => {
    const reads = fakeReads();
    const view = render(<Harness ws={DROPPED} reads={reads} last />);
    view.rerender(<Harness ws={BACK} reads={reads} last />);
    await flush();
    const dismiss = screen.getByRole("button", { name: "Dismiss" });
    dismiss.focus();
    fireEvent.click(dismiss);
    expect(screen.getByRole("main")).toHaveFocus();

    view.rerender(<Harness ws={DROPPED} reads={reads} />);
    view.rerender(<Harness ws={BACK} reads={reads} />);
    await flush();
    const elsewhere = screen.getByRole("button", { name: "Next stop" });
    elsewhere.focus();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(elsewhere).toHaveFocus(); // a pointer press from outside never moves focus
  });

  it("names only the session's accounts, by label (SR-E29-10)", () => {
    expect(summaryAccounts(ME.accounts)).toEqual([{ id: A, label: "Sub-1", env: "LIVE" }]);
    expect(summaryAccounts(undefined)).toEqual([]);
  });

  it("axe: no serious or critical violation", { timeout: 30_000 }, async () => {
    const reads = fakeReads();
    const view = render(<Harness ws={DROPPED} reads={reads} />);
    view.rerender(<Harness ws={BACK} reads={reads} />);
    await flush();
    vi.useRealTimers();
    expect(await seriousAxe(region() as HTMLElement)).toEqual([]);
  });
});

/**
 * E29-S01 (#911) the feed's announcements, owned by the panel (`feedAnnouncements.ts`): each
 * crossing once even when StrictMode runs the mount's effects twice, the loading and could-not-load
 * lines once per episode, each account withdrawn once with the lines of one change in one message,
 * and a line a focus move already spoke left unsaid (E29-D05 §5.4, F-02).
 */
import { StrictMode, createElement, type ReactNode } from "react";
import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { generated } from "@candleviewer/protocol";
import type { PanelAnnouncer } from "../../../src/features/positions/announce";
import { useFeedAnnouncements } from "../../../src/features/positions/feedAnnouncements";
import {
  accountInfo,
  type AccountInfo,
  type ExchangeAccount,
} from "../../../src/features/positions/model/rowMapping";
import {
  createPositionsStore,
  type PositionsSnapshot,
  type Withdrawn,
} from "../../../src/features/positions/positionsStore";
import { delta, golden, reset, snap } from "./support/fakes";

type Positions = generated.ws.Positions;
const snapshot = golden<Positions>("ws_positions_snapshot.json");
const accounts = golden<{ items: ExchangeAccount[] }>("rest_list_exchange_accounts.json")
  .items.map(accountInfo)
  .filter((a): a is AccountInfo => a !== null);
const strict = ({ children }: { children: ReactNode }) => createElement(StrictMode, null, children);

function fakeAnnouncer(): PanelAnnouncer & { said: [string, string][] } {
  const said: [string, string][] = [];
  return { said, say: (politeness, text) => void said.push([politeness, text]), dispose: vi.fn() };
}

/** The store's snapshots as the feed would commit them: a book read, then `then`'s frames. */
function committed(then: (store: ReturnType<typeof createPositionsStore>) => void): {
  readonly before: PositionsSnapshot;
  readonly after: PositionsSnapshot;
} {
  const store = createPositionsStore();
  store.setStarted(true);
  store.setAccounts(accounts);
  store.applyFrames([snap(snapshot)]);
  store.commit();
  const before = store.getSnapshot();
  then(store);
  store.commit();
  return { before, after: store.getSnapshot() };
}

const NONE = new Map();
const NOBODY = new WeakSet<Withdrawn>();

describe("the panel's feed announcements", () => {
  it("says a crossing once, StrictMode's second effect run included (RT-05)", () => {
    const main = snapshot.positions[0] as Positions["positions"][number];
    const { after } = committed((store) =>
      store.applyFrames([
        delta({
          positions: [{ ...main, mark_price: "58400", updated_at_ms: main.updated_at_ms + 10 }],
        }),
      ]),
    );
    expect(after.crossings).toHaveLength(1);
    const announcer = fakeAnnouncer();
    renderHook(
      () =>
        useFeedAnnouncements({
          snap: after,
          accounts: NONE,
          environment: "live",
          announcer,
          spokenByFocus: NOBODY,
        }),
      { wrapper: strict },
    );
    expect(announcer.said).toEqual([
      [
        "assertive",
        "BTCUSDT Long on Main: Critical — near liquidation: 8 % of the entry buffer left, 0.9 % from liquidation",
      ],
    ]);
  });

  it("says loading once per episode, once the accounts are known (S-01)", () => {
    const store = createPositionsStore();
    store.setStarted(true);
    store.commit();
    const unknown = store.getSnapshot();
    store.setAccounts(accounts);
    store.commit();
    const loading = store.getSnapshot();
    const announcer = fakeAnnouncer();
    const props = (snap: PositionsSnapshot) => ({
      snap,
      accounts: NONE,
      environment: "live" as const,
      announcer,
      spokenByFocus: NOBODY,
    });
    const { rerender } = renderHook((p: ReturnType<typeof props>) => useFeedAnnouncements(p), {
      initialProps: props(unknown),
    });
    rerender(props(loading));
    rerender(props({ ...loading, version: loading.version + 1 }));
    expect(announcer.said).toEqual([
      ["polite", "Loading Main · LIVE… Loading Sub-1 · LIVE… Loading Sub-2 · LIVE…"],
    ]);
  });

  it("says could not load once per failure (RT-15)", () => {
    const store = createPositionsStore();
    store.setStarted(true);
    store.setAccounts(accounts.slice(0, 1));
    store.markSnapshotFailed();
    store.commit();
    const failed = store.getSnapshot();
    const announcer = fakeAnnouncer();
    const props = (snap: PositionsSnapshot) => ({
      snap,
      accounts: NONE,
      environment: "live" as const,
      announcer,
      spokenByFocus: NOBODY,
    });
    const { rerender } = renderHook((p: ReturnType<typeof props>) => useFeedAnnouncements(p), {
      initialProps: props(failed),
    });
    rerender(props({ ...failed, version: failed.version + 1 }));
    expect(announcer.said).toEqual([["polite", "Could not load Main · LIVE"]]);
  });

  it("says each account withdrawn once, in one message, leaving out a line focus spoke (F-02)", () => {
    const { before, after } = committed((store) => store.applyFrames([reset("revoked")]));
    expect(after.withdrawn.map((w) => w.label)).toEqual(["Main", "Sub-1", "Sub-2"]);
    const spoken = new WeakSet<Withdrawn>([after.withdrawn[1] as Withdrawn]);
    const announcer = fakeAnnouncer();
    const props = (snap: PositionsSnapshot) => ({
      snap,
      accounts: NONE,
      environment: "live" as const,
      announcer,
      spokenByFocus: spoken,
    });
    const { rerender } = renderHook((p: ReturnType<typeof props>) => useFeedAnnouncements(p), {
      initialProps: props(before),
    });
    rerender(props(after));
    rerender(props({ ...after, version: after.version + 1 }));
    expect(announcer.said).toEqual([
      [
        "polite",
        "No longer shown — access to Main was withdrawn. No longer shown — access to Sub-2 was withdrawn.",
      ],
    ]);
  });
});

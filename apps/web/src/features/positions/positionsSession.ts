/**
 * The Positions panel's session (E29-S01 #911): the feed (`wsPositions.ts`), the positions store and
 * the account signals, owned by `PositionsPanel` for the route's life. CMP-042 mounts the selected
 * tab's panel only, so a session owned by the Positions tab would end on every tab switch: the book
 * re-read, every account state but the shell's last notice lost, a lock's "since" moved to the
 * return and its announcement said again. Owned here, a tab switch keeps the book and the states,
 * and the feed runs while another tab shows.
 *
 * The Working-orders tab's store, its feed and the amend store live here too (E29-S02 PR3a,
 * P3-BQ-8): the feed starts on the tab's first mount (`orders.start`) and then runs for the session,
 * so an amend's answer that lands while another tab shows is applied and said, never lost, and the
 * tab's return re-subscribes nothing. A panel never visited reads no orders.
 */
import { useEffect, useRef, useState } from "react";
import type { WsClient } from "../../lib/ws/api";
import { getShellState, subscribeShellState } from "../../shell/bootstrap/store";
import {
  createAccountSignals,
  startAccountSignals,
  type AccountSignalsStore,
} from "./accountSignals";
import type { PanelAnnouncer } from "./announce";
import { createPositionsStore, type PositionsStore, type Withdrawn } from "./positionsStore";
import type { SaveFile } from "./exportFile";
import { createAmendStore, type AmendStore } from "./orders/amendStore";
import { createOrdersStore, type OrdersStore } from "./orders/ordersStore";
import { startOrdersFeed, type OrdersDeps, type OrdersFeed } from "./orders/wsOrders";
import { startPositionsFeed, type PositionsFeed, type PositionsFeedOptions } from "./wsPositions";

/** The client the feed reads: the app's active one, or a test's fake (`support/fakes.ts`). */
export type FeedClient = Pick<WsClient, "consume" | "getState" | "subscribe">;

/** What a test injects (the `SessionsApi` pattern, BQ-19); the route passes none. */
export interface PositionsDeps {
  readonly client?: FeedClient | undefined;
  /** The feed's seams: the REST API, timers, rAF, clocks and the performance marks. */
  readonly feed?: Omit<PositionsFeedOptions, "client" | "store" | "signals"> | undefined;
  readonly saveFile?: SaveFile | undefined;
  /** The Working-orders tab's seams (E29-S02): its feed's, its writes and its clock. */
  readonly orders?: OrdersDeps | undefined;
}

export interface OrdersSession {
  readonly store: OrdersStore;
  readonly amends: AmendStore;
  /** The Working-orders tab's mount: the feed starts once, then runs for the session. */
  readonly start: () => void;
  /** S-02's Retry: the running feed's; nothing while none runs. */
  readonly retry: () => void;
}

export interface PositionsSession {
  readonly store: PositionsStore;
  readonly signals: AccountSignalsStore;
  /** S-02's Retry: the running feed's; nothing while none runs. */
  readonly retry: () => void;
  /** The withdrawn lines a focus move spoke (E29-D05 F-02): the tab writes, the panel reads. */
  readonly spokenByFocus: WeakSet<Withdrawn>;
  /** The Working-orders tab's store, feed and amends (P3-BQ-8). */
  readonly orders: OrdersSession;
}

/** The orders half: the amend store observes every item the orders store accepts. */
function useOrdersSession(
  client: FeedClient | null,
  deps: OrdersDeps | undefined,
  announcer: PanelAnnouncer | undefined,
): OrdersSession {
  const [amends] = useState(() =>
    (deps?.createAmends ?? createAmendStore)({
      writes: deps?.amendWrites,
      arm: deps?.arm,
      announce: (politeness, text) => announcer?.say(politeness, text),
      now: deps?.feed?.now,
      performance: deps?.feed?.performance,
      // N1: a press judges the orders store's row at the commit (`store` exists before any press)
      current: (orderId) => store.getSnapshot().rows.find((row) => row.id === orderId),
    }),
  );
  const [store] = useState(() =>
    createOrdersStore({ onItem: (item, via) => amends.observe(item, via) }),
  );
  const [wanted, setWanted] = useState(false);
  const running = useRef<OrdersFeed | null>(null);
  const feed = deps?.feed;
  useEffect(() => {
    if (client === null || !wanted) return undefined;
    const started = startOrdersFeed({ ...feed, client, store, amends });
    running.current = started;
    return () => {
      started.stop();
      if (running.current === started) running.current = null;
    };
  }, [client, store, amends, wanted, feed]);
  const [session] = useState<OrdersSession>(() => ({
    store,
    amends,
    start: () => setWanted(true),
    retry: () => running.current?.retry(),
  }));
  return session;
}

/** The session for `client` (none without one), its feeds restarted only when the client changes. */
export function usePositionsSession(
  client: FeedClient | null,
  feed: PositionsDeps["feed"],
  orders?: OrdersDeps,
  announcer?: PanelAnnouncer,
): PositionsSession {
  const [store] = useState(createPositionsStore);
  const [signals] = useState(createAccountSignals);
  const running = useRef<PositionsFeed | null>(null);
  const ordersSession = useOrdersSession(client, orders, announcer);
  useEffect(() => {
    if (client === null) return undefined;
    const started = startPositionsFeed({ ...feed, client, store, signals });
    running.current = started;
    const stopSignals = startAccountSignals(signals, {
      shell: { getState: getShellState, subscribe: subscribeShellState },
      ws: client,
      wall: feed?.wall,
    });
    return () => {
      stopSignals();
      started.stop();
      if (running.current === started) running.current = null;
    };
  }, [client, store, signals, feed]);
  const [session] = useState<PositionsSession>(() => ({
    store,
    signals,
    retry: () => running.current?.retry(),
    spokenByFocus: new WeakSet(),
    orders: ordersSession,
  }));
  return session;
}

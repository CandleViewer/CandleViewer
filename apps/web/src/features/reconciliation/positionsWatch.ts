/**
 * The reassurance gate's drop (E29-S07 #1028; review fold M1, OM-T08, C-2.6): a consumer of the
 * private `positions` topic of its own (`23` §6.2.3), so the Positions tab's feed
 * (`features/positions/wsPositions.ts`, E29-S01's) is not touched. Every delta names the accounts
 * whose positions moved; each one's verdict is dropped until the next read. A `reset` (gap,
 * resnapshot, revoke) drops every watched account. The handle's first `snap` is the fresh state
 * the connect read judges, so it drops nothing, though it still bumps every watched account's
 * generation (`onTouched`), so a read in flight across it publishes nothing; every later `snap` (a backpressure or incident
 * resnapshot, `23` §6.2, may come with no reset first) drops every watched account, as a reset
 * does. A frame this client cannot read (no JSON body, no record payload, no `positions` list)
 * drops them all too (fail closed). Drained on a coarse timer (C9: never per arrival).
 */
import type { ConsumerSpec, TopicFrame, TopicHandle } from "../../lib/ws/api";

/** `22` `AccountIdsQuery.maxItems`: one consumer names at most 25 accounts. */
export const MAX_WATCHED = 25;
export const DRAIN_MS = 250;
export const WATCH_PANE_ID = "reconciliation";

export interface WatchClient {
  consume(spec: ConsumerSpec): TopicHandle;
}

export interface WatchTimers {
  setInterval(fn: () => void, ms: number): unknown;
  clearInterval(id: unknown): void;
}

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);

/**
 * The accounts a frame says moved; `"all"` for a reset, a later `snap` (`firstSnap` false) or a
 * frame it cannot read. The handle's first `snap` moves nothing.
 */
export function movedAccounts(frame: TopicFrame, firstSnap = false): readonly string[] | "all" {
  if (frame.kind === "reset") return "all";
  if (frame.kind === "snap") return firstSnap ? [] : "all";
  if (frame.body.e !== "j" || !isRecord(frame.body.p)) return "all"; // unreadable: fail closed
  const rows = frame.body.p["positions"];
  if (!Array.isArray(rows)) return "all"; // a delta this client cannot read: fail closed
  return rows.flatMap((row: unknown) =>
    isRecord(row) && typeof row["exchange_account_id"] === "string"
      ? [row["exchange_account_id"].toLowerCase()]
      : [],
  );
}

/** Watches `accountIds` (the first `MAX_WATCHED`) until the returned stop. */
export function watchPositionDeltas(
  client: WatchClient,
  accountIds: readonly string[],
  onMoved: (accountId: string) => void,
  timers: WatchTimers = {
    setInterval: (fn, ms) => setInterval(fn, ms),
    clearInterval: (id) => clearInterval(id as ReturnType<typeof setInterval>),
  },
  onTouched: (accountId: string) => void = () => undefined,
): () => void {
  const watched = accountIds.slice(0, MAX_WATCHED).map((a) => a.toLowerCase());
  if (watched.length === 0) return () => undefined;
  const handle = client.consume({
    ch: "positions",
    opts: { exchange_account_ids: [...watched] },
    paneId: WATCH_PANE_ID,
    priority: "private",
  });
  let snapped = false;
  const drain = (): void => {
    for (const frame of handle.read()) {
      const moved = movedAccounts(frame, frame.kind === "snap" && !snapped);
      if (frame.kind === "snap") {
        // every snap moves the generation, the first included (a read across it never publishes)
        if (!snapped) for (const id of watched) onTouched(id);
        snapped = true;
      }
      for (const id of moved === "all" ? watched : moved) onMoved(id);
    }
  };
  const id = timers.setInterval(drain, DRAIN_MS);
  return () => {
    timers.clearInterval(id);
    // frames buffered since the last tick are applied first: a stop never throws away a delta
    // that would have dropped a verdict (C-2.6)
    drain();
    handle.release();
  };
}

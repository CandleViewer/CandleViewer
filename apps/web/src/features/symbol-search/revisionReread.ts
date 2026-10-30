/**
 * An `instrument_revision` re-reads the instrument list (E08-S09, #4703; E08-D05 §3, 23 §7.4). The server re-snaps every
 * subscription of a revised symbol, so one catalogue refresh reaches a tab as a burst of snapshots, one per subscription
 * of each symbol it changed. `note` is told of each; the index is read once, `REVISION_QUIET_MS` after the last of a burst
 * (a trailing debounce: a storm of revisions reads once, when it quiets), and only while the index runs. The server sends
 * the revisions before it has swapped in the list they describe, so a read whose list was fetched before the burst is
 * followed by one more, after another quiet, and by no further one. No React: timers on the index's own clock.
 */
import {
  SYSTEM_CLOCK,
  type Clock,
  type IndexSnapshot,
  type InstrumentIndex,
} from "./instrumentIndex";

/**
 * The quiet that ends a burst, and the wait before the one more read. A refresh publishes its `InstrumentUpdatedEvent`s
 * (`services/api/candleviewer/ingestion/instruments_refresh.py:709`) before it swaps in the snapshot `GET /instruments`
 * serves (:725); between the two come the risk-limit fetches (:723, a 15 s budget at :107) and the upsert (:724). A read
 * inside that lag can get the old list, which the index then keeps for an hour. 20 s clears the budget, with 5 s for the
 * upsert. (#4931's records ask for a debounce and name no value: this one is chosen, not measured.)
 */
export const REVISION_QUIET_MS = 20_000;

export interface RevisionReread {
  /** A snapshot whose reason is `instrument_revision` reached a consumer of the topic `channel`. */
  readonly note: (channel: string) => void;
  /** Drops the read that waits, and the wait for an answer. */
  readonly stop: () => void;
}

/** The symbol a topic names: `book.BTCUSDT.50`'s second part. A batched topic (`ticker`) names none: its symbols are options. */
const symbolOf = (channel: string): string | undefined => channel.split(".", 2)[1];

/** What the index holds of a symbol: a Trading row, a looked-up one with another status, or a cached 404. */
const holds = ({ entries, known, unlisted }: IndexSnapshot, symbol: string): boolean =>
  entries.some((e) => e.symbol === symbol) ||
  known.some((e) => e.symbol === symbol) ||
  unlisted.includes(symbol);

/**
 * Whether the list a read left in memory was fetched before the burst: the server calls it stale, or gives no age, or
 * fetched it (`loadedAt` less `cacheAgeS`) more than a quiet before the burst's first frame. A refresh fetches and then
 * publishes at once (`instruments_refresh.py:709`), so the burst's own list is fetched just before its first frame; the
 * one it replaces is far older (the schedule is 12 h, and on-demand fetches keep 60 s apart, :217).
 */
const predates = ({ loadedAt, cacheAgeS, staleSince }: IndexSnapshot, burstAt: number): boolean =>
  staleSince !== null ||
  cacheAgeS === null ||
  loadedAt === null ||
  loadedAt - cacheAgeS * 1000 < burstAt - REVISION_QUIET_MS;

/**
 * `running` is the index while it runs, else `null` (`useRunningIndex`'s source, CR-CD-01): a frame while it does not
 * starts nothing, and a read that waits is made on whichever index runs when its wait ends, if any.
 */
export function createRevisionReread(
  running: () => InstrumentIndex | null,
  clock: Clock = SYSTEM_CLOCK,
): RevisionReread {
  /** The quiet that ends a burst, or the wait before its one more read. */
  let waiting: unknown = null;
  /** When the burst's first frame came (the clock's ms): what the list a read leaves is judged against. */
  let burstAt = 0;
  /** Ends the wait for the answer to the burst's read. */
  let unwatch: (() => void) | null = null;
  /** The read that waits is the one more: it is made and not judged, so the chain ends there. */
  let again = false;

  const stop = (): void => {
    if (waiting !== null) clock.clearTimeout(waiting);
    waiting = null;
    unwatch?.();
    unwatch = null;
    again = false;
  };

  const wait = (): void => {
    waiting = clock.setTimeout(read, REVISION_QUIET_MS);
  };

  function read(): void {
    waiting = null;
    const index = running();
    const oneMore = again;
    again = false;
    if (index === null) return;
    if (oneMore) {
      index.reread(); // the one more: made, not judged
      return;
    }
    const before = index.getSnapshot().loadedAt;
    // The answer is the next list to land. Listening first: the index may tell before `reread` returns.
    unwatch = index.subscribe(() => {
      const snap = index.getSnapshot();
      if (snap.loadedAt === before) return; // a change that is no list: the read has not landed
      unwatch?.();
      unwatch = null;
      if (running() === index && predates(snap, burstAt)) {
        again = true;
        wait();
      }
    });
    index.reread();
  }

  return {
    note(channel) {
      const index = running();
      if (index === null) return;
      const symbol = symbolOf(channel);
      // A symbol the index holds nothing of is not its business: it neither starts a read nor moves one back.
      if (symbol !== undefined && !holds(index.getSnapshot(), symbol)) return;
      // A frame inside the quiet belongs to the burst; one that comes while a read awaits its answer, or its one more, starts the next.
      const first = waiting !== null && !again ? burstAt : clock.now();
      stop(); // a frame inside the quiet moves the read back: one read for the burst
      burstAt = first;
      wait();
    },
    stop,
  };
}

/**
 * E08-S09 (#4703): the symbol-search session's end of an `instrument_revision` (E08-D05 §3): `noteInstrumentRevision`
 * reads the index the session runs, once per burst, and never while it is only held (CR-CD-01); the session's stop and
 * a reset of the store take a read that waits with them. The burst's own rules are `revisionReread.test.ts`.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type * as Revisions from "../../../src/features/symbol-search/revisionReread";

// Every handle the session makes, in order, so that a test can see which one is told. The real factory still runs.
const { made } = vi.hoisted(() => ({ made: [] as Revisions.RevisionReread[] }));
vi.mock("../../../src/features/symbol-search/revisionReread", async (importOriginal) => {
  const actual = await importOriginal<typeof Revisions>();
  return {
    ...actual,
    createRevisionReread: (...args: Parameters<typeof actual.createRevisionReread>) => {
      const handle = actual.createRevisionReread(...args);
      made.push(handle);
      return handle;
    },
  };
});

import type {
  IndexSnapshot,
  InstrumentIndex,
} from "../../../src/features/symbol-search/instrumentIndex";
import { toEntry } from "../../../src/features/symbol-search/ranking";
import { REVISION_QUIET_MS } from "../../../src/features/symbol-search/revisionReread";
import {
  getSymbolSearchState,
  noteInstrumentRevision,
  resetSymbolSearch,
  setSymbolOpener,
  startSymbolSearch,
} from "../../../src/features/symbol-search/searchSession";
import { resetShellState, setShellState, type Me } from "../../../src/shell/bootstrap/store";

// Cast: only the presence of `/me`'s answer is read; the session starts the index once it has one.
const ME = { role: "owner", permissions: [], user: { username: "robin" } } as unknown as Me;
const READY: IndexSnapshot = {
  phase: "ready",
  entries: [
    toEntry({
      symbol: "BTCUSDT",
      category: "linear",
      status: "Trading",
      tick_size: "0.1",
      qty_step: "1",
    }),
  ],
  known: [],
  unlisted: [],
  loadedAt: 0,
  cacheAgeS: null,
  staleSince: null,
  refreshing: false,
  retryAt: null,
  failure: null,
};
const BOOK = "book.BTCUSDT.50";

function fakeIndex() {
  const fake = { start: vi.fn(), stop: vi.fn(), reread: vi.fn(), learn: vi.fn() };
  const index: InstrumentIndex = {
    ...fake,
    subscribe: () => () => undefined,
    getSnapshot: () => READY,
  };
  return { fake, index };
}
/** The session on a fake index, and the two things that start it: `/me` answered, a workspace's opener bound. */
function session() {
  const { fake, index } = fakeIndex();
  const end = startSymbolSearch(index);
  return {
    fake,
    end,
    run: (): void => {
      setShellState({ me: ME });
      setSymbolOpener({ target: null, open: vi.fn() });
    },
  };
}

beforeEach(() => {
  made.length = 0;
  vi.useFakeTimers();
});
afterEach(() => {
  resetSymbolSearch();
  resetShellState();
  vi.useRealTimers();
});

describe("noteInstrumentRevision", () => {
  it("reads the running index once for a burst, a quiet after its last frame", () => {
    const { fake, run } = session();
    run();
    expect(getSymbolSearchState().running).toBe(true);
    noteInstrumentRevision(BOOK);
    vi.advanceTimersByTime(300);
    noteInstrumentRevision("bars.BTCUSDT.time.1");
    vi.advanceTimersByTime(REVISION_QUIET_MS - 1);
    expect(fake.reread).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1);
    expect(fake.reread).toHaveBeenCalledTimes(1);
  });

  it("reads nothing while the index is held but not running: signed out, no opener (CR-CD-01)", () => {
    const { fake } = session(); // in the store from the start, started by neither `/me` nor an opener
    expect(getSymbolSearchState()).toMatchObject({ running: false });
    noteInstrumentRevision(BOOK);
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(10 * REVISION_QUIET_MS);
    expect(fake.reread).not.toHaveBeenCalled();
  });

  it("reads nothing while the index is held but not running: signed in, still no opener", () => {
    const { fake } = session();
    setShellState({ me: ME }); // signed in, and no workspace to show the list in
    expect(getSymbolSearchState()).toMatchObject({ running: false });
    noteInstrumentRevision(BOOK);
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(10 * REVISION_QUIET_MS);
    expect(fake.reread).not.toHaveBeenCalled();
  });

  it("reads nothing before a session has started: nobody to tell", () => {
    noteInstrumentRevision(BOOK);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("reads nothing after the session has ended", () => {
    const { fake, end, run } = session();
    run();
    end();
    noteInstrumentRevision(BOOK);
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(10 * REVISION_QUIET_MS);
    expect(fake.reread).not.toHaveBeenCalled();
  });

  it("is dropped with the session: its stop takes the read that waits, and no timer is left", () => {
    const { fake, end, run } = session();
    run();
    noteInstrumentRevision(BOOK);
    expect(vi.getTimerCount()).toBe(1);
    end();
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(10 * REVISION_QUIET_MS);
    expect(fake.reread).not.toHaveBeenCalled();
  });

  it("is dropped with a reset of the store, which tests use for the same end: the read that waits goes", () => {
    const { fake, run } = session();
    run();
    noteInstrumentRevision(BOOK);
    resetSymbolSearch();
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(10 * REVISION_QUIET_MS);
    expect(fake.reread).not.toHaveBeenCalled();
  });

  it("is dropped with a reset of the store: the stopped handle is let go, and nothing is told to it", () => {
    session();
    const stopped = made.at(-1);
    if (stopped === undefined) throw new Error("the session made no handle");
    resetSymbolSearch();
    const note = vi.spyOn(stopped, "note");
    noteInstrumentRevision(BOOK);
    expect(note).not.toHaveBeenCalled();
  });

  it("a session that replaced another is the one told: the earlier one's stop leaves it alone", () => {
    const first = session();
    const second = session(); // a second `startSymbolSearch` without the first having ended
    second.run();
    first.end(); // the stale stop of the shell this one replaced
    noteInstrumentRevision(BOOK);
    vi.advanceTimersByTime(REVISION_QUIET_MS);
    expect(second.fake.reread).toHaveBeenCalledTimes(1);
    expect(first.fake.reread).not.toHaveBeenCalled();
  });
});

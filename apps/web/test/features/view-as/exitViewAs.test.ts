import { afterEach, describe, expect, it, vi } from "vitest";
import {
  BACK_NOTE,
  BACK_NOTE_MAX_AGE_MS,
  EXIT_TIMEOUT_MS,
  EXIT_TO,
  exitViewAs,
  takeBackNote,
  takeExitRowFocus,
} from "../../../src/features/view-as/exitViewAs";
import {
  VIEW_AS_PATH,
  bootViewAs,
  resetViewAs,
  startViewAsSync,
} from "../../../src/lib/auth/viewAsContext";
import { ROUTE_MANIFEST } from "../../../src/routes/manifest";
import {
  resetShellState,
  setShellState,
  type HeldViewAs,
} from "../../../src/shell/bootstrap/store";

/**
 * E42-S03 (SCR-124 V-9, V-14; `22` `endViewAs`): Exit is one `DELETE` through `apiFetch` (no
 * step-up), then the sibling tabs hear it, this page's sync stops and the page loads SCR-121 in the
 * owner's own scope. A `503` changed nothing; no answer, or one that never comes, leaves it unknown:
 * the banner stays and Exit can be pressed again. An idle-locked session's `401` is SCR-005's to
 * unlock. The note carries the target's id across the load for SCR-121's row, never a name.
 */
const NOW = Date.parse("2026-09-14T10:20:00Z");
const ALEX = "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0002";
/** The page's context as the source keeps it: a target with a display name (`vetViewAs`). */
const HELD: HeldViewAs = {
  kind: "held",
  targetId: ALEX,
  targetName: "Alex Rivera",
  startedAtMs: NOW - 600_000,
  expiresAtMs: NOW + 1_200_000,
  state: "active",
  offsetMs: 0,
};
/** `endViewAs`'s `204`: the context ended, or none was held. */
const noContent = async (): Promise<Response> => new Response(null, { status: 204 });

function notes(): Pick<Storage, "getItem" | "setItem" | "removeItem"> & {
  all: Map<string, string>;
} {
  const all = new Map<string, string>();
  return {
    all,
    getItem: (key) => all.get(key) ?? null,
    setItem: (key, value) => void all.set(key, value),
    removeItem: (key) => void all.delete(key),
  };
}

afterEach(() => {
  takeExitRowFocus(); // the landing's slot is the module's: no test hands its id to the next
  resetViewAs();
  resetShellState();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  window.sessionStorage.clear();
});

describe("exitViewAs", () => {
  it("leaves: one DELETE, then the note, the broadcast, the sync's stop and the load of SCR-121", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
    const order: string[] = [];
    const store = notes();
    const send = vi.fn(async (input: string, init: RequestInit) => {
      order.push(`${init.method ?? "GET"} ${input}`);
      return new Response(null, { status: 204 });
    });
    const left = await exitViewAs({
      send,
      notes: {
        ...store,
        setItem: (key, value) => void (order.push("note"), store.setItem(key, value)),
      },
      broadcast: () => void order.push("broadcast"),
      stopSync: () => void order.push("stop"),
      navigate: (url) => void order.push(`navigate ${url}`),
    });
    expect(left).toBe("leaving");
    expect(order).toEqual([
      `DELETE ${VIEW_AS_PATH}`,
      "note",
      "broadcast",
      "stop",
      `navigate ${EXIT_TO}`,
    ]);
    expect([...store.all]).toEqual([[BACK_NOTE, String(NOW)]]); // a time, never a name
  });

  it("lands on R-301, SCR-121's route in the manifest", () => {
    expect(ROUTE_MANIFEST.find((route) => route.id === "R-301")?.path).toBe(EXIT_TO);
  });

  it("carries the target's id in the note beside the time, as held at the press: never in the URL", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
    setShellState({ viewAs: HELD });
    const store = notes();
    const navigate = vi.fn();
    const send = async (): Promise<Response> => {
      setShellState({ viewAs: { kind: "none" } }); // a re-read that lands during the DELETE
      return new Response(null, { status: 204 });
    };
    const left = await exitViewAs({ send, notes: store, navigate, broadcast: () => undefined });
    expect([left, [...store.all]]).toEqual(["leaving", [[BACK_NOTE, `${NOW}:${ALEX}`]]]);
    expect(navigate.mock.calls).toEqual([[EXIT_TO]]);
  });

  it("writes the time alone for a target id that is no UUID: a bad id never blocks Exit", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
    setShellState({ viewAs: { ...HELD, targetId: "not-a-uuid" } });
    const store = notes();
    const navigate = vi.fn();
    const left = await exitViewAs({
      send: noContent,
      notes: store,
      navigate,
      broadcast: () => undefined,
    });
    expect([left, [...store.all], navigate.mock.calls]).toEqual([
      "leaving",
      [[BACK_NOTE, String(NOW)]],
      [[EXIT_TO]],
    ]);
  });

  it("never writes the target's name: a user with a display name leaves digits and the id", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
    setShellState({ viewAs: HELD });
    const store = notes();
    await exitViewAs({
      send: noContent,
      notes: store,
      navigate: vi.fn(),
      broadcast: () => undefined,
    });
    const note = store.all.get(BACK_NOTE) ?? "";
    expect(note).not.toMatch(/alex|rivera/i);
    expect(note).toMatch(/^\d+:[0-9a-f-]{36}$/);
  });

  it.each<[string, () => Promise<Response>]>([
    ["a 503 (nothing changed)", async () => new Response(null, { status: 503 })],
    ["a 401", async () => new Response(null, { status: 401 })],
    ["no answer", async () => Promise.reject(new TypeError("Failed to fetch"))],
  ])("stays on %s: no note, no broadcast, no load (V-14)", async (_name, answer) => {
    const store = notes();
    const broadcast = vi.fn();
    const navigate = vi.fn();
    const left = await exitViewAs({ send: answer, notes: store, broadcast, navigate });
    expect([left, store.all.size, broadcast.mock.calls.length, navigate.mock.calls.length]).toEqual(
      ["failed", 0, 0, 0],
    );
  });

  it("gives up on an answer that never comes after EXIT_TIMEOUT_MS: V-14, and the call aborted", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    let signal: AbortSignal | null | undefined;
    const send = vi.fn(
      (_input: string, init: RequestInit) =>
        new Promise<Response>(() => {
          signal = init.signal; // it never settles: a transport that ignores the abort as well
        }),
    );
    const navigate = vi.fn();
    const done = exitViewAs({ send, navigate, broadcast: vi.fn() });
    let settled = false;
    void done.then(() => (settled = true));
    await vi.advanceTimersByTimeAsync(EXIT_TIMEOUT_MS - 1);
    expect([settled, signal?.aborted]).toEqual([false, false]);
    await vi.advanceTimersByTimeAsync(1);
    expect(await done).toBe("failed");
    expect([signal?.aborted, navigate.mock.calls.length, vi.getTimerCount()]).toEqual([true, 0, 0]);
    expect(EXIT_TIMEOUT_MS).toBe(10_000);
  });

  it("clears its timer once the server answers", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    const send = async (): Promise<Response> => new Response(null, { status: 503 });
    expect(await exitViewAs({ send })).toBe("failed");
    expect(vi.getTimerCount()).toBe(0);
  });

  it("hands an idle-locked session's 401 to SCR-005: nothing changed, and no V-14", async () => {
    const locked = async (): Promise<Response> =>
      new Response(JSON.stringify({ status: 401, code: "session_idle_locked" }), { status: 401 });
    const store = notes();
    const broadcast = vi.fn();
    const navigate = vi.fn();
    const left = await exitViewAs({ send: locked, notes: store, broadcast, navigate });
    expect([left, store.all.size, broadcast.mock.calls.length, navigate.mock.calls.length]).toEqual(
      ["locked", 0, 0, 0],
    );
  });

  it("sends through apiFetch, which the request guard passes even in the hold: one call, no step-up", async () => {
    const sent: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        sent.push(`${init?.method ?? "GET"} ${String(input)}`);
        return new Response(null, { status: 204 });
      }),
    );
    setShellState({
      viewAs: {
        kind: "held",
        targetId: "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0002",
        targetName: "alex",
        startedAtMs: 0,
        expiresAtMs: 1_800_000,
        state: "expired",
        offsetMs: 0,
      },
    });
    const navigate = vi.fn();
    expect(await exitViewAs({ navigate, broadcast: () => undefined })).toBe("leaving");
    expect(sent).toEqual([`DELETE ${VIEW_AS_PATH}`]);
    expect(navigate).toHaveBeenCalledWith(EXIT_TO);
    // the note lands in this tab's session storage, never in storage that outlives the tab
    expect(window.sessionStorage.getItem(BACK_NOTE)).toMatch(
      /^\d+:9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0002$/,
    );
    expect(window.localStorage.getItem(BACK_NOTE)).toBeNull();
  });

  it("leaves even where storage refuses the note", async () => {
    const navigate = vi.fn();
    const blocked = {
      ...notes(),
      setItem: () => {
        throw new DOMException("blocked", "SecurityError");
      },
    };
    const send = async (): Promise<Response> => new Response(null, { status: 204 });
    expect(await exitViewAs({ send, notes: blocked, navigate, broadcast: () => undefined })).toBe(
      "leaving",
    );
    expect(navigate).toHaveBeenCalledTimes(1);
  });

  it("never lets its own socket's close reload the page past its load (the sync stops first)", async () => {
    const context = {
      target_user_id: "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0002",
      target_username: "alex",
      target_display_name: null,
      started_at: "2026-09-14T10:00:00Z",
      expires_at: "2026-09-14T10:30:00Z",
      read_only: true,
      state: "active",
    };
    let reads = 0;
    const fetchImpl = vi.fn(async () => {
      reads += 1;
      return reads === 1
        ? new Response(JSON.stringify(context), { status: 200 })
        : new Response(null, { status: 204 });
    }) as unknown as typeof fetch; // the read's transport: only the answers matter here
    const reload = vi.fn();
    startViewAsSync({ fetchImpl, openChannel: () => null, reload });
    await bootViewAs({ fetchImpl });
    setShellState({ connection: { kind: "live" } });
    const navigate = vi.fn();
    const left = await exitViewAs({
      send: async () => new Response(null, { status: 204 }),
      navigate,
      notes: notes(),
      broadcast: () => undefined,
    });
    expect([left, navigate.mock.calls]).toEqual(["leaving", [[EXIT_TO]]]);
    // `endViewAs` ends every socket of the session (`bye view_as_changed`): this one leaves live
    setShellState({ connection: { kind: "reconnecting", attempt: 1, nextAttemptAtMs: 0 } });
    await new Promise((settled) => setTimeout(settled, 0));
    expect([reads, reload.mock.calls.length]).toEqual([1, 0]);
  });
});

describe("takeBackNote", () => {
  it("is true once after an Exit, then false", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
    const store = notes();
    store.setItem(BACK_NOTE, String(NOW - 2_000));
    expect([takeBackNote(store), takeBackNote(store)]).toEqual([true, false]);
    expect(store.all.size).toBe(0);
  });

  it("forgets a note older than BACK_NOTE_MAX_AGE_MS: a load that never mounted the shell is past", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
    const store = notes();
    store.setItem(BACK_NOTE, String(NOW - BACK_NOTE_MAX_AGE_MS - 1));
    expect(takeBackNote(store)).toBe(false);
    expect(store.all.size).toBe(0);
    store.setItem(BACK_NOTE, String(NOW - BACK_NOTE_MAX_AGE_MS));
    expect(takeBackNote(store)).toBe(true);
    expect(BACK_NOTE_MAX_AGE_MS).toBe(60_000);
  });

  it("is false with no note, another value, no storage or storage that throws", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
    const store = notes();
    expect(takeBackNote(store)).toBe(false);
    for (const value of ["alex", "1", `${NOW}x`, "", "Infinity"]) {
      store.setItem(BACK_NOTE, value);
      expect(takeBackNote(store), value).toBe(false);
    }
    expect(takeBackNote(null)).toBe(false);
    const throwing = {
      ...notes(),
      getItem: () => {
        throw new DOMException("blocked", "SecurityError");
      },
    };
    expect(takeBackNote(throwing)).toBe(false);
  });

  it("reads the session's storage by default", () => {
    window.sessionStorage.setItem(BACK_NOTE, String(Date.now()));
    expect(takeBackNote()).toBe(true);
    expect(window.sessionStorage.getItem(BACK_NOTE)).toBeNull();
  });
});

describe("takeExitRowFocus (V-9's landing on the target's row, SCR-121's in part 5)", () => {
  it("answers the note's target id once: the second take is null", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
    const store = notes();
    store.setItem(BACK_NOTE, `${NOW - 2_000}:${ALEX}`);
    expect(takeBackNote(store)).toBe(true);
    expect([takeExitRowFocus(), takeExitRowFocus()]).toEqual([ALEX, null]);
  });

  it("keeps nothing from a stale note: no va.back and no row", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
    const store = notes();
    store.setItem(BACK_NOTE, `${NOW - BACK_NOTE_MAX_AGE_MS - 1}:${ALEX}`);
    expect([takeBackNote(store), takeExitRowFocus(), store.all.size]).toEqual([false, null, 0]);
  });

  it("keeps nothing from a malformed id, a time alone or no storage", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
    const store = notes();
    for (const value of [`${NOW}:not-a-uuid`, `${NOW}:`, `${NOW}:${ALEX}:${ALEX}`, ALEX]) {
      store.setItem(BACK_NOTE, value);
      expect([takeBackNote(store), takeExitRowFocus()], value).toEqual([false, null]);
    }
    store.setItem(BACK_NOTE, String(NOW));
    expect([takeBackNote(store), takeExitRowFocus()]).toEqual([true, null]);
    expect([takeBackNote(null), takeExitRowFocus()]).toEqual([false, null]);
  });
});

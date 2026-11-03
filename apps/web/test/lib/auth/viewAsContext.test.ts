import { readFileSync, readdirSync } from "node:fs";
import { join, resolve, sep } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  MAX_REREAD_DELAY_MS,
  MIN_REREAD_DELAY_MS,
  VIEW_AS_CHANGED,
  VIEW_AS_PATH,
  VIEW_AS_READ_TIMEOUT_MS,
  ViewAsUnreadableError,
  announceChange,
  bootViewAs,
  getViewAs,
  isViewing,
  readViewAs,
  resetViewAs,
  startViewAsSync,
  stopViewAsSync,
  subscribeViewAs,
  vetViewAs,
  viewAsTargetName,
  type ViewAsChannel,
} from "../../../src/lib/auth/viewAsContext";
import { HttpError, HttpTimeoutError } from "../../../src/shell/bootstrap/httpClient";
import {
  getShellState,
  resetShellState,
  setShellState,
  subscribeShellState,
  type HeldViewAs,
} from "../../../src/shell/bootstrap/store";

/**
 * E42-S03 (SCR-124): the one view-as source. `GET /auth/session/view-as` (`22` `getViewAs`) is read
 * at boot and again on a sibling's broadcast, at `expires_at` on the server's clock and when the
 * socket leaves live; only a full reload changes the page's scope. A read that fails is never "no
 * context".
 */
const ALEX = "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0002";
const BEA = "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0003";
const CONTEXT = {
  target_user_id: ALEX,
  target_username: "alex",
  target_display_name: "Alex M.",
  started_at: "2026-09-14T10:00:00Z",
  expires_at: "2026-09-14T10:30:00Z",
  read_only: true,
  state: "active",
};
const STARTED = Date.parse(CONTEXT.started_at);
const EXPIRES = Date.parse(CONTEXT.expires_at);

const none = (): Response => new Response(null, { status: 204 });
const held = (body: object = CONTEXT, date?: string): Response =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json", ...(date === undefined ? {} : { date }) },
  });
const problem = (status: number, code: string): Response =>
  new Response(JSON.stringify({ status, code }), { status });

/** A fetch that answers each view-as read from `answers` in turn (the last one repeats). */
function server(...answers: (() => Response | Promise<Response>)[]) {
  const calls: string[] = [];
  const fetchImpl = vi.fn(async (input: RequestInfo | URL) => {
    calls.push(String(input));
    const answer = answers[Math.min(calls.length, answers.length) - 1] ?? none;
    return answer();
  });
  return { fetchImpl: fetchImpl as unknown as typeof fetch, calls };
}

function fakeChannel() {
  const posted: unknown[] = [];
  const channel: ViewAsChannel & { closed: boolean } = {
    onmessage: null,
    postMessage: (message) => void posted.push(message),
    close: () => void (channel.closed = true),
    closed: false,
  };
  const deliver = (data: unknown): void => channel.onmessage?.({ data } as MessageEvent<unknown>);
  return { channel, posted, deliver };
}

const flush = async (): Promise<void> => {
  for (let i = 0; i < 10; i += 1) await Promise.resolve();
};

beforeEach(() => resetShellState());
afterEach(() => {
  resetViewAs();
  resetShellState();
  vi.useRealTimers();
});

describe("readViewAs: the server's answer, never a default", () => {
  it("reads 204 as no context, with the tab's bearer path and no body", async () => {
    const { fetchImpl, calls } = server(none);
    expect(await readViewAs({ fetchImpl })).toEqual({ ok: true, state: { kind: "none" } });
    expect(calls).toEqual([VIEW_AS_PATH]);
  });

  it("reads a live context: the target's display name, its times, and the server clock's offset", async () => {
    const date = "Mon, 14 Sep 2026 10:02:20 GMT";
    const receivedAt = Date.parse("2026-09-14T10:02:23.500Z"); // the client clock runs 3.5 s ahead
    const { fetchImpl } = server(() => held(CONTEXT, date));
    const read = await readViewAs({ fetchImpl, now: () => receivedAt });
    expect(read).toEqual({
      ok: true,
      state: {
        kind: "held",
        targetId: ALEX,
        targetName: "Alex M.",
        startedAtMs: STARTED,
        expiresAtMs: EXPIRES,
        state: "active",
        offsetMs: -3_500,
      },
    });
  });

  it("reads a held context, and an answer with no Date header as no offset", async () => {
    const { fetchImpl } = server(() => held({ ...CONTEXT, state: "expired" }));
    const read = await readViewAs({ fetchImpl });
    expect(read).toMatchObject({ ok: true, state: { state: "expired", offsetMs: 0 } });
  });

  it.each([
    ["a null display name", null],
    ["an empty display name", " "],
  ])("names the target by its username for %s", async (_name, display) => {
    const { fetchImpl } = server(() => held({ ...CONTEXT, target_display_name: display }));
    expect(await readViewAs({ fetchImpl })).toMatchObject({ state: { targetName: "alex" } });
  });

  it.each<[string, Response]>([
    ["an empty object", held({})],
    ["an unknown state", held({ ...CONTEXT, state: "paused" })],
    ["a context that is not read-only", held({ ...CONTEXT, read_only: false })],
    ["a target id that is no UUID", held({ ...CONTEXT, target_user_id: "alex" })],
    ["no display name member", held({ ...CONTEXT, target_display_name: undefined })],
    ["an unreadable time", held({ ...CONTEXT, expires_at: "soon" })],
    ["the SPA's index.html", new Response("<!doctype html><html></html>", { status: 200 })],
  ])("fails on a 200 with %s, never reading it as no context", async (_name, answer) => {
    const { fetchImpl } = server(() => answer);
    const read = await readViewAs({ fetchImpl });
    expect(read.ok).toBe(false);
    if (!read.ok) expect(read.error).toBeInstanceOf(ViewAsUnreadableError);
  });

  it.each<[string, Response, number, string | undefined]>([
    ["a 503", problem(503, "store_unavailable"), 503, "store_unavailable"],
    ["a 403", problem(403, "mfa_enrollment_required"), 403, "mfa_enrollment_required"],
    ["a 404 (vite preview, no stub)", new Response("Not Found", { status: 404 }), 404, undefined],
    ["a 202", new Response(null, { status: 202 }), 202, undefined],
  ])("fails on %s with its status and problem code", async (_name, answer, status, code) => {
    const { fetchImpl } = server(() => answer);
    const read = await readViewAs({ fetchImpl });
    expect(read.ok).toBe(false);
    if (!read.ok) {
      expect(read.error).toBeInstanceOf(HttpError);
      expect(read.error).toMatchObject({ status, code });
    }
  });

  it("fails on a network error", async () => {
    const fetchImpl = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });
    const read = await readViewAs({ fetchImpl });
    expect(read).toEqual({ ok: false, error: new TypeError("Failed to fetch") });
  });

  it("fails as a timeout once VIEW_AS_READ_TIMEOUT_MS pass unanswered", async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn(
      (_input: RequestInfo | URL, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) =>
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError")),
          ),
        ),
    );
    const reading = readViewAs({ fetchImpl });
    await vi.advanceTimersByTimeAsync(VIEW_AS_READ_TIMEOUT_MS - 1);
    let settled = false;
    void reading.then(() => (settled = true));
    await flush();
    expect(settled).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    const read = await reading;
    expect(read.ok).toBe(false);
    if (!read.ok) expect(read.error).toBeInstanceOf(HttpTimeoutError);
  });
});

describe("vetViewAs", () => {
  it("keeps only the members the shell reads", () => {
    const vetted = vetViewAs({ ...CONTEXT, reason: "never here", extra: 1 }, 0);
    expect(vetted).not.toBeNull();
    expect(Object.keys(vetted ?? {}).sort()).toEqual(
      ["expiresAtMs", "kind", "offsetMs", "startedAtMs", "state", "targetId", "targetName"].sort(),
    );
    expect(JSON.stringify(vetted)).not.toContain("never here");
  });

  it.each([null, "context", 42, []])("reads %j as no context at all (null)", (body) => {
    expect(vetViewAs(body, 0)).toBeNull();
  });
});

/** The text of the call whose `(` is at `open`: up to its balanced `)`. */
function callText(text: string, open: number): string {
  let depth = 0;
  for (let i = open; i < text.length; i += 1) {
    if (text[i] === "(") depth += 1;
    if (text[i] === ")") depth -= 1;
    if (depth === 0) return text.slice(open, i + 1);
  }
  return text.slice(open);
}

describe("the shell store's view-as context has one writer", () => {
  it("no src module but this one passes `viewAs` to setShellState, so the guard keys on server truth", () => {
    const src = resolve(import.meta.dirname, "../../../src");
    const writers = readdirSync(src, { recursive: true, encoding: "utf8" }).filter((file) => {
      if (!/\.tsx?$/.test(file)) return false;
      const text = readFileSync(join(src, file), "utf8");
      // `viewAs` as a key of the state passed (`{ viewAs: … }`, `{ viewAs }`), never a value read
      return [...text.matchAll(/\bsetShellState\s*\(/g)].some(({ index }) =>
        /[{,]\s*viewAs\s*[:,}]/.test(callText(text, text.indexOf("(", index))),
      );
    });
    expect(writers.map((file) => file.split(sep).join("/"))).toEqual(["lib/auth/viewAsContext.ts"]);
  });
});

describe("bootViewAs: the page's context", () => {
  it("puts a 204 in the store as none", async () => {
    expect(getViewAs()).toEqual({ kind: "unknown" });
    await bootViewAs(server(none));
    expect(getViewAs()).toEqual({ kind: "none" });
    expect([isViewing(), viewAsTargetName()]).toEqual([false, null]);
  });

  it("puts a held context in the store, with its target's name", async () => {
    await bootViewAs(server(() => held()));
    expect(getViewAs()).toMatchObject({ kind: "held", targetName: "Alex M.", state: "active" });
    expect([isViewing(), viewAsTargetName()]).toEqual([true, "Alex M."]);
  });

  it("leaves the store unknown on a failure (the bootstrap fails closed on it)", async () => {
    const read = await bootViewAs(server(() => problem(503, "store_unavailable")));
    expect(read.ok).toBe(false);
    expect(getViewAs()).toEqual({ kind: "unknown" });
  });
});

describe("startViewAsSync: the re-reads", () => {
  function started(...answers: (() => Response | Promise<Response>)[]) {
    const api = server(...answers);
    const { channel, posted, deliver } = fakeChannel();
    const reload = vi.fn();
    const stop = startViewAsSync({ fetchImpl: api.fetchImpl, openChannel: () => channel, reload });
    return { ...api, channel, posted, deliver, reload, stop };
  }

  it("does nothing before the boot read answered", async () => {
    const s = started(none);
    s.deliver(VIEW_AS_CHANGED);
    setShellState({ connection: { kind: "offline", cause: "backend_unreachable" } });
    await flush();
    expect(s.calls).toEqual([]);
  });

  it("re-reads on a sibling's broadcast, and ignores any other message", async () => {
    const s = started(none, none);
    await bootViewAs({ fetchImpl: s.fetchImpl });
    s.deliver("something else");
    s.deliver({ changed: true });
    await flush();
    expect(s.calls).toHaveLength(1);
    s.deliver(VIEW_AS_CHANGED);
    await flush();
    expect(s.calls).toHaveLength(2);
    expect(s.reload).not.toHaveBeenCalled(); // the same scope: none
  });

  it("reloads once into a context a sibling started (none to held)", async () => {
    const s = started(none, () => held());
    await bootViewAs({ fetchImpl: s.fetchImpl });
    s.deliver(VIEW_AS_CHANGED);
    await vi.waitFor(() => expect(s.reload).toHaveBeenCalledTimes(1));
    expect(getViewAs()).toMatchObject({ kind: "held", targetId: ALEX });
  });

  it.each<[string, () => Response]>([
    ["an exit (held to none)", none],
    ["another target", () => held({ ...CONTEXT, target_user_id: BEA })],
    [
      "another start for the same target",
      () => held({ ...CONTEXT, started_at: "2026-09-14T11:00:00Z" }),
    ],
  ])("reloads on %s", async (_name, next) => {
    const s = started(() => held(), next);
    await bootViewAs({ fetchImpl: s.fetchImpl });
    s.deliver(VIEW_AS_CHANGED);
    await vi.waitFor(() => expect(s.reload).toHaveBeenCalledTimes(1));
  });

  it("updates a context the server ended in place: the data stays, no reload (V-8)", async () => {
    const s = started(
      () => held(),
      () => held({ ...CONTEXT, state: "expired" }),
    );
    await bootViewAs({ fetchImpl: s.fetchImpl });
    s.deliver(VIEW_AS_CHANGED);
    await vi.waitFor(() => expect(getViewAs()).toMatchObject({ state: "expired" }));
    expect(s.reload).not.toHaveBeenCalled();
  });

  it("keeps the context when a re-read fails, and reloads nothing", async () => {
    const s = started(
      () => held(),
      () => problem(503, "store_unavailable"),
    );
    await bootViewAs({ fetchImpl: s.fetchImpl });
    const before = getViewAs();
    s.deliver(VIEW_AS_CHANGED);
    await vi.waitFor(() => expect(s.calls).toHaveLength(2));
    await flush();
    expect(getViewAs()).toBe(before);
    expect(s.reload).not.toHaveBeenCalled();
  });

  it("re-reads when the socket leaves live or goes offline, never on reaching live", async () => {
    const s = started(none);
    await bootViewAs({ fetchImpl: s.fetchImpl });
    setShellState({ connection: { kind: "live" } });
    setShellState({ latency: getShellState().latency }); // another change of the store
    await flush();
    expect(s.calls).toHaveLength(1);
    setShellState({ connection: { kind: "reconnecting", attempt: 1, nextAttemptAtMs: 0 } });
    await vi.waitFor(() => expect(s.calls).toHaveLength(2));
    setShellState({ connection: { kind: "connecting" } });
    await flush();
    expect(s.calls).toHaveLength(2);
    // the hold refuses the socket's `auth` (`4403`): it never reaches live
    setShellState({ connection: { kind: "offline", cause: "backend_unreachable" } });
    await vi.waitFor(() => expect(s.calls).toHaveLength(3));
  });

  it("folds the triggers that arrive during a read into one more read", async () => {
    let answer!: (res: Response) => void;
    const slow = (): Promise<Response> =>
      new Promise((resolve) => {
        answer = resolve;
      });
    const s = started(none, slow, none);
    await bootViewAs({ fetchImpl: s.fetchImpl });
    s.deliver(VIEW_AS_CHANGED);
    await flush();
    s.deliver(VIEW_AS_CHANGED);
    s.deliver(VIEW_AS_CHANGED);
    setShellState({ connection: { kind: "offline", cause: "backend_unreachable" } });
    await flush();
    expect(s.calls).toHaveLength(2); // the boot read and the one in flight
    answer(none());
    await vi.waitFor(() => expect(s.calls).toHaveLength(3));
    await flush();
    expect(s.calls).toHaveLength(3);
  });

  it("re-reads at expires_at on the server's clock, never sooner than MIN_REREAD_DELAY_MS", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    // the server's clock is 10:29:50 when the client's reads 10:29:55: 10 s left on the server's
    vi.setSystemTime(Date.parse("2026-09-14T10:29:55Z"));
    const s = started(
      () => held(CONTEXT, "Mon, 14 Sep 2026 10:29:50 GMT"),
      () => held({ ...CONTEXT, state: "expired" }),
    );
    await bootViewAs({ fetchImpl: s.fetchImpl });
    expect(getViewAs()).toMatchObject({ offsetMs: -5_000 });
    await vi.advanceTimersByTimeAsync(9_999);
    expect(s.calls).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(s.calls).toHaveLength(2);
    await flush();
    expect(getViewAs()).toMatchObject({ state: "expired" });
    await vi.advanceTimersByTimeAsync(60_000);
    expect(s.calls).toHaveLength(2); // an ended context has no countdown to re-read on
    expect(MIN_REREAD_DELAY_MS).toBe(1_000);
  });

  it("backs the expiry re-read off while the server still says live: 1 s, 2 s, 4 s … 30 s at most", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    vi.setSystemTime(EXPIRES + 5_000); // past expires_at on this clock already
    const s = started(() => held()); // a server that keeps answering live past its own expiry
    await bootViewAs({ fetchImpl: s.fetchImpl });
    const waits = [1_000, 2_000, 4_000, 8_000, 16_000, 30_000, 30_000];
    for (const [n, wait] of waits.entries()) {
      await vi.advanceTimersByTimeAsync(wait - 1);
      expect(s.calls, `read ${n + 2} not before ${wait} ms`).toHaveLength(n + 1);
      await vi.advanceTimersByTimeAsync(1);
      expect(s.calls, `read ${n + 2} at ${wait} ms`).toHaveLength(n + 2);
    }
    expect([MIN_REREAD_DELAY_MS, MAX_REREAD_DELAY_MS]).toEqual([1_000, 30_000]);
  });

  it("ends the back-off once the server says the context ended", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    vi.setSystemTime(EXPIRES + 5_000);
    const s = started(
      () => held(),
      () => held(),
      () => held({ ...CONTEXT, state: "expired" }),
    );
    await bootViewAs({ fetchImpl: s.fetchImpl });
    await vi.advanceTimersByTimeAsync(MIN_REREAD_DELAY_MS + 2 * MIN_REREAD_DELAY_MS);
    expect(s.calls).toHaveLength(3);
    await flush();
    expect(getViewAs()).toMatchObject({ state: "expired" });
    await vi.advanceTimersByTimeAsync(5 * MAX_REREAD_DELAY_MS);
    expect(s.calls).toHaveLength(3); // an ended context has no countdown to re-read on
  });

  it("stops: no listener, no timer, the channel closed", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    vi.setSystemTime(STARTED);
    const s = started(() => held());
    await bootViewAs({ fetchImpl: s.fetchImpl });
    s.stop();
    expect([s.channel.onmessage, s.channel.closed]).toEqual([null, true]);
    setShellState({ connection: { kind: "offline", cause: "backend_unreachable" } });
    await vi.advanceTimersByTimeAsync(EXPIRES - STARTED + 5_000);
    expect(s.calls).toHaveLength(1);
  });

  it("leaves no timer behind: none once a read settled, none once the sync stopped", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "Date"] });
    vi.setSystemTime(STARTED);
    await readViewAs(server(() => held()));
    expect(vi.getTimerCount(), "the read's own timeout").toBe(0);
    const s = started(() => held());
    await bootViewAs({ fetchImpl: s.fetchImpl });
    expect(vi.getTimerCount(), "the expiry re-read, armed").toBe(1);
    s.stop();
    expect(vi.getTimerCount(), "the expiry re-read, once stopped").toBe(0);
  });

  it("lets go of its store listener when it stops", async () => {
    const shell = await import("../../../src/shell/bootstrap/store");
    const subscribe = shell.subscribeShellState;
    const offs: (() => void)[] = [];
    const spy = vi.spyOn(shell, "subscribeShellState").mockImplementation((listener) => {
      const off = vi.fn(subscribe(listener));
      offs.push(off);
      return off;
    });
    try {
      const stop = startViewAsSync({ openChannel: () => null });
      expect(offs).toHaveLength(1);
      stop();
      expect(offs[0]).toHaveBeenCalledTimes(1);
    } finally {
      spy.mockRestore();
    }
  });

  it("changes nothing with a read that lands after it stopped", async () => {
    let answer!: (res: Response) => void;
    const slow = (): Promise<Response> =>
      new Promise((resolve) => {
        answer = resolve;
      });
    const s = started(none, slow);
    await bootViewAs({ fetchImpl: s.fetchImpl });
    s.deliver(VIEW_AS_CHANGED);
    await vi.waitFor(() => expect(s.calls).toHaveLength(2));
    s.stop();
    // another scope: had it been applied, the page would reload. Its body read is the last await
    // before the source decides, so a task after it the decision is made
    const late = held();
    const body = late.json.bind(late);
    let landed!: () => void;
    const read = new Promise<void>((resolve) => (landed = resolve));
    late.json = async () => {
      const parsed: unknown = await body();
      setTimeout(landed, 0);
      return parsed;
    };
    answer(late);
    await read;
    expect(getViewAs()).toEqual({ kind: "none" });
    expect(s.reload).not.toHaveBeenCalled();
  });

  it("stops for good once the page leaves on its own (stopViewAsSync): nothing reads or reloads", async () => {
    const s = started(() => held(), none);
    await bootViewAs({ fetchImpl: s.fetchImpl });
    announceChange(); // Exit's broadcast goes out first
    stopViewAsSync();
    expect(s.posted).toEqual([VIEW_AS_CHANGED]);
    expect([s.channel.onmessage, s.channel.closed]).toEqual([null, true]);
    // Exit's DELETE ends the session's sockets (`bye view_as_changed`): this one leaves live
    setShellState({ connection: { kind: "live" } });
    setShellState({ connection: { kind: "reconnecting", attempt: 1, nextAttemptAtMs: 0 } });
    s.deliver(VIEW_AS_CHANGED);
    await flush();
    expect(s.calls).toHaveLength(1);
    expect(s.reload).not.toHaveBeenCalled();
    s.stop(); // startShell's own teardown after it: a second stop is a no-op
    expect(() => stopViewAsSync()).not.toThrow();
  });

  it("reloads once, however many triggers find the new scope before the page goes", async () => {
    const s = started(none, () => held());
    await bootViewAs({ fetchImpl: s.fetchImpl });
    s.deliver(VIEW_AS_CHANGED);
    await vi.waitFor(() => expect(s.reload).toHaveBeenCalledTimes(1));
    s.deliver(VIEW_AS_CHANGED);
    setShellState({ connection: { kind: "offline", cause: "backend_unreachable" } });
    await flush();
    expect(s.reload).toHaveBeenCalledTimes(1);
    expect(s.calls).toHaveLength(2);
  });

  it("goes on re-reading after a store listener throws during one: the latch is let go", async () => {
    const s = started(() => held());
    await bootViewAs({ fetchImpl: s.fetchImpl });
    const boot = getViewAs();
    let armed = true;
    const off = subscribeShellState(() => {
      if (!armed || getShellState().viewAs === boot) return;
      armed = false; // throws once, on the store write of the re-read's answer
      throw new Error("a store listener threw");
    });
    const unhandled = vi.fn();
    process.on("unhandledRejection", unhandled);
    try {
      setShellState({ connection: { kind: "live" } });
      setShellState({ connection: { kind: "reconnecting", attempt: 1, nextAttemptAtMs: 0 } });
      await vi.waitFor(() => expect(s.calls).toHaveLength(2));
      await flush();
      setShellState({ connection: { kind: "live" } });
      setShellState({ connection: { kind: "reconnecting", attempt: 2, nextAttemptAtMs: 0 } });
      await vi.waitFor(() => expect(s.calls).toHaveLength(3));
      await new Promise((settled) => setTimeout(settled, 0));
      expect(armed).toBe(false);
      expect(unhandled).not.toHaveBeenCalled();
    } finally {
      process.off("unhandledRejection", unhandled);
      off();
    }
  });

  it("starts once: a second start keeps the first", () => {
    const first = startViewAsSync({ openChannel: () => null });
    expect(startViewAsSync({ openChannel: () => null })).toBe(first);
  });
});

describe("announceChange", () => {
  it("posts `changed` and nothing else to the sibling tabs", () => {
    const { channel, posted } = fakeChannel();
    startViewAsSync({ openChannel: () => channel });
    announceChange();
    expect(posted).toEqual([VIEW_AS_CHANGED]);
    expect(VIEW_AS_CHANGED).toBe("changed");
  });

  it("is a no-op where no channel exists", () => {
    startViewAsSync({ openChannel: () => null });
    expect(() => announceChange()).not.toThrow();
  });
});

describe("subscribeViewAs", () => {
  it("calls back on a change of the context only, until unsubscribed", () => {
    const seen = vi.fn();
    const off = subscribeViewAs(seen);
    setShellState({ connection: { kind: "live" } });
    expect(seen).not.toHaveBeenCalled();
    const context: HeldViewAs = {
      kind: "held",
      targetId: ALEX,
      targetName: "alex",
      startedAtMs: STARTED,
      expiresAtMs: EXPIRES,
      state: "active",
      offsetMs: 0,
    };
    setShellState({ viewAs: context });
    expect(seen).toHaveBeenCalledTimes(1);
    off();
    setShellState({ viewAs: { kind: "none" } });
    expect(seen).toHaveBeenCalledTimes(1);
  });
});

describe("startViewAsSync: a server's view-as refusal re-reads (the request guard's seam)", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("re-reads once apiFetch sees a 403 view_as_read_only, and follows a context another tab started", async () => {
    const api = server(none, () => held());
    const reload = vi.fn();
    startViewAsSync({ fetchImpl: api.fetchImpl, openChannel: () => null, reload });
    await bootViewAs({ fetchImpl: api.fetchImpl });
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify({ status: 403, code: "view_as_read_only" }), { status: 403 }),
      ),
    );
    const { apiFetch } = await import("../../../src/lib/http/csrfFetch");
    await apiFetch("/api/v1/settings", { method: "PUT", body: "{}" });
    await vi.waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
    expect(api.calls).toHaveLength(2);
  });

  it("lets go of its refusal listener when it stops", async () => {
    const guard = await import("../../../src/lib/http/viewAsGuard");
    const listen = guard.onServerRefusal;
    const offs: (() => void)[] = [];
    const spy = vi.spyOn(guard, "onServerRefusal").mockImplementation((listener) => {
      const off = vi.fn(listen(listener));
      offs.push(off);
      return off;
    });
    try {
      const stop = startViewAsSync({ openChannel: () => null });
      expect(offs).toHaveLength(1);
      stop();
      expect(offs[0]).toHaveBeenCalledTimes(1);
    } finally {
      spy.mockRestore();
    }
  });
});

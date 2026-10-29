// E10-S04 (#306) slice 9: the SCR-159 liveness probe (`14` SCR-159 Performance; the ticket's
// "Tailnet unreachable is named precisely"). Fake clock, no sleeps: every wait is a timer advance.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  CONFIRM_TIMEOUT_MS,
  LIVENESS_INTERVAL_MS,
  LIVENESS_TIMEOUT_MS,
  LIVENESS_URL,
  markReachable,
  probeLivenessNow,
  startLiveness,
} from "../../../src/shell/bootstrap/liveness.js";
import {
  REACHABILITY_WINDOW_MS,
  REACHABLE,
  type Reachability,
} from "../../../src/shell/bootstrap/reachability.js";
import { THEME_ANALYTICS_EVENT } from "../../../src/shell/bootstrap/themeStore.js";
import { getShellState, resetShellState } from "../../../src/shell/bootstrap/store.js";
import { startShell } from "../../../src/shell/startShell.js";
import { accessToken } from "../../../src/lib/auth/accessToken.js";
import { INITIAL_WS_STATE } from "../../../src/lib/ws/state/reducer.js";
import { FakePort } from "../../lib/ws/support/fakePort";

const T0 = Date.UTC(2026, 9, 28, 14, 0, 0);
/** A route that drops packets: the request never settles until its signal aborts. */
const hanging = (_url: RequestInfo | URL, init?: RequestInit): Promise<Response> =>
  new Promise((_resolve, reject) =>
    init?.signal?.addEventListener("abort", () =>
      reject(new DOMException("aborted", "AbortError")),
    ),
  );
const refused = async (): Promise<Response> => {
  throw new TypeError("Failed to fetch");
};
const answer =
  (status = 200) =>
  async (): Promise<Response> =>
    new Response(null, { status });

let seen: Reachability[];
/** The verdicts, without the "a probe is running" updates in between. */
const settled = (): Reachability[] => seen.filter((s) => !s.probing);
let stop: (() => void) | undefined;
function start(fetchImpl: typeof fetch) {
  const liveness = startLiveness({ onChange: (r) => seen.push(r), fetchImpl, random: () => 0.5 });
  stop = liveness.stop;
  return liveness;
}
const onLine = (value: boolean) => vi.spyOn(navigator, "onLine", "get").mockReturnValue(value);

beforeEach(() => {
  seen = [];
  vi.useFakeTimers();
  vi.setSystemTime(T0);
});
afterEach(() => {
  stop?.();
  stop = undefined;
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("SCR-159 liveness probe", () => {
  it("probes 22's unauthenticated GET /health/live, without credentials, once per interval", async () => {
    const fetchImpl = vi.fn<typeof fetch>(answer());
    start(fetchImpl);
    expect(fetchImpl).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(LIVENESS_INTERVAL_MS);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
    expect(fetchImpl.mock.calls[0]?.[0]).toBe("/api/v1/health/live");
    expect(LIVENESS_URL).toBe("/api/v1/health/live");
    expect(fetchImpl.mock.calls[0]?.[1]).toMatchObject({ credentials: "omit", cache: "no-store" });
    await vi.advanceTimersByTimeAsync(LIVENESS_INTERVAL_MS);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(seen).toEqual([]); // reachable all along: nothing to show
  });

  it("names an online-but-unreachable backend tailnet_unreachable within 5 s (the AC)", async () => {
    onLine(true);
    start(vi.fn<typeof fetch>(hanging));
    expect(LIVENESS_INTERVAL_MS + LIVENESS_TIMEOUT_MS).toBeLessThanOrEqual(REACHABILITY_WINDOW_MS);
    await vi.advanceTimersByTimeAsync(REACHABILITY_WINDOW_MS);
    expect(seen.at(-1)).toMatchObject({ reachable: false, cause: "tailnet_unreachable" });
  });

  it("names it within 5 s of the loss after a healthy probe, the worst case", async () => {
    onLine(true);
    const fetchImpl = vi.fn<typeof fetch>(answer());
    start(fetchImpl);
    await vi.advanceTimersByTimeAsync(LIVENESS_INTERVAL_MS); // answered: the backend is lost now
    fetchImpl.mockImplementation(hanging);
    await vi.advanceTimersByTimeAsync(REACHABILITY_WINDOW_MS - 1);
    expect(seen.at(-1)).toMatchObject({ reachable: false, cause: "tailnet_unreachable" });
  });

  it("never declares offline on navigator.onLine alone: the offline event only probes at once", async () => {
    onLine(false);
    const fetchImpl = vi.fn<typeof fetch>(answer());
    start(fetchImpl);
    window.dispatchEvent(new Event("offline"));
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchImpl).toHaveBeenCalledTimes(1); // no wait for the interval
    expect(seen).toEqual([]); // the backend answered, so it is reachable
  });

  it("names a fast failure then a timeout within 5 s too, in the worst jitter", async () => {
    onLine(true);
    const fetchImpl = vi.fn<typeof fetch>(answer());
    const liveness = startLiveness({ onChange: (r) => seen.push(r), fetchImpl, random: () => 1 });
    stop = liveness.stop;
    await vi.advanceTimersByTimeAsync(LIVENESS_INTERVAL_MS); // answered: the backend is lost now
    fetchImpl.mockImplementationOnce(refused).mockImplementation(hanging);
    const rowOneLatest = 500 + 250; // 23 §9.2 row 1 with the most jitter
    expect(LIVENESS_INTERVAL_MS + rowOneLatest + CONFIRM_TIMEOUT_MS).toBeLessThanOrEqual(
      REACHABILITY_WINDOW_MS,
    );
    await vi.advanceTimersByTimeAsync(REACHABILITY_WINDOW_MS);
    expect(seen.at(-1)).toMatchObject({ reachable: false, cause: "tailnet_unreachable" });
  });

  it("classifies requests that fail while the browser is offline as offline", async () => {
    onLine(false);
    start(vi.fn<typeof fetch>(refused));
    await vi.advanceTimersByTimeAsync(LIVENESS_INTERVAL_MS + 500);
    expect(seen).toEqual([
      { reachable: false, cause: "offline", retryAtMs: expect.any(Number), probing: false },
    ]);
  });

  it("confirms a fast failure before declaring: a refusal, then an answer, shows and says nothing", async () => {
    const events: unknown[] = [];
    const listen = (e: Event) => events.push((e as CustomEvent).detail);
    window.addEventListener(THEME_ANALYTICS_EVENT, listen);
    try {
      const fetchImpl = vi.fn<typeof fetch>(refused);
      start(fetchImpl);
      await vi.advanceTimersByTimeAsync(LIVENESS_INTERVAL_MS); // refused: not a verdict yet
      fetchImpl.mockImplementation(answer());
      await vi.advanceTimersByTimeAsync(500); // 23 §9.2 row 1: the confirmation answers
      expect(fetchImpl).toHaveBeenCalledTimes(2);
      expect([seen, events]).toEqual([[], []]);
    } finally {
      window.removeEventListener(THEME_ANALYTICS_EVENT, listen);
    }
  });

  it("declares two fast failures in a row within 5 s, the second at 23 §9.2 row 1's delay", async () => {
    onLine(true);
    const fetchImpl = vi.fn<typeof fetch>(answer());
    start(fetchImpl);
    await vi.advanceTimersByTimeAsync(LIVENESS_INTERVAL_MS); // answered: the backend is lost now
    fetchImpl.mockImplementation(refused);
    await vi.advanceTimersByTimeAsync(LIVENESS_INTERVAL_MS + 499);
    expect([fetchImpl.mock.calls.length, seen]).toEqual([2, []]);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetchImpl).toHaveBeenCalledTimes(3);
    expect(seen.at(-1)).toMatchObject({ reachable: false, cause: "tailnet_unreachable" });
  });

  it("counts any answer as reachable, a 503 included: the host answered", async () => {
    const fetchImpl = vi.fn<typeof fetch>(answer(503));
    start(fetchImpl);
    await vi.advanceTimersByTimeAsync(LIVENESS_INTERVAL_MS * 3);
    expect(fetchImpl).toHaveBeenCalledTimes(3);
    expect(seen).toEqual([]);
  });

  it("backs off on the 23 §9.2 table while unreachable, says when, and recovers", async () => {
    onLine(true);
    const fetchImpl = vi.fn<typeof fetch>(refused);
    start(fetchImpl);
    await vi.advanceTimersByTimeAsync(LIVENESS_INTERVAL_MS + 500 + 1_000);
    fetchImpl.mockImplementation(answer());
    await vi.advanceTimersByTimeAsync(2_000);
    const at = (ms: number) => T0 + ms;
    expect(settled().map((s) => s.retryAtMs)).toEqual([at(3_500), at(5_500), null]);
    expect(seen.at(-1)).toEqual(REACHABLE);
  });

  it("publishes probing while a probe runs behind the page; Retry now sets it at once", async () => {
    const fetchImpl = vi.fn<typeof fetch>(refused);
    start(fetchImpl);
    await vi.advanceTimersByTimeAsync(LIVENESS_INTERVAL_MS + 500); // declared
    expect(seen.at(-1)).toMatchObject({ reachable: false, probing: false });
    fetchImpl.mockImplementation(hanging);
    probeLivenessNow();
    expect(seen.at(-1)).toMatchObject({ reachable: false, probing: true }); // no timer advance
    await vi.advanceTimersByTimeAsync(LIVENESS_TIMEOUT_MS);
    expect(seen.at(-1)).toMatchObject({ reachable: false, probing: false });
  });

  it("probes at once on Retry now and on the online event, one probe at a time", async () => {
    const fetchImpl = vi.fn<typeof fetch>(hanging);
    start(fetchImpl);
    probeLivenessNow();
    window.dispatchEvent(new Event("online"));
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchImpl).toHaveBeenCalledTimes(1); // the second waits for the first to settle
  });

  it("holds its probes while the page is hidden, and probes at once when it shows again", async () => {
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    const fetchImpl = vi.fn<typeof fetch>(answer());
    start(fetchImpl);
    await vi.advanceTimersByTimeAsync(LIVENESS_INTERVAL_MS * 3);
    window.dispatchEvent(new Event("online")); // a hint while hidden probes nothing either
    await vi.advanceTimersByTimeAsync(0);
    expect(fetchImpl).not.toHaveBeenCalled();
    hidden.mockReturnValue(false);
    document.dispatchEvent(new Event("visibilitychange"));
    expect(fetchImpl).toHaveBeenCalledTimes(1); // at once, no timer advance
    await vi.advanceTimersByTimeAsync(LIVENESS_INTERVAL_MS);
    expect(fetchImpl).toHaveBeenCalledTimes(2); // then on the interval again
  });

  it("reports shell.offline_detected {cause} and shell.tailscale_unreachable once per transition", async () => {
    const events: unknown[] = [];
    const listen = (e: Event) => events.push((e as CustomEvent).detail);
    window.addEventListener(THEME_ANALYTICS_EVENT, listen);
    try {
      const online = onLine(true);
      const fetchImpl = vi.fn<typeof fetch>(refused);
      start(fetchImpl);
      await vi.advanceTimersByTimeAsync(LIVENESS_INTERVAL_MS + 500 + 1_000); // three refusals
      expect(events).toEqual([
        { name: "shell.offline_detected", cause: "tailnet_unreachable" },
        { name: "shell.tailscale_unreachable" },
      ]);
      online.mockReturnValue(false);
      await vi.advanceTimersByTimeAsync(2_000);
      expect(events.at(-1)).toEqual({ name: "shell.offline_detected", cause: "offline" });
      expect(events).toHaveLength(3);
    } finally {
      window.removeEventListener(THEME_ANALYTICS_EVENT, listen);
    }
  });

  it("survives a fetch that throws at once: it fails fast and the next probe still runs", async () => {
    const fetchImpl = vi.fn<typeof fetch>(() => {
      throw new TypeError("fetch is not a function");
    });
    start(fetchImpl);
    await vi.advanceTimersByTimeAsync(LIVENESS_INTERVAL_MS + 500);
    expect(seen.at(-1)).toMatchObject({ reachable: false, cause: "tailnet_unreachable" });
    await vi.advanceTimersByTimeAsync(1_000); // 23 §9.2 row 2
    expect(fetchImpl).toHaveBeenCalledTimes(3);
  });

  it("markReachable() clears the verdict at once and puts the next probe back on the interval", async () => {
    const fetchImpl = vi.fn<typeof fetch>(refused);
    start(fetchImpl);
    await vi.advanceTimersByTimeAsync(LIVENESS_INTERVAL_MS + 500); // declared; next try in 1 s
    markReachable();
    expect(seen.at(-1)).toEqual(REACHABLE); // no timer advance
    await vi.advanceTimersByTimeAsync(LIVENESS_INTERVAL_MS - 1);
    expect(fetchImpl).toHaveBeenCalledTimes(2); // not at the 1 s backoff
    fetchImpl.mockImplementation(answer());
    await vi.advanceTimersByTimeAsync(1);
    expect(fetchImpl).toHaveBeenCalledTimes(3);
    expect(seen.at(-1)).toEqual(REACHABLE);
  });

  it("markReachable() discards the answer of a probe already in flight", async () => {
    const fetchImpl = vi.fn<typeof fetch>(refused);
    start(fetchImpl);
    await vi.advanceTimersByTimeAsync(LIVENESS_INTERVAL_MS + 500);
    fetchImpl.mockImplementationOnce(hanging).mockImplementation(answer());
    probeLivenessNow(); // in flight when the socket comes back
    markReachable();
    await vi.advanceTimersByTimeAsync(LIVENESS_INTERVAL_MS - 1);
    expect(fetchImpl).toHaveBeenCalledTimes(3); // its abort is no failure: no confirmation probe
    await vi.advanceTimersByTimeAsync(1);
    expect(fetchImpl).toHaveBeenCalledTimes(4); // the next, on the interval
    expect(seen.at(-1)).toEqual(REACHABLE);
  });

  it("markReachable() starts the next outage afresh: confirmed, row 2's retry, reported", async () => {
    const events: unknown[] = [];
    const listen = (e: Event) => events.push((e as CustomEvent).detail);
    window.addEventListener(THEME_ANALYTICS_EVENT, listen);
    try {
      const fetchImpl = vi.fn<typeof fetch>(refused);
      start(fetchImpl);
      await vi.advanceTimersByTimeAsync(LIVENESS_INTERVAL_MS + 500 + 1_000 + 2_000); // 4 refusals
      markReachable();
      await vi.advanceTimersByTimeAsync(LIVENESS_INTERVAL_MS); // refused once more
      expect(seen.at(-1)).toEqual(REACHABLE); // a first refusal again: not a verdict yet
      await vi.advanceTimersByTimeAsync(500); // the confirmation, at row 1's delay
      expect(seen.at(-1)).toMatchObject({ reachable: false, retryAtMs: Date.now() + 1_000 });
      expect(events.filter((e) => (e as { cause?: string }).cause)).toHaveLength(2);
    } finally {
      window.removeEventListener(THEME_ANALYTICS_EVENT, listen);
    }
  });

  it("stop() ends the probes, drops the browser hints and leaves the store reachable", async () => {
    const fetchImpl = vi.fn<typeof fetch>(refused);
    const liveness = start(fetchImpl);
    await vi.advanceTimersByTimeAsync(LIVENESS_INTERVAL_MS + 500);
    expect(seen.at(-1)?.reachable).toBe(false);
    liveness.stop();
    expect(seen.at(-1)).toEqual(REACHABLE);
    window.dispatchEvent(new Event("online"));
    probeLivenessNow();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(fetchImpl).toHaveBeenCalledTimes(2);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("stop() with a probe in flight aborts it and says nothing after", async () => {
    let signal: AbortSignal | undefined;
    const fetchImpl = vi.fn<typeof fetch>((url, init) => {
      signal = init?.signal ?? undefined;
      return hanging(url, init);
    });
    const liveness = start(fetchImpl);
    await vi.advanceTimersByTimeAsync(LIVENESS_INTERVAL_MS); // the first probe hangs
    liveness.stop();
    expect(signal?.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(60_000);
    expect([fetchImpl.mock.calls.length, seen, vi.getTimerCount()]).toEqual([1, [], 0]);
  });
});

describe("startShell runs the probe and feeds the store", () => {
  beforeEach(() => resetShellState());
  afterEach(() => {
    accessToken.clear();
    resetShellState();
  });

  it("writes each verdict into the store, and an observed loss of the socket probes at once", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(refused));
    const port = new FakePort();
    const handle = startShell({ wsUrl: "wss://localhost/api/v1/ws", port, fetchImpl: refused });
    const probes = () =>
      vi.mocked(fetch).mock.calls.filter(([url]) => String(url) === LIVENESS_URL).length;
    const up = { kind: "up" } as const;
    const lost = { kind: "reconnecting", attempt: 1, nextAttemptAtMs: T0 + 500 } as const;
    port.say({ t: "state", state: { ...INITIAL_WS_STATE, link: up } });
    port.say({ t: "state", state: { ...INITIAL_WS_STATE, link: lost } });
    await vi.advanceTimersByTimeAsync(0);
    expect(probes()).toBe(1); // before the interval: the loss was observed
    await vi.advanceTimersByTimeAsync(750); // refused again within row 1's 500 +/- 250 ms
    expect(probes()).toBe(2);
    expect(getShellState().reachability).toMatchObject({ reachable: false });
    handle.stop();
    expect(getShellState().reachability).toEqual(REACHABLE);
  });

  it("marks reachable on the transition into live only: chatter while live leaves the cadence", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(answer()));
    const port = new FakePort();
    const handle = startShell({ wsUrl: "wss://localhost/api/v1/ws", port, fetchImpl: refused });
    const probes = () =>
      vi.mocked(fetch).mock.calls.filter(([url]) => String(url) === LIVENESS_URL).length;
    for (let n = 1; n <= 6; n += 1) {
      const link = { kind: "up" } as const;
      port.say({ t: "state", state: { ...INITIAL_WS_STATE, link, transitionSeq: n } });
      await vi.advanceTimersByTimeAsync(1_000);
    }
    expect(probes()).toBeGreaterThanOrEqual(2); // every 2 s, whatever the socket says meanwhile
    handle.stop();
  });

  it("clears the verdict the moment the socket is live again, with no timer advance", async () => {
    vi.stubGlobal("fetch", vi.fn<typeof fetch>(refused));
    const port = new FakePort();
    const handle = startShell({ wsUrl: "wss://localhost/api/v1/ws", port, fetchImpl: refused });
    const up = { kind: "up" } as const;
    const lost = { kind: "reconnecting", attempt: 1, nextAttemptAtMs: T0 + 500 } as const;
    port.say({ t: "state", state: { ...INITIAL_WS_STATE, link: up } });
    port.say({ t: "state", state: { ...INITIAL_WS_STATE, link: lost } });
    await vi.advanceTimersByTimeAsync(750);
    expect(getShellState().reachability).toMatchObject({ reachable: false });
    port.say({ t: "state", state: { ...INITIAL_WS_STATE, link: up } }); // live: proof enough
    expect(getShellState().reachability).toEqual(REACHABLE);
    handle.stop();
  });
});

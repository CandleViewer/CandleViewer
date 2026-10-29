/**
 * E10-S04 (#306) slice 9: the liveness probe behind SCR-159's in-canvas states (`14` SCR-159
 * Performance). `GET /health/live` (`22` getLiveness: no auth, no database) every
 * LIVENESS_INTERVAL_MS, each try bounded by LIVENESS_TIMEOUT_MS, so a backend that stops answering
 * is named within REACHABILITY_WINDOW_MS. Any answer, whatever its status, is reachable: the host
 * answered, and what it said is other surfaces' (SCR-152 / SCR-153). No answer is a failure the
 * tracker classifies: `navigator.onLine` false is offline, else tailnet_unreachable. A timeout
 * counts at once (the 5 s budget leaves no room to confirm it); a fast failure (refused, DNS) is
 * confirmed by a second probe at 23 §9.2 row 1's delay, cut at CONFIRM_TIMEOUT_MS so that even a
 * fast failure then a timeout is named inside the budget, before it counts. The browser's
 * `online` / `offline` events and an observed loss only probe at once; none is a verdict. An
 * observed success (`markReachable`: the socket is live) is one. While unreachable the probe backs
 * off on the 23 §9.2 table, the WS reconnect's own, and the store learns when it tries next and
 * whether a try is running. A hidden page is not probed; it probes at once when it shows again.
 */
import type { generated } from "@candleviewer/protocol";
import { backoffDelayWithJitter } from "./backoff.js";
import {
  REACHABLE,
  ReachabilityTracker,
  type Reachability,
  type ReachabilityCause,
} from "./reachability.js";
import { THEME_ANALYTICS_EVENT } from "./themeStore.js";

const LIVENESS_PATH: keyof generated.rest.paths = "/health/live";
export const LIVENESS_URL = `/api/v1${LIVENESS_PATH}`;
/** Interval plus timeout stays inside REACHABILITY_WINDOW_MS (5 s): the detection budget. */
export const LIVENESS_INTERVAL_MS = 2_000;
export const LIVENESS_TIMEOUT_MS = 2_500;
/** The confirming probe's cut: interval + row 1's latest 750 ms + this stays inside the 5 s. */
export const CONFIRM_TIMEOUT_MS = 2_000;

type Outcome = "answered" | "refused" | "timeout";

export interface LivenessOptions {
  /** Each verdict while unreachable, a try starting behind one, and the return to reachable. */
  readonly onChange: (next: Reachability) => void;
  readonly fetchImpl?: typeof fetch | undefined;
  readonly random?: (() => number) | undefined;
}

export interface Liveness {
  probeNow(): void;
  /** An observed success: reachable at once, a try in flight discarded, the next on the interval. */
  markReachable(): void;
  stop(): void;
}

let active: Liveness | null = null;

/** SCR-159's Retry now: the running shell's probe, at once. */
export function probeLivenessNow(): void {
  active?.probeNow();
}

/** An observed success for the running shell's probe (the socket is live; R-902's boot answered). */
export function markReachable(): void {
  active?.markReachable();
}

/** SCR-159's analytics (`14` SCR-159) on the app's analytics seam, `cv:analytics` on `window`. */
export function reportOffline(cause: ReachabilityCause): void {
  const say = (detail: object): boolean =>
    window.dispatchEvent(new CustomEvent(THEME_ANALYTICS_EVENT, { detail }));
  say({ name: "shell.offline_detected", cause });
  if (cause === "tailnet_unreachable") say({ name: "shell.tailscale_unreachable" });
}

export function startLiveness(options: LivenessOptions): Liveness {
  const { onChange, random = Math.random } = options;
  const fetchImpl: typeof fetch = options.fetchImpl ?? ((url, init) => fetch(url, init));
  const tracker = new ReachabilityTracker();
  let published: Reachability = REACHABLE; // what the store holds
  let failures = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let inFlight: AbortController | undefined; // the try whose outcome still counts
  let stopped = false;

  const publish = (next: Reachability): void => {
    published = next;
    onChange(next);
  };
  const schedule = (delayMs: number): void => {
    clearTimeout(timer);
    timer = setTimeout(probeNow, delayMs);
  };

  function settle(outcome: Outcome): void {
    if (outcome === "answered") {
      failures = 0;
      tracker.recordSuccess();
      schedule(LIVENESS_INTERVAL_MS);
      if (!published.reachable) publish(REACHABLE);
      return;
    }
    failures += 1;
    if (outcome === "refused" && failures === 1 && tracker.current.reachable) {
      schedule(backoffDelayWithJitter(1, random)); // confirmed before it counts
      return;
    }
    const was = tracker.current.cause;
    tracker.recordFailure();
    const { reachable, cause } = tracker.current;
    const delayMs = backoffDelayWithJitter(failures, random);
    schedule(delayMs);
    if (cause !== null && cause !== was) reportOffline(cause);
    publish({ reachable, cause, retryAtMs: Date.now() + delayMs, probing: false });
  }

  async function probe(): Promise<void> {
    if (stopped || inFlight !== undefined || document.hidden) return; // hidden: wait to be shown
    clearTimeout(timer);
    const request = new AbortController();
    inFlight = request;
    if (!published.reachable) publish({ ...published, probing: true }); // the page's busy state
    const confirming = failures === 1 && tracker.current.reachable;
    const cutMs = confirming ? CONFIRM_TIMEOUT_MS : LIVENESS_TIMEOUT_MS;
    let deadline: ReturnType<typeof setTimeout> | undefined;
    let outcome: Outcome = "refused";
    try {
      outcome = await Promise.race([
        fetchImpl(LIVENESS_URL, {
          cache: "no-store",
          credentials: "omit",
          signal: request.signal,
        }).then(
          (): Outcome => "answered",
          (): Outcome => "refused",
        ),
        new Promise<Outcome>((resolve) => {
          deadline = setTimeout(() => resolve("timeout"), cutMs);
        }),
      ]);
    } catch {
      // A fetch that throws at once (no `fetch` at all) failed as fast as a refused one.
    } finally {
      clearTimeout(deadline);
      request.abort(); // a request still open past the deadline is let go
      if (inFlight === request) {
        inFlight = undefined;
        if (!stopped) settle(outcome);
      }
    }
  }

  const probeNow = (): void => void probe();
  const onVisibility = (): void => {
    if (!document.hidden) probeNow();
  };
  const self: Liveness = {
    probeNow,
    markReachable() {
      if (stopped) return;
      inFlight?.abort();
      inFlight = undefined; // what it answers no longer counts
      failures = 0;
      tracker.recordSuccess();
      schedule(LIVENESS_INTERVAL_MS);
      if (!published.reachable) publish(REACHABLE);
    },
    stop() {
      stopped = true;
      clearTimeout(timer);
      inFlight?.abort();
      inFlight = undefined;
      window.removeEventListener("online", probeNow);
      window.removeEventListener("offline", probeNow);
      document.removeEventListener("visibilitychange", onVisibility);
      if (active === self) active = null;
      if (!published.reachable) publish(REACHABLE); // a stopped probe leaves no page behind
    },
  };
  window.addEventListener("online", probeNow);
  window.addEventListener("offline", probeNow);
  document.addEventListener("visibilitychange", onVisibility);
  schedule(LIVENESS_INTERVAL_MS);
  active = self;
  return self;
}

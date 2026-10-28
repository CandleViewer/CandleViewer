// E10-S04 (#306) slice 9: SCR-159 backend-unreachable at boot, R-902 `/offline` (E10-D03 §9.2,
// board 10; E10-D02 f27). Fake clock; the bootstrap's calls answer through a stubbed fetch.
import { createRequire } from "node:module";
import { StrictMode, type JSX } from "react";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createMemoryRouter, useLocation } from "react-router";
import { RouterProvider } from "react-router/dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { clearAnnouncements, ShellAnnouncer } from "../../../src/features/app-shell/announcer";
import { ShellLayout } from "../../../src/features/app-shell/ShellLayout";
import { BackendUnreachable } from "../../../src/features/system-states/BackendUnreachable";
import {
  bootDiverted,
  divertUnreachableBoot,
  isUnreachableBoot,
  OFFLINE_PATH,
  resumeBoot,
  takeHandedBack,
  takeResumePath,
} from "../../../src/features/system-states/bootOffline";
import {
  BOOT_CHECKS,
  CHECK_GLYPHS,
  OFFLINE_COPY,
  SCR159_COPY,
} from "../../../src/features/system-states/copy";
import { OfflineOverlay } from "../../../src/features/system-states/OfflineOverlay";
import { accessToken, REFRESH_SENT_KEY } from "../../../src/lib/auth/accessToken";
import { resetMeClaims } from "../../../src/lib/auth/meCache";
import { INITIAL_WS_STATE } from "../../../src/lib/ws/state/reducer";
import { buildRoutes } from "../../../src/routes/tree";
import { REACHABLE } from "../../../src/shell/bootstrap/reachability";
import { THEME_ANALYTICS_EVENT } from "../../../src/shell/bootstrap/themeStore";
import {
  getShellState,
  resetShellState,
  setShellState,
  subscribeShellState,
  type BootstrapPhase,
} from "../../../src/shell/bootstrap/store";
import { buildDiagnostics, installCrashReporter } from "../../../src/shell/crash/reportCrash";
import { startShell } from "../../../src/shell/startShell";
import { FakePort } from "../../lib/ws/support/fakePort";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

const copy = OFFLINE_COPY.backend_unreachable;
const refused = async (): Promise<Response> => {
  throw new TypeError("Failed to fetch");
};
const hanging = (): Promise<Response> => new Promise<Response>(() => {});
/** A dropped route: no answer, and a rejection once the caller gives up (aborts). */
const dropped = (init?: RequestInit): Promise<Response> =>
  new Promise<Response>((_resolve, reject) =>
    init?.signal?.addEventListener("abort", () =>
      reject(new DOMException("aborted", "AbortError")),
    ),
  );
/** Holds every call until `open`: then each answers, or is refused. */
function gate(): { readonly fetch: typeof fetch; readonly open: (answer: boolean) => void } {
  let open: (answer: boolean) => void = () => {};
  const opened = new Promise<boolean>((resolve) => (open = resolve));
  return { fetch: async (url) => ((await opened) ? answering(url) : refused()), open };
}
/** A store listener that throws once, so `runBootstrap` rejects as if its own code threw. */
function throwOnce(): () => void {
  let armed = true;
  return subscribeShellState(() => {
    if (!armed) return;
    armed = false;
    throw new Error("a store listener threw");
  });
}
const ME = { role: "owner", permissions: [], session: { environment: "demo" } };
const answering = async (url: RequestInfo | URL): Promise<Response> =>
  new Response(JSON.stringify(String(url).endsWith("/me") ? ME : {}), { status: 200 });
const failed = (reason: "timeout" | "http_error" | "unknown", status?: number): BootstrapPhase =>
  status === undefined ? { kind: "failed", reason } : { kind: "failed", reason, status };

/** The page asked for, with its query rendered so a test reads it from the DOM. */
function Positions(): JSX.Element {
  return (
    <>
      <h1>Positions</h1>
      <p>{useLocation().search}</p>
    </>
  );
}
function openOffline(strict = false) {
  const router = createMemoryRouter(
    [
      { path: OFFLINE_PATH, element: <BackendUnreachable /> },
      { path: "/positions", element: <Positions /> },
      { path: "/", element: <h1>Home</h1> },
    ],
    { initialEntries: [OFFLINE_PATH] },
  );
  const tree = <RouterProvider router={router} />;
  return render(strict ? <StrictMode>{tree}</StrictMode> : tree);
}
const settle = () =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
const advance = (ms: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
const fetches = (): number => vi.mocked(fetch).mock.calls.length;
const page = (): HTMLElement =>
  screen.getByRole("heading", { level: 1, name: copy.heading }).parentElement as HTMLElement;
/** What main.tsx does when the boot found no server, asked for /positions?tab=1. */
function divertFromPositions(): void {
  setShellState({ bootstrap: failed("unknown") });
  divertUnreachableBoot(
    { pathname: "/positions", search: "?tab=1", hash: "" },
    { replaceState: vi.fn() },
  );
}
function listenAnalytics(): { events: unknown[]; stop: () => void } {
  const events: unknown[] = [];
  const listen = (e: Event) => events.push((e as CustomEvent).detail);
  window.addEventListener(THEME_ANALYTICS_EVENT, listen);
  return { events, stop: () => window.removeEventListener(THEME_ANALYTICS_EVENT, listen) };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.spyOn(Math, "random").mockReturnValue(0.5); // the 23 §9.2 delays without jitter
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(refused));
});
afterEach(() => {
  takeResumePath(); // no diverted boot outlives its test
  takeHandedBack();
  accessToken.clear();
  localStorage.removeItem(REFRESH_SENT_KEY); // a refused page-load refresh leaves its send mark
  act(() => {
    resetShellState();
    clearAnnouncements();
  });
  resetMeClaims();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("R-902: when a boot is backend-unreachable", () => {
  it.each([
    [failed("timeout"), true],
    [failed("unknown"), true],
    [failed("http_error", 499), false],
    [failed("http_error", 500), true],
    [failed("http_error", 502), true],
    [failed("http_error", 503), true],
    [failed("http_error", 504), true],
    [failed("http_error"), false], // no status: not an answer the rule can read as 5xx
    [failed("http_error", 401), false], // the server answered: sign in
    [failed("http_error", 404), false],
    [{ kind: "ready" } as const, false],
    [{ kind: "locked" } as const, false],
  ])("%j: %s", (phase, unreachable) => {
    expect(isUnreachableBoot(phase)).toBe(unreachable);
  });

  it("opens /offline before the router exists, keeping the page asked for, and reports it", () => {
    const { events, stop } = listenAnalytics();
    const history = { replaceState: vi.fn() };
    const location = { pathname: "/positions", search: "?tab=1", hash: "" };
    try {
      setShellState({ bootstrap: failed("http_error", 401) });
      expect(divertUnreachableBoot(location, history)).toBe(false);
      setShellState({ bootstrap: failed("timeout") });
      expect(divertUnreachableBoot(location, history)).toBe(true);
      expect(history.replaceState).toHaveBeenCalledExactlyOnceWith(null, "", "/offline");
      expect(events).toEqual([{ name: "shell.offline_detected", cause: "backend_unreachable" }]);
      expect(takeResumePath()).toBe("/positions?tab=1");
    } finally {
      stop();
    }
  });

  it("a reload at /offline resumes at /", () => {
    setShellState({ bootstrap: failed("unknown") });
    divertUnreachableBoot(
      { pathname: OFFLINE_PATH, search: "", hash: "" },
      { replaceState: vi.fn() },
    );
    expect(takeResumePath()).toBe("/");
  });

  it.each([
    ["//host/x", "?a=1", "#h", "/"], // scheme-relative: another host
    ["/\\host/x", "", "", "/"], // a browser reads the backslash as a slash
    ["javascript:void(0)", "", "", "/"],
    ["http://host/x", "", "", "/"],
    ["https://host/x", "", "", "/"],
    [`${window.location.origin}/positions`, "", "", "/"], // a scheme, even this origin's
    ["/\t/host/x", "", "", "/"], // the URL parser drops the tab: another host
    ["/%2F%2Fhost/x", "", "", "/"], // percent-encoded, as a router decodes it
    ["/%5Chost/x", "", "", "/"],
    ["/./%2Fhost/x", "", "", "/"],
    ["%2F%2Fhost/x", "", "", "/"],
    ["/%E0%A4%A", "", "", "/"], // a malformed escape
    ["/offline", "?x=1", "#y", "/"], // R-902 itself, however it is spelt
    ["/offline/", "", "", "/"],
    ["/Offline", "", "", "/"],
    ["/offline//", "", "", "/"],
    ["/OFFLINE///", "", "", "/"],
    ["/%6Fffline", "", "", "/"],
    ["/positions", "?x=1", "#y", "/positions?x=1#y"], // the app's own page: kept
    ["/x/../positions", "?x=1", "#y", "/positions?x=1#y"], // as the URL reads it
  ])("resumes %j%s%s at %s: the app's own pages only", (pathname, search, hash, resumed) => {
    setShellState({ bootstrap: failed("unknown") });
    divertUnreachableBoot({ pathname, search, hash }, { replaceState: vi.fn() });
    expect(takeResumePath()).toBe(resumed);
  });
});

describe("R-902 /offline: the full-screen takeover", () => {
  it("renders the wordmark, the heading (focused), the sentence, the checklist and the version", async () => {
    divertFromPositions();
    openOffline();
    const heading = screen.getByRole("heading", { level: 1, name: copy.heading });
    expect(document.activeElement).toBe(heading);
    expect(screen.getByText(SCR159_COPY.wordmark)).toBeInTheDocument();
    expect(screen.getByText(copy.sentence)).toBeInTheDocument();
    const rows = within(screen.getByRole("list")).getAllByRole("listitem");
    expect(
      rows.map((li) => [within(li).getByRole("img").getAttribute("aria-label"), li.textContent]),
    ).toEqual([
      [CHECK_GLYPHS.passed, BOOT_CHECKS.network],
      [CHECK_GLYPHS.failed, BOOT_CHECKS.backend],
      [CHECK_GLYPHS.unknown, BOOT_CHECKS.version],
    ]);
    expect(screen.getByText(SCR159_COPY.retryIn(1))).toBeInTheDocument(); // 500 ms: "~1 s"
    expect(screen.getByRole("button", { name: SCR159_COPY.retryNow })).toBeVisible();
    expect(screen.getByText(SCR159_COPY.buildLine(__CV_APP_VERSION__))).toBeInTheDocument();
    // no chrome: nothing from the server is known, the environment included (no ENV badge)
    expect(screen.queryByRole("banner")).toBeNull();
    expect(screen.queryByRole("navigation")).toBeNull();
    vi.useRealTimers(); // axe schedules with real timers; jsdom has no canvas for contrast
    const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
    expect(res.violations.filter((v) => ["serious", "critical"].includes(v.impact ?? ""))).toEqual(
      [],
    );
  });

  it("marks the network check failed when the browser is offline", () => {
    vi.spyOn(navigator, "onLine", "get").mockReturnValue(false);
    openOffline();
    const network = screen.getByText(BOOT_CHECKS.network);
    expect(within(network).getByRole("img", { name: CHECK_GLYPHS.failed })).toBeInTheDocument();
  });

  it("retries on the 23 §9.2 table, then Retry now finds the server and start-up resumes", async () => {
    divertFromPositions();
    openOffline();
    await settle();
    expect(fetches()).toBe(0); // the first automatic try waits 500 ms
    await act(async () => await vi.advanceTimersByTimeAsync(500));
    await vi.waitFor(() => expect(screen.getByText(SCR159_COPY.retryIn(1))).toBeInTheDocument());
    expect(fetches()).toBe(3); // it ran (the three bootstrap calls) and failed; the next waits 1 s
    vi.useRealTimers(); // the router commits the navigation in a scheduler task
    vi.mocked(fetch).mockImplementation(answering);
    fireEvent.click(screen.getByRole("button", { name: SCR159_COPY.retryNow }));
    expect(
      await screen.findByRole("heading", { name: "Positions" }, { timeout: 5_000 }),
    ).toBeInTheDocument();
    expect(screen.getByText("?tab=1")).toBeInTheDocument();
  });

  it("resumes by itself when an automatic try finds the server", async () => {
    divertFromPositions();
    vi.mocked(fetch).mockImplementation(answering);
    openOffline();
    await act(async () => await vi.advanceTimersByTimeAsync(500));
    await vi.waitFor(() =>
      expect(screen.getByRole("heading", { name: "Positions" })).toBeVisible(),
    );
  });

  it.each([
    ["diverted", true],
    ["opened as is", false],
  ])("%s: busy while a try runs, without a countdown, one try at a time", async (_, diverted) => {
    if (diverted) divertFromPositions();
    vi.mocked(fetch).mockImplementation(hanging);
    openOffline();
    fireEvent.click(screen.getByRole("button", { name: SCR159_COPY.retryNow }));
    fireEvent.click(screen.getByRole("button", { name: SCR159_COPY.retryNow })); // re-entry
    await settle();
    expect(fetches()).toBe(3); // one bootstrap, not two
    expect(page()).toHaveAttribute("aria-busy", "true");
    expect(screen.queryByText(/^Retrying in/)).toBeNull();
  });

  it("a try that answers after an unmount navigates nowhere and hands nothing back", async () => {
    divertFromPositions();
    const held = gate();
    vi.mocked(fetch).mockImplementation(held.fetch);
    const view = openOffline();
    fireEvent.click(screen.getByRole("button", { name: SCR159_COPY.retryNow }));
    await settle();
    view.unmount();
    held.open(true); // the server answers, the session is ready
    await settle();
    expect([takeHandedBack(), bootDiverted(), vi.getTimerCount()]).toEqual([false, true, 0]);
  });

  it("a try that throws after an unmount leaves nothing unhandled and no timer", async () => {
    divertFromPositions();
    const held = gate();
    vi.mocked(fetch).mockImplementation(held.fetch);
    const view = openOffline();
    fireEvent.click(screen.getByRole("button", { name: SCR159_COPY.retryNow }));
    await settle();
    view.unmount();
    const unsubscribe = throwOnce();
    held.open(false);
    await settle();
    unsubscribe();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("a throw while busy clears it: a second press waited, a third tries again", async () => {
    const held = gate();
    vi.mocked(fetch).mockImplementation(held.fetch);
    openOffline();
    const retry = screen.getByRole("button", { name: SCR159_COPY.retryNow });
    fireEvent.click(retry);
    fireEvent.click(retry); // busy: ignored
    const unsubscribe = throwOnce();
    held.open(false);
    await settle();
    unsubscribe();
    expect(fetches()).toBe(3);
    expect(page()).not.toHaveAttribute("aria-busy");
    fireEvent.click(retry);
    await settle();
    expect(fetches()).toBe(6);
  });

  it("goes on retrying by itself after a try throws", async () => {
    divertFromPositions();
    openOffline();
    const unsubscribe = throwOnce();
    await advance(500); // the first automatic try throws
    unsubscribe();
    expect(screen.getByText(SCR159_COPY.retryIn(1))).toBeInTheDocument(); // row 2, rescheduled
    await advance(1_000);
    expect(fetches()).toBe(6);
  });

  it("records a try that throws in the crash log, by the error's class and never its message", async () => {
    const uninstall = installCrashReporter({ version: "test", target: undefined }); // a fresh log
    try {
      divertFromPositions();
      openOffline();
      const unsubscribe = throwOnce();
      await advance(500); // the first automatic try throws
      unsubscribe();
      const lines = buildDiagnostics().recentLogLines;
      expect(lines).toEqual([expect.stringMatching(/ crash route \S+ R-902: a try threw Error$/)]);
      expect(lines.join("\n")).not.toContain("a store listener threw");
    } finally {
      uninstall();
    }
  });

  it("hands nothing back when the answer is a sign-in (401): no shell mounts to say it", async () => {
    divertFromPositions();
    vi.mocked(fetch).mockImplementation(async () => new Response("{}", { status: 401 }));
    openOffline();
    vi.useRealTimers();
    fireEvent.click(screen.getByRole("button", { name: SCR159_COPY.retryNow }));
    expect(
      await screen.findByRole("heading", { name: "Positions" }, { timeout: 5_000 }),
    ).toBeInTheDocument();
    expect(takeHandedBack()).toBe(false);
  });

  it("clears its retry timer and its clock when it unmounts", async () => {
    divertFromPositions();
    const view = openOffline();
    await settle();
    expect(vi.getTimerCount()).toBe(2); // the next try and the countdown's 1 Hz clock
    view.unmount();
    await settle();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("under StrictMode schedules one try, not two", async () => {
    divertFromPositions();
    openOffline(true);
    await act(async () => await vi.advanceTimersByTimeAsync(500));
    expect(fetches()).toBe(3);
  });

  it("opened as is: no countdown and no clock; a failed Retry now stays, a success goes to /", async () => {
    openOffline();
    await settle();
    expect(vi.getTimerCount()).toBe(0);
    fireEvent.click(screen.getByRole("button", { name: SCR159_COPY.retryNow }));
    await act(async () => await vi.advanceTimersByTimeAsync(0));
    expect(fetches()).toBe(3);
    expect(screen.getByRole("heading", { level: 1, name: copy.heading })).toBeVisible();
    expect(screen.queryByText(/^Retrying in/)).toBeNull();
    vi.useRealTimers();
    vi.mocked(fetch).mockImplementation(answering);
    fireEvent.click(screen.getByRole("button", { name: SCR159_COPY.retryNow }));
    expect(
      await screen.findByRole("heading", { name: "Home" }, { timeout: 5_000 }),
    ).toBeInTheDocument();
  });

  it("is R-902's element in the route tree, outside the shell; opened as is, it waits for Retry now", async () => {
    const router = createMemoryRouter(buildRoutes(), { initialEntries: [OFFLINE_PATH] });
    render(<RouterProvider router={router} />);
    await settle(); // the route's loader (its guard) runs first
    expect(screen.getByRole("heading", { level: 1, name: copy.heading })).toBeInTheDocument();
    expect(screen.getAllByRole("main")).toHaveLength(1);
    expect(screen.queryByRole("banner")).toBeNull();
    await act(async () => await vi.advanceTimersByTimeAsync(60_000));
    expect(screen.queryByText(/^Retrying in/)).toBeNull();
    expect(fetches()).toBe(0); // no boot was diverted: no automatic try
  });
});

describe("R-902 owns its outage, then hands the shell a clean start", () => {
  it("a hung boot: one offline event, and no stale verdict reaches the shell after the resume", async () => {
    const { events, stop } = listenAnalytics();
    let bootUp = false;
    let probeUp = false;
    vi.mocked(fetch).mockImplementation((url, init) => {
      const path = String(url);
      if (path.endsWith("/refresh")) return refused(); // no session to re-derive: on to the boot
      const up = path.endsWith("/health/live") ? probeUp : bootUp;
      return up ? answering(url) : dropped(init ?? undefined);
    });
    const handle = startShell({ wsUrl: "wss://localhost/api/v1/ws", port: new FakePort() });
    const t0 = Date.now(); // probes at 2, 5 and 8.5 s hang; the last one's deadline is t0 + 11 s
    try {
      let settled = false;
      void handle.ready.then(() => (settled = true));
      await advance(10_000); // the bootstrap's calls time out: a probe is in flight across it
      expect(settled).toBe(true);
      expect(events).toEqual([]); // the probe failed throughout, quietly: the boot owns it
      expect(getShellState().reachability).toEqual(REACHABLE); // loading, then slow: no verdict
      divertUnreachableBoot(
        { pathname: "/positions", search: "", hash: "" },
        { replaceState: vi.fn() },
      );
      const router = createMemoryRouter(
        [
          { path: OFFLINE_PATH, element: <BackendUnreachable /> },
          { element: <ShellLayout />, children: [{ path: "/positions", element: <Positions /> }] },
        ],
        { initialEntries: [OFFLINE_PATH] },
      );
      render(<RouterProvider router={router} />);
      bootUp = true; // the boot's calls answer now; the probe's route is still down
      await advance(500); // a probe starts and hangs, then R-902's try answers and resumes
      await vi.waitFor(() =>
        expect(screen.getByRole("heading", { name: "Positions" })).toBeVisible(),
      );
      probeUp = true;
      await advance(t0 + 11_500 - Date.now()); // past the hung probe's deadline, before the next
      expect(getShellState().reachability).toEqual(REACHABLE);
      expect(
        screen.queryByRole("heading", { name: OFFLINE_COPY.tailnet_unreachable.heading }),
      ).toBeNull();
      expect(events).toEqual([{ name: "shell.offline_detected", cause: "backend_unreachable" }]);
    } finally {
      handle.stop();
      stop();
    }
  });

  it("one offline event; the shell mounts with no page; the resume is said once, when live", async () => {
    const { events, stop } = listenAnalytics();
    let down = true;
    vi.mocked(fetch).mockImplementation(async (url) =>
      down || String(url).endsWith("/health/live") ? refused() : answering(url),
    );
    const port = new FakePort();
    const handle = startShell({ wsUrl: "wss://localhost/api/v1/ws", port });
    try {
      await act(async () => await handle.ready);
      divertFromPositions(); // main.tsx's step: the one backend_unreachable event
      const router = createMemoryRouter(
        [
          { path: OFFLINE_PATH, element: <BackendUnreachable /> },
          { element: <ShellLayout />, children: [{ path: "/positions", element: <Positions /> }] },
        ],
        { initialEntries: [OFFLINE_PATH] },
      );
      render(<RouterProvider router={router} />);
      await act(async () => await vi.advanceTimersByTimeAsync(10_000)); // probes refused all along
      expect(getShellState().reachability).toEqual(REACHABLE); // R-902's outage, not the probe's
      vi.useRealTimers();
      down = false;
      fireEvent.click(screen.getByRole("button", { name: SCR159_COPY.retryNow }));
      expect(
        await screen.findByRole("heading", { name: "Positions" }, { timeout: 5_000 }),
      ).toBeInTheDocument();
      expect(
        screen.queryByRole("heading", { name: OFFLINE_COPY.tailnet_unreachable.heading }),
      ).toBeNull();
      expect(getShellState().reachability).toEqual(REACHABLE);
      // the shell announcer's polite region: the last one, after CMP-092's pair
      const polite = (): string =>
        [...document.querySelectorAll('[aria-live="polite"]')].at(-1)?.textContent ?? "";
      expect(polite()).toBe(""); // the socket is not live yet
      act(() => port.say({ t: "state", state: { ...INITIAL_WS_STATE, link: { kind: "up" } } }));
      await waitFor(() => expect(polite()).toBe(SCR159_COPY.recovered), { timeout: 5_000 });
      expect(events).toEqual([{ name: "shell.offline_detected", cause: "backend_unreachable" }]);
    } finally {
      handle.stop();
      stop();
    }
  });

  it("under StrictMode a ready resume is still said once, when the socket is live", () => {
    resumeBoot(true); // R-902's success with a ready session
    render(
      <StrictMode>
        <OfflineOverlay />
        <ShellAnnouncer />
      </StrictMode>,
    );
    const polite = (): string => document.querySelector('[aria-live="polite"]')?.textContent ?? "";
    expect(polite()).toBe(""); // the socket is not live yet
    act(() => setShellState({ connection: { kind: "live" } }));
    expect(polite()).toBe(SCR159_COPY.recovered);
  });
});

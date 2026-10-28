// E10-S04 (#306) slice 9: SCR-159's in-canvas states (E10-D03 §9.2, board 10) in the shell's canvas
// overlay slot. RTL by role; fake clock; the announcer's text, never its counters or the wall time.
import { createRequire } from "node:module";
import { StrictMode, useEffect, useState, type JSX } from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "../../../src/features/app-shell/AppShell";
import {
  announce,
  clearAnnouncements,
  REGION_BUDGET_MS,
  ShellAnnouncer,
} from "../../../src/features/app-shell/announcer";
import { ShellLayout } from "../../../src/features/app-shell/ShellLayout";
import { ShellCanvasOverlaySlot } from "../../../src/features/app-shell/slots";
import {
  OFFLINE_COPY,
  SCR159_COPY,
  TAILNET_CHECKS,
} from "../../../src/features/system-states/copy";
import { resetMeClaims, setMeClaims } from "../../../src/lib/auth/meCache";
import { setActiveClient } from "../../../src/lib/ws/client/activeClient";
import type { WsClientHandle } from "../../../src/lib/ws/client/createWsClient";
import { INITIAL_WS_STATE, reduce } from "../../../src/lib/ws/state/reducer";
import type { WsState } from "../../../src/lib/ws/state/types";
import { startLiveness } from "../../../src/shell/bootstrap/liveness.js";
import { REACHABLE, type Reachability } from "../../../src/shell/bootstrap/reachability.js";
import { resetShellState, setShellState } from "../../../src/shell/bootstrap/store.js";
import { OFF, authOk, connecting, stream } from "../../lib/ws/support/engineEvents";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

const T0 = Date.UTC(2026, 9, 28, 14, 0, 0);
const lost = (cause: "offline" | "tailnet_unreachable", retryInMs = 4_000): Reachability => ({
  reachable: false,
  cause,
  retryAtMs: Date.now() + retryInMs,
  probing: false,
});
const reach = (r: Reachability): void => act(() => setShellState({ reachability: r }));
let renders = 0;
let mounts = 0;
let hideControl: () => void = () => {};
function Workspace(): JSX.Element {
  renders += 1;
  const [shown, setShown] = useState(true);
  hideControl = () => setShown(false);
  useEffect(() => {
    mounts += 1;
  }, []);
  return shown ? <button type="button">Chart control</button> : <p>No control</p>;
}
const shell = (strict = false) => {
  const tree = (
    <>
      <AppShell
        mainId="cv-main"
        nav={<button type="button">Rail item</button>}
        canvasOverlay={<ShellCanvasOverlaySlot />}
      >
        <Workspace />
      </AppShell>
      <ShellAnnouncer />
    </>
  );
  return render(strict ? <StrictMode>{tree}</StrictMode> : tree);
};
const observers: MutationObserver[] = [];
/** Every message written into one of the announcer's regions from now on. */
function watch(live: "polite" | "assertive"): string[] {
  const said: string[] = [];
  const observer = new MutationObserver((records) => {
    for (const r of records) {
      if ((r.target as Element).getAttribute?.("aria-live") !== live) continue;
      for (const node of r.addedNodes) said.push(node.textContent ?? "");
    }
  });
  observer.observe(document.body, { childList: true, subtree: true });
  observers.push(observer);
  return said;
}
/** Lets the probe's promise chain and the observer's records run (both are microtasks). */
const settle = () =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
/** Another assertive writer (CMP-077 row 14, "sign out failed"): the overlay waits it out too. */
const otherWriter = (): void =>
  void act(() => announce("assertive", "Sign out failed.", "t:other"));
const advance = (ms: number) =>
  act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
const page = (): HTMLElement =>
  screen.getByRole("heading", { level: 1 }).parentElement as HTMLElement;
async function seriousAxe(el: Element): Promise<unknown[]> {
  vi.useRealTimers(); // axe schedules with real timers; jsdom has no canvas for contrast
  const res = await axe.run(el, { rules: { "color-contrast": { enabled: false } } });
  return res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}

beforeEach(() => {
  renders = 0;
  mounts = 0;
  vi.useFakeTimers();
  vi.setSystemTime(T0);
});
afterEach(() => {
  observers.splice(0).forEach((observer) => observer.disconnect());
  act(() => {
    resetShellState();
    clearAnnouncements();
  });
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("SCR-159 in the canvas: offline and tailnet-unreachable", () => {
  it("renders nothing while reachable, over AppShell's canvas (main's data-shell-canvas child)", () => {
    shell();
    const overlay = document.querySelector('[data-shell-slot="canvas-overlay"]');
    expect(overlay).toBeEmptyDOMElement();
    const canvas = screen.getByRole("main").querySelector(":scope > [data-shell-canvas]");
    expect(canvas?.contains(screen.getByRole("button", { name: "Chart control" }))).toBe(true);
    expect(canvas?.nextElementSibling).toBe(overlay);
  });

  it.each([
    ["offline", 0],
    ["tailnet_unreachable", 3],
  ] as const)("%s: its h1, sentence, checks and named actions", async (cause, checks) => {
    shell();
    reach(lost(cause));
    const copy = OFFLINE_COPY[cause];
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(copy.heading);
    expect(within(page()).getByText(copy.sentence)).toBeInTheDocument();
    expect(
      within(page())
        .queryAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual(TAILNET_CHECKS.slice(0, checks));
    expect(within(page()).getByText(SCR159_COPY.retryIn(4))).toBeInTheDocument();
    expect(within(page()).getByText(SCR159_COPY.fallback)).toBeInTheDocument();
    expect(within(page()).getByText(SCR159_COPY.command).tagName).toBe("CODE");
    expect(within(page()).getByRole("button", { name: SCR159_COPY.copyCommand })).toBeVisible();
    expect(within(page()).getByRole("button", { name: SCR159_COPY.retryNow })).toBeVisible();
    expect(await seriousAxe(page())).toEqual([]);
  });

  it("names the tailnet condition, never a generic offline message, when the browser is online", () => {
    shell();
    reach(lost("tailnet_unreachable"));
    expect(screen.getByRole("heading", { name: "Not connected to the tailnet" })).toBeVisible();
    expect(screen.queryByText(/you're offline/i)).toBeNull();
  });

  it("says the page once: the sentence as the alert, then focus on the h1; later probes say nothing", async () => {
    shell();
    const alerts = watch("assertive");
    reach(lost("tailnet_unreachable"));
    await settle();
    expect(alerts).toEqual([OFFLINE_COPY.tailnet_unreachable.sentence]); // no heading in it
    expect(document.activeElement).toBe(screen.getByRole("heading", { level: 1 }));
    act(() => vi.advanceTimersByTime(3_000)); // the 1 Hz countdown
    expect(screen.getByText(SCR159_COPY.retryIn(1))).toBeInTheDocument();
    reach(lost("tailnet_unreachable", 10_000)); // the next failed probe
    await settle();
    expect(alerts).toHaveLength(1);
  });

  it("returns focus on recovery to the element that had it, or to main once that is gone", async () => {
    shell();
    const control = screen.getByRole("button", { name: "Chart control" });
    control.focus();
    reach(lost("offline"));
    await settle();
    expect(document.activeElement).toBe(screen.getByRole("heading", { level: 1 }));
    reach(REACHABLE);
    expect(document.activeElement).toBe(control);
    reach(lost("offline"));
    await settle();
    act(() => hideControl()); // the element that had focus is gone by the recovery
    reach(REACHABLE);
    expect(document.activeElement).toBe(screen.getByRole("main"));
  });

  it("says the recovery once, politely, when the data is live, and leaves no stale alert", async () => {
    shell();
    const polite = watch("polite");
    act(() =>
      setShellState({ connection: { kind: "reconnecting", attempt: 1, nextAttemptAtMs: 0 } }),
    );
    reach(lost("offline"));
    await settle();
    reach(REACHABLE);
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull(); // recovery is automatic
    expect(document.querySelectorAll('[aria-live="assertive"]')[0]).toBeEmptyDOMElement();
    await settle();
    expect(polite).toEqual([]); // the socket is not back yet: not live
    act(() => setShellState({ connection: { kind: "live" } }));
    await settle();
    expect(polite).toEqual([SCR159_COPY.recovered]);
    act(() => setShellState({ connection: { kind: "live" }, preferencesWarning: "x" }));
    await settle();
    expect(polite).toHaveLength(1);
  });

  it("forgets its alert when unmounted mid-outage, so the next outage alerts again", async () => {
    const first = shell();
    reach(lost("offline"));
    await settle();
    first.unmount();
    reach(REACHABLE);
    shell();
    const alerts = watch("assertive");
    reach(lost("offline"));
    await act(async () => await vi.advanceTimersByTimeAsync(REGION_BUDGET_MS)); // past its last alert
    expect(alerts).toEqual([OFFLINE_COPY.offline.sentence]);
  });

  it("Retry now probes at once: the page is busy, without a countdown, until the answer", async () => {
    let answer: (r: Response) => void = () => {};
    const fetchImpl = vi.fn<typeof fetch>(async (): Promise<Response> => {
      throw new TypeError("Failed to fetch");
    });
    const liveness = startLiveness({
      onChange: (r) => setShellState({ reachability: r }),
      fetchImpl,
      random: () => 0.5, // 23 §9.2 row 1 without jitter: the confirmation at 500 ms
    });
    try {
      shell();
      await act(async () => await vi.advanceTimersByTimeAsync(2_500)); // refused twice
      fetchImpl.mockImplementation(() => new Promise<Response>((resolve) => (answer = resolve)));
      fireEvent.click(screen.getByRole("button", { name: SCR159_COPY.retryNow }));
      expect(fetchImpl).toHaveBeenCalledTimes(3);
      expect(page()).toHaveAttribute("aria-busy", "true");
      expect(screen.queryByText(/^Retrying in/)).toBeNull();
      answer(new Response(null, { status: 200 }));
      await settle();
      expect(screen.queryByRole("button", { name: SCR159_COPY.retryNow })).toBeNull();
    } finally {
      liveness.stop();
    }
  });

  it("runs its 1 Hz clock only while shown: cleared on recovery and on unmount", async () => {
    const view = shell();
    reach(lost("offline"));
    await settle();
    expect(vi.getTimerCount()).toBe(1);
    reach(REACHABLE);
    await settle(); // jsdom's 0 ms selectionchange from the focus going back
    expect(vi.getTimerCount()).toBe(0);
    reach(lost("offline"));
    await settle();
    view.unmount();
    await settle();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("under StrictMode keeps one clock and says one alert", async () => {
    shell(true);
    const alerts = watch("assertive");
    reach(lost("offline"));
    await settle();
    expect([vi.getTimerCount(), alerts]).toEqual([1, [OFFLINE_COPY.offline.sentence]]);
  });

  it("under StrictMode, mounted mid-outage: the sentence once, at once, focus on the h1", async () => {
    reach(lost("offline")); // the store holds the verdict before the shell mounts
    const alerts = watch("assertive");
    shell(true);
    await settle();
    expect(alerts).toEqual([OFFLINE_COPY.offline.sentence]);
    expect(document.activeElement).toBe(screen.getByRole("heading", { level: 1 }));
    await advance(REGION_BUDGET_MS);
    expect(alerts).toHaveLength(1); // no late heading-plus-sentence
    reach(REACHABLE);
    expect(document.activeElement).toBe(screen.getByRole("main")); // nothing had focus before
  });

  it("under StrictMode, mounted mid-outage: focus goes back to what had it before the page", async () => {
    const outside = document.body.appendChild(document.createElement("button"));
    try {
      outside.focus(); // outside the canvas, before the shell mounts
      reach(lost("offline"));
      shell(true);
      await settle();
      expect(document.activeElement).toBe(screen.getByRole("heading", { level: 1 }));
      reach(REACHABLE);
      expect(document.activeElement).toBe(outside); // the rehearsal kept no page element for it
    } finally {
      outside.remove();
    }
  });

  it("under StrictMode, mounted mid-outage behind another writer: focus stays until it speaks", async () => {
    otherWriter(); // the entry waits 5 s
    reach(lost("offline"));
    shell(true);
    await settle();
    expect(document.activeElement).toBe(document.body); // the rehearsal hands nothing back
    await advance(REGION_BUDGET_MS);
    expect(document.activeElement).toBe(screen.getByRole("heading", { level: 1 }));
  });

  it("never waits longer than the budget, even when the wall clock steps back", async () => {
    shell();
    otherWriter(); // the region's last write
    vi.setSystemTime(T0 - 3_600_000); // then the clock steps back an hour
    const alerts = watch("assertive");
    reach(lost("offline"));
    await advance(REGION_BUDGET_MS);
    expect(alerts).toEqual([OFFLINE_COPY.offline.sentence]);
  });

  it("speaks 15 s after the verdict at the latest, however often another writer speaks", async () => {
    shell();
    const alerts = watch("assertive");
    const toast = (n: number): void =>
      void act(() => announce("assertive", `Toast ${n}.`, `t:toast:${n}`));
    toast(0);
    reach(lost("offline")); // the entry waits out each toast in turn
    for (const n of [1, 2, 3]) {
      await advance(4_000);
      toast(n); // every 4 s, inside each wait
    }
    await advance(2_999);
    expect(alerts).toEqual(["Toast 0.", "Toast 1.", "Toast 2.", "Toast 3."]);
    await advance(1);
    expect(alerts.at(-1)).toBe(OFFLINE_COPY.offline.sentence);
    expect(document.activeElement).toBe(screen.getByRole("heading", { level: 1 }));
  });

  it("says a second episode's recovery too", async () => {
    shell();
    act(() => setShellState({ connection: { kind: "live" } }));
    const polite = watch("polite");
    for (const cause of ["offline", "tailnet_unreachable"] as const) {
      reach(lost(cause));
      await settle();
      reach(REACHABLE);
      await settle();
    }
    expect(polite).toEqual([SCR159_COPY.recovered, SCR159_COPY.recovered]);
  });

  it("moves focus once per episode, and leaves it where the user took it on recovery", async () => {
    shell();
    const rail = screen.getByRole("button", { name: "Rail item" });
    screen.getByRole("button", { name: "Chart control" }).focus(); // what the page would hand back
    reach(lost("offline"));
    await settle();
    expect(document.activeElement).toBe(screen.getByRole("heading", { level: 1 }));
    rail.focus(); // the user moves on, to the chrome
    reach(lost("tailnet_unreachable")); // a later cause: said, but focus stays
    await settle();
    expect(document.activeElement).toBe(rail);
    const events: string[] = [];
    for (const type of ["blur", "focusout"]) rail.addEventListener(type, () => events.push(type));
    reach(REACHABLE);
    expect(document.activeElement).toBe(rail);
    expect(events).toEqual([]); // no round trip through the old control
  });

  it("starts each episode afresh: after the user moved on, the next recovery falls back to main", async () => {
    shell();
    act(() => setShellState({ connection: { kind: "live" } })); // each recovery ends its episode
    const rail = screen.getByRole("button", { name: "Rail item" });
    screen.getByRole("button", { name: "Chart control" }).focus(); // episode 1's to hand back
    reach(lost("offline"));
    await settle();
    rail.focus(); // the user moves on, so episode 1 hands nothing back
    reach(REACHABLE);
    rail.blur(); // episode 2 starts with nothing focused
    reach(lost("offline"));
    await settle();
    expect(document.activeElement).toBe(screen.getByRole("heading", { level: 1 }));
    reach(REACHABLE);
    expect(document.activeElement).toBe(screen.getByRole("main")); // not episode 1's control
  });

  it("falls back to main when what had focus is inert by the recovery", async () => {
    shell();
    const rail = screen.getByRole("button", { name: "Rail item" });
    rail.focus();
    reach(lost("offline"));
    await settle();
    rail.setAttribute("inert", ""); // out of reach now; jsdom would still focus it
    reach(REACHABLE);
    expect(document.activeElement).toBe(screen.getByRole("main"));
  });

  it("returns focus to the canvas element the page covered, after the browser's inert blur", async () => {
    shell();
    otherWriter(); // the entry waits 5 s
    const control = screen.getByRole("button", { name: "Chart control" });
    control.focus();
    reach(lost("offline"));
    control.blur(); // jsdom's inert keeps focus; a browser drops it to the body here
    await advance(REGION_BUDGET_MS);
    expect(document.activeElement).toBe(screen.getByRole("heading", { level: 1 }));
    reach(REACHABLE);
    expect(document.activeElement).toBe(control);
  });

  it("returns focus to a chrome element the user took during the wait", async () => {
    shell();
    otherWriter();
    screen.getByRole("button", { name: "Chart control" }).focus();
    reach(lost("offline"));
    const rail = screen.getByRole("button", { name: "Rail item" });
    rail.focus(); // during the wait, before the page takes focus
    await advance(REGION_BUDGET_MS);
    expect(document.activeElement).toBe(screen.getByRole("heading", { level: 1 }));
    reach(REACHABLE);
    expect(document.activeElement).toBe(rail);
  });

  it("covers the canvas without re-rendering it, and takes it out of reach while shown", async () => {
    shell();
    const control = screen.getByRole("button", { name: "Chart control" });
    control.focus();
    const canvas = control.parentElement as HTMLElement;
    const base = { renders, mounts };
    reach(lost("offline"));
    expect(canvas).toHaveAttribute("inert");
    await settle();
    expect(document.activeElement).toBe(screen.getByRole("heading", { level: 1 }));
    act(() => vi.advanceTimersByTime(5_000));
    reach(lost("tailnet_unreachable"));
    reach(REACHABLE);
    expect(canvas).not.toHaveAttribute("inert");
    expect({ renders, mounts }).toEqual(base);
  });
});

describe("SCR-159 beside CMP-077 in the shell layout", () => {
  let ws: WsState = INITIAL_WS_STATE;
  const listeners = new Set<() => void>();
  const client = {
    getState: () => ws,
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => void listeners.delete(listener);
    },
  } as unknown as WsClientHandle; // the hook reads only `getState` and `subscribe`
  const go = (next: WsState): void =>
    act(() => {
      ws = next;
      listeners.forEach((listener) => listener());
    });
  const UP = [connecting, authOk(OFF), stream("live")].reduce(reduce, INITIAL_WS_STATE);
  /** The shell announcer's assertive region: rendered last, after CMP-092's own pair. */
  const announcer = (): Element =>
    [...document.querySelectorAll('[aria-live="assertive"]')].at(-1) as Element;

  beforeEach(() => {
    ws = UP;
    setMeClaims({ authenticated: true, role: "owner", permissions: [] });
    act(() => setActiveClient(client));
  });
  afterEach(() => {
    act(() => setActiveClient(null));
    resetMeClaims();
  });

  it("waits out row 1's 5 s before its alert and focus, then returns focus on recovery", async () => {
    const router = createMemoryRouter(
      [{ element: <ShellLayout />, children: [{ path: "/", element: <Workspace /> }] }],
      { initialEntries: ["/"] },
    );
    render(<RouterProvider router={router} />);
    const control = screen.getByRole("button", { name: "Chart control" });
    control.focus();
    const lostAt = { sinceMs: T0, lastDataMs: T0 - 12_000 };
    go(reduce(UP, { type: "reconnecting", attempt: 1, nextAttemptAtMs: T0 + 4_000, lost: lostAt }));
    const row1 = announcer().textContent ?? "";
    expect(row1).toMatch(/^Disconnected\. New orders off\./);
    await act(async () => await vi.advanceTimersByTimeAsync(1_000));
    reach(lost("tailnet_unreachable")); // the probe's verdict, a second after row 1
    expect(screen.getByRole("heading", { name: "Not connected to the tailnet" })).toBeVisible();
    await act(async () => await vi.advanceTimersByTimeAsync(3_999));
    expect(announcer().textContent).toBe(row1); // row 1 kept its 5 s
    expect(document.activeElement).toBe(control);
    await act(async () => await vi.advanceTimersByTimeAsync(1));
    expect(announcer().textContent).toBe(OFFLINE_COPY.tailnet_unreachable.sentence);
    expect(document.activeElement).toBe(
      screen.getByRole("heading", { name: "Not connected to the tailnet" }),
    );
    reach(REACHABLE);
    expect(document.activeElement).toBe(control);
    router.dispose();
  });

  it("re-arms when another writer speaks during the wait, so that writer is not cut either", async () => {
    const router = createMemoryRouter(
      [{ element: <ShellLayout />, children: [{ path: "/", element: <Workspace /> }] }],
      { initialEntries: ["/"] },
    );
    render(<RouterProvider router={router} />);
    const lostAt = { sinceMs: T0, lastDataMs: T0 - 12_000 };
    go(reduce(UP, { type: "reconnecting", attempt: 1, nextAttemptAtMs: T0 + 4_000, lost: lostAt }));
    await advance(1_000);
    reach(lost("tailnet_unreachable"));
    await advance(3_500);
    otherWriter(); // at T0 + 4.5 s, inside the overlay's wait
    await advance(500);
    expect(announcer().textContent).toBe("Sign out failed."); // not cut at the first deadline
    await advance(4_499);
    expect(announcer().textContent).toBe("Sign out failed.");
    await advance(1);
    expect(announcer().textContent).toBe(OFFLINE_COPY.tailnet_unreachable.sentence);
    router.dispose();
  });
});

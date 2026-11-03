// E10-S04 (#306) slice 4b: the CMP-077 connection region in `ShellBannerSlot` (E17-D02 §4.1, §6,
// §10 B / D / F / R, §11, §13). Fake timers; the WS state comes from a fake active client.
import { createRequire } from "node:module";
import { StrictMode, useEffect, type JSX } from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "../../../src/features/app-shell/AppShell";
import {
  announce,
  clearAnnouncements,
  ShellAnnouncer,
} from "../../../src/features/app-shell/announcer";
import {
  ShellBannerSlot,
  ShellCanvasOverlaySlot,
  ShellConnectionSlot,
} from "../../../src/features/app-shell/slots";
import { positionsApi } from "../../../src/features/positions/api";
import { getReassurance } from "../../../src/features/reconciliation/reassurance";
import { INITIAL_DEGRADED_FACTS } from "../../../src/features/system-states/degradedIssues";
import { REFRESH_SENT_KEY, accessToken } from "../../../src/lib/auth/accessToken";
import { bootViewAs, resetViewAs, startViewAsSync } from "../../../src/lib/auth/viewAsContext";
import { setActiveClient } from "../../../src/lib/ws/client/activeClient";
import type { WsClientHandle } from "../../../src/lib/ws/client/createWsClient";
import { INITIAL_WS_STATE, reduce } from "../../../src/lib/ws/state/reducer";
import type { EngineEvent, WsState } from "../../../src/lib/ws/state/types";
import {
  resetShellState,
  setShellState,
  type ConnectionState,
  type HeldViewAs,
  type Me,
} from "../../../src/shell/bootstrap/store.js";
import {
  OFF,
  ON,
  authOk,
  connecting,
  killSwitch,
  shutdown,
  stream,
} from "../../lib/ws/support/engineEvents";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };
// color-contrast is off: jsdom computes no styles (the E17-D02 §14 matrix owns contrast).
const seriousAxe = async (el: Element): Promise<unknown[]> =>
  (await axe.run(el, { rules: { "color-contrast": { enabled: false } } })).violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );

const T0 = Date.UTC(2026, 9, 27, 13, 42, 5);
const LOST = { sinceMs: T0, lastDataMs: T0 - 12_000 };
const run = (...events: EngineEvent[]): WsState => events.reduce(reduce, INITIAL_WS_STATE);
const UP = run(connecting, authOk(OFF), stream("live"));
const DROPPED = reduce(UP, {
  type: "reconnecting",
  attempt: 1,
  nextAttemptAtMs: T0 + 4_000,
  lost: LOST,
});
const fatal = (closeCode: number): WsState =>
  reduce(UP, { type: "offline", cause: "fatal", closeCode, lost: LOST });

let state: WsState = INITIAL_WS_STATE;
const listeners = new Set<() => void>();
const retryNow = vi.fn(() => true);
const client = {
  retryNow,
  getState: () => state,
  subscribe: (listener: () => void) => {
    listeners.add(listener);
    return () => void listeners.delete(listener);
  },
  topics: () => [], // the CMP-076 chip's (#5345): no topic is consumed here
  clockMs: () => performance.now(), // and the clock they are on
} as unknown as WsClientHandle; // the slots read only `getState`, `subscribe`, `retryNow`, `topics`, `clockMs`
const go = (next: WsState): void =>
  act(() => {
    state = next;
    listeners.forEach((listener) => listener());
  });
const region = (): HTMLElement => screen.getByRole("region", { name: "Connection" });
/** The shell announcer's region: rendered last, after CMP-092's polite one in the banner slot. */
const announcerRegion = (live: "polite" | "assertive"): HTMLElement => {
  const el = [...document.querySelectorAll<HTMLElement>(`[aria-live="${live}"]`)].at(-1);
  if (el === undefined) throw new Error(`no ${live} region`);
  return el;
};
const assertive = (): HTMLElement => announcerRegion("assertive");

/** Every message written into the assertive region from now on, a first render's included. */
function watchAssertive(): Node[] {
  const said: Node[] = [];
  const watch = new MutationObserver((records) => {
    for (const r of records) {
      const live = (r.target as Element).getAttribute?.("aria-live");
      if (live === "assertive") said.push(...r.addedNodes);
    }
  });
  watch.observe(document.body, { childList: true, subtree: true });
  return said;
}
const settle = async (): Promise<void> => {
  await Promise.resolve(); // the observer's records arrive as a microtask
};

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(T0);
  retryNow.mockClear();
  state = UP;
  act(() => setActiveClient(client));
});
afterEach(() => {
  act(() => {
    setActiveClient(null);
    resetShellState();
    clearAnnouncements();
  });
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("CMP-077 region: one view per state", () => {
  it("renders nothing while live: the banner slot holds only CMP-092's empty polite region", () => {
    const { container } = render(<ShellBannerSlot />);
    expect(screen.queryByRole("region")).toBeNull(); // its assertive words: the shell announcer's
    expect(
      [...container.children].map((c) => [c.getAttribute("aria-live"), c.textContent]),
    ).toEqual([["polite", ""]]);
  });

  const CASES: readonly [string, () => void, string, readonly string[], boolean][] = [
    [
      "reconnecting",
      () => go(DROPPED),
      "Disconnected — reconnecting (1)",
      ["Next try in ~4 s"],
      true,
    ],
    [
      "long-outage",
      () => {
        go(DROPPED);
        act(() => vi.advanceTimersByTime(300_000));
      },
      "Disconnected for 05:00 — escalated",
      ["Last data 05:12 ago."],
      true,
    ],
    [
      "offline fatal",
      () => go(fatal(1002)),
      "Offline — retry stopped",
      ["disagree on the protocol"],
      true,
    ],
    ["session ended", () => go(fatal(4403)), "Session ended", ["Your access was removed"], false],
    [
      "R1",
      () => go(reduce(UP, shutdown)),
      "Order entry off — backend restarting",
      ["Cancel and close"],
      false,
    ],
    [
      "R2",
      () => go(reduce(UP, killSwitch(ON))),
      "trading frozen by the owner",
      ["Cancel still works."],
      false,
    ],
    [
      "R5",
      () =>
        act(() =>
          setShellState({ degraded: { ...INITIAL_DEGRADED_FACTS, privateHandedOver: true } }),
        ),
      "private feed down",
      ["confirmed over REST"],
      false,
    ],
    [
      "R6",
      () => go(run(connecting, authOk(), stream("live"))),
      "kill-switch status unknown",
      [],
      false,
    ],
  ];

  it.each(CASES)(
    "%s: its title and lines, pointer events on, no axe failure",
    async (_, to, title, texts, retry) => {
      render(<ShellBannerSlot />);
      to();
      const el = region();
      expect(within(el).getByText(title, { exact: false })).toBeInTheDocument();
      for (const text of texts) expect(el).toHaveTextContent(text);
      // Retry now on a down link that may come back; never on a session end or a read-only reason.
      expect(within(el).queryByRole("button", { name: "Retry now" }) !== null).toBe(retry);
      vi.useRealTimers(); // axe schedules with real timers
      expect(await seriousAxe(document.body)).toEqual([]);
    },
  );

  it("emphasises the age line from T4 30 s", () => {
    render(<ShellBannerSlot />);
    go(DROPPED);
    const age = (): HTMLElement => within(region()).getByText(/^Last data/);
    expect(age().style.color).toBe("");
    act(() => vi.advanceTimersByTime(30_000));
    expect(age()).toHaveTextContent("Last data 00:42 ago.");
    expect(age().style.color).toBe("var(--color-status-danger-strong)");
  });
});

describe("CMP-077 region: Retry now (#304 S10, BQ-07)", () => {
  it("asks the client for one handshake from the keyboard, and stays focused while it runs", () => {
    render(<ShellBannerSlot />);
    go(DROPPED);
    const button = within(region()).getByRole("button", { name: "Retry now" });
    expect(button.tagName).toBe("BUTTON");
    expect(button.tabIndex).toBe(0);
    button.focus();
    // Enter / Space on a native <button> dispatch a click with detail 0 (no user-event devDependency)
    fireEvent.click(document.activeElement ?? document.body, { detail: 0 });
    expect(retryNow).toHaveBeenCalledTimes(1);
    go(reduce(DROPPED, connecting)); // the handshake is under way
    const busy = within(region()).getByRole("button", { name: "Retry now" });
    expect(busy).toHaveFocus();
    expect(busy).toHaveAttribute("aria-busy", "true");
    fireEvent.click(busy, { detail: 0 });
    expect(retryNow).toHaveBeenCalledTimes(1); // busy: a press does nothing, never a loop
  });

  it("offers no retry after a 4403: the session ended, sign in again", () => {
    render(<ShellBannerSlot />);
    go(fatal(4403));
    expect(within(region()).queryByRole("button", { name: "Retry now" })).toBeNull();
    expect(within(region()).getByRole("button", { name: "Sign in" })).toBeInTheDocument();
    expect(retryNow).not.toHaveBeenCalled();
  });
});

describe("CMP-077 region: the 1 Hz clock", () => {
  it("ticks the countdown while it shows, and stops once it does not", () => {
    render(<ShellBannerSlot />);
    expect(vi.getTimerCount()).toBe(0);
    go(DROPPED);
    expect(within(region()).getByText("Next try in ~4 s")).toHaveAttribute("aria-live", "off");
    act(() => vi.advanceTimersByTime(1_000));
    expect(within(region()).getByText("Next try in ~3 s")).toBeInTheDocument();
    expect(region()).toHaveTextContent("Last data 00:13 ago.");
    expect(vi.getTimerCount()).toBe(1);
    go(fatal(1002));
    expect(vi.getTimerCount()).toBe(0);
    go(UP);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("under StrictMode, mounted already disconnected: one interval and one announcement", async () => {
    state = DROPPED;
    const said = watchAssertive();
    render(
      <StrictMode>
        <ShellBannerSlot />
        <ShellAnnouncer />
      </StrictMode>,
    );
    await settle();
    expect(vi.getTimerCount()).toBe(1);
    expect(said).toHaveLength(1);
  });

  it("stops the interval on unmount", () => {
    state = DROPPED;
    const { unmount } = render(<ShellBannerSlot />);
    expect(vi.getTimerCount()).toBe(1);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });
});

describe("CMP-077 region: the stops clause needs the stream (E29-S07, BQ-7, C-2.6)", () => {
  const A = "a1000000-0000-4000-8000-00000000000a";
  const ME = { accounts: [{ exchange_account_id: A, label: "Sub-1" }] } as unknown as Me;

  it("a held verdict is claimed while the stream is live, and not while the link is up and it is not", async () => {
    vi.spyOn(positionsApi, "listPositions").mockResolvedValue({
      kind: "ok",
      items: [],
      aggregates: [],
    });
    act(() => setShellState({ me: ME }));
    // the reassurance watch consumes the `positions` topic: an idle handle, no frame arrives
    const idle = { read: () => [], release: () => undefined };
    act(() => setActiveClient({ ...client, consume: () => idle } as unknown as WsClientHandle));
    render(<ShellBannerSlot />);
    const live = run(connecting, authOk(OFF), stream("live"), shutdown);
    go(live);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(300); // the read's answer and the watch's first drain
    });
    expect(getReassurance().get(A)?.kind).toBe("true");
    expect(region()).toHaveTextContent("exchange-side stops still protect open positions");
    go(reduce(live, stream("resyncing"))); // the link is up; the watch's baseline is not
    expect(region()).not.toHaveTextContent("stops still protect");
    expect(region()).toHaveTextContent(
      "Cancel and close still work; app-managed rules are paused.",
    );
  });
});

describe("CMP-077 region: announcements through the shell announcer (§11)", () => {
  function mountBoth(): Node[] {
    const said = watchAssertive();
    render(
      <>
        <ShellConnectionSlot />
        <ShellBannerSlot />
        <ShellAnnouncer />
      </>,
    );
    return said;
  }
  const SOCKET_FIRST = (next: WsState, connection: ConnectionState): void => {
    go(next);
    act(() => setShellState({ connection }));
  };
  const STORE_FIRST = (next: WsState, connection: ConnectionState): void => {
    act(() => setShellState({ connection }));
    go(next);
  };
  // E29-S07 (#1028, BQ-7 ruled 6610918411): no account is confirmed in these sessions (`/me` names
  // none), so the stops clause is dropped (fail closed); `reassurance.test.tsx` covers it kept.
  const ROW_1 =
    "Disconnected. New orders off. Cancel and close still work, confirmed over the server.";
  const DOWN: ConnectionState = { kind: "offline", cause: "backend_unreachable" };

  // The two sources in separate commits, in either order: the chip never speaks, the region once.
  it.each([
    ["socket first", SOCKET_FIRST],
    ["store first", STORE_FIRST],
  ])("says row 1 once per episode with the chip mounted, %s", async (_, both) => {
    const said = mountBoth();
    both(UP, { kind: "live" });
    both(DROPPED, { kind: "reconnecting", attempt: 1, nextAttemptAtMs: T0 + 4_000 });
    for (let s = 0; s < 40; s += 1) act(() => void vi.advanceTimersByTime(1_000));
    const retry2 = reduce(DROPPED, { type: "connecting" });
    both(retry2, { kind: "connecting" });
    const attempt2 = { type: "reconnecting", attempt: 2, nextAttemptAtMs: T0 + 45_000 } as const;
    both(reduce(retry2, attempt2), {
      kind: "reconnecting",
      attempt: 2,
      nextAttemptAtMs: T0 + 45_000,
    });
    await settle();
    expect(said.map((p) => p.textContent)).toEqual([ROW_1]);
    // The return to live ends the episode and empties the region; the next drop speaks again, once.
    both(UP, { kind: "live" });
    expect(assertive()).toBeEmptyDOMElement();
    const again = {
      type: "reconnecting",
      attempt: 1,
      nextAttemptAtMs: T0 + 50_000,
      lost: LOST,
    } as const;
    both(reduce(UP, again), { kind: "reconnecting", attempt: 1, nextAttemptAtMs: T0 + 50_000 });
    await settle();
    expect(said.map((p) => p.textContent)).toEqual([ROW_1, ROW_1]);
  });

  it.each([
    [4403, "Your access was removed — contact the owner."],
    [
      1002,
      "Offline — retry stopped. New orders off. Cancel and close still work, confirmed over the server.",
    ],
  ])("UP → fatal %i with the chip mounted: one message, the region's", async (code, text) => {
    const said = mountBoth();
    SOCKET_FIRST(UP, { kind: "live" });
    SOCKET_FIRST(fatal(code), DOWN);
    await settle();
    expect(said.map((p) => p.textContent)).toEqual([text]);
    if (code === 4403) expect(assertive()).not.toHaveTextContent("Cancel and close still work");
  });

  // E42-S03 (SCR-124 V-8): while a view-as context is held, a 4403 is the server ending or holding
  // it (`bye` `view_as_expired`), never "Session ended": the banner speaks, the region does not
  const HELD: HeldViewAs = {
    kind: "held",
    targetId: "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0002",
    targetName: "alex",
    startedAtMs: T0 - 1_800_000,
    expiresAtMs: T0,
    state: "expired",
    offsetMs: 0,
  };

  it("shows nothing and says nothing for a 4403 while a view-as context is held; with none it reads Session ended", async () => {
    act(() => setShellState({ viewAs: HELD }));
    const said = mountBoth();
    SOCKET_FIRST(UP, { kind: "live" });
    SOCKET_FIRST(fatal(4403), DOWN);
    await settle();
    expect(screen.queryByRole("region", { name: "Connection" })).toBeNull();
    expect(said).toEqual([]);
    act(() => setShellState({ viewAs: { kind: "none" } }));
    await settle();
    expect(region()).toHaveTextContent("Session ended");
    expect(said.map((p) => p.textContent)).toEqual([
      "Your access was removed — contact the owner.",
    ]);
  });

  it("still shows any other stop while a view-as context is held", async () => {
    act(() => setShellState({ viewAs: { ...HELD, state: "active" } }));
    const said = mountBoth();
    SOCKET_FIRST(UP, { kind: "live" });
    SOCKET_FIRST(fatal(1002), DOWN);
    await settle();
    expect(region()).toHaveTextContent("Offline — retry stopped");
    expect(said).toHaveLength(1);
  });

  // A viewer disabled while viewing also gets a 4403 (`bye user_disabled`, `23` §9.6), which the
  // region mutes: the view-as source's re-read on that close is what surfaces it, as a 401
  it("leaves a revocation to the source's re-read: a 4403 while held, then its 401, ends in the holder's sign-in", async () => {
    const assign = vi.fn();
    const { origin } = window.location;
    vi.stubGlobal("location", { origin, pathname: "/positions", search: "", assign });
    const context = {
      target_user_id: HELD.targetId,
      target_username: "alex",
      target_display_name: null,
      started_at: new Date(T0 - 60_000).toISOString(),
      expires_at: new Date(T0 + 1_740_000).toISOString(),
      read_only: true,
      state: "active",
    };
    let reads = 0;
    // the view-as read's transport: the boot read answers live, the re-read 401 (`23` §9.5)
    const fetchImpl = vi.fn(async () =>
      (reads += 1) === 1
        ? new Response(JSON.stringify(context), { status: 200 })
        : new Response(JSON.stringify({ status: 401, code: "unauthenticated" }), { status: 401 }),
    ) as unknown as typeof fetch; // a transport double: only its answers are read
    // the holder's one renewal on that 401 finds the session gone
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify({ status: 401, code: "refresh_token_invalid" }), {
            status: 401,
          }),
      ),
    );
    accessToken.set({
      access_token: ["probe", "1", "x".repeat(20)].join("-"),
      token_type: "Bearer",
      expires_in: 600,
    });
    const stop = startViewAsSync({ fetchImpl, openChannel: () => null, reload: vi.fn() });
    try {
      await bootViewAs({ fetchImpl });
      const said = mountBoth();
      SOCKET_FIRST(UP, { kind: "live" });
      SOCKET_FIRST(fatal(4403), DOWN);
      await vi.waitFor(() => expect(assign).toHaveBeenCalledWith("/login?next=%2Fpositions"));
      expect(reads).toBe(2);
      expect(screen.queryByRole("region", { name: "Connection" })).toBeNull();
      expect(said).toEqual([]);
    } finally {
      stop();
      resetViewAs();
      accessToken.clear();
      localStorage.removeItem(REFRESH_SENT_KEY);
      vi.unstubAllGlobals();
    }
  });

  it("ends the episode for the connection keys only: another writer's message survives", () => {
    mountBoth();
    go(DROPPED);
    act(() => void announce("polite", "Layout changed to 2 by 2", "layout:preset"));
    go(UP);
    expect(assertive()).toBeEmptyDOMElement();
    expect(announcerRegion("polite")).toHaveTextContent("Layout changed to 2 by 2");
    act(() => expect(announce("polite", "Layout changed to 2 by 2", "layout:preset")).toBe(false));
  });

  it("says row 14 once per stop, and row 2 per read-only reason", async () => {
    const said = mountBoth();
    go(fatal(1002));
    go(reduce(UP, killSwitch(ON)));
    go(reduce(reduce(UP, killSwitch(ON)), shutdown));
    await settle();
    expect(said.map((p) => p.textContent)).toEqual([
      "Offline — retry stopped. New orders off. Cancel and close still work, confirmed over the server.",
      "Order entry off — trading frozen by the owner. Cancel still works.",
      "Order entry off — backend restarting. Cancel and close still work; app-managed rules are paused.",
    ]);
  });
});

describe("CMP-077 region: focus, keyboard and the outlet", () => {
  it("never moves focus; Sign in is a Tab stop that routes through the auth path", () => {
    const endSession = vi.spyOn(accessToken, "endSession").mockImplementation(() => undefined);
    render(
      <>
        <button type="button">Cancel order</button>
        <ShellBannerSlot />
      </>,
    );
    const cancel = screen.getByRole("button", { name: "Cancel order" });
    cancel.focus();
    go(fatal(4403));
    expect(document.activeElement).toBe(cancel);
    const signIn = within(region()).getByRole("button", { name: "Sign in" });
    expect(signIn.tabIndex).toBe(0);
    expect(region().querySelector("[tabindex='-1']")).toBeNull(); // no trap, nothing pulled out
    fireEvent.click(signIn);
    expect(endSession).toHaveBeenCalledTimes(1);
  });

  it("renders in the banner slot below the top bar, never over the canvas", () => {
    render(
      <AppShell mainId="m" banner={<ShellBannerSlot />} canvasOverlay={<ShellCanvasOverlaySlot />}>
        <h1>Screen</h1>
      </AppShell>,
    );
    go(DROPPED);
    const banner = document.querySelector('[data-shell-slot="banner"]');
    const overlay = document.querySelector('[data-shell-slot="canvas-overlay"]');
    expect(banner?.contains(region())).toBe(true);
    // E17-D02 §8: CMP-092 renders below the region (its live-region pair follows it).
    expect(banner?.firstElementChild).toBe(region());
    expect(region().nextElementSibling?.getAttribute("aria-live")).toBe("polite");
    expect(overlay).toBeEmptyDOMElement();
    expect(screen.getByRole("main").contains(region())).toBe(false);
  });

  it("renders beside the outlet without remounting or re-rendering it", () => {
    let mounts = 0;
    let renders = 0;
    function Screen(): JSX.Element {
      renders += 1;
      useEffect(() => {
        mounts += 1;
      }, []);
      return <h1>Screen</h1>;
    }
    render(
      <AppShell mainId="m" banner={<ShellBannerSlot />}>
        <Screen />
      </AppShell>,
    );
    go(DROPPED);
    act(() => vi.advanceTimersByTime(5_000));
    go(fatal(4403));
    go(UP);
    expect(screen.queryByRole("region", { name: "Connection" })).toBeNull();
    expect([mounts, renders]).toEqual([1, 1]);
  });
});

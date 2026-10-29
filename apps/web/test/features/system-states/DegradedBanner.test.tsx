// E10-S04 (#306) slice 3: the SCR-153 banner in the shell's banner slot (CMP-092, E17-D02 §8, §11,
// §13). RTL by role: every severity, the §6 order, announce-once (the assertive words through the
// shell announcer at their turn), dismissal and re-assert, focus after it (E10-D04 T-19), axe.
import { createRequire } from "node:module";
import { StrictMode, type ReactNode } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "../../../src/features/app-shell/AppShell";
import {
  announce,
  clearAnnouncements,
  REGION_BUDGET_MS,
  ShellAnnouncer,
} from "../../../src/features/app-shell/announcer";
import { ShellBannerSlot } from "../../../src/features/app-shell/slots";
import { SEARCH_TRIGGER_ID } from "../../../src/features/app-shell/TopBar";
import { POLITE_GAP_MS } from "../../../src/features/system-states/DegradedBanner";
import { DEGRADED_COPY } from "../../../src/features/system-states/copy";
import {
  applySystemUpdate,
  resetShellState,
  setShellState,
  type SystemUpdate,
} from "../../../src/shell/bootstrap/store";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

const say = (u: object): void => act(() => applySystemUpdate(u as SystemUpdate));
const MAINTENANCE = { kind: "notice", reason: "maintenance.enabled" };
const FEED_DOWN = { kind: "exchange_state", public_ws: "disconnected" };
const FEED_UP = { kind: "exchange_state", public_ws: "connected" };
const RULES_DOWN = { kind: "health", components: [{ name: "rule_engine", state: "down" }] };
const { maintenance, exchangeFeedDown, ruleEngineDown } = DEGRADED_COPY;

const dismissNames = (): string[] =>
  screen
    .getAllByRole("button", { name: /^Dismiss / })
    .map((b) => b.getAttribute("aria-label") ?? "");
/** The last region of each kind: CMP-092's own polite one, the shell announcer's assertive one. */
const region = (live: "polite" | "assertive"): Element | undefined =>
  [...document.querySelectorAll(`[aria-live="${live}"]`)].at(-1);
const alertText = (): string => region("assertive")?.textContent ?? "";
const statusText = (): string => region("polite")?.textContent ?? "";

async function expectNoSeriousAxe(): Promise<void> {
  vi.useRealTimers(); // axe schedules with real timers; jsdom has no canvas for contrast
  const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
  expect(res.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
    [],
  );
}

/** CMP-070's frame: a search trigger in the TopBar, the banner slot, then a canvas control. */
const shell = (banner: ReactNode = <ShellBannerSlot />) =>
  render(
    <AppShell
      mainId="m"
      topBar={() => (
        <button type="button" id={SEARCH_TRIGGER_ID}>
          Search commands
        </button>
      )}
      banner={banner}
    >
      <button type="button">Chart control</button>
    </AppShell>,
  );

beforeEach(() => {
  resetShellState();
  clearAnnouncements();
  render(<ShellAnnouncer />); // ShellLayout's, first here: the rows render after it
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
  resetShellState();
});

describe("CMP-092 DegradedModeBanner in ShellBannerSlot", () => {
  it("pre-renders both regions empty at load and no rows; clears them when the last row goes", async () => {
    render(<ShellBannerSlot />);
    expect(screen.queryByRole("button")).toBeNull();
    expect([statusText(), alertText()]).toEqual(["", ""]); // §11: pre-rendered empty at load
    say(FEED_DOWN);
    expect(statusText()).toBe(exchangeFeedDown.message);
    say(FEED_UP);
    expect(statusText()).toBe(""); // no stale sentence left behind
    say(MAINTENANCE);
    expect(alertText()).toBe(`${maintenance.message} ${maintenance.stillWorks}`);
    await expectNoSeriousAxe();
  });

  it.each([
    ["blocking", MAINTENANCE, "Blocking", maintenance],
    ["warning", FEED_DOWN, "Warning", exchangeFeedDown],
    ["info", RULES_DOWN, "Info", ruleEngineDown],
  ])(
    "shows a %s row with its word, message, stillWorks and dismiss control",
    async (_s, frame, word, copy) => {
      render(<ShellBannerSlot />);
      say(frame);
      expect(screen.getByText(word)).toBeInTheDocument();
      expect(screen.getByText(copy.message, { selector: "span span" })).toBeInTheDocument();
      expect(
        screen.getByText(copy.stillWorks, { exact: false, selector: "span span" }),
      ).toBeTruthy();
      expect(dismissNames()).toEqual([`Dismiss ${copy.message}`]);
      await expectNoSeriousAxe();
    },
  );

  it("orders the rows blocking, warning, info whatever order the frames came in", async () => {
    render(<ShellBannerSlot />);
    say(RULES_DOWN);
    say(FEED_DOWN);
    say(MAINTENANCE);
    expect(dismissNames()).toEqual([
      `Dismiss ${maintenance.message}`,
      `Dismiss ${exchangeFeedDown.message}`,
      `Dismiss ${ruleEngineDown.message}`,
    ]);
    await expectNoSeriousAxe();
  });

  it("announces a blocking row assertively once, never again per re-asserting frame", () => {
    render(<ShellBannerSlot />);
    say(MAINTENANCE);
    expect(alertText()).toBe(`${maintenance.message} ${maintenance.stillWorks}`);
    const node = region("assertive")?.firstChild;
    say(MAINTENANCE);
    act(() => setShellState({ connection: { kind: "live" } })); // an unrelated store change
    expect(region("assertive")?.firstChild).toBe(node);
    expect(statusText()).toBe("");
  });

  it("announces info and warning rows politely, ≤1 per 5 s, dropping rows that left meanwhile", () => {
    render(<ShellBannerSlot />);
    say(FEED_DOWN);
    expect(statusText()).toBe(exchangeFeedDown.message);
    say(RULES_DOWN);
    say({ kind: "health", components: [{ name: "recorder", state: "down" }] });
    say({ kind: "health", components: [{ name: "recorder", state: "up" }] });
    expect(statusText()).toBe(exchangeFeedDown.message);
    act(() => vi.advanceTimersByTime(POLITE_GAP_MS));
    expect(statusText()).toBe(ruleEngineDown.message);
    expect(alertText()).toBe("");
  });

  it("hides a dismissed row until a frame re-asserts it, then shows and announces it again", () => {
    render(<ShellBannerSlot />);
    say(MAINTENANCE);
    say(RULES_DOWN);
    const before = region("assertive")?.firstChild;
    fireEvent.click(screen.getByRole("button", { name: `Dismiss ${maintenance.message}` }));
    expect(dismissNames()).toEqual([`Dismiss ${ruleEngineDown.message}`]);
    expect(document.activeElement).toBe(screen.getByRole("button", { name: /^Dismiss Armed/ }));
    act(() => setShellState({ preferencesWarning: "x" })); // no frame: stays dismissed
    expect(dismissNames()).toHaveLength(1);
    say(MAINTENANCE);
    expect(dismissNames()[0]).toBe(`Dismiss ${maintenance.message}`);
    expect(region("assertive")?.firstChild).toBe(before); // its turn: 5 s after its last words
    act(() => vi.advanceTimersByTime(REGION_BUDGET_MS));
    expect(region("assertive")?.firstChild).not.toBe(before);
    expect(alertText()).toBe(`${maintenance.message} ${maintenance.stillWorks}`);
  });

  it("forgets a dismissal once the condition clears, so the next episode shows at once", () => {
    render(<ShellBannerSlot />);
    say(FEED_DOWN);
    fireEvent.click(screen.getByRole("button", { name: `Dismiss ${exchangeFeedDown.message}` }));
    expect(screen.queryByRole("button")).toBeNull();
    say(FEED_UP);
    say(FEED_DOWN); // a new episode starts its count again at 1
    expect(dismissNames()).toEqual([`Dismiss ${exchangeFeedDown.message}`]);
  });

  it("after the last row's dismissal focuses the next banner, else the search trigger (E10-D04 T-19)", () => {
    say(RULES_DOWN);
    const first = shell(
      <>
        <ShellBannerSlot />
        <button type="button">Next banner</button>
      </>,
    );
    fireEvent.click(screen.getByRole("button", { name: `Dismiss ${ruleEngineDown.message}` }));
    expect(screen.queryByRole("button", { name: /^Dismiss / })).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Next banner" }));
    first.unmount();
    shell(); // no banner follows: never the canvas's first control, where a held key could act
    fireEvent.click(screen.getByRole("button", { name: `Dismiss ${ruleEngineDown.message}` }));
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Search commands" }));
  });

  it("dismisses from the keyboard: a native button in the Tab order, activated with detail 0", () => {
    // Enter / Space on a native <button> dispatch a click with detail 0; user-event is not a web
    // devDependency, so the keyboard path is that click on the focused control.
    render(<ShellBannerSlot />);
    say(FEED_DOWN);
    const dismiss = screen.getByRole("button", { name: `Dismiss ${exchangeFeedDown.message}` });
    expect(dismiss.tagName).toBe("BUTTON");
    expect(dismiss.tabIndex).toBe(0);
    dismiss.focus();
    fireEvent.click(document.activeElement ?? document.body, { detail: 0 });
    expect(screen.queryByRole("button", { name: /^Dismiss / })).toBeNull();
  });

  it("clears the pending polite timer and the assertive turn on unmount", () => {
    const { unmount } = render(<ShellBannerSlot />);
    say(FEED_DOWN);
    say(RULES_DOWN); // queued behind the 5 s gap
    say(MAINTENANCE);
    say({ kind: "health", components: [{ name: "postgres", state: "down" }] }); // waits its turn
    expect(vi.getTimerCount()).toBe(2);
    unmount();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("never announces late a row dismissed while it was queued", () => {
    render(<ShellBannerSlot />);
    say(FEED_DOWN);
    say(RULES_DOWN);
    fireEvent.click(screen.getByRole("button", { name: `Dismiss ${ruleEngineDown.message}` }));
    act(() => vi.advanceTimersByTime(POLITE_GAP_MS));
    expect(statusText()).toBe(exchangeFeedDown.message);
  });
});

describe("SR-023: the break-glass notice in ShellBannerSlot", () => {
  /** `23` §15.9, as services/api/candleviewer/auth/break_glass_notice.py sends it after a first `auth_ok`. */
  const BREAK_GLASS = {
    kind: "notice",
    severity: "critical",
    message: "Break-glass recovery was used on this server; the Owner must review it.",
    reason: "auth.break_glass_used",
  };
  const SAID = `${BREAK_GLASS.message} Order entry unaffected.`;

  it("renders one Warning row, announced assertively once, and never moves focus", async () => {
    render(
      <>
        <button type="button">Before</button>
        <ShellBannerSlot />
      </>,
    );
    const before = screen.getByRole("button", { name: "Before" });
    before.focus();
    say(BREAK_GLASS);
    expect(screen.getByText("Warning")).toBeInTheDocument();
    expect(screen.queryByText("Blocking")).toBeNull(); // it gates nothing (`23` §15.9)
    expect(screen.getByText(BREAK_GLASS.message, { selector: "span span" })).toBeInTheDocument();
    expect(
      screen.getByText("Order entry unaffected.", { exact: false, selector: "span span" }),
    ).toBeTruthy();
    expect(dismissNames()).toEqual([`Dismiss ${BREAK_GLASS.message}`]);
    expect([alertText(), statusText()]).toEqual([SAID, ""]);
    expect(document.activeElement).toBe(before);
    await expectNoSeriousAxe();
  });

  it("says nothing again until a dismissed row is re-asserted by the next notice", () => {
    render(<ShellBannerSlot />);
    say(BREAK_GLASS);
    const node = region("assertive")?.firstChild;
    act(() => setShellState({ connection: { kind: "live" } })); // an in-place re-auth: no frame
    say(BREAK_GLASS); // the same notice while the row shows: no second row, no second announcement
    expect(region("assertive")?.firstChild).toBe(node);
    expect(dismissNames()).toHaveLength(1);
    const dismiss = screen.getByRole("button", { name: `Dismiss ${BREAK_GLASS.message}` });
    dismiss.focus();
    fireEvent.click(document.activeElement ?? document.body, { detail: 0 }); // Enter on the button
    act(() => setShellState({ preferencesWarning: "x" })); // no frame: it stays dismissed
    expect(screen.queryByRole("button", { name: /^Dismiss / })).toBeNull();
    expect(alertText()).toBe(""); // the last row went: no stale sentence
    say(BREAK_GLASS); // a reconnect's first auth while the reset is unresolved
    expect(dismissNames()).toEqual([`Dismiss ${BREAK_GLASS.message}`]);
    act(() => vi.advanceTimersByTime(REGION_BUDGET_MS)); // its turn: 5 s after its last words
    expect(alertText()).toBe(SAID);
  });

  it("speaks rows entering in one commit as one message, in the §6 order", () => {
    render(<ShellBannerSlot />);
    act(() => [BREAK_GLASS, MAINTENANCE].forEach((u) => applySystemUpdate(u as SystemUpdate)));
    expect(alertText()).toBe(`${maintenance.message} ${maintenance.stillWorks} ${SAID}`);
  });

  it("speaks a row entering close behind another after the other's words, never over them", () => {
    render(<ShellBannerSlot />);
    say(MAINTENANCE); // the first-auth burst: a gate notice, then this one, each in its own commit
    say(BREAK_GLASS);
    expect(alertText()).toBe(`${maintenance.message} ${maintenance.stillWorks}`);
    act(() => vi.advanceTimersByTime(REGION_BUDGET_MS - 1));
    expect(alertText()).toBe(`${maintenance.message} ${maintenance.stillWorks}`);
    act(() => vi.advanceTimersByTime(1));
    expect(alertText()).toBe(SAID);
  });
});

describe("CMP-092's assertive turn: 9a's 15 s cap", () => {
  it("holds across frames that re-assert a held row while another writer keeps speaking", () => {
    render(<ShellBannerSlot />);
    let n = 0;
    const noise = (): void => act(() => void announce("assertive", `noise ${(n += 1)}`, `n:${n}`));
    noise();
    say(MAINTENANCE);
    let spokenAt: number | null = null;
    for (let s = 1; s <= 30 && spokenAt === null; s += 1) {
      act(() => vi.advanceTimersByTime(1_000));
      say({ kind: "feature_flags", feature_flags: { "maintenance.mode": true } }); // re-asserts the row
      if (s % 4 === 0) noise();
      if (alertText() === `${maintenance.message} ${maintenance.stillWorks}`) spokenAt = s;
    }
    expect(spokenAt).not.toBeNull();
    expect(spokenAt).toBeLessThanOrEqual(16);
  });

  it("keeps its turn under StrictMode: waits out a busy region, then speaks once", () => {
    render(
      <StrictMode>
        <ShellBannerSlot />
      </StrictMode>,
    );
    act(() => void announce("assertive", "Disconnected. New orders off.", "connection:off"));
    say(MAINTENANCE);
    const seq = (): string | null =>
      region("assertive")?.firstElementChild?.getAttribute("data-seq") ?? null;
    expect(alertText()).toBe("Disconnected. New orders off.");
    act(() => vi.advanceTimersByTime(REGION_BUDGET_MS - 1));
    expect(alertText()).toBe("Disconnected. New orders off.");
    act(() => vi.advanceTimersByTime(1));
    expect(alertText()).toBe(`${maintenance.message} ${maintenance.stillWorks}`);
    const said = seq();
    act(() => vi.advanceTimersByTime(60_000));
    expect(seq()).toBe(said); // said once: no second write
  });
});

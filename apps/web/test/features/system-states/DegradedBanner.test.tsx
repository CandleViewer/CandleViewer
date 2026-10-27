// E10-S04 (#306) slice 3: the SCR-153 banner in the shell's banner slot (CMP-092, E17-D02 §8, §11,
// §13). RTL by role: every severity, the §6 order, announce-once, dismissal and re-assert, axe.
import { createRequire } from "node:module";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ShellBannerSlot } from "../../../src/features/app-shell/slots";
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
const alertText = (): string => screen.getByRole("alert").textContent ?? "";
const statusText = (): string => screen.getByRole("status").textContent ?? "";

async function expectNoSeriousAxe(): Promise<void> {
  vi.useRealTimers(); // axe schedules with real timers; jsdom has no canvas for contrast
  const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
  expect(res.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
    [],
  );
}

beforeEach(() => {
  resetShellState();
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
    const node = screen.getByRole("alert").firstChild;
    say(MAINTENANCE);
    act(() => setShellState({ connection: { kind: "live" } })); // an unrelated store change
    expect(screen.getByRole("alert").firstChild).toBe(node);
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
    const before = screen.getByRole("alert").firstChild;
    fireEvent.click(screen.getByRole("button", { name: `Dismiss ${maintenance.message}` }));
    expect(dismissNames()).toEqual([`Dismiss ${ruleEngineDown.message}`]);
    expect(document.activeElement).toBe(screen.getByRole("button", { name: /^Dismiss Armed/ }));
    act(() => setShellState({ preferencesWarning: "x" })); // no frame: stays dismissed
    expect(dismissNames()).toHaveLength(1);
    say(MAINTENANCE);
    expect(dismissNames()[0]).toBe(`Dismiss ${maintenance.message}`);
    expect(screen.getByRole("alert").firstChild).not.toBe(before);
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

  it("dismissing the last row moves focus to the next focusable element after the slot", () => {
    render(
      <>
        <ShellBannerSlot />
        <button type="button">Next stop</button>
      </>,
    );
    say(RULES_DOWN);
    fireEvent.click(screen.getByRole("button", { name: `Dismiss ${ruleEngineDown.message}` }));
    expect(screen.queryByRole("button", { name: /^Dismiss / })).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Next stop" }));
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

  it("clears the pending polite timer on unmount", () => {
    const { unmount } = render(<ShellBannerSlot />);
    say(FEED_DOWN);
    say(RULES_DOWN); // queued behind the 5 s gap
    expect(vi.getTimerCount()).toBe(1);
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

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
  it("renders nothing while nothing is degraded, and its regions empty with the first row", () => {
    const { container } = render(<ShellBannerSlot />);
    expect(container.childNodes).toHaveLength(0); // the slot's 0 px contract (and R-203's tree)
    say(FEED_DOWN);
    say({ kind: "exchange_state", public_ws: "connected" });
    expect(container.childNodes).toHaveLength(0);
    say(MAINTENANCE);
    expect(alertText()).toBe(`${maintenance.message} ${maintenance.stillWorks}`);
    expect(statusText()).toBe(""); // the earlier, cleared warning is not left behind
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
});

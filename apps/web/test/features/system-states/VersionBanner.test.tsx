// E10-S04 (#306) slice 10a: SCR-157's non-blocking banner (E10-D03 §9.1, board 10), by role: both
// variants, Later (E10-D04 T-19), analytics once per pair, nothing when compatible or incompatible,
// the band at once and its words after the announcer's window, axe, StrictMode, unmount.
import { createRequire } from "node:module";
import { StrictMode, type JSX, type ReactNode } from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "../../../src/features/app-shell/AppShell";
import {
  announce,
  clearAnnouncements,
  REGION_BUDGET_MS,
} from "../../../src/features/app-shell/announcer";
import { ShellBannerSlot } from "../../../src/features/app-shell/slots";
import { StatusBar } from "../../../src/features/app-shell/StatusBar";
import { TopBar } from "../../../src/features/app-shell/TopBar";
import { VersionBannerSlot } from "../../../src/features/system-states/VersionBanner";
import { resetVersionReports } from "../../../src/features/system-states/versionMismatch";
import type { CvBridge } from "../../../src/shell/ElectronShellAdapter";
import { resetShellState, setShellState } from "../../../src/shell/bootstrap/store";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

async function expectNoSeriousAxe(): Promise<void> {
  vi.useRealTimers(); // axe schedules with real timers; jsdom has no canvas for contrast
  const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
  expect(res.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
    [],
  );
}

/** A `welcome` as the store holds it (`null`: a protocol label refused); this client runs 0.1.0. */
const welcome = (protocol: string | null | undefined, version: string | undefined): void =>
  act(() => setShellState({ serverProtocol: protocol, serverVersion: version }));
const speak = (politeness: "polite" | "assertive", text: string): void =>
  act(() => void announce(politeness, text, `other:${text}`));
const advance = (ms: number): void => act(() => void vi.advanceTimersByTime(ms));
/** The band's hidden `role="status"` region: its words, said once at their turn. */
const spoken = (): string => screen.getByRole("status").textContent ?? "";
const reminder = (): Element | null => document.querySelector('[data-chip="update"]');
const SENTENCE =
  "This tab runs 0.1.0, the server serves 0.2.0. " +
  "Browser tabs update on page reload; there is no installer to update.";
const SPOKEN = `Update available. ${SENTENCE}`;

/** The shell's frame: the TopBar and its search trigger, the banner slot, a canvas control. */
function Shell({ banner }: { readonly banner: ReactNode }): JSX.Element {
  const topBar = (connection: JSX.Element): JSX.Element => (
    <TopBar
      env="unknown"
      user={null}
      connection={connection}
      searchHint="Ctrl+K"
      onSignOut={() => undefined}
      signingOut={false}
      signOutFailed={false}
    />
  );
  return (
    <AppShell mainId="m" topBar={topBar} banner={banner} status={<StatusBar />}>
      <button type="button">Chart control</button>
    </AppShell>
  );
}

let heard: unknown[];
const listen = (event: Event): void => void heard.push((event as CustomEvent).detail);
const said = (serverVersion: string) => ({
  name: "app.version_mismatch",
  clientVersion: "0.1.0",
  serverVersion,
  blocking: false,
});

beforeEach(() => {
  resetShellState();
  resetVersionReports();
  clearAnnouncements();
  heard = [];
  window.addEventListener("cv:analytics", listen);
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
  window.removeEventListener("cv:analytics", listen);
  Reflect.deleteProperty(window, "cv");
  resetShellState();
});

describe("SCR-157 update-available banner", () => {
  it("in a browser: the label, both versions, the adapter's reason, then Later and Reload (primary)", async () => {
    const reload = vi.fn();
    render(<VersionBannerSlot reload={reload} />);
    expect(screen.queryByRole("status")).toBeNull(); // nothing before the first welcome
    welcome("cv.v1", "0.2.0");
    expect(screen.getByText("Update available")).toBeInTheDocument();
    expect(screen.getByText(SENTENCE)).toBeInTheDocument();
    const region = screen.getByRole("status");
    expect([
      spoken(),
      region.getAttribute("aria-live"),
      region.getAttribute("aria-atomic"),
    ]).toEqual([SPOKEN, "polite", "true"]);
    const actions = screen.getAllByRole("button");
    expect(actions.map((b) => [b.textContent, b.dataset["variant"]])).toEqual([
      ["Later", "secondary"],
      ["Reload", "primary"],
    ]);
    expect(within(region).queryByRole("button")).toBeNull(); // not read with the words
    expect(screen.queryByRole("button", { name: /what's new|restart/i })).toBeNull(); // G-rows
    fireEvent.click(screen.getByRole("button", { name: "Reload" }));
    expect(reload).toHaveBeenCalledTimes(1);
    await expectNoSeriousAxe();
  });

  it("in the desktop app before signing: no Restart and update, no Reload, the release-page sentence", async () => {
    window.cv = {} as CvBridge; // the preload bridge marks the desktop shell, as createShellPort reads it
    render(<VersionBannerSlot reload={vi.fn()} />);
    welcome("cv.v1", "0.2.0");
    expect(spoken()).toBe(
      "Update available. This app runs 0.1.0, the server serves 0.2.0. " +
        "Updates are installed from the release page until signed auto-updates ship.",
    );
    expect(screen.getAllByRole("button").map((b) => b.textContent)).toEqual(["Later"]);
    await expectNoSeriousAxe();
  });

  it("Later: gone for the session, focus on the search trigger (E10-D04 T-19), the StatusBar reminds", () => {
    render(<Shell banner={<ShellBannerSlot />} />);
    welcome("cv.v1", "0.2.0");
    expect(reminder()).toBeNull(); // the reminder follows Later, never the banner
    const later = screen.getByRole("button", { name: "Later" });
    later.focus();
    fireEvent.click(later);
    expect(screen.queryByRole("button", { name: "Later" })).toBeNull();
    // no next banner: the TopBar's search trigger, never the canvas's next control
    expect(document.activeElement).toBe(screen.getByRole("button", { name: /^Search commands/ }));
    expect(reminder()?.textContent).toBe("Update available");
    // plain text beside the version, outside the StatusBar's live part: never re-announced
    expect(screen.getByRole("status", { name: "System status" }).contains(reminder())).toBe(false);
    welcome("cv.v1", "0.3.0"); // another build this session: still postponed
    expect(screen.queryByRole("button", { name: "Later" })).toBeNull();
    expect(heard).toEqual([said("0.2.0"), said("0.3.0")]); // the mismatch is still said
    welcome("cv.v1", "0.1.0"); // the same build again: nothing to remind of
    expect(reminder()).toBeNull();
  });

  it("Later: focus on the next banner's first control when one follows it (E10-D04 T-19)", () => {
    const banners = (
      <>
        <VersionBannerSlot />
        <button type="button">Next banner</button>
      </>
    );
    render(<Shell banner={banners} />);
    welcome("cv.v1", "0.2.0");
    fireEvent.click(screen.getByRole("button", { name: "Later" }));
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Next banner" }));
  });

  it.each<[string, string | null | undefined, string | undefined]>([
    ["before any welcome", undefined, undefined],
    ["for the same build", "cv.v1", "0.1.0"],
    ["for a build label the client did not keep", "cv.v1", undefined],
    ["for another protocol: 10b's blocking dialog, not this banner", "cv.v2", "0.2.0"],
    ["for a protocol label the worker refused: 10b's, failing closed", null, "0.2.0"],
  ])("shows, says and reports nothing %s", (_case, protocol, version) => {
    render(<VersionBannerSlot />);
    welcome(protocol, version);
    advance(REGION_BUDGET_MS);
    expect(document.querySelector("[data-version-banner]")).toBeNull();
    expect([screen.queryByRole("button"), heard]).toEqual([null, []]);
  });

  it("says its words and reports each pair once: StrictMode, an unrelated change, a remount", () => {
    const first = render(
      <StrictMode>
        <VersionBannerSlot />
      </StrictMode>,
    );
    welcome("cv.v1", "0.2.0");
    const words = screen.getByRole("status").firstChild;
    act(() => setShellState({ everLive: true }));
    expect(screen.getAllByRole("status")).toHaveLength(1);
    expect(screen.getByRole("status").firstChild).toBe(words);
    welcome("cv.v1", "0.3.0"); // a new pair: a new band and region, said again
    expect(screen.getByRole("status").firstChild).not.toBe(words);
    expect(spoken()).toContain("the server serves 0.3.0.");
    first.unmount();
    render(<VersionBannerSlot />);
    welcome("cv.v1", "0.2.0");
    expect(heard).toEqual([said("0.2.0"), said("0.3.0")]);
  });
});

describe("SCR-157's words (E17-D02 §11: polite, once, never cutting another writer)", () => {
  it("shows the band at once and says its words when the window after CMP-077's row 1 is over", () => {
    render(<VersionBannerSlot />);
    speak("assertive", "Disconnected. New orders off.");
    welcome("cv.v1", "0.2.0");
    expect(screen.getByText(SENTENCE)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Later" })).toBeInTheDocument(); // pressable at once
    expect(spoken()).toBe(""); // the region is in the tree before its words
    advance(REGION_BUDGET_MS - 1);
    expect(spoken()).toBe("");
    advance(1);
    expect(spoken()).toBe(SPOKEN);
  });

  it("never waits past the window when the wall clock steps back (9a's pin)", () => {
    render(<VersionBannerSlot />);
    speak("assertive", "Disconnected.");
    vi.setSystemTime(Date.now() - 3_600_000); // then the clock steps back an hour
    welcome("cv.v1", "0.2.0");
    advance(REGION_BUDGET_MS - 1);
    expect(spoken()).toBe("");
    advance(1);
    expect(spoken()).toBe(SPOKEN);
  });

  it("waits again when another writer speaks meanwhile, and gives way for 15 s in all at most", () => {
    render(<VersionBannerSlot />);
    speak("polite", "m0");
    welcome("cv.v1", "0.2.0");
    for (let s = 2; s <= 14; s += 2) {
      advance(2_000);
      speak(s % 4 === 0 ? "assertive" : "polite", `m${s}`); // a writer that never stops
    }
    advance(999);
    expect(spoken()).toBe("");
    advance(1); // 15 s after the welcome
    expect(spoken()).toBe(SPOKEN);
  });

  it("leaves no timer behind when it unmounts during its wait", () => {
    const { unmount } = render(<VersionBannerSlot />);
    speak("assertive", "Disconnected.");
    welcome("cv.v1", "0.2.0");
    const pending = vi.getTimerCount();
    unmount();
    expect(vi.getTimerCount()).toBe(pending - 1);
  });
});

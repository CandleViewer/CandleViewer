// E10-S04 (#306) slice 10b: SCR-157's blocking dialog (E10-D03 §9.1, boards 10 and 11; E10-D04
// T-15, T-16, T-18, §13.2), by role: when it opens (failing closed) and opens again, its words,
// focus, Tab, Esc, Continue read-only and the T2 leg that outlives it, analytics once per pair, the
// chrome left unscrimmed and live (E05-D02 H23), the 200 % reflow, axe.
import { createRequire } from "node:module";
import type { JSX } from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AppShell } from "../../../src/features/app-shell/AppShell";
import { ShellAnnouncer } from "../../../src/features/app-shell/announcer";
import { ShellBannerSlot } from "../../../src/features/app-shell/slots";
import { StatusBar } from "../../../src/features/app-shell/StatusBar";
import { TopBar } from "../../../src/features/app-shell/TopBar";
import {
  protocolLeg,
  resetVersionReports,
} from "../../../src/features/system-states/versionMismatch";
import { getShellState, resetShellState, setShellState } from "../../../src/shell/bootstrap/store";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

/** A `welcome` as the store holds it (`null`: a protocol label refused); this client runs 0.1.0. */
const welcome = (protocol: string | null | undefined, version?: string): void =>
  act(() => setShellState({ serverProtocol: protocol, serverVersion: version }));
const dialog = (): HTMLElement => screen.getByRole("alertdialog");
const button = (name: string | RegExp): HTMLElement => screen.getByRole("button", { name });
const HEADING = "This version can't trade with the server";
const STOPS = "What stops: new orders, cancel, reduce-only close, flatten, the in-app kill switch";
const WORKS = "Still works: read-only views — charts, positions, the journal";
const FALLBACK = "Fallback: the server console command";
/** The card's description in §9.1's order: the versions row, then what will happen (`14`). */
const described = (versions: string): string =>
  `${versions} ${STOPS} ${WORKS} ${FALLBACK} candleviewer kill`;

/** CMP-043's reflow breakpoint (`dialog.css`): 200 % zoom on the 1280 x 800 frame. */
const REFLOW = "(max-width: 40rem), (max-height: 25rem)";
let zoomed = false;
/** Zooms to 200 % or back: `matchMedia` answers as a 640 x 400 viewport would; a resize fires. */
const zoom = (on: boolean): void => {
  zoomed = on;
  fireEvent(window, new Event("resize"));
};
const inset = (side: "top" | "bottom"): string =>
  document.documentElement.style.getPropertyValue(`--cv-scrim-inset-${side}`);
/** Out of the accessibility tree and the focus order (CMP-043's inert page, or its fallback). */
const INERT = '[inert], [aria-hidden="true"]';

/** The shell's frame: the TopBar and its search trigger, the banner slot, a canvas control. */
function Shell(): JSX.Element {
  const topBar = (connection: JSX.Element): JSX.Element => (
    <TopBar
      env="unknown"
      user={null}
      connection={connection}
      searchHint="Ctrl+K"
      onSearch={() => undefined}
      onSignOut={() => undefined}
      signingOut={false}
      signOutFailed={false}
    />
  );
  return (
    <>
      <AppShell mainId="m" topBar={topBar} banner={<ShellBannerSlot />} status={<StatusBar />}>
        <button type="button">Chart control</button>
      </AppShell>
      <ShellAnnouncer />
    </>
  );
}

let heard: unknown[];
const listen = (event: Event): void => void heard.push((event as CustomEvent).detail);
const said = (serverVersion: string | null) => ({
  name: "app.version_mismatch",
  clientVersion: "0.1.0",
  serverVersion,
  blocking: true,
});

beforeEach(() => {
  zoomed = false;
  vi.stubGlobal(
    "matchMedia",
    (query: string) =>
      ({
        get matches() {
          return zoomed && query === REFLOW;
        },
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
      }) as unknown as MediaQueryList,
  );
  resetShellState();
  resetVersionReports();
  heard = [];
  window.addEventListener("cv:analytics", listen);
  render(<Shell />);
});
afterEach(() => {
  window.removeEventListener("cv:analytics", listen);
  vi.unstubAllGlobals();
});

describe("SCR-157 blocking dialog: when it opens", () => {
  it("opens for another protocol: a modal alertdialog named by its heading (E10-D04 F-08)", () => {
    welcome("cv.v2", "0.2.0");
    expect(dialog()).toHaveAttribute("aria-modal", "true");
    expect(dialog()).toHaveAccessibleName(HEADING);
  });

  it("is described by the versions row (PROPOSED), what stops, what works, the fallback", () => {
    welcome("cv.v2", "0.2.0");
    expect(dialog()).toHaveAccessibleDescription(
      described(
        "Your client v0.1.0 (ws protocol cv.v1) · the server 0.2.0 requires ws protocol cv.v2",
      ),
    );
  });

  it("fails closed: a protocol label the worker refused opens it too", () => {
    welcome(null);
    expect(dialog()).toHaveAccessibleDescription(
      described(
        "Your client v0.1.0 (ws protocol cv.v1) · the server requires " +
          "a ws protocol this client can't read",
      ),
    );
  });

  it.each<[string, string | undefined, string | undefined]>([
    ["before any welcome", undefined, undefined],
    ["for the same build", "cv.v1", "0.1.0"],
    ["for another build on cv.v1 (the banner's)", "cv.v1", "0.2.0"],
  ])("stays shut %s", (_case, protocol, version) => {
    welcome(protocol, version);
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it("closes at once when the builds match again, and its T2 leg with it (T-18)", () => {
    welcome("cv.v2", "0.2.0");
    welcome("cv.v1", "0.1.0");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(protocolLeg(getShellState())).toBeNull();
  });

  it("opens again when the build it answered comes back after a matching one (T-18, T-15)", () => {
    welcome("cv.v2", "0.2.0");
    fireEvent.click(button("Continue read-only"));
    welcome("cv.v1", "0.1.0");
    welcome("cv.v2", "0.2.0");
    expect(dialog()).toHaveAccessibleName(HEADING);
  });

  it("stays answered while the server keeps that build (a reconnect's welcome)", () => {
    welcome("cv.v2", "0.2.0");
    fireEvent.click(button("Continue read-only"));
    welcome("cv.v2", "0.2.0");
    expect(screen.queryByRole("alertdialog")).toBeNull();
  });

  it.each([
    ["another version", "cv.v2", "0.3.0"],
    ["another protocol", "cv.v3", "0.2.0"],
  ])("reopens for another build, then for the answered one: %s", (_case, protocol, version) => {
    welcome("cv.v2", "0.2.0");
    fireEvent.click(button("Continue read-only"));
    welcome(protocol, version);
    expect(dialog()).toHaveAccessibleName(HEADING);
    welcome("cv.v2", "0.2.0"); // either part's change forgot the answer
    expect(dialog()).toHaveAccessibleName(HEADING);
  });
});

describe("SCR-157 blocking dialog: what it says and how it is used", () => {
  it("lists what stops, what still works and the console fallback (board 10)", () => {
    welcome("cv.v2", "0.2.0");
    const card = within(dialog());
    for (const line of [STOPS, WORKS, FALLBACK, "candleviewer kill"]) {
      expect(card.getByText(line)).toBeInTheDocument();
    }
    expect(card.getByText(FALLBACK).style.fontWeight).toBe("var(--font-weight-semibold)");
  });

  it("starts focus on its heading", () => {
    welcome("cv.v2", "0.2.0");
    expect(document.activeElement).toBe(within(dialog()).getByRole("heading", { name: HEADING }));
  });

  it("keeps Tab inside: the copy block's button, then Continue read-only, round again", () => {
    welcome("cv.v2", "0.2.0");
    const copy = button("Copy the server console command");
    fireEvent.keyDown(document.activeElement ?? dialog(), { key: "Tab" });
    expect(document.activeElement).toBe(copy);
    fireEvent.keyDown(copy, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(button("Continue read-only"));
    fireEvent.keyDown(button("Continue read-only"), { key: "Tab" });
    expect(document.activeElement).toBe(copy);
  });

  it("Continue read-only closes it and puts focus on the TopBar's search trigger (§13.2)", () => {
    button("Chart control").focus(); // where focus was when the server answered
    welcome("cv.v2", "0.2.0");
    fireEvent.click(button("Continue read-only"));
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(document.activeElement).toBe(button(/^Search commands/));
    expect(screen.getByRole("main").closest(INERT)).toBeNull(); // the read-only views are back
  });

  it("takes Esc as Continue read-only (E10-D04 BQ-14, C-08)", () => {
    welcome("cv.v2", "0.2.0");
    fireEvent.keyDown(dialog(), { key: "Escape" });
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(document.activeElement).toBe(button(/^Search commands/));
    expect(screen.getByRole("main").closest(INERT)).toBeNull();
  });

  it("keeps the T2 leg after Continue read-only: its reason, the kill-switch line (T-16)", () => {
    welcome("cv.v2", "0.2.0");
    fireEvent.click(button("Continue read-only"));
    expect(protocolLeg(getShellState())).toEqual({
      key: "health.protocol_incompatible",
      reason: "Unavailable until you update.",
      killSwitchLine: "Kill switch: unknown — incompatible version",
    });
  });

  it("reports app.version_mismatch, blocking, once per pair: versions only", () => {
    welcome("cv.v2", "0.2.0");
    welcome("cv.v3", "0.2.0"); // another protocol, the same pair
    welcome(null); // a refused build label: no version to name
    expect(heard).toEqual([said("0.2.0"), said(null)]);
  });

  it("has no serious or critical axe finding", async () => {
    welcome("cv.v2", "0.2.0");
    const res = await axe.run(dialog(), { rules: { "color-contrast": { enabled: false } } });
    expect(res.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
      [],
    );
  });
});

describe("SCR-157 blocking dialog over the body only (§9.1, §1.2; E05-D02 H23)", () => {
  it("insets its scrim to the body, and fills the viewport at 200 % (§11.3: no band)", () => {
    const main = screen.getByRole("main");
    vi.spyOn(main, "getBoundingClientRect").mockReturnValue({ top: 80, bottom: 720 } as DOMRect);
    welcome("cv.v2", "0.2.0");
    zoom(true);
    expect([inset("top"), inset("bottom")]).toEqual(["", ""]);
    // the TopBar's path stays outside the inert page, under the scrim, until Continue read-only
    expect(screen.getByRole("banner").closest(INERT)).toBeNull();
    zoom(false); // the body's band: the TopBar and the StatusBar are never scrimmed (§1.2)
    expect([inset("top"), inset("bottom")]).toEqual(["80px", `${window.innerHeight - 720}px`]);
  });

  it("leaves the TopBar, the banner slot, the StatusBar and the live regions live", () => {
    welcome("cv.v2", "0.2.0");
    const hidden = (el: Element | null): boolean => el?.closest('[aria-hidden="true"]') != null;
    const live = [...document.querySelectorAll("[aria-live]")].filter((r) => !dialog().contains(r));
    const slot = document.querySelector('[data-shell-slot="banner"]');
    const kept = [screen.getByRole("banner"), slot, screen.getByRole("contentinfo"), ...live];
    expect([live.length > 1, kept.filter(hidden)]).toEqual([true, []]); // the announcer's pair too
    expect(hidden(screen.getByRole("main", { hidden: true }))).toBe(true); // the body is inert
  });
});

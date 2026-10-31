// E10-S01 (#304) S10, BQ-06 (A11Y-F-0016, SC 1.4.10): at CMP-043's reflow breakpoint the nav rail
// is collapsed whatever the stored choice (never overwritten), and an expanded rail is an overlay over
// `main` (the drawer pattern), never a column, so the workspace keeps its width at 320 CSS px.
import { createRequire } from "node:module";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RAIL_STORAGE_KEY, resetShellLayout } from "../../../src/features/app-shell/layoutStore";
import { REFLOW_QUERY } from "../../../src/features/app-shell/reflow";
import { resetMeClaims, setMeClaims } from "../../../src/lib/auth/meCache";
import { buildRoutes } from "../../../src/routes/tree";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

let narrow = false;
const changes = new Set<() => void>();
/** Crosses the breakpoint as a zoom or a resize would: the query's `change` fires. */
const setNarrow = (on: boolean): void =>
  act(() => {
    narrow = on;
    changes.forEach((listener) => listener());
  });

let router: ReturnType<typeof createMemoryRouter>;
async function renderAt(path: string): Promise<void> {
  router = createMemoryRouter(buildRoutes(), { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  await screen.findByRole("heading", { name: /R-150/ });
  await act(async () => {});
}

const rail = (): HTMLElement => screen.getByRole("navigation", { name: "Primary" });
const frame = (): HTMLElement => {
  const el = rail().querySelector<HTMLElement>("[data-rail]");
  if (el === null) throw new Error("no rail frame");
  return el;
};
const toggle = (): HTMLElement =>
  within(rail()).getByRole("button", { name: /^(Collapse|Expand) navigation rail$/ });

beforeEach(() => {
  narrow = false;
  changes.clear();
  vi.stubGlobal(
    "matchMedia",
    (query: string) =>
      ({
        get matches() {
          return narrow && query === REFLOW_QUERY;
        },
        addEventListener: (_: string, listener: () => void) => void changes.add(listener),
        removeEventListener: (_: string, listener: () => void) => void changes.delete(listener),
      }) as unknown as MediaQueryList,
  );
  resetMeClaims();
  setMeClaims({ authenticated: true, role: "owner", permissions: [] });
  localStorage.clear();
  resetShellLayout();
});
afterEach(() => {
  vi.unstubAllGlobals();
});

describe("E10-S01 S10: the nav rail at the reflow breakpoint (A11Y-F-0016)", () => {
  it("collapses at the breakpoint without touching the stored choice, and restores it when wider", async () => {
    await renderAt("/risk");
    expect(frame()).toHaveAttribute("data-rail", "expanded");
    setNarrow(true);
    expect(frame()).toHaveAttribute("data-rail", "collapsed");
    expect(frame()).toHaveAttribute("data-rail-mode", "overlay");
    expect(toggle()).toHaveAttribute("aria-expanded", "false");
    expect(localStorage.getItem(RAIL_STORAGE_KEY)).toBeNull(); // never written
    setNarrow(false);
    expect(frame()).toHaveAttribute("data-rail", "expanded");
    expect(frame()).toHaveAttribute("data-rail-mode", "column");
  });

  it("expands as an overlay over main, never a column: the rail's column stays 64 px", async () => {
    await renderAt("/risk");
    setNarrow(true);
    fireEvent.click(toggle());
    expect(frame()).toHaveAttribute("data-rail", "expanded");
    expect(frame().style.width).toBe("240px");
    const column = rail().firstElementChild as HTMLElement;
    expect(column.style.width).toBe("64px"); // the grid column: `main` keeps its width
    const overlay = frame().parentElement as HTMLElement;
    expect(overlay.style.position).toBe("absolute");
    expect(toggle()).toHaveAttribute("aria-expanded", "true");
    expect(localStorage.getItem(RAIL_STORAGE_KEY)).toBeNull(); // the overlay is this page's only
    const { violations } = await axe.run(document.body, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
  });

  it("closes the overlay on Escape, focus back on the toggle", async () => {
    await renderAt("/risk");
    setNarrow(true);
    fireEvent.click(toggle());
    const link = within(rail()).getByRole("link", { name: "Rules" });
    link.focus();
    fireEvent.keyDown(link, { key: "Escape" });
    expect(frame()).toHaveAttribute("data-rail", "collapsed");
    expect(toggle()).toHaveFocus();
  });

  it("closes the overlay when focus leaves the rail, so the drawer hides no focused control", async () => {
    await renderAt("/risk");
    setNarrow(true);
    fireEvent.click(toggle());
    act(() => toggle().focus());
    const link = within(rail()).getByRole("link", { name: "Rules" });
    act(() => link.focus()); // inside the rail: stays open
    expect(frame()).toHaveAttribute("data-rail", "expanded");
    const outside = screen.getByRole("heading", { name: /R-150/ });
    outside.tabIndex = -1;
    act(() => outside.focus());
    expect(frame()).toHaveAttribute("data-rail", "collapsed");
  });

  it("leaves the overlay open on an Escape another layer already handled", async () => {
    await renderAt("/risk");
    setNarrow(true);
    fireEvent.click(toggle());
    const link = within(rail()).getByRole("link", { name: "Rules" });
    link.addEventListener("keydown", (event) => event.preventDefault(), { once: true });
    fireEvent.keyDown(link, { key: "Escape" });
    expect(frame()).toHaveAttribute("data-rail", "expanded");
  });

  it("closes the overlay on a navigation", async () => {
    await renderAt("/risk");
    setNarrow(true);
    fireEvent.click(toggle());
    expect(frame()).toHaveAttribute("data-rail", "expanded");
    await act(async () => {
      await router.navigate("/journal");
    });
    expect(frame()).toHaveAttribute("data-rail", "collapsed");
  });

  it("keeps the stored collapse working above the breakpoint", async () => {
    await renderAt("/risk");
    fireEvent.click(toggle());
    expect(frame()).toHaveAttribute("data-rail", "collapsed");
    expect(JSON.parse(localStorage.getItem(RAIL_STORAGE_KEY) ?? "{}")).toEqual({
      railCollapsed: true,
    });
  });
});

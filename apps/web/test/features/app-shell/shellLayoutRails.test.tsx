import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { useEffect, type JSX } from "react";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ShellLayout } from "../../../src/features/app-shell/ShellLayout";
import {
  RAIL_STORAGE_KEY,
  getShellLayout,
  resetShellLayout,
  setRailCollapsed,
} from "../../../src/features/app-shell/layoutStore";
import { resetMeClaims, setMeClaims } from "../../../src/lib/auth/meCache";
import { buildRoutes } from "../../../src/routes/tree";
import { appThemeStore } from "../../../src/shell/bootstrap/themeStore";

// axe-core is a transitive dependency of @axe-core/playwright (already a devDependency).
const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

async function renderAt(path: string, heading: RegExp = /R-150/): Promise<void> {
  const router = createMemoryRouter(buildRoutes(), { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  await screen.findByRole("heading", { name: heading });
  // findByRole resolves outside act: flush the passive effects that subscribe the rails to their
  // stores, or a store change right after can land before the subscription (a load-only race).
  await act(async () => {});
}

const rail = (): HTMLElement => screen.getByRole("navigation", { name: "Primary" });
const railToggle = (): HTMLElement =>
  within(rail()).getByRole("button", { name: /^(Collapse|Expand) navigation rail$/ });
const aside = (): HTMLElement => screen.getByRole("complementary", { name: "Side panels" });
const launcher = (): HTMLElement => within(aside()).getByRole("button", { name: "Notifications" });
const label = (name: string): HTMLElement => {
  const el = within(rail())
    .getByRole("link", { name })
    .querySelector<HTMLElement>("span:last-child");
  if (el === null) throw new Error(`no label for ${name}`);
  return el;
};

/**
 * A motion token's value in ms, from the token source the design system builds its CSS from
 * (`packages/ui/tokens/primitives.tokens.json`; `motion.duration.fast` → `--motion-duration-fast`).
 * jsdom loads no stylesheet, so a `var()` can't be resolved from the computed style.
 */
function tokenMs(name: string): number {
  const file = resolve(
    import.meta.dirname,
    "../../../../../packages/ui/tokens/primitives.tokens.json",
  );
  const tokens = JSON.parse(readFileSync(file, "utf8")) as Record<string, { $value?: unknown }>;
  const value = tokens[name]?.$value;
  if (typeof value !== "string" || !/^\d+ms$/.test(value))
    throw new Error(`${name}: ${String(value)}`);
  return Number.parseInt(value, 10);
}

/** The `--motion-duration-*` tokens a `transition` string names. */
const durations = (transition: string): string[] =>
  [...transition.matchAll(/var\(--motion-duration-([a-z]+)\)/g)].map(
    (m) => `motion.duration.${m[1] ?? ""}`,
  );

/** The rail's echoes (the only tooltips carrying an Alt+N hint). */
const railEchoes = (): (string | null)[] =>
  [...document.querySelectorAll('[role="tooltip"]')]
    .map((n) => n.textContent)
    .filter((t) => t?.includes("Alt+"));

beforeEach(() => {
  resetMeClaims();
  setMeClaims({ authenticated: true, role: "owner", permissions: [] });
  localStorage.clear();
  resetShellLayout();
});
afterEach(() => {
  act(() => appThemeStore().setMotionOverride("system"));
  vi.unstubAllGlobals();
});

describe("E10-S01 S6: nav rail collapse", () => {
  it("toggles aria-expanded and its name, and keeps every item named when collapsed", async () => {
    await renderAt("/risk");
    expect(railToggle()).toHaveAttribute("aria-expanded", "true");
    expect(railToggle()).toHaveAccessibleName("Collapse navigation rail");
    expect(railToggle()).not.toHaveAttribute("aria-pressed");
    fireEvent.click(railToggle());
    expect(railToggle()).toHaveAttribute("aria-expanded", "false");
    expect(railToggle()).toHaveAccessibleName("Expand navigation rail");
    expect(rail().querySelector("[data-rail]")).toHaveAttribute("data-rail", "collapsed");
    for (const name of ["Terminal", "Rules", "Settings", "Admin"]) {
      const link = within(rail()).getByRole("link", { name });
      expect(link).not.toHaveAttribute("title"); // the CMP-016 echo replaced the title (SC 1.4.13)
      fireEvent.focus(link);
      // the item's own echo carries its hint (what the old title held), aria-hidden: the name stays the only read
      expect(railEchoes()).toContainEqual(expect.stringContaining(`${name} · Alt+`));
    }
    for (const tip of document.querySelectorAll('[role="tooltip"]'))
      expect(tip).toHaveAttribute("aria-hidden", "true");
    fireEvent.click(railToggle());
    expect(railToggle()).toHaveAttribute("aria-expanded", "true");
    expect(railToggle()).toHaveAccessibleName("Collapse navigation rail");
    expect(within(rail()).getByRole("link", { name: "Rules" })).not.toHaveAttribute("title");
    expect(railEchoes()).toEqual([]); // expanded: no tooltip node
  });

  it("keeps a denied item out of the collapsed rail: no link, tooltip or glyph (manager)", async () => {
    setMeClaims({ authenticated: true, role: "manager", permissions: [] });
    await renderAt("/journal", /R-180/);
    fireEvent.click(railToggle());
    expect(rail().querySelector('a[href^="/admin"]')).toBeNull();
    const links = within(rail()).getAllByRole("link");
    for (const a of links) fireEvent.focus(a);
    expect(railEchoes().join("|")).not.toContain("Admin");
    // one hidden initial per visible item, each inside its own (non-admin) link
    const glyphs = [...rail().querySelectorAll('a > span[aria-hidden="true"]')];
    expect(glyphs).toHaveLength(links.length);
    expect(links).toHaveLength(6);
    for (const glyph of glyphs)
      expect(glyph.closest("a")?.getAttribute("href")).not.toMatch(/^\/admin/);
  });

  it("persists the collapse under one key and restores it on the next page", async () => {
    await renderAt("/risk");
    fireEvent.click(railToggle());
    expect(JSON.parse(localStorage.getItem(RAIL_STORAGE_KEY) ?? "null")).toEqual({
      railCollapsed: true,
    });
    expect(Object.keys(localStorage)).toEqual([RAIL_STORAGE_KEY]);
    act(() => resetShellLayout());
    expect(getShellLayout()).toEqual({ railCollapsed: true, rightRailOpen: false });
    expect(railToggle()).toHaveAttribute("aria-expanded", "false");
  });

  it.each([["not json"], ["[true]"], ['{"railCollapsed":"yes"}']])(
    "reads a malformed stored value %j as expanded",
    (raw) => {
      localStorage.setItem(RAIL_STORAGE_KEY, raw);
      resetShellLayout();
      expect(getShellLayout().railCollapsed).toBe(false);
    },
  );

  it("renders and toggles with no usable storage", async () => {
    const broken = {
      getItem: () => {
        throw new Error("denied");
      },
      setItem: () => {
        throw new Error("denied");
      },
    };
    vi.stubGlobal("localStorage", broken);
    resetShellLayout();
    await renderAt("/risk");
    expect(railToggle()).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(railToggle());
    expect(railToggle()).toHaveAttribute("aria-expanded", "false");
    vi.stubGlobal("localStorage", undefined);
    expect(() => setRailCollapsed(false)).not.toThrow();
    expect(() => resetShellLayout()).not.toThrow();
  });

  it("moves the labels by transform and opacity only, never the width, within 120 ms", async () => {
    await renderAt("/risk");
    const frame = rail().querySelector<HTMLElement>("[data-rail]");
    expect(frame?.style.transition).toBe("");
    expect(label("Rules").style.transition).toMatch(/^transform var\(--motion-duration-fast\)/);
    expect(label("Rules").style.transition).toContain("opacity");
    expect(label("Rules").style.transition).not.toMatch(/width|left|height/);
    expect(label("Rules").style.transform).toBe("none");
    fireEvent.click(railToggle());
    expect(label("Rules").style.transform).toBe("translateX(-100%)");
    expect(label("Rules").style.opacity).toBe("0");
    expect(frame?.style.width).toBe("64px");
    expect(frame?.style.transition).toBe("");
    // D03 §5.4: ≤ 120 ms, both ways, by the value of every duration token the transition names
    const collapsing = label("Rules").style.transition; // the rail is collapsed here
    fireEvent.click(railToggle());
    const expanding = label("Rules").style.transition;
    for (const t of [collapsing, expanding]) {
      expect(durations(t).length).toBeGreaterThan(0);
      for (const token of durations(t)) expect(tokenMs(token), token).toBeLessThanOrEqual(120);
    }
  });

  it("drops the transition under the app's reduced-motion setting", async () => {
    await renderAt("/risk");
    act(() => appThemeStore().setMotionOverride("on"));
    expect(label("Rules").style.transition).toBe("none");
    fireEvent.click(railToggle());
    expect(label("Rules").style.transition).toBe("none");
    act(() => appThemeStore().setMotionOverride("off"));
    expect(label("Rules").style.transition).toContain("transform");
  });

  it("never remounts or re-renders the routed screen when the rails change", async () => {
    let mounts = 0;
    let renders = 0;
    function Screen(): JSX.Element {
      renders += 1;
      useEffect(() => {
        mounts += 1;
      }, []);
      return <h1>Screen</h1>;
    }
    const router = createMemoryRouter(
      [{ element: <ShellLayout />, children: [{ path: "/", element: <Screen /> }] }],
      { initialEntries: ["/"] },
    );
    render(<RouterProvider router={router} />);
    await screen.findByRole("heading", { name: "Screen" });
    await act(async () => {});
    const before = renders;
    fireEvent.click(railToggle());
    fireEvent.click(railToggle());
    fireEvent.click(launcher());
    fireEvent.keyDown(launcher(), { key: "Escape" });
    act(() => resetShellLayout());
    expect(mounts).toBe(1);
    expect(renders).toBe(before);
  });
});

describe("E10-S01 S6: right rail (CMP-209)", () => {
  it("is a named complementary landmark with a closed drawer and its toggle", async () => {
    await renderAt("/risk");
    expect(launcher()).toHaveAttribute("aria-expanded", "false");
    expect(launcher()).not.toHaveAttribute("aria-pressed");
    const panelId = launcher().getAttribute("aria-controls") ?? "";
    expect(document.getElementById(panelId)).not.toBeNull();
    expect(within(aside()).queryByRole("heading", { name: "Notifications" })).toBeNull();
  });

  it("opens without moving focus, and Esc closes it and returns focus to the launcher", async () => {
    await renderAt("/risk");
    act(() => launcher().focus());
    fireEvent.click(launcher());
    expect(launcher()).toHaveAttribute("aria-expanded", "true");
    expect(document.activeElement).toBe(launcher());
    const panel = document.getElementById(launcher().getAttribute("aria-controls") ?? "");
    expect(within(aside()).getByRole("group", { name: "Notifications" })).toBe(panel);
    expect(panel?.style.transition).toMatch(/^transform /);
    act(() => screen.getByRole("main").focus());
    if (panel !== null) fireEvent.keyDown(panel, { key: "Escape" });
    expect(launcher()).toHaveAttribute("aria-expanded", "false");
    expect(document.activeElement).toBe(launcher());
    expect(within(aside()).queryByRole("heading", { name: "Notifications" })).toBeNull();
  });

  it("keeps the panel painted while it slides out, inert at once, hidden at the slide's end", async () => {
    await renderAt("/risk");
    fireEvent.click(launcher());
    const panel = document.getElementById(launcher().getAttribute("aria-controls") ?? "");
    const box = panel?.parentElement;
    expect(panel?.style.visibility).toBe("visible");
    expect(panel?.style.pointerEvents).toBe("");
    expect(panel?.style.transition).not.toContain("visibility");
    fireEvent.keyDown(launcher(), { key: "Escape" });
    expect(panel?.style.transform).toBe("translateX(100%)");
    expect(panel?.style.pointerEvents).toBe("none");
    // the end state is `hidden`; the discrete switch waits for the slide's duration
    expect(panel?.style.visibility).toBe("hidden");
    expect(panel?.style.transition).toMatch(/^transform var\(--motion-duration-fast\) /);
    expect(panel?.style.transition).toContain("visibility 0s linear var(--motion-duration-fast)");
    // the reserved space steps to 0 at the last frame, never animated (D04 T-04 "Layout")
    expect(box?.style.width).toBe("0px");
    expect(box?.style.transition).toBe("width 0s linear var(--motion-duration-fast)");
  });

  it("hides the closing panel at once under reduced motion", async () => {
    await renderAt("/risk");
    act(() => appThemeStore().setMotionOverride("on"));
    fireEvent.click(launcher());
    fireEvent.keyDown(launcher(), { key: "Escape" });
    const panel = document.getElementById(launcher().getAttribute("aria-controls") ?? "");
    expect(panel?.style.visibility).toBe("hidden");
    expect(panel?.style.pointerEvents).toBe("none");
    expect(panel?.style.transition).toBe("none");
    expect(panel?.parentElement?.style.transition).toBe("none");
  });

  it("leaves Esc to an inner widget that already handled it", async () => {
    await renderAt("/risk");
    fireEvent.click(launcher());
    const panel = document.getElementById(launcher().getAttribute("aria-controls") ?? "");
    panel?.addEventListener("keydown", (e) => e.preventDefault());
    if (panel !== null) fireEvent.keyDown(panel, { key: "Escape" });
    expect(launcher()).toHaveAttribute("aria-expanded", "true");
  });

  it("ignores Esc while closed", async () => {
    await renderAt("/risk");
    act(() => screen.getByRole("main").focus());
    fireEvent.keyDown(launcher(), { key: "Escape" });
    expect(document.activeElement).toBe(screen.getByRole("main"));
  });
});

describe("E10-S01 S6: landmarks and axe", () => {
  it("keeps one landmark of each kind with the rail collapsed and the drawer open", async () => {
    await renderAt("/risk");
    fireEvent.click(railToggle());
    fireEvent.click(launcher());
    for (const role of ["banner", "navigation", "main", "complementary", "contentinfo"]) {
      expect(screen.getAllByRole(role), role).toHaveLength(1);
    }
    expect(screen.queryAllByRole("region")).toHaveLength(0);
  });

  it("has no serious or critical axe violations, expanded and collapsed", async () => {
    await renderAt("/risk");
    for (let i = 0; i < 2; i += 1) {
      const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } }); // jsdom has no layout
      expect(
        res.violations.filter((v) => v.impact === "serious" || v.impact === "critical"),
      ).toEqual([]);
      fireEvent.click(railToggle());
      fireEvent.click(launcher());
    }
  });
});

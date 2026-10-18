import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createEngine } from "@candleviewer/chart-engine";
import { AppearanceScreen, LEGEND_VIEWS } from "../../src/features/appearance/AppearanceScreen";
import { registerEngine } from "../../src/features/appearance/engineRegistry";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
  document.documentElement.removeAttribute("data-palette");
  document.documentElement.removeAttribute("data-convention");
});

describe("SCR-116 appearance screen", () => {
  it("palette choice persists locally and updates the root", async () => {
    render(<AppearanceScreen />);
    fireEvent.click(screen.getByRole("radio", { name: /colour-blind safe/i }));
    expect(JSON.parse(localStorage.getItem("cv.chartColorMode") ?? "{}")).toEqual({
      palette: "cvd-safe",
      convention: "standard",
    });
    expect(document.documentElement.getAttribute("data-palette")).toBe("cvd-safe");
    await screen.findByText("Saved.");
  });

  it("change palette -> engine setTheme with CVD palette -> one texture re-upload", async () => {
    const upload = vi.fn();
    const engine = createEngine({ uploadPalette: upload });
    const unregister = registerEngine(engine);
    render(<AppearanceScreen />);
    fireEvent.click(screen.getByRole("radio", { name: /colour-blind safe/i }));
    await screen.findByText("Saved.");
    // one upload on register (current theme) + exactly one for the palette switch
    expect(engine.stats().paletteUploads).toBe(2);
    expect(upload).toHaveBeenCalledTimes(2);
    expect((upload.mock.calls[1]?.[0] as { palette: string }).palette).toBe("cvd-safe");
    unregister();
  });

  it("theme and high-contrast switches repaint registered canvases via setTheme", async () => {
    const setTheme = vi.fn();
    const unregister = registerEngine({ setTheme });
    expect(setTheme).toHaveBeenCalledTimes(1);
    document.documentElement.style.setProperty("--color-buy-default", "#112233");
    document.documentElement.setAttribute("data-theme", "light");
    await waitFor(() => expect(setTheme).toHaveBeenCalledTimes(2));
    // High contrast reaches the root as a theme of the runtime, not as an attribute of its own.
    document.documentElement.setAttribute("data-theme", "high-contrast");
    await waitFor(() => expect(setTheme).toHaveBeenCalledTimes(3));
    unregister();
    document.documentElement.setAttribute("data-theme", "dark");
    await Promise.resolve();
    expect(setTheme).toHaveBeenCalledTimes(3);
    document.documentElement.style.removeProperty("--color-buy-default");
  });

  it("every affected view's legend reflects palette/convention switches", async () => {
    render(<AppearanceScreen />);
    const groups = LEGEND_VIEWS.map((v) =>
      screen.getByRole("group", { name: `${v} colour legend` }),
    );
    for (const g of groups) expect(within(g).getByText("Green = buy / bid / up")).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: /colour-blind safe/i }));
    for (const g of groups) expect(within(g).getByText("Blue = buy / bid / up")).toBeTruthy();
    fireEvent.click(screen.getByRole("checkbox", { name: /invert/i }));
    for (const g of groups) {
      expect(within(g).getByText("Orange = buy / bid / up")).toBeTruthy();
      expect(g.getAttribute("data-convention")).toBe("inverted");
      expect(within(g).getAllByTestId("legend-swatch")[0]?.getAttribute("style")).toContain(
        "--color-buy-default",
      );
    }
    expect(screen.getByRole("status").textContent).toBe("Saved.");
  });

  it("compact density: token >=24px and every interactive element carries it", () => {
    const tokens = JSON.parse(
      readFileSync(
        resolve(import.meta.dirname, "../../../../packages/ui/tokens/primitives.tokens.json"),
        "utf-8",
      ),
    ) as Record<string, { $value: string }>;
    expect(Number(tokens["size.target.min"]?.$value)).toBeGreaterThanOrEqual(24);
    document.documentElement.setAttribute("data-density", "compact");
    render(<AppearanceScreen />);
    const controls = screen.getAllByRole("radio").concat(screen.getAllByRole("checkbox"));
    expect(controls.length).toBe(3);
    for (const el of controls) {
      for (const node of [el, el.closest("label") as HTMLElement]) {
        expect(node.style.minWidth).toBe("var(--size-target-min, 24px)");
        expect(node.style.minHeight).toBe("var(--size-target-min, 24px)");
      }
    }
    document.documentElement.removeAttribute("data-density");
  });
});

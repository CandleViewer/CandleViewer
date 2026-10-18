import { afterEach, describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { resetSharedThemeStores, sharedThemeStore } from "@candleviewer/ui";
import { App } from "../src/App";
import { THEME_ANALYTICS_EVENT } from "../src/shell/bootstrap/themeStore";

const RUNTIME_ATTRIBUTES = ["data-theme", "data-density", "data-motion", "data-text-scale"];

afterEach(() => {
  resetSharedThemeStores();
  localStorage.clear();
  for (const name of RUNTIME_ATTRIBUTES) document.documentElement.removeAttribute(name);
});

describe("App", () => {
  it("renders inside a main landmark after the root redirect", async () => {
    render(<App />);
    expect(await screen.findByRole("main")).toBeInTheDocument();
  });

  it("mounts the theme runtime once above the router: it writes the four root attributes", async () => {
    render(<App />);
    await screen.findByRole("main");
    for (const name of RUNTIME_ATTRIBUTES) {
      expect(document.documentElement.hasAttribute(name), name).toBe(true);
    }
    expect(document.querySelectorAll("#cv-theme-live-region")).toHaveLength(1);
  });

  it("wires the runtime's analytics to the app: a user's change is reported as a cv:analytics event", async () => {
    render(<App />);
    await screen.findByRole("main");
    const events: unknown[] = [];
    const on = (event: Event): void => void events.push((event as CustomEvent<unknown>).detail);
    window.addEventListener(THEME_ANALYTICS_EVENT, on);
    sharedThemeStore().setTheme("light"); // the store of the page is the one the provider mounted
    window.removeEventListener(THEME_ANALYTICS_EVENT, on);
    expect(events).toStrictEqual([
      { name: "appearance.theme_changed", theme: "light", matchSystem: false },
    ]);
  });
});

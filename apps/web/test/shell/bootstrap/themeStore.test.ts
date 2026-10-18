import { afterEach, describe, expect, it, vi } from "vitest";
import { THEME_STORAGE_KEY, resetSharedThemeStores, sharedThemeStore } from "@candleviewer/ui";
import {
  APP_THEME_OPTIONS,
  HYDRATE,
  THEME_ANALYTICS_EVENT,
  appThemeStore,
} from "../../../src/shell/bootstrap/themeStore.js";

const ROOT_ATTRIBUTES = ["data-theme", "data-density", "data-motion", "data-text-scale"];

function listen(): { events: unknown[]; stop: () => void } {
  const events: unknown[] = [];
  const on = (event: Event): void => void events.push((event as CustomEvent<unknown>).detail);
  window.addEventListener(THEME_ANALYTICS_EVENT, on);
  return { events, stop: () => window.removeEventListener(THEME_ANALYTICS_EVENT, on) };
}

afterEach(() => {
  resetSharedThemeStores();
  localStorage.clear();
  for (const name of ROOT_ATTRIBUTES) document.documentElement.removeAttribute(name);
  vi.restoreAllMocks();
});

describe("appThemeStore", () => {
  it("is the one shared store of the document root, however often it is asked for", () => {
    const store = appThemeStore();
    expect(appThemeStore()).toBe(store);
    expect(sharedThemeStore()).toBe(store);
  });

  it("agrees with a provider that passes the same options, so no later caller is ignored", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    appThemeStore();
    sharedThemeStore(APP_THEME_OPTIONS);
    expect(warn).not.toHaveBeenCalled();
  });

  it("reports a user's change to the analytics sink as a cv:analytics event", () => {
    const { events, stop } = listen();
    const store = appThemeStore();
    store.setTheme("light");
    store.setDensity("comfortable");
    store.setMotionOverride("on");
    stop();
    expect(events).toStrictEqual([
      { name: "appearance.theme_changed", theme: "light", matchSystem: false },
      { name: "appearance.density_changed", density: "comfortable" },
      { name: "a11y.preference_changed", key: "reduced_motion", value: "on" },
    ]);
  });
});

describe("HYDRATE", () => {
  it("applies server values without reporting them as a user's choice or writing them to storage", () => {
    const { events, stop } = listen();
    appThemeStore().apply({ density: "comfortable", highContrast: true, textScale: 125 }, HYDRATE);
    stop();
    expect(events).toStrictEqual([]);
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBeNull();
    const root = document.documentElement;
    expect(root.getAttribute("data-theme")).toBe("high-contrast");
    expect(root.getAttribute("data-density")).toBe("comfortable");
    expect(root.getAttribute("data-text-scale")).toBe("125");
  });
});

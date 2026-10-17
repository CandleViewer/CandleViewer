// @vitest-environment node
import { describe, expect, it, vi } from "vitest";
import { createThemeStore, sharedThemeStore } from "../../src/theme/index.js";

describe("theme store without a DOM (SSR, Node)", () => {
  it("is inert but works: nothing throws, state and subscriptions behave", () => {
    const listener = vi.fn();
    const store = createThemeStore();
    store.subscribe(listener);
    const disconnect = store.connect();
    store.setTheme("light");
    expect(store.getSnapshot()).toMatchObject({ theme: "light", motion: "safe" });
    expect(listener).toHaveBeenCalledTimes(1);
    expect(() => disconnect()).not.toThrow();
  });

  it("never shares a store, so server rendering cannot leak state between requests", () => {
    expect(sharedThemeStore()).not.toBe(sharedThemeStore());
  });
});

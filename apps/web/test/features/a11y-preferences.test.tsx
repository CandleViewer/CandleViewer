import { createRequire } from "node:module";
import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { resetSharedThemeStores } from "@candleviewer/ui";
import {
  AccessibilitySettingsScreen,
  PreferencesProvider,
  DEFAULT_PREFERENCES,
  parsePreferences,
  resolveFlags,
  resolveTriState,
  shouldAnnounce,
  type EngineFlags,
} from "../../src/features/a11y-preferences";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

function reply(status: number, body: unknown): Response {
  return { ok: status < 400, status, json: async () => body } as unknown as Response;
}

function stubMedia(reduce: boolean): void {
  vi.stubGlobal(
    "matchMedia",
    (q: string) =>
      ({
        matches: q.includes("reduced-motion") ? reduce : false,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
      }) as unknown as MediaQueryList,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  resetSharedThemeStores(); // each test stubs its own OS media, which the shared store reads once
  for (const name of ["data-theme", "data-density", "data-motion", "data-text-scale"]) {
    document.documentElement.removeAttribute(name);
  }
});

describe("pure model", () => {
  it("resolves tri-state: system follows media, override wins", () => {
    expect(resolveTriState("system", true)).toBe(true);
    expect(resolveTriState("off", true)).toBe(false);
    expect(resolveTriState("on", false)).toBe(true);
  });
  it("disable canvas animation clears every engine flag", () => {
    const f = resolveFlags(
      { ...DEFAULT_PREFERENCES, disable_canvas_animation: true },
      { reducedMotion: false, highContrast: false },
    );
    expect(f).toEqual({ animate: false, heatmapFade: false, inertia: false, flashOnTick: false });
  });
  it("rejects non-enum values", () => {
    expect(parsePreferences({ verbosity: "<x>", keyboard_only: "yes" })).toEqual(
      DEFAULT_PREFERENCES,
    );
  });
  it("low verbosity announces only significant events; high restores cadence", () => {
    const tick = { significant: false, cadenceElapsed: true };
    const low = { announce_prices: "always", verbosity: "low" } as const;
    expect(shouldAnnounce(low, tick)).toBe(false);
    expect(shouldAnnounce(low, { significant: true, cadenceElapsed: false })).toBe(true);
    expect(shouldAnnounce({ ...low, verbosity: "high" }, tick)).toBe(true);
    expect(shouldAnnounce({ announce_prices: "off", verbosity: "high" }, tick)).toBe(false);
  });
});

describe("AccessibilitySettingsScreen (SCR-117)", () => {
  function mount(onFlags?: (f: EngineFlags) => void): void {
    render(
      <PreferencesProvider {...(onFlags ? { onEngineFlags: onFlags } : {})}>
        <AccessibilitySettingsScreen />
      </PreferencesProvider>,
    );
  }

  it("applies disable-canvas-animation immediately, no refetch of GET", async () => {
    stubMedia(false);
    const f = vi
      .fn()
      .mockResolvedValueOnce(reply(200, {}))
      .mockResolvedValueOnce(reply(200, { accessibility: { disable_canvas_animation: true } }));
    vi.stubGlobal("fetch", f);
    const flags = vi.fn();
    mount(flags);
    fireEvent.click(screen.getByLabelText("Disable canvas animation"));
    expect(flags).toHaveBeenLastCalledWith(expect.objectContaining({ animate: false }));
    await waitFor(() => expect(f).toHaveBeenCalledTimes(2));
    expect(f.mock.calls[1]?.[1]).toMatchObject({ method: "PUT" });
  });

  it("shows OS default and honours an explicit override", async () => {
    stubMedia(true);
    const f = vi
      .fn()
      .mockResolvedValueOnce(reply(200, {}))
      .mockResolvedValueOnce(reply(200, { accessibility: { reduced_motion: "off" } }));
    vi.stubGlobal("fetch", f);
    mount();
    expect(screen.getByLabelText("On (from system)")).toBeChecked();
    fireEvent.click(screen.getByLabelText("Off", { selector: "[name=reduced-motion]" }));
    await waitFor(() =>
      expect(JSON.parse(f.mock.calls[1]?.[1].body as string)).toEqual({
        accessibility: { reduced_motion: "off" },
      }),
    );
    // The runtime owns the attribute: the explicit "off" wins over the OS preference stubbed above.
    await waitFor(() => expect(document.documentElement.getAttribute("data-motion")).toBe("safe"));
  });

  it("restores persisted preferences on load", async () => {
    stubMedia(false);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(reply(200, { accessibility: { keyboard_only: true } })),
    );
    mount();
    await waitFor(() => expect(screen.getByLabelText("Keyboard-only mode")).toBeChecked());
    expect(document.documentElement.dataset["keyboardOnly"]).toBe("true");
  });

  it("failed save announces, reverts and offers retry", async () => {
    stubMedia(false);
    const f = vi
      .fn()
      .mockResolvedValueOnce(reply(200, {}))
      .mockResolvedValueOnce(reply(500, {}))
      .mockResolvedValueOnce(reply(200, { accessibility: { thick_focus_ring: true } }));
    vi.stubGlobal("fetch", f);
    mount();
    fireEvent.click(screen.getByLabelText("Increase focus-ring thickness"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not save");
    expect(screen.getByLabelText("Increase focus-ring thickness")).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() =>
      expect(screen.getByLabelText("Increase focus-ring thickness")).toBeChecked(),
    );
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("has zero serious/critical axe violations and links statement + cheatsheet", async () => {
    stubMedia(false);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(200, {})));
    mount();
    expect(screen.getByRole("link", { name: /Accessibility statement/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /SCR-013/ })).toBeInTheDocument();
    const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
    expect(res.violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
      [],
    );
  });
});

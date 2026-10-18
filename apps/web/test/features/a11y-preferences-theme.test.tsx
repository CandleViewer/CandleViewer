import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { THEME_STORAGE_KEY, ThemeProvider, resetSharedThemeStores } from "@candleviewer/ui";
import {
  AccessibilitySettingsScreen,
  PreferencesProvider,
} from "../../src/features/a11y-preferences";
import { resetShellState, setShellState } from "../../src/shell/bootstrap/store";
import { APP_THEME_OPTIONS, appThemeStore } from "../../src/shell/bootstrap/themeStore";

const root = document.documentElement;
const PREPAINT = {
  "data-theme": "light",
  "data-density": "comfortable",
  "data-motion": "reduce",
  "data-text-scale": "125",
};
const attributes = (): Record<string, string | null> =>
  Object.fromEntries(Object.keys(PREPAINT).map((name) => [name, root.getAttribute(name)]));

function reply(status: number, body: unknown): Response {
  return { ok: status < 400, status, json: async () => body } as unknown as Response;
}

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
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

/** The app's tree: the runtime's provider above the preferences provider. */
function mount(): void {
  render(
    <ThemeProvider options={APP_THEME_OPTIONS}>
      <PreferencesProvider>
        <AccessibilitySettingsScreen />
      </PreferencesProvider>
    </ThemeProvider>,
  );
}

/** What the pre-paint snippet leaves behind for a persisted local override. */
function persistLocalOverride({ highContrast = false } = {}): void {
  localStorage.setItem(
    THEME_STORAGE_KEY,
    JSON.stringify({
      baseTheme: "light",
      matchSystem: false,
      highContrast,
      density: "comfortable",
      motionOverride: "on",
      textScale: 125,
    }),
  );
  for (const [name, value] of Object.entries(PREPAINT)) root.setAttribute(name, value);
  if (highContrast) root.setAttribute("data-theme", "high-contrast");
}

beforeEach(() => {
  resetSharedThemeStores();
  resetShellState();
});

afterEach(() => {
  vi.unstubAllGlobals();
  resetSharedThemeStores();
  localStorage.clear();
  for (const name of Object.keys(PREPAINT)) root.removeAttribute(name);
});

describe("PreferencesProvider feeds the theme runtime", () => {
  it("No clobber: the provider's defaults leave the persisted values until /settings answers", async () => {
    stubMedia(false);
    persistLocalOverride();
    const settings = deferred<Response>();
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(settings.promise));
    mount();
    await act(async () => {}); // let every effect of the first render run
    expect(attributes()).toStrictEqual(PREPAINT);

    await act(async () => {
      settings.resolve(
        reply(200, { accessibility: { reduced_motion: "off", increased_contrast: "on" } }),
      );
    });
    await waitFor(() => expect(root.getAttribute("data-motion")).toBe("safe"));
    expect(root.getAttribute("data-theme")).toBe("high-contrast");
    expect(root.getAttribute("data-density")).toBe("comfortable"); // not a server value: untouched
  });

  it("No clobber: a persisted high contrast stays until /settings answers, then the server decides", async () => {
    stubMedia(false);
    persistLocalOverride({ highContrast: true });
    const settings = deferred<Response>();
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(settings.promise));
    mount();
    await act(async () => {});
    expect(root.getAttribute("data-theme")).toBe("high-contrast");

    await act(async () => {
      settings.resolve(reply(200, { accessibility: { increased_contrast: "off" } }));
    });
    await waitFor(() => expect(root.getAttribute("data-theme")).toBe("light")); // the persisted base theme
  });

  it("keeps the persisted values when /settings fails", async () => {
    stubMedia(false);
    persistLocalOverride();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(500, {})));
    mount();
    await act(async () => {});
    expect(attributes()).toStrictEqual(PREPAINT);
  });

  it("applies the reduced-motion tri-state and increased contrast once they load", async () => {
    stubMedia(false);
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          reply(200, { accessibility: { reduced_motion: "on", increased_contrast: "on" } }),
        ),
    );
    mount();
    await waitFor(() => expect(root.getAttribute("data-motion")).toBe("reduce"));
    expect(root.getAttribute("data-theme")).toBe("high-contrast");
  });

  it("combines with the appearance the bootstrap loaded, so the accessibility defaults do not undo it", async () => {
    stubMedia(false);
    setShellState({ preferences: { appearance: { reduce_motion: true, high_contrast: true } } });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(200, {}))); // every accessibility value is its default
    mount();
    await waitFor(() => expect(root.getAttribute("data-motion")).toBe("reduce"));
    expect(root.getAttribute("data-theme")).toBe("high-contrast");
  });

  it("leaves a theme chosen in this session alone when a preference it feeds changes", async () => {
    stubMedia(false);
    setShellState({ preferences: { appearance: { theme: "dark", font_scale: 1 } } });
    const f = vi
      .fn()
      .mockResolvedValueOnce(reply(200, {}))
      .mockResolvedValueOnce(reply(200, { accessibility: { reduced_motion: "on" } }));
    vi.stubGlobal("fetch", f);
    mount();
    await waitFor(() => expect(f).toHaveBeenCalledTimes(1));
    await act(async () => {}); // the load settled and was applied
    appThemeStore().setTheme("light"); // the user's choice, made after the bootstrap

    fireEvent.click(screen.getByLabelText("On", { selector: "[name=reduced-motion]" }));
    await waitFor(() => expect(root.getAttribute("data-motion")).toBe("reduce"));
    expect(root.getAttribute("data-theme")).toBe("light"); // the bootstrap's dark is not re-applied
  });

  // The two preferences are fed one at a time: each is a session override once the hotkeys of
  // 05-accessibility-standard.md §3.2 are registered (#305), so changing one must not revert the other.
  it("keeps a high contrast toggled in this session when the reduced-motion preference changes", async () => {
    stubMedia(false);
    const f = vi
      .fn()
      .mockResolvedValueOnce(reply(200, {}))
      .mockResolvedValueOnce(reply(200, { accessibility: { reduced_motion: "on" } }));
    vi.stubGlobal("fetch", f);
    mount();
    await waitFor(() => expect(f).toHaveBeenCalledTimes(1));
    await act(async () => {}); // the load settled and was applied
    appThemeStore().toggleHighContrast(); // the user's override (Ctrl+Shift+H once registered)
    expect(root.getAttribute("data-theme")).toBe("high-contrast");

    fireEvent.click(screen.getByLabelText("On", { selector: "[name=reduced-motion]" }));
    await waitFor(() => expect(root.getAttribute("data-motion")).toBe("reduce"));
    expect(root.getAttribute("data-theme")).toBe("high-contrast");
    expect(JSON.parse(localStorage.getItem(THEME_STORAGE_KEY) ?? "{}")).toMatchObject({
      highContrast: true,
    });
  });

  it("keeps a reduced-motion override set in this session when the contrast preference changes", async () => {
    stubMedia(false);
    const f = vi
      .fn()
      .mockResolvedValueOnce(reply(200, {}))
      .mockResolvedValueOnce(reply(200, { accessibility: { increased_contrast: "on" } }));
    vi.stubGlobal("fetch", f);
    mount();
    await waitFor(() => expect(f).toHaveBeenCalledTimes(1));
    await act(async () => {}); // the load settled and was applied
    appThemeStore().setMotionOverride("on"); // the user's override (Ctrl+Shift+M once registered)
    expect(root.getAttribute("data-motion")).toBe("reduce");

    fireEvent.click(screen.getByLabelText("On", { selector: "[name=contrast]" }));
    await waitFor(() => expect(root.getAttribute("data-theme")).toBe("high-contrast"));
    expect(root.getAttribute("data-motion")).toBe("reduce");
    expect(JSON.parse(localStorage.getItem(THEME_STORAGE_KEY) ?? "{}")).toMatchObject({
      motionOverride: "on",
    });
  });

  it("feeds the runtime after a save when the load had failed, and not before it answers", async () => {
    stubMedia(false);
    const save = deferred<Response>();
    const f = vi.fn().mockResolvedValueOnce(reply(500, {})).mockReturnValueOnce(save.promise);
    vi.stubGlobal("fetch", f);
    mount();
    await waitFor(() => expect(f).toHaveBeenCalledTimes(1));
    await act(async () => {});
    fireEvent.click(screen.getByLabelText("On", { selector: "[name=reduced-motion]" }));
    await act(async () => {});
    expect(root.getAttribute("data-motion")).toBe("safe"); // the prefs do not mirror the server yet

    await act(async () => {
      save.resolve(reply(200, { accessibility: { reduced_motion: "on" } }));
    });
    await waitFor(() => expect(root.getAttribute("data-motion")).toBe("reduce"));
  });

  it("applies a change at once and reverts the runtime when the save fails", async () => {
    stubMedia(false);
    const save = deferred<Response>();
    const f = vi.fn().mockResolvedValueOnce(reply(200, {})).mockReturnValueOnce(save.promise);
    vi.stubGlobal("fetch", f);
    mount();
    await waitFor(() => expect(f).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(root.getAttribute("data-motion")).toBe("safe"));

    fireEvent.click(screen.getByLabelText("On", { selector: "[name=reduced-motion]" }));
    await waitFor(() => expect(root.getAttribute("data-motion")).toBe("reduce"));

    await act(async () => {
      save.resolve(reply(500, {}));
    });
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not save");
    await waitFor(() => expect(root.getAttribute("data-motion")).toBe("safe"));
  });

  it("does not write the retired attributes, and still writes the focus-ring and keyboard-only ones", async () => {
    stubMedia(false);
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          reply(200, { accessibility: { thick_focus_ring: true, keyboard_only: true } }),
        ),
    );
    mount();
    await waitFor(() => expect(root.dataset["keyboardOnly"]).toBe("true"));
    expect(root.dataset["focusRing"]).toBe("thick");
    for (const retired of ["data-reduced-motion", "data-high-contrast", "data-contrast"]) {
      expect(root.hasAttribute(retired), retired).toBe(false);
    }
  });
});

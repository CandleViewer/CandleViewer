import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { THEME_STORAGE_KEY, ThemeProvider, resetSharedThemeStores } from "@candleviewer/ui";
import {
  AccessibilitySettingsScreen,
  PreferencesProvider,
  usePreferences,
  type EngineFlags,
} from "../../src/features/a11y-preferences";
import { applyAppearance } from "../../src/shell/bootstrap/preferencesApply";
import { resetShellState, setShellState, type Settings } from "../../src/shell/bootstrap/store";
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

/** `matchMedia` whose reduced-motion answer can flip while the app runs (the user changes the OS setting). */
function osMotion(initial: boolean): { set: (reduce: boolean) => void } {
  let reduce = initial;
  const listeners = new Set<() => void>();
  vi.stubGlobal(
    "matchMedia",
    (q: string) =>
      ({
        get matches() {
          return q.includes("reduced-motion") ? reduce : false;
        },
        addEventListener: (_type: string, listener: () => void) => void listeners.add(listener),
        removeEventListener: (_type: string, listener: () => void) =>
          void listeners.delete(listener),
      }) as unknown as MediaQueryList,
  );
  return {
    set: (next) => {
      reduce = next;
      listeners.forEach((listener) => listener());
    },
  };
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
    act(() => {
      appThemeStore().setMotionOverride("on"); // the user's override (Ctrl+Shift+M once registered)
    });
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

/**
 * #3436: one rule decides motion for the DOM and for the canvas. The DOM follows the motion the theme
 * runtime resolved (`data-motion`); the engine flags follow the same value, whichever of the OS query,
 * the tri-state, its boolean twin, a persisted local choice or the session override produced it.
 */
describe("the engine flags follow the motion the runtime resolved", () => {
  /** Every flag the engine is told, so that one row reads as one statement. */
  const flagsFor = (calm: boolean): EngineFlags => ({
    animate: !calm,
    heatmapFade: !calm,
    inertia: !calm,
    flashOnTick: !calm,
  });

  /** What `PreferencesProvider.onEngineFlags` delivers; the engine only ever acts on the latest set. */
  function recordFlags(): {
    readonly onEngineFlags: (flags: EngineFlags) => void;
    readonly latest: () => EngineFlags | undefined;
  } {
    const told: EngineFlags[] = [];
    return {
      onEngineFlags: (flags) => void told.push(flags),
      latest: () => told[told.length - 1],
    };
  }

  /** The context's own answer to "is motion reduced?", for DOM components. */
  function ReducedMotionProbe(): JSX.Element {
    return <p>{usePreferences().reducedMotion ? "context: reduced" : "context: full motion"}</p>;
  }

  function mountWith(told: {
    readonly onEngineFlags: (flags: EngineFlags) => void;
  }): ReturnType<typeof render> {
    return render(
      <ThemeProvider options={APP_THEME_OPTIONS}>
        <PreferencesProvider onEngineFlags={told.onEngineFlags}>
          <AccessibilitySettingsScreen />
          <ReducedMotionProbe />
        </PreferencesProvider>
      </ThemeProvider>,
    );
  }

  /** What `runBootstrap` does with `GET /me/preferences`: feeds the runtime, then caches the settings. */
  function bootstrapWith(settings: Settings): void {
    applyAppearance(settings);
    setShellState({ preferences: settings });
  }

  /**
   * The acceptance criterion: `data-motion === "reduce"` exactly when all four flags are false (and all
   * four are true otherwise). The DOM side is read from the attribute the runtime wrote, never recomputed.
   */
  function expectCanvasToFollowDom(
    told: { readonly latest: () => EngineFlags | undefined },
    when = "now",
  ): void {
    const motion = root.getAttribute("data-motion");
    expect(told.latest(), `${when}: data-motion is ${motion}`).toStrictEqual(
      flagsFor(motion === "reduce"),
    );
    // The context's boolean for DOM components is the same decision.
    expect(
      screen.getByText(motion === "reduce" ? "context: reduced" : "context: full motion"),
    ).toBeInTheDocument();
  }

  // [accessibility.reduced_motion, appearance.reduce_motion (undefined: not sent), whether the OS asks for
  // reduced motion, data-motion]. The last column is what the runtime resolves (themeFromSettings.ts and the
  // store's resolve). It is only here so that a row cannot pass for the wrong reason, because the runtime was
  // never fed it: the flags are compared with the attribute the runtime wrote, not with this column.
  it.each([
    ["system", true, false, "reduce"], // the defect: the boolean reduces the DOM, the OS does not ask
    ["system", true, true, "reduce"],
    ["system", false, false, "safe"],
    ["system", false, true, "reduce"],
    ["system", undefined, false, "safe"],
    ["system", undefined, true, "reduce"],
    ["on", true, false, "reduce"],
    ["on", true, true, "reduce"],
    ["on", false, false, "reduce"],
    ["on", false, true, "reduce"],
    ["on", undefined, false, "reduce"],
    ["on", undefined, true, "reduce"],
    ["off", true, false, "safe"],
    ["off", true, true, "safe"],
    ["off", false, false, "safe"],
    ["off", false, true, "safe"],
    ["off", undefined, false, "safe"],
    ["off", undefined, true, "safe"],
  ] as const)(
    "tri-state %s, appearance.reduce_motion %s, OS reduce %s: data-motion is %s and the flags agree",
    async (tri, twin, os, motion) => {
      stubMedia(os);
      bootstrapWith({
        appearance: twin === undefined ? {} : { reduce_motion: twin },
        accessibility: { reduced_motion: tri },
      });
      const answer = deferred<Response>();
      vi.stubGlobal("fetch", vi.fn().mockReturnValue(answer.promise));
      const told = recordFlags();
      mountWith(told);
      await act(async () => {});
      // From the first frame: the bootstrap fed the runtime, and /settings has not answered yet.
      expect(root.getAttribute("data-motion")).toBe(motion);
      expectCanvasToFollowDom(told, "before /settings answers");

      await act(async () => {
        answer.resolve(reply(200, { accessibility: { reduced_motion: tri } }));
      });
      expect(root.getAttribute("data-motion")).toBe(motion);
      expectCanvasToFollowDom(told, "once /settings has answered");
    },
  );

  it("follows a persisted local choice from the first frame, before /settings answers", async () => {
    stubMedia(false);
    persistLocalOverride(); // what the pre-paint snippet leaves behind: motionOverride "on", data-motion reduce
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(deferred<Response>().promise));
    const told = recordFlags();
    mountWith(told);
    await act(async () => {});
    expect(root.getAttribute("data-motion")).toBe("reduce");
    expectCanvasToFollowDom(told);
  });

  // The session override (05-accessibility-standard.md §3.2, §7.1) is `setMotionOverride` on the runtime's
  // store; the hotkey that calls it is registered by #305, the existing tests of this file drive it the same way.
  // [accessibility.reduced_motion, whether the OS asks for reduced motion, the override, data-motion before, after]
  it.each([
    ["system", false, "on", "safe", "reduce"], // reduction switched on over a calm OS
    ["off", false, "on", "safe", "reduce"],
    ["system", true, "off", "reduce", "safe"], // and switched off over an OS that asks for it
    ["on", true, "off", "reduce", "safe"],
  ] as const)(
    "tri-state %s, OS reduce %s, session override %s: data-motion %s becomes %s and the flags follow",
    async (tri, os, override, before, after) => {
      stubMedia(os);
      bootstrapWith({ accessibility: { reduced_motion: tri } });
      const f = vi.fn().mockResolvedValue(reply(200, { accessibility: { reduced_motion: tri } }));
      vi.stubGlobal("fetch", f);
      const told = recordFlags();
      mountWith(told);
      await waitFor(() => expect(f).toHaveBeenCalledTimes(1));
      await act(async () => {}); // the load settled and was applied
      expect(root.getAttribute("data-motion")).toBe(before);
      expectCanvasToFollowDom(told, "before the override");

      act(() => {
        appThemeStore().setMotionOverride(override);
      });
      expect(root.getAttribute("data-motion")).toBe(after);
      expectCanvasToFollowDom(told, "after the override");
    },
  );

  it("follows an OS change while the app runs, in both directions", async () => {
    const os = osMotion(false);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(200, {})));
    const told = recordFlags();
    mountWith(told);
    await act(async () => {});
    expect(root.getAttribute("data-motion")).toBe("safe");
    expectCanvasToFollowDom(told, "OS does not ask");

    act(() => os.set(true));
    expect(root.getAttribute("data-motion")).toBe("reduce");
    expectCanvasToFollowDom(told, "OS asks");

    act(() => os.set(false));
    expect(root.getAttribute("data-motion")).toBe("safe");
    expectCanvasToFollowDom(told, "OS asks no more");
  });

  it("changes the flags in the same step as the runtime when a preference is applied and then reverted", async () => {
    stubMedia(false);
    const save = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValueOnce(reply(200, {})).mockReturnValueOnce(save.promise),
    );
    const told = recordFlags();
    mountWith(told);
    await act(async () => {});
    expect(root.getAttribute("data-motion")).toBe("safe");
    expectCanvasToFollowDom(told, "loaded");

    fireEvent.click(screen.getByLabelText("On", { selector: "[name=reduced-motion]" }));
    expect(root.getAttribute("data-motion")).toBe("reduce"); // at once, not after the save
    expectCanvasToFollowDom(told, "applied, save pending");

    await act(async () => {
      save.resolve(reply(500, {}));
    });
    expect(root.getAttribute("data-motion")).toBe("safe"); // the failed save reverts both
    expectCanvasToFollowDom(told, "save failed");
  });

  it("stops listening to the runtime when the provider unmounts", async () => {
    stubMedia(false);
    const store = appThemeStore();
    const subscribe = store.subscribe;
    let listening = 0;
    vi.spyOn(store, "subscribe").mockImplementation((listener) => {
      const stop = subscribe(listener);
      listening += 1;
      return () => {
        listening -= 1;
        stop();
      };
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(200, {})));
    const { unmount } = mountWith(recordFlags());
    await act(async () => {});
    expect(listening).toBeGreaterThan(0); // the provider does read the runtime
    unmount();
    expect(listening).toBe(0);
  });

  // disable_canvas_animation is the one input that is not the runtime's: it only ever calms the canvas.
  it.each([
    [false, "safe"], // nothing reduces the DOM, and the canvas is calm all the same
    [true, "reduce"],
  ] as const)(
    "with disable-canvas-animation on and OS reduce %s (data-motion %s), every flag is off",
    async (os, motion) => {
      stubMedia(os);
      vi.stubGlobal(
        "fetch",
        vi
          .fn()
          .mockResolvedValue(reply(200, { accessibility: { disable_canvas_animation: true } })),
      );
      const told = recordFlags();
      mountWith(told);
      await waitFor(() => expect(screen.getByLabelText("Disable canvas animation")).toBeChecked());
      await act(async () => {}); // the effect that tells the engine has run
      expect(told.latest()).toStrictEqual(flagsFor(true));
      expect(root.getAttribute("data-motion")).toBe(motion);
      // It is a canvas preference: the context's boolean for DOM components stays the runtime's.
      expect(
        screen.getByText(motion === "reduce" ? "context: reduced" : "context: full motion"),
      ).toBeInTheDocument();
    },
  );

  it("never un-calms: turning disable-canvas-animation off leaves a canvas the runtime reduced calm", async () => {
    stubMedia(false);
    const f = vi
      .fn()
      .mockResolvedValueOnce(
        reply(200, { accessibility: { reduced_motion: "on", disable_canvas_animation: true } }),
      )
      .mockResolvedValueOnce(
        reply(200, { accessibility: { reduced_motion: "on", disable_canvas_animation: false } }),
      );
    vi.stubGlobal("fetch", f);
    const told = recordFlags();
    mountWith(told);
    await waitFor(() => expect(screen.getByLabelText("Disable canvas animation")).toBeChecked());

    fireEvent.click(screen.getByLabelText("Disable canvas animation"));
    await waitFor(() =>
      expect(screen.getByLabelText("Disable canvas animation")).not.toBeChecked(),
    );
    expect(root.getAttribute("data-motion")).toBe("reduce");
    expectCanvasToFollowDom(told);
  });
});

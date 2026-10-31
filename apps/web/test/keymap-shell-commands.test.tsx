import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * #305 (E10-S02) PR B: the shell's own new commands and the reserved `Ctrl+K`, through the wired host (BQ-6, BQ-7, D9).
 * `Ctrl+\` cycles the landmark ring (E10-D04 G-04, `05` §3.4 rule 1), `Ctrl+Shift+H` toggles high contrast (E05-T02),
 * `Ctrl+Shift+M` the reduced-motion override (E10-D04 G-03, E05-D03 §6.5), and the cheatsheet marks the keys that are
 * not remappable and the reviewed overrides of a browser or OS key (E10-D04 §15, DS-305B-02); the lens's A11Y-305B-03
 * and CR-305B-06 too. Each test loads its own copy of the modules, which keep their state at module level.
 */
const load = async () => ({
  ...(await import("../src/keymap/KeymapHost")),
  ...(await import("../src/keymap/Cheatsheet")),
  ...(await import("../src/keymap/keymap")),
  ...(await import("../src/keymap/registry")),
  ...(await import("../src/keymap/profile")),
  ...(await import("../src/features/app-shell/announcer")),
  ...(await import("../src/shell/bootstrap/themeStore")),
  ...(await import("@candleviewer/ui")),
});
let m: Awaited<ReturnType<typeof load>>;

beforeEach(async () => {
  window.localStorage.clear();
  vi.resetModules();
  m = await load();
});

afterEach(() => {
  document.getElementById("cv-theme-live-region")?.remove();
  vi.unstubAllGlobals();
});

const press = (init: KeyboardEventInit): boolean => fireEvent.keyDown(window, init);
const cycle = (repeat = false): boolean =>
  press({ key: "\\", code: "Backslash", ctrlKey: true, repeat });
const polite = (): string => document.querySelector('[aria-live="polite"]')?.textContent ?? "";
const themeRegion = (): string =>
  document.getElementById("cv-theme-live-region")?.textContent ?? "";

describe("BQ-7, D9: Ctrl+K is reserved for the palette", () => {
  it("an unhandled Ctrl+K is taken, its default prevented, with no notice", () => {
    const { KeymapHost } = m;
    render(<KeymapHost />);
    expect(press({ key: "k", code: "KeyK", ctrlKey: true })).toBe(false);
    expect(screen.queryByRole("region", { name: "Notifications" })).toBeNull();
  });

  it("once a palette registers on Ctrl+K, the palette runs (E15)", () => {
    const { KeymapHost, registerCommand } = m;
    render(<KeymapHost />);
    const palette = vi.fn();
    const off = registerCommand("global.palette", palette);
    press({ key: "k", code: "KeyK", ctrlKey: true });
    expect(palette).toHaveBeenCalledTimes(1);
    off();
  });

  it("the cheatsheet lists Ctrl+K and the Esc commands as not remappable, and nothing else", () => {
    const { Cheatsheet } = m;
    render(<Cheatsheet />);
    const marked = screen.getAllByText("not remappable").map((n) => n.closest("tr")?.textContent);
    expect(marked).toEqual([
      expect.stringMatching(/^Command palette ?Ctrl\+K/),
      expect.stringMatching(/^Cancel in-progress drawing ?Esc/),
      expect.stringMatching(/^Clear ticket ?Esc/),
    ]);
  });
});

describe("DS-305B-02: a reviewed override reads 'reserved by the browser or OS' (E10-D04 §15)", () => {
  const MARK = "reserved by the browser or OS";
  const rowIn = (context: string, label: string): HTMLElement | null =>
    within(screen.getByRole("table", { name: context }))
      .getByText(label, { selector: 'th[scope="row"]' })
      .closest("tr");

  it("marks each binding holding its reviewed reservedOverride, and nothing else", () => {
    const { Cheatsheet, KEYMAP } = m;
    render(<Cheatsheet />);
    const reviewed = KEYMAP.filter((c) => c.reservedOverride?.rationale.trim());
    expect(reviewed).toHaveLength(11); // E10-D04 §15: the keymap carries 11 reviewed overrides
    expect(screen.getAllByText(MARK)).toHaveLength(reviewed.length);
    for (const c of reviewed) {
      expect(rowIn(c.context, c.label), c.id).toHaveTextContent(`${c.defaultBinding} ${MARK}`);
    }
  });

  it("only while the binding is still that reviewed default", () => {
    const { Cheatsheet, getBindings, setBindings } = m;
    act(() => setBindings(new Map(getBindings()).set("rules.duplicate", "Ctrl+Alt+D")));
    render(<Cheatsheet />);
    expect(rowIn("Rules", "Duplicate row")).not.toHaveTextContent(MARK);
    expect(screen.getAllByText(MARK)).toHaveLength(10);
  });
});

describe("Ctrl+\\ cycles the landmark ring (E10-D04 G-04; `05` §3.4 rule 1)", () => {
  function Shell({ modal = false }: { readonly modal?: boolean }): JSX.Element {
    const { KeymapHost, ShellAnnouncer } = m;
    return (
      <>
        <header>
          <button type="button">Search</button>
        </header>
        <nav aria-label="Primary" />
        <div>banner slot</div>
        <main tabIndex={-1}>
          <section aria-labelledby="hk-h">
            <h2 id="hk-h">Hotkeys</h2>
          </section>
          <header>a section header, not a banner</header>
          <section aria-label="Hidden panel" hidden />
        </main>
        <aside aria-label="Side panels" />
        <footer />
        {modal ? <div role="dialog" aria-modal="true" aria-label="Confirm" /> : null}
        <ShellAnnouncer />
        <KeymapHost />
      </>
    );
  }

  const visit = (presses: number): string[] =>
    Array.from({ length: presses }, () => {
      cycle();
      return (document.activeElement as HTMLElement).tagName.toLowerCase();
    });

  it("visits banner, navigation, main, a labelled region, complementary and contentinfo in DOM order, then wraps", () => {
    render(<Shell />);
    expect(visit(7)).toEqual(["header", "nav", "main", "section", "aside", "footer", "header"]);
  });

  it("takes the key: its default is prevented", () => {
    render(<Shell />);
    expect(cycle()).toBe(false);
  });

  it("A11Y-305B-03: says no name itself, since the reader reports the landmark it focuses", () => {
    render(<Shell />);
    visit(6);
    expect(polite()).toBe("");
  });

  it("A11Y-305B-03: skips a landmark that cannot take focus, as a CSS-hidden one cannot", () => {
    render(<Shell />);
    const aside = document.querySelector("aside") as HTMLElement;
    aside.focus = () => undefined; // as `display: none` leaves it: focus() changes nothing
    visit(4); // banner, navigation, main, the labelled region
    cycle();
    expect(document.activeElement?.tagName).toBe("FOOTER");
  });

  it("moves on from the landmark that holds focus", () => {
    render(<Shell />);
    act(() => screen.getByRole("button", { name: "Search" }).focus());
    cycle();
    expect(document.activeElement?.tagName).toBe("NAV");
  });

  it("a held key moves once", () => {
    render(<Shell />);
    cycle();
    cycle(true);
    expect(document.activeElement?.tagName).toBe("HEADER");
  });

  it("leaves focus in an open modal dialog (`05` §3.4 rule 4)", () => {
    render(<Shell modal />);
    const search = screen.getByRole("button", { name: "Search" });
    act(() => search.focus());
    cycle();
    expect(document.activeElement).toBe(search);
  });
});

describe("Ctrl+Shift+H toggles high contrast (E05-T02; BQ-6)", () => {
  it("is the command E05-T02's shortcut contract names", () => {
    const { commandMeta, HIGH_CONTRAST_SHORTCUT } = m;
    expect(commandMeta(HIGH_CONTRAST_SHORTCUT.id)).toMatchObject({
      label: HIGH_CONTRAST_SHORTCUT.label,
      defaultBinding: HIGH_CONTRAST_SHORTCUT.defaultBinding,
      ignoreRepeat: HIGH_CONTRAST_SHORTCUT.ignoreRepeat,
      group: "Global",
    });
  });

  const hc = { key: "H", code: "KeyH", ctrlKey: true, shiftKey: true };

  it("toggles high contrast on and off, saying each, and takes the key", () => {
    const { KeymapHost, appThemeStore, THEME_ANNOUNCEMENTS } = m;
    render(<KeymapHost />);
    expect(press(hc)).toBe(false);
    expect(appThemeStore().getSnapshot().highContrast).toBe(true);
    expect(themeRegion()).toBe(THEME_ANNOUNCEMENTS.highContrastOn);
    press(hc);
    expect(appThemeStore().getSnapshot().highContrast).toBe(false);
    expect(themeRegion()).toBe(THEME_ANNOUNCEMENTS.highContrastOff);
  });

  it("a held Ctrl+Shift+H does not flap it", () => {
    const { KeymapHost, appThemeStore } = m;
    render(<KeymapHost />);
    press(hc);
    press({ ...hc, repeat: true });
    expect(appThemeStore().getSnapshot().highContrast).toBe(true);
  });
});

describe("Ctrl+Shift+M toggles reduced motion to an explicit choice (E10-D04 G-03; E05-D03 §6.5)", () => {
  const rm = { key: "M", code: "KeyM", ctrlKey: true, shiftKey: true };

  it("flips the resolved mode to an explicit choice, saying each", () => {
    const { KeymapHost, appThemeStore } = m;
    render(<KeymapHost />);
    press(rm);
    expect(appThemeStore().getSnapshot()).toMatchObject({ motionOverride: "on", motion: "reduce" });
    expect(themeRegion()).toBe("Reduced motion on");
    press(rm);
    expect(appThemeStore().getSnapshot()).toMatchObject({ motionOverride: "off", motion: "safe" });
    expect(themeRegion()).toBe("Reduced motion off");
  });

  it("persists the choice, as SCR-117 does", () => {
    const { KeymapHost } = m;
    render(<KeymapHost />);
    press(rm);
    expect(JSON.parse(window.localStorage.getItem("cv.theme.v1") ?? "{}")).toMatchObject({
      motionOverride: "on",
    });
  });

  it("G-3: prevents the browser's own chord (jsdom shows the call; the reference browser is E10-Q03's)", () => {
    const { KeymapHost } = m;
    render(<KeymapHost />);
    expect(press(rm)).toBe(false);
  });

  it("from system under an OS reduce it writes off", () => {
    vi.stubGlobal("matchMedia", (q: string) => ({
      matches: q.includes("reduced-motion"),
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
    }));
    const { KeymapHost, appThemeStore } = m;
    render(<KeymapHost />);
    expect(appThemeStore().getSnapshot().motion).toBe("reduce");
    press(rm);
    expect(appThemeStore().getSnapshot()).toMatchObject({ motionOverride: "off", motion: "safe" });
  });

  it("does nothing while the idle lock is up", () => {
    const { KeymapHost, appThemeStore } = m;
    render(
      <>
        <div data-keymap-context="Locked" />
        <KeymapHost />
      </>,
    );
    press(rm);
    expect(appThemeStore().getSnapshot().motionOverride).toBe("system");
    expect(themeRegion()).toBe("");
  });
});

describe("the cheatsheet and an unbound command (A11Y-305BD-02)", () => {
  it("reads 'unbound' where the key was", () => {
    const { Cheatsheet, getBindings, setBindings } = m;
    act(() => setBindings(new Map(getBindings()).set("global.symbol_search", "")));
    render(<Cheatsheet />);
    const global = within(screen.getByRole("table", { name: "Global" }));
    expect(global.getByRole("row", { name: /^Symbol search/ })).toHaveTextContent(
      /^Symbol search ?unbound$/,
    );
  });
});

describe("the new defaults in the cheatsheet's Global table", () => {
  it("lists region cycling, high contrast and reduced motion with their keys", () => {
    const { Cheatsheet } = m;
    render(<Cheatsheet />);
    const global = within(screen.getByRole("table", { name: "Global" }));
    for (const [label, key] of [
      ["Region cycling", "Ctrl+\\"],
      ["Toggle high-contrast theme", "Ctrl+Shift+H"],
      ["Toggle reduced-motion override", "Ctrl+Shift+M"],
    ] as const) {
      expect(global.getByRole("row", { name: new RegExp(`^${label}`) }), label).toHaveTextContent(
        key,
      );
    }
  });
});

describe("teardown (CR-305B-06)", () => {
  it("unmounting the host unregisters the three commands it registers", () => {
    const { KeymapHost, isCommandValid } = m;
    const ids = [
      "global.region_cycle",
      "global.toggle_high_contrast",
      "global.toggle_reduced_motion",
    ];
    const view = render(<KeymapHost />);
    expect(ids.map((id) => isCommandValid(id))).toEqual([true, true, true]);
    view.unmount();
    expect(ids.map((id) => isCommandValid(id))).toEqual([false, false, false]);
  });
});

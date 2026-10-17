// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { act, useEffect, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { renderToStaticMarkup } from "react-dom/server";
import { composeStories, type StoryContext } from "@storybook/react";
import { within } from "@storybook/test";
import { afterEach, describe, expect, it, vi } from "vitest";
import { withThemeRuntime } from "../../.storybook/withThemeRuntime.js";
import * as stories from "../../src/theme/ThemeRuntime.stories.js";
import {
  HIGH_CONTRAST_SHORTCUT,
  THEME_STORAGE_KEY,
  ThemeProvider,
  createThemeStore,
  sharedThemeStore,
  toggleHighContrastAnnounced,
  useDensity,
  useReducedMotion,
  useTextScale,
  useTheme,
} from "../../src/theme/index.js";
import { mediaStub, memoryStorage } from "./helpers.js";
import { mount } from "./mount.js";

type Axe = {
  run: (context: object, options?: object) => Promise<{ violations: { impact?: string | null }[] }>;
};
const axe = createRequire(createRequire(import.meta.url).resolve("@storybook/addon-a11y"))(
  "axe-core",
) as Axe;
const newStore = () =>
  createThemeStore({ storage: memoryStorage(), matchMedia: mediaStub().matchMedia });
const rootData = document.documentElement.dataset;

describe("theme provider and hooks", () => {
  it("switches theme without remounting or re-rendering components that do not subscribe", async () => {
    const store = newStore();
    const counts = { mounts: 0, still: 0, theme: 0, density: 0 };
    const Still = (): JSX.Element => {
      counts.still += 1;
      useEffect(() => void (counts.mounts += 1), []);
      return <i>still</i>;
    };
    const Themed = (): JSX.Element => {
      const [theme] = useTheme();
      counts.theme += 1;
      return <b>{theme}</b>;
    };
    const Dense = (): JSX.Element => {
      const [density] = useDensity();
      counts.density += 1;
      return <u>{density}</u>;
    };
    const host = await mount(
      <ThemeProvider store={store}>
        <Still />
        <Themed />
        <Dense />
      </ThemeProvider>,
    );
    const html = host.innerHTML;
    expect(html).toBe("<i>still</i><b>dark</b><u>compact</u>"); // the provider renders exactly its children
    await act(async () => store.setTheme("high-contrast"));
    expect(rootData["theme"]).toBe("high-contrast");
    expect(counts).toEqual({ mounts: 1, still: 1, theme: 2, density: 1 });
    expect(host.innerHTML).toBe(html.replace(">dark<", ">high-contrast<"));
  });

  it("density switches leave the serialized DOM structure identical (the provider adds no wrapper)", async () => {
    const store = newStore();
    const host = await mount(
      <ThemeProvider store={store}>
        <div
          role="row"
          style={{ height: "var(--size-row-height)", padding: "var(--space-field-gap)" }}
        >
          <span>cell</span>
          <button type="button">Act</button>
        </div>
      </ThemeProvider>,
    );
    expect(host.firstElementChild?.getAttribute("role")).toBe("row");
    const before = host.innerHTML;
    await act(async () => store.setDensity("comfortable"));
    expect(rootData["density"]).toBe("comfortable");
    expect(host.innerHTML).toBe(before);
  });

  it("connects its store to the root on mount and releases the OS listeners on unmount", async () => {
    const root = document.createElement("html");
    const media = mediaStub();
    const storage = memoryStorage({ [THEME_STORAGE_KEY]: JSON.stringify({ baseTheme: "light" }) });
    const store = createThemeStore({ root, storage, matchMedia: media.matchMedia });
    const mounted = createRoot(document.body.appendChild(document.createElement("div")));
    const page = (
      <ThemeProvider store={store}>
        <i />
      </ThemeProvider>
    );
    await act(async () => mounted.render(page));
    expect(root.getAttribute("data-theme")).toBe("light");
    expect([media.listeners.dark.size, media.listeners.reduce.size]).toEqual([1, 1]);
    await act(async () => mounted.unmount());
    expect([media.listeners.dark.size, media.listeners.reduce.size]).toEqual([0, 0]);
  });

  it("uses the root's shared store when none is passed, exposes values and setters, and refuses to run without a provider", async () => {
    let api:
      | { scale: number; reduced: boolean; setScale: (s: 125) => void; override: (o: "on") => void }
      | undefined;
    const Probe = (): null => {
      const [scale, setScale] = useTextScale();
      const [reduced, override] = useReducedMotion();
      api = { scale, reduced, setScale, override };
      return null;
    };
    const options = {
      root: document.createElement("html"),
      storage: memoryStorage(),
      matchMedia: mediaStub().matchMedia,
    };
    await mount(
      <ThemeProvider options={options}>
        <Probe />
      </ThemeProvider>,
    );
    await act(async () => {
      api?.setScale(125);
      api?.override("on");
    });
    expect(api).toMatchObject({ scale: 125, reduced: true });
    expect(options.root.dataset["textScale"]).toBe("125");
    expect(() => renderToStaticMarkup(<Probe />)).toThrow("requires <ThemeProvider>");
    // jsdom defines `document`, so React warns that the layout effect does nothing on the server
    const quiet = vi.spyOn(console, "error").mockImplementation(() => undefined);
    const served = renderToStaticMarkup(
      <ThemeProvider options={options}>
        <Probe />
      </ThemeProvider>,
    );
    quiet.mockRestore();
    expect(served).toBe("");
  });

  it("providers on one root share a store, so they agree and the root is written once", async () => {
    const root = document.createElement("html");
    const options = { root, storage: memoryStorage(), matchMedia: mediaStub().matchMedia };
    let setTheme: (theme: "light") => void = () => undefined;
    const Reader = ({ id }: { id: string }): JSX.Element => {
      const [theme, set] = useTheme();
      setTheme = set;
      return <output aria-label={id}>{theme}</output>;
    };
    const host = await mount(
      <>
        <ThemeProvider options={options}>
          <Reader id="first" />
        </ThemeProvider>
        <ThemeProvider options={options}>
          <Reader id="second" />
        </ThemeProvider>
      </>,
    );
    const writes: MutationRecord[] = [];
    const observer = new MutationObserver((records) => writes.push(...records));
    observer.observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    await act(async () => setTheme("light"));
    const shown = ["first", "second"].map((id) => within(host).getByLabelText(id).textContent);
    expect(shown).toEqual(["light", "light"]);
    expect(root.dataset["theme"]).toBe("light");
    expect(writes).toHaveLength(1);
    observer.disconnect();
    expect(sharedThemeStore({ root })).toBe(sharedThemeStore(options));
  });

  it("exposes the Ctrl+Shift+H contract, announces each toggle through one polite live region and ignores key auto-repeat", () => {
    const store = newStore();
    expect(HIGH_CONTRAST_SHORTCUT.defaultBinding).toBe("Ctrl+Shift+H");
    expect(toggleHighContrastAnnounced(store)).toBe(true);
    const region = within(document.body).getByRole("status");
    expect([region.getAttribute("aria-live"), region.textContent]).toEqual([
      "polite",
      "High-contrast theme on",
    ]);
    toggleHighContrastAnnounced(store);
    expect(within(document.body).getAllByRole("status")).toHaveLength(1);
    expect(region.textContent).toBe("High-contrast theme off");
    expect(HIGH_CONTRAST_SHORTCUT.ignoreRepeat).toBe(true);
    expect(toggleHighContrastAnnounced(store, { repeat: true })).toBe(false);
    expect(region.textContent).toBe("High-contrast theme off");
    expect(toggleHighContrastAnnounced(store)).toBe(true);
    expect(toggleHighContrastAnnounced(store, { repeat: true })).toBe(true); // a held key leaves it on
    expect(region.textContent).toBe("High-contrast theme on");
    const announce = vi.fn();
    toggleHighContrastAnnounced(store, { announce });
    expect(announce).toHaveBeenCalledWith("High-contrast theme off");
    expect(region.textContent).toBe("High-contrast theme on"); // an injected announcer replaces the region
  });

  it("pre-renders the empty polite live region at mount, so the first announcement is heard", async () => {
    await mount(<ThemeProvider store={newStore()}>x</ThemeProvider>);
    expect(within(document.body).getByRole("status").textContent).toBe("");
  });
});

describe("theme runtime stories", () => {
  const { Default, StyleRecalcBenchmark, TextScaleReflow } = composeStories(stories);
  const render = (Story: typeof Default) =>
    mount(
      <ThemeProvider store={newStore()}>
        <Story />
      </ThemeProvider>,
    );

  it("Default plays through: switching leaves the mount count unchanged, controls are keyboard reachable", async () => {
    const host = await render(Default);
    const first = within(host).getAllByRole("radio")[0];
    first?.focus();
    expect(document.activeElement).toBe(first);
    await act(async () => Default.play?.({ canvasElement: host }));
    expect(rootData["motion"]).toBe("reduce");
  });

  it.each([
    ["Default", Default],
    ["StyleRecalcBenchmark", StyleRecalcBenchmark],
    ["TextScaleReflow", TextScaleReflow],
  ])(
    "%s has no serious or critical axe violations",
    async (_name, Story) => {
      const host = await render(Story);
      // Rows 4+ of the 500-row table repeat row 1's structure; axe is quadratic on them in jsdom.
      const context = { include: [host], exclude: [["tbody tr:nth-child(n+4)"]] };
      const { violations } = await axe.run(context, {
        rules: { "color-contrast": { enabled: false } },
      });
      expect(violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual(
        [],
      );
    },
    30_000,
  );

  it("a 500-row table switches theme and density within a CI-safe budget without re-rendering rows", async () => {
    const host = await render(StyleRecalcBenchmark);
    expect(host.querySelectorAll("tbody tr")).toHaveLength(500);
    const rows = host.querySelector("tbody")?.innerHTML;
    await act(async () => within(host).getByRole("button", { name: "Run benchmark" }).click());
    const ms = JSON.parse(
      within(host).getByLabelText("Benchmark result").textContent ?? "{}",
    ) as Record<string, number>;
    expect(ms["theme"]).toBeLessThan(250);
    expect(ms["density"]).toBeLessThan(250);
    expect(host.querySelector("tbody")?.innerHTML).toBe(rows);
  });
});

describe("TextScaleReflow story", () => {
  const { TextScaleReflow } = composeStories(stories);
  const themeCss = readFileSync(resolve(import.meta.dirname, "../../src/theme/theme.css"), "utf-8");
  afterEach(() => vi.restoreAllMocks());

  // jsdom has no layout, so what the play function reads is stubbed the way a browser reports it: the text
  // overflows its box (480 > 320) in the one leg the test names, and an element's font size is its
  // inherited size times its own percentage (jsdom computes neither), starting from the root's declared
  // percentage of 16 px, which jsdom does take from the page's CSS. `pageCss` is that stylesheet: without
  // theme.css, or without its font-size rules, the text never grows and an overflow check alone passes.
  async function playWithOverflowAt(leg?: string, pageCss = themeCss): Promise<void> {
    const legNow = (el: Element): string | undefined =>
      el instanceof HTMLElement && el.style.fontSize === "200%" ? "200" : rootData["textScale"];
    vi.spyOn(Element.prototype, "clientWidth", "get").mockReturnValue(320);
    vi.spyOn(Element.prototype, "scrollWidth", "get").mockImplementation(function (this: Element) {
      return legNow(this) === leg ? 480 : 320;
    });
    const computed = window.getComputedStyle.bind(window);
    const fontPx = (el: Element): number => {
      const parent = el.parentElement;
      const declared = parent === null ? computed(el).fontSize : (el as HTMLElement).style.fontSize;
      const inherited = parent === null ? 16 : fontPx(parent);
      return declared.endsWith("%") ? (inherited * parseFloat(declared)) / 100 : inherited;
    };
    vi.spyOn(window, "getComputedStyle").mockImplementation((el, pseudo) => {
      const style = computed(el, pseudo);
      return new Proxy(style, {
        get: (target, name) => {
          const value: unknown = Reflect.get(target, name);
          if (name === "fontSize") return `${fontPx(el)}px`;
          return typeof value === "function" ? value.bind(target) : value;
        },
      });
    });
    const css = document.head.appendChild(document.createElement("style"));
    css.textContent = pageCss;
    try {
      const host = await mount(
        <ThemeProvider store={newStore()}>
          <TextScaleReflow />
        </ThemeProvider>,
      );
      await act(async () => TextScaleReflow.play?.({ canvasElement: host }));
    } finally {
      css.remove();
    }
  }

  it("passes while the text fits at every text scale and at a 200 % zoom", async () => {
    await expect(playWithOverflowAt()).resolves.toBeUndefined();
  });

  it.each(["100", "112", "125", "150", "200"])(
    "fails when the text overflows its box at %s",
    async (leg) => {
      await expect(playWithOverflowAt(leg)).rejects.toThrow(/less than or equal to 320/);
    },
  );

  it("fails when theme.css is not loaded, instead of passing with text that never grows", async () => {
    await expect(playWithOverflowAt(undefined, "")).rejects.toThrow(/expected '' to be '1'/);
  });

  it("fails when --cv-text-scale moves but the text does not grow", async () => {
    const pinned = themeCss.replace(/^\s*font-size: \d+%;\n/gm, "");
    expect(pinned).not.toBe(themeCss);
    await expect(playWithOverflowAt(undefined, pinned)).rejects.toThrow(/close to 17\.92/);
  });
});

describe("preview decorator", () => {
  it("starts every story at 100 % text scale, so a story cannot leak its scale into the next", async () => {
    const globals = { theme: "dark", density: "compact", motion: "system" };
    const story = (): ReactNode =>
      withThemeRuntime(() => <i />, { globals } as unknown as StoryContext);
    await mount(story());
    await act(async () => sharedThemeStore().setTextScale(150));
    expect(rootData["textScale"]).toBe("150");
    await mount(story()); // the next story applies the toolbar globals again on mount
    expect(rootData["textScale"]).toBe("100");
  });
});

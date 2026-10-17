// @vitest-environment jsdom
import { createRequire } from "node:module";
import { act, useEffect } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { composeStories } from "@storybook/react";
import { within } from "@storybook/test";
import { describe, expect, it, vi } from "vitest";
import * as stories from "../../src/theme/ThemeRuntime.stories.js";
import {
  HIGH_CONTRAST_SHORTCUT,
  ThemeProvider,
  createThemeStore,
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
    const before = host.innerHTML;
    await act(async () => store.setDensity("comfortable"));
    expect(rootData["density"]).toBe("comfortable");
    expect(host.innerHTML).toBe(before);
  });

  it("owns a store when none is passed, exposes values and setters, and refuses to run without a provider", async () => {
    let api:
      | { scale: number; reduced: boolean; setScale: (s: 125) => void; override: (o: "on") => void }
      | undefined;
    const Probe = (): null => {
      const [scale, setScale] = useTextScale();
      const [reduced, override] = useReducedMotion();
      api = { scale, reduced, setScale, override };
      return null;
    };
    const options = { storage: memoryStorage(), matchMedia: mediaStub().matchMedia };
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
    expect(rootData["textScale"]).toBe("125");
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

  it("exposes the Ctrl+Shift+H contract and announces each toggle through one polite live region", () => {
    const store = newStore();
    expect(HIGH_CONTRAST_SHORTCUT.binding).toBe("Ctrl+Shift+H");
    expect(toggleHighContrastAnnounced(store)).toBe(true);
    const region = within(document.body).getByRole("status");
    expect([region.getAttribute("aria-live"), region.textContent]).toEqual([
      "polite",
      "High-contrast theme on",
    ]);
    toggleHighContrastAnnounced(store);
    expect(within(document.body).getAllByRole("status")).toHaveLength(1);
    expect(region.textContent).toBe("High-contrast theme off");
  });

  it("pre-renders the empty polite live region at mount, so the first announcement is heard", async () => {
    await mount(<ThemeProvider store={newStore()}>x</ThemeProvider>);
    expect(within(document.body).getByRole("status").textContent).toBe("");
  });
});

describe("theme runtime stories", () => {
  const { Default, StyleRecalcBenchmark } = composeStories(stories);
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

// @vitest-environment jsdom
import { act, useState, type JSX } from "react";
import { expect, userEvent, within } from "storybook/test";
import { describe, it, vi } from "vitest";
import {
  THEME_SWITCHER_COPY,
  ThemeProvider,
  ThemeSwitcher,
  ThemeSwitcherConnected,
  createThemeStore,
  type ThemeAnalyticsEvent,
  type ThemeName,
  type ThemeSwitcherProps,
} from "../src/index.js";
import { seriousViolations } from "./axe.js";
import { mount } from "./theme/mount.js";

/** A host that applies what the switcher asks for, as the store would. */
function Host(props: Partial<ThemeSwitcherProps> & { initial?: ThemeName }): JSX.Element {
  const [value, setValue] = useState<ThemeName>(props.initial ?? "dark");
  const [matchSystem, setMatchSystem] = useState(false);
  return (
    <ThemeSwitcher
      {...props}
      value={value}
      matchSystem={matchSystem}
      onChange={(next) => {
        setValue(next);
        setMatchSystem(false);
        props.onChange?.(next);
      }}
      onMatchSystemChange={(on) => {
        setMatchSystem(on);
        if (on) setValue("light"); // the system resolves to light here
        props.onMatchSystemChange?.(on);
      }}
    />
  );
}

const status = (host: HTMLElement): HTMLElement => within(host).getByRole("status");

const inertStore = (onAnalytics?: (event: ThemeAnalyticsEvent) => void) =>
  createThemeStore({
    root: document.createElement("div"),
    storage: { getItem: () => null, setItem: () => undefined },
    matchMedia: (query) =>
      ({
        matches: false,
        media: query,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
      }) as unknown as MediaQueryList,
    ...(onAnalytics ? { onAnalytics } : {}),
  });

describe("ThemeSwitcher (CMP-062)", () => {
  it("exports the default English copy", () => {
    expect(THEME_SWITCHER_COPY.label).toBe("Theme");
    expect(THEME_SWITCHER_COPY.announce["high-contrast"]).toBe("Theme changed to High Contrast");
  });

  it("renders the named radiogroup with three values and the match-system switch, off by default", async () => {
    const host = await mount(<ThemeSwitcher value="dark" />);
    const group = within(host).getByRole("radiogroup", { name: "Theme" });
    const radios = within(group).getAllByRole("radio");
    expect(radios.map((r) => r.textContent)).toEqual(["Dark", "Light", "High contrast"]);
    expect(within(group).getByRole("radio", { name: "Dark" })).toBeChecked();
    expect(within(host).getByRole("switch", { name: "Match system" })).not.toBeChecked();
    expect(host.querySelector(".cv-theme-switcher")?.getAttribute("data-cmp")).toBe("CMP-062");
  });

  it("the pre-rendered polite region says nothing on the initial render (J16)", async () => {
    const host = await mount(<ThemeSwitcher value="dark" />);
    expect(status(host)).toHaveTextContent("");
    expect(status(host)).toHaveAttribute("aria-live", "polite");
  });

  it("a chosen segment calls onChange once and speaks one sentence", async () => {
    const onChange = vi.fn();
    const host = await mount(<Host onChange={onChange} />);
    await act(async () =>
      userEvent.click(within(host).getByRole("radio", { name: "High contrast" })),
    );
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("high-contrast");
    expect(within(host).getByRole("radio", { name: "High contrast" })).toBeChecked();
    expect(status(host)).toHaveTextContent("Theme changed to High Contrast");
  });

  it("arrows move and check; a quick run speaks its last value", async () => {
    const onChange = vi.fn();
    const host = await mount(<Host onChange={onChange} />);
    await act(async () => userEvent.tab());
    expect(within(host).getByRole("radio", { name: "Dark" })).toHaveFocus();
    await act(async () => userEvent.keyboard("{ArrowRight}{ArrowRight}"));
    expect(onChange.mock.calls).toEqual([["light"], ["high-contrast"]]);
    expect(within(host).getByRole("radio", { name: "High contrast" })).toHaveFocus();
    expect(status(host)).toHaveTextContent("Theme changed to High Contrast");
    await act(async () => userEvent.tab());
    expect(within(host).getByRole("switch", { name: "Match system" })).toHaveFocus();
  });

  it("the switch reports its state and speaks the theme the host applied", async () => {
    const onMatch = vi.fn();
    const host = await mount(<Host onMatchSystemChange={onMatch} />);
    await act(async () =>
      userEvent.click(within(host).getByRole("switch", { name: "Match system" })),
    );
    expect(onMatch).toHaveBeenCalledWith(true);
    expect(within(host).getByRole("switch")).toBeChecked();
    expect(within(host).getByRole("radio", { name: "Light" })).toBeChecked();
    expect(status(host)).toHaveTextContent("Theme changed to Light");
    // Choosing a segment turns match system off (J13).
    await act(async () => userEvent.click(within(host).getByRole("radio", { name: "Dark" })));
    expect(within(host).getByRole("switch")).not.toBeChecked();
    expect(status(host)).toHaveTextContent("Theme changed to Dark");
  });

  it("two commits ending on the same theme each change the region, so both are spoken (J16)", async () => {
    const host = await mount(<Host />);
    await act(async () => userEvent.click(within(host).getByRole("radio", { name: "Dark" })));
    await act(async () => userEvent.click(within(host).getByRole("radio", { name: "Light" })));
    const first = status(host).textContent;
    // Match system on resolves to light here: the same sentence, a new DOM text.
    await act(async () => userEvent.click(within(host).getByRole("switch")));
    expect(status(host)).toHaveTextContent("Theme changed to Light");
    expect(status(host).textContent).not.toBe(first);
  });

  it("disabled: neither control changes anything", async () => {
    const onChange = vi.fn();
    const onMatch = vi.fn();
    const host = await mount(
      <ThemeSwitcher value="dark" disabled onChange={onChange} onMatchSystemChange={onMatch} />,
    );
    await act(async () => userEvent.click(within(host).getByRole("radio", { name: "Light" })));
    await act(async () => userEvent.click(within(host).getByRole("switch")));
    expect(onChange).not.toHaveBeenCalled();
    expect(onMatch).not.toHaveBeenCalled();
    expect(status(host)).toHaveTextContent("");
  });

  it("takes copy overrides for every string", async () => {
    const host = await mount(
      <Host
        copy={{
          label: "Colour theme",
          light: "Bright",
          matchSystem: "Follow the OS",
          announce: { dark: "Now dark", light: "Now bright", "high-contrast": "Now HC" },
        }}
      />,
    );
    within(host).getByRole("radiogroup", { name: "Colour theme" });
    within(host).getByRole("switch", { name: "Follow the OS" });
    await act(async () => userEvent.click(within(host).getByRole("radio", { name: "Bright" })));
    expect(status(host)).toHaveTextContent("Now bright");
  });

  it("has no serious or critical axe violations, density set", async () => {
    const host = await mount(<ThemeSwitcher value="light" matchSystem density="comfortable" />);
    expect(await seriousViolations(host)).toEqual([]);
  });
});

describe("ThemeSwitcherConnected (CMP-062, store-bound)", () => {
  it("reads and writes the store; the store emits one event per change, the mount none", async () => {
    const events: ThemeAnalyticsEvent[] = [];
    const store = inertStore((e) => events.push(e));
    const host = await mount(
      <ThemeProvider store={store}>
        <ThemeSwitcherConnected />
      </ThemeProvider>,
    );
    expect(events).toEqual([]);
    expect(within(host).getByRole("radio", { name: "Dark" })).toBeChecked();
    await act(async () => userEvent.click(within(host).getByRole("radio", { name: "Light" })));
    expect(store.getSnapshot().theme).toBe("light");
    expect(events).toEqual([
      { name: "appearance.theme_changed", theme: "light", matchSystem: false },
    ]);
    expect(status(host)).toHaveTextContent("Theme changed to Light");
  });

  it("match system on drops high contrast; off keeps the resolved theme", async () => {
    const store = inertStore();
    store.setTheme("high-contrast");
    const host = await mount(
      <ThemeProvider store={store}>
        <ThemeSwitcherConnected />
      </ThemeProvider>,
    );
    await act(async () =>
      userEvent.click(within(host).getByRole("switch", { name: "Match system" })),
    );
    expect(store.getSnapshot()).toMatchObject({ matchSystem: true, highContrast: false });
    // The fake OS is light (no dark match), so the light segment is checked.
    expect(within(host).getByRole("radio", { name: "Light" })).toBeChecked();
    expect(status(host)).toHaveTextContent("Theme changed to Light");
    await act(async () => userEvent.click(within(host).getByRole("switch")));
    expect(store.getSnapshot()).toMatchObject({ matchSystem: false, theme: "light" });
  });

  it("an outside store change (Ctrl+Shift+H path, server apply) speaks nothing here", async () => {
    const store = inertStore();
    const host = await mount(
      <ThemeProvider store={store}>
        <ThemeSwitcherConnected />
      </ThemeProvider>,
    );
    await act(async () => store.apply({ highContrast: true }, { persist: false, track: false }));
    expect(within(host).getByRole("radio", { name: "High contrast" })).toBeChecked();
    expect(status(host)).toHaveTextContent("");
  });
});

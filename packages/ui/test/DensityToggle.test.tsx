// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { createRequire } from "node:module";
import { useState, type JSX } from "react";
import { expect, fn, userEvent, within } from "storybook/test";
import { describe, it } from "vitest";
import {
  DENSITIES,
  DENSITY_TOGGLE_COPY,
  DensityToggle,
  DensityToggleConnected,
  ThemeProvider,
  createThemeStore,
  type DensityName,
  type ThemeAnalyticsEvent,
} from "../src/index.js";
import * as stories from "../src/components/DensityToggle.stories.js";
import { mediaStub, memoryStorage } from "./theme/helpers.js";
import { mount } from "./theme/mount.js";
import { clearPolite, politeText } from "./theme/polite.js";

type Axe = {
  run: (context: object, options?: object) => Promise<{ violations: { impact?: string | null }[] }>;
};
const axe = createRequire(createRequire(import.meta.url).resolve("@storybook/addon-a11y"))(
  "axe-core",
) as Axe;

const radio = (host: HTMLElement, name: string): HTMLElement =>
  within(host).getByRole("radio", { name });
const labels = (host: HTMLElement): string[] =>
  within(host)
    .getAllByRole("radio")
    .map((r) => r.textContent ?? "");

function Panel(): JSX.Element {
  const [value, setValue] = useState<DensityName>("compact");
  return <DensityToggle scope="panel" panelName="Chart panel" value={value} onChange={setValue} />;
}

describe("DensityToggle (CMP-063)", () => {
  it("global: a radiogroup named Density offering exactly the runtime DENSITIES", async () => {
    const host = await mount(<DensityToggle value="compact" onChange={fn()} />);
    expect(within(host).getByRole("radiogroup", { name: "Density" })).toBeInTheDocument();
    expect(labels(host)).toEqual(DENSITIES.map((d) => DENSITY_TOGGLE_COPY.options[d]));
    expect(radio(host, "Compact")).toBeChecked();
    const root = host.querySelector(".cv-density-toggle");
    expect(root).toHaveAttribute("data-cmp", "CMP-063");
    expect(root).toHaveAttribute("data-scope", "global");
  });

  it("panel: the group names the panel and offers exactly the runtime DENSITIES (BQ-19)", async () => {
    const plain = await mount(<Panel />);
    expect(within(plain).getByRole("radiogroup", { name: "Chart panel density" })).toBeVisible();
    expect(labels(plain)).toEqual(DENSITIES.map((d) => DENSITY_TOGGLE_COPY.options[d]));
    expect(within(plain).queryByRole("radio", { name: "Dense" })).toBeNull();
  });

  it("a committed change calls onChange once and speaks one sentence with the scope (J16)", async () => {
    const onChange = fn();
    const host = await mount(<DensityToggle value="compact" onChange={onChange} />);
    clearPolite();
    await userEvent.click(radio(host, "Comfortable"));
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith("comfortable");
    expect(await politeText()).toBe("Density: Comfortable");
    const panel = await mount(<Panel />);
    await userEvent.click(radio(panel, "Comfortable"));
    expect(await politeText()).toBe("Chart panel density: comfortable");
  });

  it("arrows commit (selection follows focus); the region keeps the last value", async () => {
    const host = await mount(<Panel />);
    await userEvent.tab();
    await userEvent.keyboard("{ArrowRight}");
    expect(radio(host, "Comfortable")).toHaveFocus();
    expect(radio(host, "Comfortable")).toBeChecked();
    expect(await politeText()).toBe("Chart panel density: comfortable");
  });

  it("a host-fed value speaks nothing and calls nothing; re-picking the checked value is no change", async () => {
    const onChange = fn();
    function Fed(): JSX.Element {
      const [value, setValue] = useState<DensityName>("compact");
      return (
        <>
          <button type="button" onClick={() => setValue("comfortable")}>
            Server apply
          </button>
          <DensityToggle value={value} onChange={onChange} />
        </>
      );
    }
    const host = await mount(<Fed />);
    clearPolite();
    await userEvent.click(within(host).getByRole("button", { name: "Server apply" }));
    expect(radio(host, "Comfortable")).toBeChecked();
    await userEvent.click(radio(host, "Comfortable"));
    expect(onChange).not.toHaveBeenCalled();
    expect(await politeText()).toBe("");
  });

  it("disabled: out of the Tab order, a click changes nothing", async () => {
    const onChange = fn();
    const host = await mount(<DensityToggle value="compact" onChange={onChange} disabled />);
    await userEvent.tab();
    expect(document.body).toHaveFocus();
    await userEvent.click(radio(host, "Comfortable"));
    expect(onChange).not.toHaveBeenCalled();
  });

  it("copy overrides replace the defaults", async () => {
    const host = await mount(
      <DensityToggle
        value="compact"
        onChange={fn()}
        copy={{ groupLabel: "Dichte", globalAnnouncement: (l) => `Dichte: ${l}` }}
      />,
    );
    expect(within(host).getByRole("radiogroup", { name: "Dichte" })).toBeInTheDocument();
    await userEvent.click(radio(host, "Comfortable"));
    expect(await politeText()).toBe("Dichte: Comfortable");
  });

  it("connected: reads and writes the store, which alone emits the analytics event once (BQ-16)", async () => {
    const events: ThemeAnalyticsEvent[] = [];
    const store = createThemeStore({
      storage: memoryStorage(),
      matchMedia: mediaStub().matchMedia,
      onAnalytics: (e) => events.push(e),
    });
    const host = await mount(
      <ThemeProvider store={store}>
        <DensityToggleConnected />
      </ThemeProvider>,
    );
    expect(radio(host, "Compact")).toBeChecked();
    expect(events).toEqual([]);
    await userEvent.click(radio(host, "Comfortable"));
    expect(store.getSnapshot().density).toBe("comfortable");
    expect(radio(host, "Comfortable")).toBeChecked();
    expect(events).toEqual([{ name: "appearance.density_changed", density: "comfortable" }]);
    expect(await politeText()).toBe("Density: Comfortable");
  });

  describe("menu form", () => {
    const MenuHost = ({ onChange }: { onChange: (v: DensityName) => void }): JSX.Element => {
      const [value, setValue] = useState<DensityName>("compact");
      return (
        <DensityToggle
          form="menu"
          value={value}
          onChange={(v) => {
            setValue(v);
            onChange(v);
          }}
        />
      );
    };
    const trigger = (host: HTMLElement, name = "Density: Compact"): HTMLElement =>
      within(host).getByRole("button", { name });

    it.each([["{Enter}"], [" "], ["{ArrowDown}"]])("opens with %j on the trigger", async (key) => {
      const host = await mount(<MenuHost onChange={fn()} />);
      trigger(host).focus();
      await userEvent.keyboard(key);
      const items = within(document.body).getAllByRole("menuitemradio");
      expect(items.map((i) => i.textContent)).toEqual(["Compact", "Comfortable"]);
      expect(items[0]).toHaveAttribute("aria-checked", "true");
      expect(items[1]).toHaveAttribute("aria-checked", "false");
    });

    it.each([["{Enter}"], [" "]])(
      "a pick with %j commits and speaks once, closes, refocuses",
      async (key) => {
        const onChange = fn();
        const host = await mount(<MenuHost onChange={onChange} />);
        await clearPolite();
        trigger(host).focus();
        await userEvent.keyboard("{Enter}{ArrowDown}");
        expect(
          within(document.body).getByRole("menuitemradio", { name: "Comfortable" }),
        ).toHaveFocus();
        await userEvent.keyboard(key);
        expect(onChange).toHaveBeenCalledTimes(1);
        expect(onChange).toHaveBeenCalledWith("comfortable");
        expect(await politeText()).toBe("Density: Comfortable");
        expect(within(document.body).queryByRole("menu")).toBeNull();
        expect(trigger(host, "Density: Comfortable")).toHaveFocus();
      },
    );

    it("re-picking the checked item is no change: no onChange, no sentence, closes, refocuses", async () => {
      const onChange = fn();
      const host = await mount(<MenuHost onChange={onChange} />);
      await clearPolite();
      trigger(host).focus();
      await userEvent.keyboard("{Enter}");
      const checked = within(document.body).getByRole("menuitemradio", { name: "Compact" });
      expect(checked).toHaveFocus();
      await userEvent.keyboard("{Enter}");
      expect(onChange).not.toHaveBeenCalled();
      expect(await politeText()).toBe("");
      expect(within(document.body).queryByRole("menu")).toBeNull();
      expect(trigger(host)).toHaveFocus();
    });

    it("Esc closes the open menu and returns focus to the trigger", async () => {
      const host = await mount(<MenuHost onChange={fn()} />);
      trigger(host).focus();
      await userEvent.keyboard("{Enter}");
      expect(within(document.body).getByRole("menu")).toBeInTheDocument();
      await userEvent.keyboard("{Escape}");
      expect(within(document.body).queryByRole("menu")).toBeNull();
      expect(trigger(host)).toHaveFocus();
    });

    it("has no serious or critical axe violations with the menu open", async () => {
      const host = await mount(<MenuHost onChange={fn()} />);
      await userEvent.click(trigger(host));
      const found = (
        await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } })
      ).violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(found).toEqual([]);
    });
  });

  it("has no serious or critical axe violations in any story", async () => {
    for (const Story of Object.values(composeStories(stories))) {
      const store = createThemeStore({
        storage: memoryStorage(),
        matchMedia: mediaStub().matchMedia,
      });
      const host = await mount(
        <ThemeProvider store={store}>
          <Story />
        </ThemeProvider>,
      );
      const found = (
        await axe.run(host, { rules: { "color-contrast": { enabled: false } } })
      ).violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(found).toEqual([]);
    }
  });
});

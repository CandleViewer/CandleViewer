// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { act, useEffect, useLayoutEffect, useRef, useState, type JSX } from "react";
import { expect, fn, userEvent, within } from "storybook/test";
import { describe, it } from "vitest";
import { Tabs, type TabItem, type TabsBaseProps } from "../src/components/index.js";
import * as stories from "../src/components/Tabs.stories.js";
import { mount } from "./theme/mount.js";

const REASON = "Your role can't view algos.";
const TABS: readonly TabItem[] = [
  { id: "a", label: "Alpha" },
  { id: "b", label: "Bravo" },
  { id: "c", label: "Charlie" },
];
const GATED: readonly TabItem[] = [
  { id: "a", label: "Alpha" },
  { id: "b", label: "Bravo", disabledReason: REASON },
  { id: "c", label: "Charlie" },
  { id: "d", label: "Delta", disabledReason: REASON },
];
const tab = (host: HTMLElement, name: string): HTMLElement =>
  within(host).getByRole("tab", { name });
const selectedOf = (host: HTMLElement): string[] =>
  within(host)
    .getAllByRole("tab")
    .filter((t) => t.getAttribute("aria-selected") === "true")
    .map((t) => t.textContent ?? "");
const textPanel = (id: string): JSX.Element => <p>Panel {id}</p>;

/** Keeps the value like a real host does. */
function Host(props: Partial<TabsBaseProps>): JSX.Element {
  const [value, setValue] = useState(props.value ?? "a");
  return (
    <Tabs
      aria-label="Sections"
      tabs={TABS}
      renderPanel={textPanel}
      {...props}
      value={value}
      onChange={(v) => {
        setValue(v);
        props.onChange?.(v);
      }}
    />
  );
}

describe("Tabs (CMP-042)", () => {
  it("renders a named tablist, tabs wired to their panels, one tab stop on the selected tab", async () => {
    const host = await mount(<Host value="b" />);
    const list = within(host).getByRole("tablist", { name: "Sections" });
    expect(list).not.toHaveAttribute("aria-orientation");
    expect(host.querySelector('[data-cmp="CMP-042"]')).not.toBeNull();
    const tabs = within(host).getAllByRole("tab");
    expect(tabs.map((t) => t.tabIndex)).toEqual([-1, 0, -1]);
    expect(selectedOf(host)).toEqual(["Bravo"]);
    const panel = within(host).getByRole("tabpanel", { name: "Bravo" });
    expect(tab(host, "Bravo")).toHaveAttribute("aria-controls", panel.id);
    expect(panel).toHaveTextContent("Panel b");
    // One panel per tab; the others are hidden and not mounted.
    const all = host.querySelectorAll('[role="tabpanel"]');
    expect(all).toHaveLength(3);
    expect([...all].filter((p) => p.hasAttribute("hidden"))).toHaveLength(2);
    expect(host).not.toHaveTextContent("Panel a");
  });

  it("vertical: aria-orientation=vertical", async () => {
    const host = await mount(<Host orientation="vertical" />);
    expect(within(host).getByRole("tablist")).toHaveAttribute("aria-orientation", "vertical");
  });

  it("automatic: arrows, Home and End move and select, wrapping; focus stays on the tab", async () => {
    const onChange = fn();
    const host = await mount(<Host onChange={onChange} />);
    await userEvent.tab();
    expect(tab(host, "Alpha")).toHaveFocus();
    await userEvent.keyboard("{ArrowRight}");
    expect(tab(host, "Bravo")).toHaveFocus();
    expect(selectedOf(host)).toEqual(["Bravo"]);
    await userEvent.keyboard("{End}{ArrowRight}");
    expect(selectedOf(host)).toEqual(["Alpha"]);
    await userEvent.keyboard("{ArrowLeft}");
    expect(tab(host, "Charlie")).toHaveFocus();
    await userEvent.keyboard("{Home}");
    expect(onChange.mock.calls.map((c) => c[0])).toEqual(["b", "c", "a", "c", "a"]);
  });

  it("manual: arrows move focus only; Enter or Space selects the focused tab", async () => {
    const onChange = fn();
    const host = await mount(<Host activation="manual" onChange={onChange} />);
    await userEvent.tab();
    await userEvent.keyboard("{ArrowRight}");
    expect(tab(host, "Bravo")).toHaveFocus();
    expect(selectedOf(host)).toEqual(["Alpha"]);
    expect(onChange).not.toHaveBeenCalled();
    await userEvent.keyboard("{Enter}");
    expect(selectedOf(host)).toEqual(["Bravo"]);
    await userEvent.keyboard("{ArrowRight} ");
    expect(selectedOf(host)).toEqual(["Charlie"]);
    expect(tab(host, "Charlie")).toHaveFocus();
    expect(onChange.mock.calls.map((c) => c[0])).toEqual(["b", "c"]);
  });

  it("manual: Tab from a focused, unselected tab goes into the panel; focus leaving resets the tab stop", async () => {
    const host = await mount(<Host activation="manual" />);
    await userEvent.tab();
    await userEvent.keyboard("{ArrowRight}");
    expect(tab(host, "Bravo").tabIndex).toBe(0);
    await userEvent.tab();
    expect(within(host).getByRole("tabpanel")).toHaveFocus();
    expect(tab(host, "Alpha").tabIndex).toBe(0);
  });

  it("a gated tab: aria-disabled, the reason as its description, one shared reason line", async () => {
    const host = await mount(<Host tabs={GATED} />);
    const bravo = tab(host, "Bravo");
    expect(bravo).toHaveAttribute("aria-disabled", "true");
    expect(bravo).not.toHaveAttribute("disabled");
    expect(bravo).toHaveAccessibleDescription(REASON);
    expect(tab(host, "Delta").getAttribute("aria-describedby")).toBe(
      bravo.getAttribute("aria-describedby"),
    );
    expect(within(host).getAllByText(REASON)).toHaveLength(1);
    expect(tab(host, "Alpha")).not.toHaveAttribute("aria-describedby");
  });

  it.each(["automatic", "manual"] as const)(
    "%s: an arrow onto a gated tab focuses it, selects nothing and says nothing",
    async (activation) => {
      const onChange = fn();
      const host = await mount(<Host tabs={GATED} activation={activation} onChange={onChange} />);
      await userEvent.tab();
      await userEvent.keyboard("{ArrowRight}");
      expect(tab(host, "Bravo")).toHaveFocus();
      expect(selectedOf(host)).toEqual(["Alpha"]);
      expect(within(host).getByRole("status")).toBeEmptyDOMElement();
      await userEvent.keyboard("{End}");
      expect(tab(host, "Delta")).toHaveFocus();
      expect(onChange).not.toHaveBeenCalled();
    },
  );

  it.each(["{Enter}", " "])(
    "%s on a gated tab selects nothing and re-announces the reason once per press",
    async (key) => {
      const onChange = fn();
      const host = await mount(<Host tabs={GATED} onChange={onChange} />);
      await userEvent.tab();
      await userEvent.keyboard("{ArrowRight}");
      const status = within(host).getByRole("status");
      await userEvent.keyboard(key);
      expect(status).toHaveTextContent(REASON);
      const first = status.firstElementChild;
      await userEvent.keyboard(key);
      // A fresh node: the polite region speaks the same sentence again.
      expect(status.firstElementChild).not.toBe(first);
      expect(status.childElementCount).toBe(1);
      expect(onChange).not.toHaveBeenCalled();
      // Moving on clears it, so landing elsewhere stays silent.
      await userEvent.keyboard("{ArrowRight}");
      expect(status).toBeEmptyDOMElement();
    },
  );

  it("a press selects a tab in both modes; a press on a gated tab refuses with the reason", async () => {
    const onChange = fn();
    const host = await mount(<Host tabs={GATED} activation="manual" onChange={onChange} />);
    await userEvent.click(tab(host, "Charlie"));
    expect(selectedOf(host)).toEqual(["Charlie"]);
    expect(tab(host, "Charlie")).toHaveFocus();
    await userEvent.click(tab(host, "Bravo"));
    expect(selectedOf(host)).toEqual(["Charlie"]);
    expect(tab(host, "Bravo")).toHaveFocus();
    expect(within(host).getByRole("status")).toHaveTextContent(REASON);
    await userEvent.click(tab(host, "Charlie"));
    expect(onChange.mock.calls.map((c) => c[0])).toEqual(["c"]);
  });

  it("the status clears when focus leaves the strip", async () => {
    const host = await mount(
      <>
        <Host tabs={GATED} />
        <button type="button">After</button>
      </>,
    );
    await userEvent.click(tab(host, "Bravo"));
    expect(within(host).getByRole("status")).toHaveTextContent(REASON);
    await userEvent.click(within(host).getByRole("button", { name: "After" }));
    expect(within(host).getByRole("status")).toBeEmptyDOMElement();
  });

  it("J10: an empty-of-controls panel is a tab stop; one holding a control is not", async () => {
    const renderPanel = (id: string): JSX.Element =>
      id === "a" ? <p>Text only</p> : <button type="button">Act</button>;
    const host = await mount(<Host renderPanel={renderPanel} />);
    expect(within(host).getByRole("tabpanel")).toHaveAttribute("tabindex", "0");
    await userEvent.click(tab(host, "Bravo"));
    expect(within(host).getByRole("tabpanel")).not.toHaveAttribute("tabindex");
  });

  it("J10: the panel's tab stop follows content that arrives after mount", async () => {
    function Late(): JSX.Element {
      const [ready, setReady] = useState(false);
      return (
        <>
          <button type="button" onClick={() => setReady(true)}>
            Load
          </button>
          <Host renderPanel={() => (ready ? <a href="#x">Row</a> : <p>Loading</p>)} />
        </>
      );
    }
    const host = await mount(<Late />);
    expect(within(host).getByRole("tabpanel")).toHaveAttribute("tabindex", "0");
    await userEvent.click(within(host).getByRole("button", { name: "Load" }));
    await act(async () => Promise.resolve());
    expect(within(host).getByRole("tabpanel")).not.toHaveAttribute("tabindex");
  });

  it("a lazy panel that grabs focus as it mounts never steals it from the tab", async () => {
    // One grabs focus in its effect, the other in its layout pass (as autoFocus does).
    function Grabby({ layout }: { readonly layout: boolean }): JSX.Element {
      const ref = useRef<HTMLInputElement>(null);
      const useGrab = layout ? useLayoutEffect : useEffect;
      useGrab(() => ref.current?.focus(), []);
      return <input ref={ref} aria-label="Grabby" />;
    }
    const renderPanel = (id: string): JSX.Element =>
      id === "a" ? <p>A</p> : <Grabby layout={id === "c"} />;
    const host = await mount(<Host renderPanel={renderPanel} />);
    await userEvent.tab();
    await userEvent.keyboard("{ArrowRight}");
    expect(tab(host, "Bravo")).toHaveFocus();
    await userEvent.keyboard("{ArrowRight}");
    expect(tab(host, "Charlie")).toHaveFocus();
  });

  it("a host's own value change never moves focus", async () => {
    function Remote(): JSX.Element {
      const [value, setValue] = useState("a");
      return (
        <>
          <button type="button" onClick={() => setValue("b")}>
            Go
          </button>
          <Tabs
            aria-label="Sections"
            tabs={TABS}
            value={value}
            onChange={setValue}
            renderPanel={textPanel}
          />
        </>
      );
    }
    const host = await mount(<Remote />);
    const go = within(host).getByRole("button", { name: "Go" });
    await userEvent.click(go);
    expect(selectedOf(host)).toEqual(["Bravo"]);
    expect(go).toHaveFocus();
  });

  it("ignores Alt, Ctrl and Meta chords", async () => {
    const onChange = fn();
    const host = await mount(<Host onChange={onChange} />);
    await userEvent.tab();
    await userEvent.keyboard("{Control>}{ArrowRight}{/Control}");
    expect(tab(host, "Alpha")).toHaveFocus();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("leading icons are decorative: the name stays the label", async () => {
    const tabs: TabItem[] = [
      { id: "a", label: "Alpha", icon: "search" },
      { id: "b", label: "Bravo" },
    ];
    const host = await mount(<Host tabs={tabs} />);
    expect(tab(host, "Alpha").querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });
});

describe("Tabs stories", () => {
  it.each(Object.entries(composeStories(stories)))("%s renders", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(within(host).getAllByRole("tablist").length).toBeGreaterThan(0);
  });
});

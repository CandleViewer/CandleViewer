// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { act, useState, type JSX } from "react";
import { expect, fn, userEvent, within } from "storybook/test";
import { describe, it } from "vitest";
import { Button, FilterBar, type FilterChip } from "../src/components/index.js";
import * as stories from "../src/components/FilterBar.stories.js";
import { seriousViolations } from "./axe.js";
import { mount } from "./theme/mount.js";

const page = within(document.body);
const group = (): HTMLElement => page.getByRole("group", { name: "Active filters" });
const remove = (label: string): HTMLElement =>
  page.getByRole("button", { name: `Remove filter ${label}` });
const addButton = (): HTMLElement => page.getByRole("button", { name: "Filter" });

/** A host that drops chips as the bar asks; `drop` false keeps them (a host that refuses). */
function Host({
  initial,
  drop = true,
  add = true,
  onClear,
}: {
  readonly initial: readonly string[];
  readonly drop?: boolean;
  readonly add?: boolean;
  readonly onClear?: () => void;
}): JSX.Element {
  const [labels, setLabels] = useState(initial);
  const filters: FilterChip[] = labels.map((label) => ({
    id: label,
    label,
    onRemove: () => {
      if (drop) setLabels((all) => all.filter((l) => l !== label));
    },
  }));
  return (
    <>
      <FilterBar
        filters={filters}
        onClearAll={() => {
          onClear?.();
          if (drop) setLabels([]);
        }}
        {...(add ? { addFilter: <Button iconLeft="plus">Filter</Button> } : {})}
      />
      <Button>Elsewhere</Button>
      <Button onClick={() => setLabels((all) => all.slice(1))}>Drop first</Button>
    </>
  );
}

describe("FilterBar (CMP-055)", () => {
  it("marks exactly one root with data-cmp", async () => {
    const host = await mount(<FilterBar filters={[]} />);
    expect(host.querySelectorAll('[data-cmp="CMP-055"]')).toHaveLength(1);
  });

  it("is a group named 'Active filters' of CMP-011 chips, each remove named 'Remove filter {label}'", async () => {
    await mount(<Host initial={["Account: Sub-1", "Symbol: BTCUSDT"]} />);
    const bar = group();
    expect(bar.dataset["cmp"]).toBe("CMP-055");
    expect(bar.querySelectorAll('[data-cmp="CMP-011"]')).toHaveLength(2);
    expect(within(bar).getByText("Account: Sub-1")).toBeDefined();
    expect(remove("Account: Sub-1").dataset["cmp"]).toBe("CMP-002");
    expect(remove("Symbol: BTCUSDT")).toBeDefined();
  });

  it("orders chips, then the add control, then 'Clear all'", async () => {
    await mount(<Host initial={["Account: Sub-1", "Symbol: BTCUSDT"]} />);
    const order = within(group())
      .getAllByRole("button")
      .map((b) => b.getAttribute("aria-label") ?? b.textContent);
    expect(order).toEqual([
      "Remove filter Account: Sub-1",
      "Remove filter Symbol: BTCUSDT",
      "Filter",
      "Clear all",
    ]);
  });

  it("shows 'Clear all' from two chips on, and only with onClearAll", async () => {
    await mount(<Host initial={["Account: Sub-1"]} />);
    expect(page.queryByRole("button", { name: "Clear all" })).toBeNull();
    const host = await mount(
      <FilterBar
        filters={[
          { id: "a", label: "Account: Sub-1", onRemove: fn() },
          { id: "s", label: "Symbol: BTCUSDT", onRemove: fn() },
        ]}
      />,
    );
    expect(within(host).queryByRole("button", { name: "Clear all" })).toBeNull();
  });

  it("Enter and Space on a remove drop that chip; focus moves to the next remove, then the previous", async () => {
    await mount(<Host initial={["Account: Sub-1", "Symbol: BTCUSDT", "Side: Long"]} />);
    await userEvent.tab();
    expect(remove("Account: Sub-1")).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(page.queryByText("Account: Sub-1")).toBeNull();
    expect(remove("Symbol: BTCUSDT")).toHaveFocus();
    await userEvent.tab();
    expect(remove("Side: Long")).toHaveFocus();
    await userEvent.keyboard(" ");
    // The last chip went: its previous neighbour takes focus.
    expect(remove("Symbol: BTCUSDT")).toHaveFocus();
  });

  it("the last chip's removal hands focus to the add control", async () => {
    await mount(<Host initial={["Account: Sub-1"]} />);
    await userEvent.click(remove("Account: Sub-1"));
    expect(addButton()).toHaveFocus();
  });

  it("without an add control, the last removal leaves focus on the group, never the body", async () => {
    await mount(<Host initial={["Account: Sub-1"]} add={false} />);
    await userEvent.click(remove("Account: Sub-1"));
    expect(group()).toHaveFocus();
    expect(group()).toHaveAttribute("tabindex", "-1");
  });

  it("'Clear all' drops every chip and hands focus to the add control", async () => {
    const onClear = fn();
    await mount(<Host initial={["Account: Sub-1", "Symbol: BTCUSDT"]} onClear={onClear} />);
    await userEvent.click(page.getByRole("button", { name: "Clear all" }));
    expect(onClear).toHaveBeenCalledTimes(1);
    expect(page.queryByRole("button", { name: /^Remove filter/ })).toBeNull();
    expect(page.queryByRole("button", { name: "Clear all" })).toBeNull();
    expect(addButton()).toHaveFocus();
  });

  it("a host that keeps the chip keeps focus on its remove", async () => {
    await mount(<Host initial={["Account: Sub-1", "Symbol: BTCUSDT"]} drop={false} />);
    await userEvent.click(remove("Account: Sub-1"));
    expect(remove("Account: Sub-1")).toHaveFocus();
    await userEvent.click(page.getByRole("button", { name: "Clear all" }));
    expect(page.getByRole("button", { name: "Clear all" })).toHaveFocus();
  });

  it("never takes focus from elsewhere when a pending chip leaves later", async () => {
    await mount(<Host initial={["Account: Sub-1", "Symbol: BTCUSDT"]} drop={false} />);
    await userEvent.click(remove("Account: Sub-1"));
    const elsewhere = page.getByRole("button", { name: "Elsewhere" });
    await act(async () => elsewhere.focus());
    // The host drops the first chip on its own, later: focus stays where the user put it.
    await userEvent.click(page.getByRole("button", { name: "Drop first" }));
    expect(page.getByRole("button", { name: "Drop first" })).toHaveFocus();
    expect(page.queryByText("Account: Sub-1")).toBeNull();
  });

  it("a re-render that keeps the pending chip moves nothing", async () => {
    await mount(<Host initial={["Account: Sub-1", "Symbol: BTCUSDT"]} drop={false} />);
    await userEvent.click(remove("Symbol: BTCUSDT"));
    // Another chip goes; the pending one is still there, so the bar hands nothing on.
    await userEvent.click(page.getByRole("button", { name: "Drop first" }));
    expect(page.getByRole("button", { name: "Drop first" })).toHaveFocus();
    expect(remove("Symbol: BTCUSDT")).toBeDefined();
  });

  it("emits density on the bar and its chips", async () => {
    const host = await mount(
      <FilterBar
        density="comfortable"
        filters={[{ id: "a", label: "Account: Sub-1", onRemove: fn() }]}
      />,
    );
    expect(within(host).getByRole("group").dataset["density"]).toBe("comfortable");
    expect(host.querySelector(".cv-tag")?.getAttribute("data-density")).toBe("comfortable");
  });

  it("has no serious or critical axe violation, empty or with chips", async () => {
    await mount(<Host initial={[]} />);
    expect(await seriousViolations(document.body)).toEqual([]);
    await mount(<Host initial={["Account: Sub-1", "Symbol: BTCUSDT"]} />);
    expect(await seriousViolations(document.body)).toEqual([]);
  });
});

describe("FilterBar stories", () => {
  it.each(Object.entries(composeStories(stories)))("%s renders", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(within(host).getByRole("group", { name: "Active filters" })).toBeDefined();
  });
});

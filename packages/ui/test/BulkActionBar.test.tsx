// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";
import { describe, expectTypeOf, it } from "vitest";
import * as Entry from "../src/index.js";
import {
  BulkActionBar,
  type BulkAction,
  type BulkActionBarProps,
} from "../src/components/BulkActionBar.js";
import * as stories from "../src/components/BulkActionBar.stories.js";
import { seriousViolations } from "./axe.js";
import { find, loadCss } from "./css-contract.js";
import { mount } from "./theme/mount.js";

const actions = (): BulkAction[] => [
  { id: "disarm", label: "Disarm", onClick: fn() },
  { id: "export", label: "Export", onClick: fn() },
];
const toolbar = (host: HTMLElement): HTMLElement => within(host).getByRole("toolbar");

describe("BulkActionBar (CMP-243): states", () => {
  it("is exported from the package entry", () => {
    expect(Entry.BulkActionBar).toBe(BulkActionBar);
  });

  it("hidden with no selection: nothing renders", async () => {
    const host = await mount(<BulkActionBar count={0} actions={actions()} onClear={fn()} />);
    expect(within(host).queryByRole("toolbar")).toBeNull();
    expect(host).toBeEmptyDOMElement();
  });

  it("shown with a selection: a toolbar named by its count, the actions in order, then Clear", async () => {
    const host = await mount(<BulkActionBar count={3} actions={actions()} onClear={fn()} />);
    const bar = within(host).getByRole("toolbar", { name: "3 selected" });
    expect(bar).toHaveAttribute("data-cmp", "CMP-243");
    expect(
      within(bar)
        .getAllByRole("button")
        .map((b) => [b.textContent, b.dataset["cmp"]]),
    ).toEqual([
      ["Disarm", "CMP-001"],
      ["Export", "CMP-001"],
      ["Clear", "CMP-001"],
    ]);
  });

  it("updates its count text and name as the selection grows", async () => {
    const host = await mount(<BulkActionBar count={12} actions={actions()} onClear={fn()} />);
    expect(toolbar(host)).toHaveAccessibleName("12 selected");
  });
});

describe("BulkActionBar: actions, Clear and the keyboard", () => {
  it("each action's press calls its own handler; Clear calls onClear", async () => {
    const list = actions();
    const onClear = fn();
    const host = await mount(<BulkActionBar count={2} actions={list} onClear={onClear} />);
    await userEvent.click(within(host).getByRole("button", { name: "Export" }));
    await userEvent.click(within(host).getByRole("button", { name: "Clear" }));
    expect(list[1]?.onClick).toHaveBeenCalledTimes(1);
    expect(list[0]?.onClick).not.toHaveBeenCalled();
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it("its appearance never moves focus", async () => {
    const outside = document.body.appendChild(document.createElement("button"));
    outside.focus();
    await mount(<BulkActionBar count={3} actions={actions()} onClear={fn()} />);
    expect(outside).toHaveFocus();
  });

  it("is one Tab stop: → / ← rove with wrap, Home / End jump, Tab leaves", async () => {
    const host = await mount(
      <div>
        <BulkActionBar count={3} actions={actions()} onClear={fn()} />
        <button type="button">After</button>
      </div>,
    );
    const button = (name: string): HTMLElement => within(host).getByRole("button", { name });
    await userEvent.tab();
    expect(button("Disarm")).toHaveFocus();
    await userEvent.keyboard("{ArrowRight}");
    expect(button("Export")).toHaveFocus();
    await userEvent.keyboard("{End}");
    expect(button("Clear")).toHaveFocus();
    await userEvent.keyboard("{ArrowRight}");
    expect(button("Disarm")).toHaveFocus();
    await userEvent.keyboard("{ArrowLeft}");
    expect(button("Clear")).toHaveFocus();
    await userEvent.keyboard("{Home}");
    expect(button("Disarm")).toHaveFocus();
    expect(
      within(toolbar(host))
        .getAllByRole("button")
        .map((b) => b.tabIndex),
    ).toEqual([0, -1, -1]);
    await userEvent.tab();
    expect(button("After")).toHaveFocus();
  });

  it("Enter and Space press the roving button", async () => {
    const onClear = fn();
    const host = await mount(<BulkActionBar count={1} actions={[]} onClear={onClear} />);
    await userEvent.tab();
    await userEvent.keyboard("{Enter} ");
    expect(onClear).toHaveBeenCalledTimes(2);
    expect(within(host).getByRole("button", { name: "Clear" })).toHaveFocus();
  });

  it("a gated action is T2: focusable, aria-disabled with its reason, and a press does nothing", async () => {
    const onClick = fn();
    const reason = "Your role can't change rules.";
    const host = await mount(
      <BulkActionBar
        count={3}
        actions={[{ id: "disarm", label: "Disarm", onClick, disabledReason: reason }]}
        onClear={fn()}
      />,
    );
    const disarm = within(host).getByRole("button", { name: /Disarm/ });
    expect(disarm).toHaveAttribute("aria-disabled", "true");
    expect(disarm).toHaveAccessibleDescription(reason);
    await userEvent.tab();
    expect(disarm).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    expect(onClick).not.toHaveBeenCalled();
  });

  it("the type-level contract: count, actions and onClear, and nothing else is required", () => {
    expectTypeOf({
      count: 1,
      actions: [],
      onClear: () => undefined,
    }).toExtend<BulkActionBarProps>();
    expectTypeOf({ count: 1, actions: [] }).not.toExtend<BulkActionBarProps>();
  });

  it("has no serious or critical axe violation, with a gated action", async () => {
    const host = await mount(
      <BulkActionBar
        count={3}
        actions={[...actions(), { id: "x", label: "Delete", onClick: fn(), disabledReason: "No." }]}
        onClear={fn()}
      />,
    );
    expect(await seriousViolations(host)).toEqual([]);
  });
});

describe("bulkactionbar.css contract (A-14, A-17)", () => {
  const css = loadCss("bulkactionbar.css");

  it("binds tokens only: no raw colour and no raw length", () => {
    expect(css.all).not.toMatch(/#[0-9a-f]{3,8}\b|rgba?\(|hsla?\(/i);
    expect(css.all).not.toMatch(/\d+px/);
  });

  it("appears through the panel-in recipe alone, which resolves to none under reduced motion", () => {
    expect(find(css.normal, ".cv-bulk-bar", "animation")).toContain(
      "animation: var(--cv-recipe-panel-in)",
    );
    expect(css.all).not.toMatch(/transition/);
    expect(css.all.match(/animation:/g)).toHaveLength(1);
  });

  it("never truncates a button's label: a narrow bar wraps", () => {
    expect(find(css.normal, ".cv-bulk-bar", "flex-wrap")).toContain("flex-wrap: wrap");
    expect(find(css.normal, ".cv-bulk-bar > .cv-button", "flex")).toContain("flex: none");
  });
});

describe("BulkActionBar stories", () => {
  // ReducedMotion reads the computed animation, which needs the stylesheet: the storybook project runs it.
  const all = Object.entries(composeStories(stories)).filter(([name]) => name !== "ReducedMotion");

  it("runs each story's play function", { timeout: 20_000 }, async () => {
    for (const [name, Story] of all) {
      const canvasElement = document.body.appendChild(document.createElement("div"));
      await expect(Story.run({ canvasElement }), name).resolves.toBeUndefined();
    }
  });
});

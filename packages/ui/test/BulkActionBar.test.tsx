// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { useState, type JSX } from "react";
import { expect, fireEvent, fn, userEvent, within } from "storybook/test";
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

  it("leaves modified arrows and Home / End to the browser", async () => {
    const host = await mount(<BulkActionBar count={3} actions={actions()} onClear={fn()} />);
    await userEvent.tab();
    const first = within(host).getByRole("button", { name: "Disarm" });
    expect(first).toHaveFocus();
    await userEvent.keyboard(
      "{Alt>}{ArrowRight}{/Alt}{Control>}{End}{/Control}{Meta>}{ArrowLeft}{/Meta}",
    );
    expect(first).toHaveFocus();
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

  it("a key from a descendant that is not a button (the count) is left alone: no roving, default intact", async () => {
    const host = await mount(<BulkActionBar count={3} actions={actions()} onClear={fn()} />);
    const bar = toolbar(host);
    const count = within(bar).getByText("3 selected");
    const kept = [];
    for (const key of ["ArrowRight", "End", "ArrowLeft", "Home"]) {
      kept.push(await fireEvent.keyDown(count, { key }));
    }
    expect(kept).toEqual([true, true, true, true]);
    expect(within(bar).getByRole("button", { name: "Disarm" })).not.toHaveFocus();
    expect(
      within(bar)
        .getAllByRole("button")
        .map((b) => b.tabIndex),
    ).toEqual([0, -1, -1]);
  });

  it("when the actions shrink under the roving stop, the stop clamps to the last button: one Tab stop stays", async () => {
    function Shrinking(): JSX.Element {
      const [list, setList] = useState(actions);
      return (
        <BulkActionBar count={2} actions={list} onClear={() => setList((now) => now.slice(1))} />
      );
    }
    const host = await mount(<Shrinking />);
    await userEvent.click(within(host).getByRole("button", { name: "Clear" }));
    const stops = (): [string | null, number][] =>
      within(toolbar(host))
        .getAllByRole("button")
        .map((b) => [b.textContent, b.tabIndex]);
    expect(stops()).toEqual([
      ["Export", -1],
      ["Clear", 0],
    ]);
    await userEvent.keyboard("{ArrowLeft}");
    expect(within(host).getByRole("button", { name: "Export" })).toHaveFocus();
  });

  it("a handled roving key (arrows, Home, End) is prevented, so it never scrolls the panel", async () => {
    const host = await mount(<BulkActionBar count={3} actions={actions()} onClear={fn()} />);
    const disarm = within(host).getByRole("button", { name: "Disarm" });
    disarm.focus();
    const kept = [];
    for (const key of ["ArrowRight", "End", "ArrowLeft", "Home"]) {
      const focused = document.activeElement ?? disarm;
      kept.push(await fireEvent.keyDown(focused, { key }));
    }
    expect(kept).toEqual([false, false, false, false]);
    expect(disarm).toHaveFocus();
  });

  /** A host whose action list changes from Clear's press (focus stays on Clear) or from a gated toggle. */
  const stopsOf = (host: HTMLElement): [string | null, number][] =>
    within(toolbar(host))
      .getAllByRole("button")
      .map((b) => [b.textContent, b.tabIndex]);

  it("an action added before the focused button: the stop stays on it, and ← moves from it", async () => {
    const hideLock = (): BulkAction[] => [
      { id: "hide", label: "Hide", onClick: fn() },
      { id: "lock", label: "Lock", onClick: fn() },
    ];
    function Growing(): JSX.Element {
      const [list, setList] = useState(hideLock);
      return (
        <BulkActionBar
          count={2}
          actions={list}
          onClear={() => setList((now) => [{ id: "show", label: "Show", onClick: fn() }, ...now])}
        />
      );
    }
    const host = await mount(<Growing />);
    await userEvent.click(within(host).getByRole("button", { name: "Clear" }));
    expect(stopsOf(host)).toEqual([
      ["Show", -1],
      ["Hide", -1],
      ["Lock", -1],
      ["Clear", 0],
    ]);
    await userEvent.keyboard("{ArrowLeft}");
    expect(within(host).getByRole("button", { name: "Lock" })).toHaveFocus();
  });

  it("an action removed before the focused button: the stop stays on it, and → moves from it", async () => {
    function Dropping(): JSX.Element {
      const [list, setList] = useState<BulkAction[]>(() => [
        { id: "disarm", label: "Disarm", onClick: fn() },
        { id: "export", label: "Export", onClick: () => setList((now) => now.slice(1)) },
      ]);
      return <BulkActionBar count={2} actions={list} onClear={fn()} />;
    }
    const host = await mount(<Dropping />);
    const exportButton = within(host).getByRole("button", { name: "Export" });
    await userEvent.click(exportButton);
    expect(exportButton).toHaveFocus();
    expect(stopsOf(host)).toEqual([
      ["Export", 0],
      ["Clear", -1],
    ]);
    await userEvent.keyboard("{ArrowRight}");
    expect(within(host).getByRole("button", { name: "Clear" })).toHaveFocus();
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

  it("its height is the host's custom property, falling back to the control height (`15` CMP-243 Tokens)", () => {
    expect(find(css.normal, ".cv-bulk-bar", "min-block-size")).toContain(
      "min-block-size: var(--cv-bulk-bar-height, var(--size-control-height))",
    );
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

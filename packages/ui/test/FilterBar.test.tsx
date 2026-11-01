// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { act, useState, type JSX } from "react";
import { expect, fireEvent, fn, userEvent, within } from "storybook/test";
import { describe, it } from "vitest";
import {
  FilterBar,
  type FilterBarField,
  type FilterBarFilter,
  type FilterBarProps,
} from "../src/components/index.js";
import * as stories from "../src/components/FilterBar.stories.js";
import { seriousViolations } from "./axe.js";
import { mount } from "./theme/mount.js";

// E16-D02 §1's filter row: "Add filter" offers Reason, State, Pinned and Needs attention (BQ-10).
const options = (...labels: string[]) =>
  labels.map((label) => ({ value: label.toLowerCase(), label }));
const FIELDS: readonly FilterBarField[] = [
  { id: "reason", label: "Reason", options: options("Manual", "Auto") },
  { id: "state", label: "State", options: options("Recording", "Degraded", "Stopped") },
  { id: "pinned", label: "Pinned", options: options("Yes", "No") },
  { id: "attention", label: "Needs attention", options: options("Yes", "No") },
];
const AUTO: FilterBarFilter = { field: "reason", value: "auto" };
const DEGRADED: FilterBarFilter = { field: "state", value: "degraded" };
const PINNED: FilterBarFilter = { field: "pinned", value: "yes" };
const REASON = "Only the owner can change recording.";

const page = within(document.body);
const button = (name: string): HTMLButtonElement =>
  page.getByRole("button", { name }) as HTMLButtonElement;
const group = (): HTMLElement => page.getByRole("group", { name: "Active filters" });

type HostProps = Partial<FilterBarProps> & { readonly initial?: readonly FilterBarFilter[] };
let setFromHost: (next: readonly FilterBarFilter[]) => void = () => undefined;

/** The host owns the list, as a screen does (its URL or store): every change lands, and is recorded. */
function Host({ initial = [], onChange, ...props }: HostProps): JSX.Element {
  const [value, setValue] = useState(initial);
  setFromHost = setValue;
  const change = (next: readonly FilterBarFilter[]): void => {
    onChange?.(next);
    setValue(next);
  };
  return <FilterBar fields={FIELDS} value={value} onChange={change} {...props} />;
}

describe("FilterBar (CMP-055): names and states", () => {
  it("is a group named 'Active filters'; each chip says its whole filter, and so does its remove", async () => {
    await mount(<Host initial={[AUTO, DEGRADED, { field: "venue", value: "x" }]} />);
    expect(group()).toHaveAttribute("data-cmp", "CMP-055");
    const chips = within(group()).getAllByRole("listitem");
    expect(chips.map((chip) => chip.textContent)).toEqual([
      "Reason: Auto",
      "State: Degraded",
      "venue: x",
    ]);
    expect(button("Remove Reason: Auto")).toBeVisible();
    expect(button("Remove State: Degraded")).toBeVisible();
    expect(button("Add filter")).toHaveAttribute("aria-haspopup", "menu");
    expect(button("Clear all")).toBeVisible(); // from two chips on (one: the WithFilters story)
  });

  it("empty: says so and offers Add filter; no list and no Clear all", async () => {
    await mount(<Host />);
    expect(within(group()).getByText("No filters")).toBeVisible();
    expect(within(group()).queryByRole("list")).toBeNull();
    expect(button("Add filter")).toBeVisible();
    expect(page.queryByRole("button", { name: "Clear all" })).toBeNull();
  });
});

describe("FilterBar (CMP-055): keyboard and focus", () => {
  it("Tab reaches each chip's remove, then Add filter, then Clear all", async () => {
    await mount(<Host initial={[AUTO, DEGRADED]} />);
    const order = ["Remove Reason: Auto", "Remove State: Degraded", "Add filter", "Clear all"];
    for (const name of order) {
      await userEvent.tab();
      expect(button(name)).toHaveFocus();
    }
  });

  it.each(["{Enter}", " ", "{Delete}", "{Backspace}"])(
    "%s on a chip removes it and focus moves to the next chip",
    async (key) => {
      const onChange = fn();
      await mount(<Host initial={[AUTO, DEGRADED, PINNED]} onChange={onChange} />);
      act(() => button("Remove State: Degraded").focus());
      await userEvent.keyboard(key);
      expect(onChange.mock.calls).toEqual([[[AUTO, PINNED]]]);
      expect(button("Remove Pinned: Yes")).toHaveFocus();
    },
  );

  it("the last chip hands focus back to the previous one, the only chip to Add filter", async () => {
    await mount(<Host initial={[AUTO, DEGRADED]} />);
    act(() => button("Remove State: Degraded").focus());
    await userEvent.keyboard("{Delete}");
    expect(button("Remove Reason: Auto")).toHaveFocus();
    await userEvent.keyboard("{Backspace}");
    expect(button("Add filter")).toHaveFocus();
    expect(within(group()).getByText("No filters")).toBeVisible();
  });

  it("a held key acts once: its repeats are refused, so none reaches the control focus moved to", async () => {
    const onChange = fn();
    await mount(<Host initial={[AUTO, DEGRADED, PINNED]} onChange={onChange} />);
    act(() => button("Remove Reason: Auto").focus());
    await userEvent.keyboard("{Delete}");
    const next = button("Remove State: Degraded");
    expect(next).toHaveFocus();
    // user-event never sets `repeat` under jsdom: a held key's repeats are dispatched as such.
    for (const key of ["Delete", "Backspace", "Enter"])
      expect(fireEvent.keyDown(next, { key, repeat: true })).toBe(false);
    expect(fireEvent.keyDown(button("Add filter"), { key: "Enter", repeat: true })).toBe(false);
    expect(onChange.mock.calls).toEqual([[[DEGRADED, PINNED]]]);
  });

  it("Clear all empties the bar and leaves focus on Add filter", async () => {
    const onChange = fn();
    await mount(<Host initial={[AUTO, DEGRADED, PINNED]} onChange={onChange} />);
    await userEvent.click(button("Clear all"));
    expect(onChange.mock.calls).toEqual([[[]]]);
    expect(button("Add filter")).toHaveFocus();
  });

  it("Add filter opens the fields, each with its value submenu; an applied value is checked", async () => {
    await mount(<Host initial={[DEGRADED]} />);
    act(() => button("Add filter").focus());
    await userEvent.keyboard("{Enter}");
    const menu = page.getByRole("menu", { name: "Add filter" });
    const fields = within(menu).getAllByRole("menuitem");
    expect(fields.map((item) => item.textContent)).toEqual([
      "Reason",
      "State",
      "Pinned",
      "Needs attention",
    ]);
    fields.forEach((item) => expect(item).toHaveAttribute("aria-haspopup", "menu"));
    await userEvent.keyboard("{ArrowDown}{ArrowRight}");
    const values = page.getByRole("menu", { name: "State" });
    expect(within(values).getByRole("menuitemcheckbox", { name: "Recording" })).toHaveFocus();
    const checked = within(values).getAllByRole("menuitemcheckbox");
    expect(checked.map((item) => item.getAttribute("aria-checked"))).toEqual([
      "false",
      "true",
      "false",
    ]);
    await userEvent.keyboard("{ArrowLeft}");
    expect(page.getByRole("menuitem", { name: "State" })).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(page.queryByRole("menu")).toBeNull();
    expect(button("Add filter")).toHaveFocus();
  });

  it("Enter on a value adds it and closes, focus on Add filter; Space toggles and stays open", async () => {
    const onChange = fn();
    await mount(<Host initial={[AUTO]} onChange={onChange} />);
    act(() => button("Add filter").focus());
    await userEvent.keyboard("{Enter}{ArrowDown}{ArrowRight}{ArrowDown}{Enter}");
    expect(onChange.mock.calls).toEqual([[[AUTO, DEGRADED]]]);
    expect(page.queryByRole("menu")).toBeNull();
    expect(button("Add filter")).toHaveFocus();
    await userEvent.keyboard("{Enter}{ArrowDown}{ArrowRight}{ArrowDown} ");
    expect(onChange).toHaveBeenLastCalledWith([AUTO]);
    expect(page.getByRole("menuitemcheckbox", { name: "Degraded" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
  });
});

describe("FilterBar (CMP-055): one polite announcement per change", () => {
  it("says each change once, never on mount, a host's change too, and never per arrow key", async () => {
    const announce = fn();
    await mount(<Host initial={[AUTO, DEGRADED]} announce={announce} />);
    act(() => button("Add filter").focus());
    await userEvent.keyboard("{Enter}{ArrowDown}{ArrowDown}{ArrowRight} {ArrowDown}{ArrowUp}");
    await userEvent.keyboard("{Escape}{Escape}");
    await userEvent.click(button("Remove Reason: Auto"));
    await act(async () => setFromHost([DEGRADED, PINNED, AUTO]));
    await userEvent.click(button("Clear all"));
    await act(async () => setFromHost([AUTO, DEGRADED]));
    expect(announce.mock.calls).toEqual([
      ["Filter added: Pinned: Yes."],
      ["Filter removed: Reason: Auto."],
      ["Filter added: Reason: Auto."],
      ["All filters cleared."],
      ["Filters: Reason: Auto, State: Degraded."],
    ]);
  });

  it("without a host announcer it speaks through its own polite region, empty at mount", async () => {
    await mount(<Host initial={[AUTO, DEGRADED]} />);
    const region = within(group()).getByRole("status");
    expect(region).toHaveTextContent("");
    // The sentence is set by an effect's update, which act() flushes.
    await act(async () => userEvent.click(button("Remove Reason: Auto")));
    expect(region).toHaveTextContent("Filter removed: Reason: Auto.");
  });
});

describe("FilterBar (CMP-055): read-only (T2, E09-D09 §2.2)", () => {
  it("every control keeps its role, name and focus; aria-disabled, described by the reason", async () => {
    await mount(<Host initial={[AUTO, DEGRADED]} writeReason={REASON} />);
    const add = button("Not available Add filter");
    const controls = [
      button("Remove Reason: Auto"),
      button("Remove State: Degraded"),
      add,
      button("Not available Clear all"),
    ];
    for (const control of controls) {
      expect(control).toHaveAttribute("aria-disabled", "true");
      expect(control.disabled).toBe(false);
      expect(control).toHaveAccessibleDescription(REASON);
    }
    // Composed as CMP-177's controls are (2a): CMP-001's named lock leads, and the one notice describes them.
    for (const pointed of [add, controls[3]]) {
      const lock = within(pointed as HTMLElement).getByRole("img", { name: "Not available" });
      expect(pointed?.firstElementChild).toContainElement(lock);
      expect(pointed).toHaveAttribute("data-cmp", "CMP-001");
    }
    const notice = group().querySelectorAll(".cv-filterbar__reason");
    expect([...notice].map((node) => [node.textContent, node.getAttribute("aria-hidden")])).toEqual(
      [[REASON, null]],
    );
    // One notice, many pointers (G-T2.5, B-5309-05): Add filter, Clear all and every chip's remove point at it.
    for (const control of controls)
      expect(control).toHaveAttribute("aria-describedby", notice[0]?.id);
    await userEvent.tab();
    expect(controls[0]).toHaveFocus();
  });

  it("Enter, Space, Delete or Backspace changes nothing and says the reason once per press", async () => {
    const onChange = fn();
    const announce = fn();
    const props = { onChange, announce, writeReason: REASON };
    await mount(<Host initial={[AUTO, DEGRADED]} {...props} />);
    const add = button("Not available Add filter");
    act(() => add.focus());
    await userEvent.keyboard("{Enter} {ArrowDown}");
    expect(add).toHaveAttribute("aria-expanded", "false");
    expect(page.queryByRole("menu")).toBeNull();
    const remove = button("Remove Reason: Auto");
    act(() => remove.focus());
    await userEvent.keyboard("{Enter} {Delete}{Backspace}");
    expect(fireEvent.keyDown(remove, { key: "Delete", repeat: true })).toBe(false);
    expect(fireEvent.keyDown(add, { key: "Enter", repeat: true })).toBe(false);
    await userEvent.click(button("Not available Clear all"));
    expect(onChange).not.toHaveBeenCalled();
    expect(announce.mock.calls).toEqual(Array.from({ length: 7 }, () => [REASON]));
  });

  it("a gate that engages keeps Add filter's element and its focus", async () => {
    let gate: (reason: string | undefined) => void = () => undefined;
    function Gated(): JSX.Element {
      const [reason, setReason] = useState<string | undefined>(undefined);
      gate = setReason;
      return <Host initial={[AUTO]} {...(reason === undefined ? {} : { writeReason: reason })} />;
    }
    await mount(<Gated />);
    const add = button("Add filter");
    act(() => add.focus());
    await act(async () => gate(REASON));
    expect(button("Not available Add filter")).toBe(add);
    expect(add).toHaveFocus();
  });
});

it("has no serious axe violation, empty, filtered and read-only, dark and light", async () => {
  const host = await mount(
    <>
      <Host />
      <Host initial={[AUTO, DEGRADED]} />
      <Host initial={[AUTO, DEGRADED]} writeReason={REASON} />
    </>,
  );
  for (const theme of ["dark", "light"]) {
    document.documentElement.dataset["theme"] = theme;
    expect(await seriousViolations(host)).toEqual([]);
  }
  delete document.documentElement.dataset["theme"];
});

it(
  "runs each story's play; a theme story renders (its theme is the preview's)",
  { timeout: 20_000 },
  async () => {
    for (const [name, Story] of Object.entries(composeStories(stories))) {
      if (name.startsWith("Contrast")) {
        const host = await mount(<Story />);
        expect(within(host).getAllByRole("group", { name: "Active filters" })).toHaveLength(2);
        continue;
      }
      const canvasElement = document.body.appendChild(document.createElement("div"));
      await expect(Story.run({ canvasElement }), name).resolves.toBeUndefined();
      canvasElement.remove();
    }
  },
);

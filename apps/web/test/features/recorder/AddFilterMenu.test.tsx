/**
 * E16-S01, SCR-140's "+ Add filter" (E16-D02 §1; BQ-10: "Add filter is a Menu"), the add control the grid puts in
 * CMP-055's `addFilter` slot: a CMP-041 menu on a CMP-001 trigger, a submenu per filter field, each value a
 * `menuitemcheckbox` checked while applied. Presses are `fireEvent`s (user-event is no web dependency); the menu's
 * own keyboard is CMP-041's tests'.
 */
import { createRequire } from "node:module";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AddFilterMenu } from "../../../src/features/recorder/AddFilterMenu";
import type { RecorderFilter } from "../../../src/features/recorder/grid";

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

const AUTO: RecorderFilter = { field: "reason", value: "auto" };
const PINNED: RecorderFilter = { field: "pinned", value: "yes" };
/** Shares Pinned's values (yes and no), so a remove by value alone would take both. */
const ATTENTION: RecorderFilter = { field: "attention", value: "yes" };

const trigger = (): HTMLElement => screen.getByRole("button", { name: "Add filter" });
/** Opens the menu, then the field's values. */
const openField = (field: string): void => {
  fireEvent.click(trigger());
  fireEvent.click(screen.getByRole("menuitem", { name: field }));
};

describe("AddFilterMenu: SCR-140's Add filter (E16-D02 §1; BQ-10)", { timeout: 20_000 }, () => {
  it("opens the five fields in order, each a submenu of its values; no live region of its own (a1)", () => {
    render(<AddFilterMenu filters={[]} onChange={vi.fn()} />);
    expect(trigger()).toHaveAttribute("aria-haspopup", "menu");
    fireEvent.click(trigger());
    const names = ["Reason", "State", "Pinned", "Needs attention", "Depth"];
    const fields = screen.getAllByRole("menuitem");
    expect(fields).toHaveLength(names.length);
    for (const [at, name] of names.entries()) {
      expect(fields[at]).toHaveAccessibleName(name);
      expect(fields[at]).toHaveAttribute("aria-haspopup", "menu");
    }
    // The grid's count line is the filter row's one voice: nothing here speaks.
    expect(document.querySelector('[role="status"], [aria-live]')).toBeNull();
  });

  it("a field's values are menuitemcheckbox items, checked while applied", () => {
    render(<AddFilterMenu filters={[AUTO]} onChange={vi.fn()} />);
    openField("Reason");
    expect(screen.getByRole("menuitemcheckbox", { name: "Auto" })).toBeChecked();
    expect(screen.getByRole("menuitemcheckbox", { name: "Manual" })).not.toBeChecked();
  });

  it("an unchecked value adds its filter after the others; a checked one removes only itself (delta D-5309-03)", () => {
    const onChange = vi.fn();
    render(<AddFilterMenu filters={[PINNED, ATTENTION]} onChange={onChange} />);
    openField("State");
    fireEvent.click(screen.getByRole("menuitemcheckbox", { name: "Degraded" }));
    expect(onChange).toHaveBeenLastCalledWith([
      PINNED,
      ATTENTION,
      { field: "state", value: "degraded" },
    ]);
    // Pinned: Yes and Needs attention: Yes share a value: unchecking the one leaves the other.
    openField("Pinned");
    fireEvent.click(screen.getByRole("menuitemcheckbox", { name: "Yes" }));
    expect(onChange).toHaveBeenLastCalledWith([ATTENTION]);
    expect(onChange).toHaveBeenCalledTimes(2);
  });

  it("a held Enter's repeats never press it: focus lands here after Clear all with the key still down", () => {
    render(<AddFilterMenu filters={[]} onChange={vi.fn()} />);
    // `false`: the repeat's default (the button's click) is prevented; a first Enter is the button's own.
    expect(fireEvent.keyDown(trigger(), { key: "Enter", repeat: true })).toBe(false);
    expect(fireEvent.keyDown(trigger(), { key: "Enter" })).toBe(true);
    expect(screen.queryByRole("menu")).toBeNull();
  });

  it("has no serious axe violation with a field's values open", async () => {
    render(<AddFilterMenu filters={[AUTO]} onChange={vi.fn()} />);
    openField("Reason");
    const res = await axe.run(document.body, { rules: { "color-contrast": { enabled: false } } });
    const serious = res.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    expect(serious).toEqual([]);
  });
});

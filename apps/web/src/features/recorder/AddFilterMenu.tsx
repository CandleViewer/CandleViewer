/**
 * SCR-140's "+ Add filter" (E16-D02 §1; BQ-10: "Add filter is a Menu"), the add control the grid puts in CMP-055's
 * `addFilter` slot: CMP-041 on a CMP-001 trigger, a submenu per filter field (Reason, State, Pinned, Needs
 * attention, Depth), each value a `menuitemcheckbox` checked while applied; picking one adds its filter after the
 * others or removes it. The slot makes it the bar's input: focus lands on its trigger when the last chip or Clear
 * all goes. Never T2 (SCR-140 is the owner's alone, D02 §7) and no live region of its own: the grid's count line
 * speaks what a change shows.
 */
import type { JSX, KeyboardEvent } from "react";
import { Button, Menu, type MenuActionItem, type MenuItem } from "@candleviewer/ui";
import { FILTER_FIELDS, filterKey, type RecorderFilter } from "./grid";
import { PAGE_TEXT } from "./pageCopy";

export interface AddFilterMenuProps {
  /** The active filters, in chip order: the grid's state. */
  readonly filters: readonly RecorderFilter[];
  /** A value checked (appended) or unchecked (removed). */
  readonly onChange: (next: readonly RecorderFilter[]) => void;
}

/** A held Enter's repeats press nothing: focus lands here after Clear all with the key still down. */
const onTriggerKey = (event: KeyboardEvent<HTMLButtonElement>): void => {
  if (event.repeat && event.key === "Enter") event.preventDefault();
};

export function AddFilterMenu({ filters, onChange }: AddFilterMenuProps): JSX.Element {
  const applied = new Set(filters.map(filterKey));
  const items: MenuItem[] = FILTER_FIELDS.map((field) => ({
    id: field.id,
    label: field.label,
    items: field.options.map((option): MenuActionItem => {
      const filter: RecorderFilter = { field: field.id, value: option.value };
      const key = filterKey(filter);
      const on = applied.has(key);
      return {
        id: option.value,
        label: option.label,
        kind: "checkbox",
        checked: on,
        onSelect: () =>
          onChange(on ? filters.filter((each) => filterKey(each) !== key) : [...filters, filter]),
      };
    }),
  }));
  return (
    <Menu
      trigger={
        <Button variant="secondary" iconLeft="plus" onKeyDown={onTriggerKey}>
          {PAGE_TEXT.addFilter}
        </Button>
      }
      items={items}
    />
  );
}

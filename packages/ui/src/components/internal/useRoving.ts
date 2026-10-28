import { useCallback, useMemo, useRef, useState, type FocusEvent, type KeyboardEvent } from "react";

export interface RovingItem {
  readonly value: string;
  /** Plain disabled: skipped by the arrows and out of the Tab order. */
  readonly disabled?: boolean;
  /** Disabled with a reason: reachable by the arrows (so the reason can be read) but never checked. */
  readonly locked?: boolean;
}

export interface UseRovingOptions {
  readonly items: readonly RovingItem[];
  /** The checked value; it holds the tab stop (the first enabled item when none is checked). */
  readonly checked: string | undefined;
  /** Arrows, Home/End and Space check the item they land on, unless it is locked or `gated`. */
  readonly onSelect: (value: string) => void;
  /** The whole group is refused (T2): keys move nothing and select nothing; the tab stop stays put. */
  readonly gated?: boolean;
  /**
   * `false` = manual activation (APG Tabs): the arrows, Home and End move focus only, and Enter or Space selects
   * the focused item. Default `true`: the item an arrow lands on is selected (the radio pattern).
   */
  readonly selectOnFocus?: boolean;
  /** The role of the element that holds the items; focus leaving it gives the tab stop back to the checked item. */
  readonly groupRole?: "radiogroup" | "tablist";
}

export interface RovingItemProps {
  /** Absent on a plain-disabled item: it is not focusable at all, so a click cannot focus it. */
  readonly tabIndex: 0 | -1 | undefined;
  readonly ref: (node: HTMLElement | null) => void;
  readonly onKeyDown: (event: KeyboardEvent<HTMLElement>) => void;
  readonly onFocus: (event: FocusEvent<HTMLElement>) => void;
  readonly onBlur: (event: FocusEvent<HTMLElement>) => void;
}

export interface Roving {
  /** The value that currently holds the tab stop, or `undefined` when every item is plain disabled. */
  readonly tabStop: string | undefined;
  readonly itemProps: (value: string) => RovingItemProps;
}

const KEY_STEP: Readonly<Record<string, 1 | -1>> = {
  ArrowDown: 1,
  ArrowRight: 1,
  ArrowUp: -1,
  ArrowLeft: -1,
};

/**
 * Roving tabindex for the APG radio pattern (CMP-006 RadioGroup, CMP-003 SegmentedControl) and CMP-042 Tabs.
 * Arrows move focus and select (focus only with `selectOnFocus: false`), wrapping; Home/End jump; Space selects;
 * Tab leaves the group.
 * Alt/Ctrl/Meta chords are ignored; Shift+arrow acts as the plain arrow. Orientation does not matter: Up/Left go back and Down/Right go forward in both.
 */
export function useRoving({
  items,
  checked,
  onSelect,
  gated = false,
  selectOnFocus = true,
  groupRole = "radiogroup",
}: UseRovingOptions): Roving {
  const nodes = useRef(new Map<string, HTMLElement>());
  // The item holding focus: while focus is inside, the tab stop follows it, so Tab from a locked item
  // (focused, never checked) leaves the group instead of landing on the checked one further on.
  const [focused, setFocused] = useState<string>();

  const reachable = useMemo(() => items.filter((item) => item.disabled !== true), [items]);
  const disabledValues = useMemo(
    () => new Set(items.filter((item) => item.disabled === true).map((item) => item.value)),
    [items],
  );
  const focusedOk = focused !== undefined && reachable.some((item) => item.value === focused);
  const checkedOk = checked !== undefined && reachable.some((item) => item.value === checked);
  // A refused (gated) group keeps the tab stop on the checked item, wherever a pointer click put focus.
  const tabStop = focusedOk && !gated ? focused : checkedOk ? checked : reachable[0]?.value;

  const land = useCallback(
    (value: string): void => {
      nodes.current.get(value)?.focus();
      if (!selectOnFocus) return;
      const item = items.find((candidate) => candidate.value === value);
      if (item?.locked !== true) onSelect(value);
    },
    [items, onSelect, selectOnFocus],
  );

  const onKeyDown = useCallback(
    (value: string) =>
      (event: KeyboardEvent<HTMLElement>): void => {
        // Alt, Ctrl and Meta chords belong to the browser and the host (back/forward, shortcuts): not ours.
        if (event.altKey || event.ctrlKey || event.metaKey) return;
        const at = reachable.findIndex((item) => item.value === value);
        // A plain-disabled item that took focus by pointer answers no key at all.
        if (at < 0) return;
        const step = KEY_STEP[event.key];
        let target: RovingItem | undefined;
        if (step !== undefined) {
          target = reachable[(at + step + reachable.length) % reachable.length];
        } else if (event.key === "Home") {
          target = reachable[0];
        } else if (event.key === "End") {
          target = reachable[reachable.length - 1];
        } else if (event.key === " " || (event.key === "Enter" && !selectOnFocus)) {
          // Space checks the focused radio (with manual activation Enter too); the page does not scroll and
          // nothing else activates.
          event.preventDefault();
          if (!gated && items.find((item) => item.value === value)?.locked !== true) {
            onSelect(value);
          }
          return;
        } else {
          return;
        }
        // A handled key never scrolls the page or submits a form, even when the group refuses it.
        event.preventDefault();
        if (!gated && target !== undefined) land(target.value);
      },
    [reachable, items, gated, land, onSelect, selectOnFocus],
  );

  const itemProps = useCallback(
    (value: string): RovingItemProps => ({
      tabIndex: disabledValues.has(value) ? undefined : value === tabStop ? 0 : -1,
      ref: (node) => {
        if (node === null) nodes.current.delete(value);
        else nodes.current.set(value, node);
      },
      onKeyDown: onKeyDown(value),
      onFocus: () => setFocused(value),
      onBlur: (event) => {
        // Focus moving to a sibling re-sets `focused` in its own onFocus; only leaving the group clears it.
        const group = event.currentTarget.closest(`[role="${groupRole}"]`);
        if (!group?.contains(event.relatedTarget)) setFocused(undefined);
      },
    }),
    [tabStop, onKeyDown, disabledValues, groupRole],
  );

  return { tabStop, itemProps };
}

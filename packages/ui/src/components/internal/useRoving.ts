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
}

export interface RovingItemProps {
  readonly tabIndex: 0 | -1;
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
 * Roving tabindex for the APG radio pattern (CMP-006 RadioGroup, CMP-003 SegmentedControl).
 * Arrows move focus and select, wrapping; Home/End jump; Space selects; Tab leaves the group.
 * Orientation does not matter: Up/Left go back and Down/Right go forward in both.
 */
export function useRoving({ items, checked, onSelect, gated = false }: UseRovingOptions): Roving {
  const nodes = useRef(new Map<string, HTMLElement>());
  // The item holding focus: while focus is inside, the tab stop follows it, so Tab from a locked item
  // (focused, never checked) leaves the group instead of landing on the checked one further on.
  const [focused, setFocused] = useState<string>();

  const reachable = useMemo(() => items.filter((item) => item.disabled !== true), [items]);
  const focusedOk = focused !== undefined && reachable.some((item) => item.value === focused);
  const checkedOk = checked !== undefined && reachable.some((item) => item.value === checked);
  const tabStop = focusedOk ? focused : checkedOk ? checked : reachable[0]?.value;

  const land = useCallback(
    (value: string): void => {
      nodes.current.get(value)?.focus();
      const item = items.find((candidate) => candidate.value === value);
      if (item?.locked !== true) onSelect(value);
    },
    [items, onSelect],
  );

  const onKeyDown = useCallback(
    (value: string) =>
      (event: KeyboardEvent<HTMLElement>): void => {
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
        } else if (event.key === " ") {
          // Space checks the focused radio; the page does not scroll and nothing else activates.
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
    [reachable, items, gated, land, onSelect],
  );

  const itemProps = useCallback(
    (value: string): RovingItemProps => ({
      tabIndex: value === tabStop ? 0 : -1,
      ref: (node) => {
        if (node === null) nodes.current.delete(value);
        else nodes.current.set(value, node);
      },
      onKeyDown: onKeyDown(value),
      onFocus: () => setFocused(value),
      onBlur: (event) => {
        // Focus moving to a sibling re-sets `focused` in its own onFocus; only leaving the group clears it.
        const group = event.currentTarget.closest('[role="radiogroup"]');
        if (!group?.contains(event.relatedTarget)) setFocused(undefined);
      },
    }),
    [tabStop, onKeyDown],
  );

  return { tabStop, itemProps };
}

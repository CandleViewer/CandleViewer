import { useLayoutEffect, useRef, type JSX, type ReactNode } from "react";
import { Button } from "./Button.js";
import { useFocusRing } from "./FocusRing.js";
import { Tag } from "./Tag.js";
import { cx } from "./internal/cx.js";
import { tabbables } from "./internal/tabbable.js";

export interface FilterChip {
  /** Stable key, unique within the bar: the focus hand-off follows it. */
  readonly id: string;
  /** The chip's words, the filter and its value: "Account: Sub-1" (E29-D02:375). */
  readonly label: string;
  /** Removes this filter. The host drops the chip; the bar then hands focus on (CMP-011's contract). */
  readonly onRemove: () => void;
}

export interface FilterBarProps {
  /** The active filters, one removable CMP-011 chip each, in this order. */
  readonly filters: readonly FilterChip[];
  /** "Clear all", shown while two or more chips exist (E29-D04 §2.8.5): the host drops every filter. */
  readonly onClearAll?: () => void;
  /**
   * The host's add control after the chips: "+ Filter", a CMP-041 menu button or CMP-105's picker (E29-D02:375).
   * It is the bar's "input": focus lands on it when the last chip or "Clear all" goes.
   */
  readonly addFilter?: ReactNode;
  /** Emits `data-density` on the bar and its chips; absent = inherit. */
  readonly density?: "comfortable" | "compact";
}

/** The press whose result decides where focus goes once the host re-renders. */
type Pending =
  | { readonly kind: "chip"; readonly id: string; readonly index: number }
  | { readonly kind: "clear" };

/** The group's name (`15` CMP-055 A11y). */
const NAME = "Active filters";

/**
 * CMP-055 FilterBar (E29-D04 §2.8.5; E29-S01): a `role="group"` named "Active filters" holding removable CMP-011
 * chips, each remove a labelled CMP-002 "Remove filter {label}" (E29-D05 N-03), then the host's add control, then
 * "Clear all" while two or more chips exist. Removing hands focus on as CMP-011 asks of its owning group: to the
 * next chip's remove, else the previous one, else the add control, else the group itself, never `<body>`; "Clear
 * all" hands it to the add control. A reading and view choice: never T2 (E29-D04 §4.2), no live region of its own
 * (the table's polite line speaks the filtered result).
 */
export function FilterBar({
  filters,
  onClearAll,
  addFilter,
  density,
}: FilterBarProps): JSX.Element {
  const group = useRef<HTMLDivElement>(null);
  const add = useRef<HTMLSpanElement>(null);
  const pending = useRef<Pending | null>(null);
  const ring = useFocusRing();

  useLayoutEffect(() => {
    const asked = pending.current;
    const bar = group.current;
    if (asked === null || bar === null) return;
    // Not gone yet (the host kept it, or drops it later): nothing moved, so focus stays where it is.
    if (asked.kind === "chip" ? filters.some((f) => f.id === asked.id) : filters.length >= 2)
      return;
    pending.current = null;
    // Only focus the bar held, or lost to the body with the removed control, is handed on: never taken from elsewhere.
    // The bar's own document, so a popped-out panel hands focus on as a docked one does.
    const doc = bar.ownerDocument;
    const active = doc.activeElement;
    if (active !== null && active !== doc.body && !bar.contains(active)) return;
    const removes = [...bar.querySelectorAll<HTMLElement>(":scope > .cv-tag button")];
    const sibling =
      asked.kind === "chip" ? (removes[asked.index] ?? removes[asked.index - 1]) : undefined;
    const input = add.current === null ? undefined : tabbables(add.current)[0];
    (sibling ?? input ?? bar).focus();
  }, [filters]);

  return (
    <div
      ref={group}
      role="group"
      aria-label={NAME}
      // The last resort of the hand-off: focusable by script only, never a Tab stop.
      tabIndex={-1}
      className={cx("cv-filter-bar", ring.className)}
      data-cmp="CMP-055"
      data-density={density}
    >
      {filters.map((filter, index) => (
        <Tag
          key={filter.id}
          label={filter.label}
          removable
          removeLabel={`Remove filter ${filter.label}`}
          onRemove={() => {
            pending.current = { kind: "chip", id: filter.id, index };
            filter.onRemove();
          }}
          {...(density === undefined ? {} : { density })}
        />
      ))}
      {addFilter === undefined ? null : (
        <span ref={add} className="cv-filter-bar__add">
          {addFilter}
        </span>
      )}
      {onClearAll !== undefined && filters.length >= 2 ? (
        <Button
          variant="ghost"
          {...(density === undefined ? {} : { density })}
          onClick={() => {
            pending.current = { kind: "clear" };
            onClearAll();
          }}
        >
          Clear all
        </Button>
      ) : null}
    </div>
  );
}

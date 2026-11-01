import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type JSX,
  type KeyboardEvent,
} from "react";
import { Button } from "./Button.js";
import { GatedAnnounceProvider } from "./internal/disabledReason.js";
import { Menu, type MenuActionItem, type MenuItem } from "./Menu.js";
import { Tag } from "./Tag.js";

/** One value of a field (`value`, the host's key; `label`, "Degraded"): a submenu item, a chip's second half. */
export interface FilterBarOption {
  readonly value: string;
  readonly label: string;
}

/** A field "Add filter" offers (`id`, the host's key; `label`, "State"), opening its value submenu. */
export interface FilterBarField {
  readonly id: string;
  readonly label: string;
  readonly options: readonly FilterBarOption[];
}

/** An active filter: one value of one field. A pair appears at most once. */
export interface FilterBarFilter {
  readonly field: string;
  readonly value: string;
}

export interface FilterBarProps {
  /** What "Add filter" offers, in order. */
  fields: readonly FilterBarField[];
  /** The active filters in chip order: the host's state (its URL, its store). */
  value: readonly FilterBarFilter[];
  /** Every change: a chip removed, a value toggled in the menu, or Clear all (`[]`). */
  onChange: (next: readonly FilterBarFilter[]) => void;
  /**
   * T2 (E09-D09 §2.2): the reason the host resolved (a §3.1 key through `formatRbacReason`, or a registered state's
   * string). Every control keeps its name and focus, is `aria-disabled`, described by it, and a press says it once.
   */
  writeReason?: string;
  /** The host's polite announcer, when it owns its surface's one region; else the bar renders its own. */
  announce?: (text: string) => void;
  /** Emits `data-density`; absent = inherit. */
  density?: "comfortable" | "compact";
}

/** The group's name is `15`'s and "Add filter" E16-D02 §1's; the rest is PROPOSED (E16-S01). */
const COPY = {
  group: "Active filters",
  empty: "No filters",
  add: "Add filter",
  clearAll: "Clear all",
  added: (chip: string) => `Filter added: ${chip}.`,
  removed: (chip: string) => `Filter removed: ${chip}.`,
  cleared: "All filters cleared.",
  changed: (chips: string) => `Filters: ${chips}.`,
} as const;

const keyOf = (filter: FilterBarFilter): string => JSON.stringify([filter.field, filter.value]);

/** One sentence for a change of the set; null when the set is the same (a re-render, a reorder). */
function changeSentence(
  before: readonly FilterBarFilter[],
  after: readonly FilterBarFilter[],
  chipOf: (filter: FilterBarFilter) => string,
): string | null {
  const had = new Set(before.map(keyOf));
  const has = new Set(after.map(keyOf));
  const added = after.filter((filter) => !had.has(keyOf(filter)));
  const removed = before.filter((filter) => !has.has(keyOf(filter)));
  const [only] = added.length + removed.length === 1 ? [...added, ...removed] : [];
  if (only !== undefined) return (added.length === 1 ? COPY.added : COPY.removed)(chipOf(only));
  if (added.length + removed.length === 0) return null;
  return after.length === 0 ? COPY.cleared : COPY.changed(after.map(chipOf).join(", "));
}

/**
 * CMP-055 FilterBar: a `role="group"` "Active filters" of removable CMP-011 chips, "{field}: {value}", then "Add
 * filter", a CMP-041 menu of the fields whose value submenus check the applied values, then "Clear all" from two
 * chips on. Enter, Space, Delete or Backspace on a chip removes it; focus goes to the next chip, else the previous,
 * else Add filter, and a held key acts once. Each change of the set, whoever made it, is said once, politely, never
 * at mount or per key. With `writeReason` every control is T2 and the reason is drawn once, beside them: Add filter
 * and Clear all point at it (rendering 2a, CMP-001's named lock leading the full label, as CMP-177's controls do);
 * a chip's remove, icon-only, echoes it (2b).
 */
export function FilterBar({
  fields,
  value,
  onChange,
  writeReason,
  announce,
  density,
}: FilterBarProps): JSX.Element {
  const reason = writeReason?.trim() || undefined; // whitespace is no reason, as CMP-001 reads it
  const addId = useId();
  const reasonId = useId();
  const root = useRef<HTMLDivElement>(null);
  // The bar's own region re-keys its node, so the same sentence said twice is read twice.
  const [said, setSaid] = useState({ text: "", n: 0 });
  const say = useCallback(
    (text: string): void =>
      announce === undefined ? setSaid((prev) => ({ text, n: prev.n + 1 })) : announce(text),
    [announce],
  );
  const chipOf = (filter: FilterBarFilter): string => {
    const field = fields.find((each) => each.id === filter.field);
    const option = field?.options.find((each) => each.value === filter.value);
    return `${field?.label ?? filter.field}: ${option?.label ?? filter.value}`;
  };
  const keys = value.map(keyOf).join("\n");
  const applied = new Set(value.map(keyOf));

  const before = useRef<readonly FilterBarFilter[] | null>(null);
  const latest = useRef({ value, say, chipOf });
  latest.current = { value, say, chipOf };
  useEffect(() => {
    const { value: after, say: speak, chipOf: chip } = latest.current;
    const text = before.current === null ? null : changeSentence(before.current, after, chip);
    before.current = after;
    if (text !== null) speak(text);
  }, [keys]);

  // A removal: once the host's list drops it, focus lost with it goes to the next chip, else the previous, else
  // Add filter (CMP-011), never <body>; focus that went elsewhere stays there.
  const pending = useRef<{ readonly at: number; readonly from: string } | null>(null);
  useLayoutEffect(() => {
    const removal = pending.current;
    if (removal === null || removal.from === keys) return;
    pending.current = null;
    if (document.activeElement !== document.body && document.activeElement !== null) return;
    const removes = root.current?.querySelectorAll<HTMLElement>(".cv-filterbar__chip button");
    (removes?.[removal.at] ?? removes?.[removal.at - 1] ?? document.getElementById(addId))?.focus();
  }, [keys, addId]);
  /** Removes the chip at `at`, or every chip (`at` -1, Clear all). */
  const drop = (at: number): void => {
    pending.current = { at, from: keys };
    onChange(at < 0 ? [] : value.filter((_, index) => index !== at));
  };

  // Delete and Backspace remove, as Enter and Space do; a held key's repeats would reach the next control.
  const onChipKey = (event: KeyboardEvent<HTMLLIElement>, at: number): void => {
    const removing = event.key === "Delete" || event.key === "Backspace";
    if (event.altKey || event.ctrlKey || event.metaKey || !(removing || event.key === "Enter"))
      return;
    if (event.repeat || removing) event.preventDefault();
    if (event.repeat || !removing) return;
    if (reason === undefined) drop(at);
    else say(reason);
  };
  // Add filter: a repeat never opens it (focus lands here after Clear all); a T2 trigger's arrows open nothing.
  const onAddKey = (event: KeyboardEvent<HTMLButtonElement>): void => {
    const arrow = event.key === "ArrowDown" || event.key === "ArrowUp";
    if ((event.repeat && event.key === "Enter") || (arrow && reason !== undefined))
      event.preventDefault();
  };

  const items: MenuItem[] = fields.map((field) => ({
    id: field.id,
    label: field.label,
    items: field.options.map((option): MenuActionItem => {
      const filter = { field: field.id, value: option.value };
      const key = keyOf(filter);
      const on = applied.has(key);
      const next = on ? value.filter((each) => keyOf(each) !== key) : [...value, filter];
      return {
        id: option.value,
        label: option.label,
        kind: "checkbox",
        checked: on,
        onSelect: () => onChange(next),
      };
    }),
  }));
  // The one notice beside the controls describes every one of them (E09-D09 §2.2, one notice, many pointers): Add
  // filter and Clear all lead with CMP-001's named lock (2a), each chip's remove keeps its badge and echo (2b).
  const pointed =
    reason === undefined ? {} : { disabledReason: reason, disabledReasonId: reasonId };
  const add = (
    <Button
      id={addId}
      variant="secondary"
      {...(reason === undefined ? { iconLeft: "plus" as const } : pointed)}
      onKeyDown={onAddKey}
    >
      {COPY.add}
    </Button>
  );

  return (
    <GatedAnnounceProvider announce={say}>
      <div
        ref={root}
        role="group"
        aria-label={COPY.group}
        className="cv-filterbar"
        data-cmp="CMP-055"
        data-density={density}
      >
        {value.length === 0 ? (
          <span className="cv-filterbar__empty">{COPY.empty}</span>
        ) : (
          <ul className="cv-filterbar__chips">
            {value.map((filter, at) => (
              // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- Delete and Backspace bubbling from the chip's remove (CMP-002); the item is no widget
              <li
                key={keyOf(filter)}
                className="cv-filterbar__chip"
                onKeyDown={(event) => onChipKey(event, at)}
              >
                <Tag label={chipOf(filter)} removable onRemove={() => drop(at)} {...pointed} />
              </li>
            ))}
          </ul>
        )}
        <Menu trigger={add} items={items} announceReason={say} />
        {value.length < 2 ? null : (
          <Button variant="ghost" {...pointed} onClick={() => drop(-1)}>
            {COPY.clearAll}
          </Button>
        )}
        {reason === undefined ? null : (
          <span id={reasonId} className="cv-filterbar__reason">
            {reason}
          </span>
        )}
        {announce === undefined ? (
          <span className="cv-visually-hidden" role="status">
            {said.n === 0 ? null : <span key={said.n}>{said.text}</span>}
          </span>
        ) : null}
      </div>
    </GatedAnnounceProvider>
  );
}

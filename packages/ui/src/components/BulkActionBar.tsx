import { useId, useRef, useState, type JSX, type KeyboardEvent } from "react";
import { Button } from "./Button.js";

/** One bulk action: a CMP-001 button (`15` CMP-243 Props, E36-D05 §C A-11; SCR-080's Disarm · Export). */
export interface BulkAction {
  readonly id: string;
  readonly label: string;
  readonly onClick: () => void;
  /** T2, disabled with a visible reason (E09-D09 §2.2): SCR-080's viewer sees Disarm gated by role. */
  readonly disabledReason?: string;
}

/** Clear's stop key: a symbol, so no action `id` can collide with it. */
const CLEAR: unique symbol = Symbol("clear");
type StopKey = string | typeof CLEAR;
interface Stop {
  readonly key: StopKey | undefined;
  readonly index: number;
}

export interface BulkActionBarProps {
  /** How many items are selected: "{count} selected", the toolbar's name. Zero hides the bar. */
  readonly count: number;
  /** The actions, one CMP-001 button each in this order, before Clear. */
  readonly actions: readonly BulkAction[];
  /** Clear: the host empties the selection and returns focus to its list (E36-D03 §2, A-16). */
  readonly onClear: () => void;
}

/**
 * CMP-243 BulkActionBar (E13-D02 §10 G-4; `15` CMP-243, E36-D05 §C A-11..A-17): "N selected", the actions and Clear
 * in a `role="toolbar"` named by its count, placed by the host after its list in the Tab order. Two states: hidden
 * with no selection (nothing renders) and shown with one. Its appearance never takes focus; it slides in (opacity +
 * 8 px, `motion.duration.fast` · `motion.easing.decelerate`), instantly under reduced motion (E36-D03 §10 row 9).
 * One Tab stop with a roving tabindex (`05` §3.4 R-2): `←` / `→` move between the buttons, `Home` / `End` jump.
 */
export function BulkActionBar({ count, actions, onClear }: BulkActionBarProps): JSX.Element | null {
  const countId = useId();
  const bar = useRef<HTMLDivElement>(null);
  // The roving stop is a button's identity (an action's `id`, or Clear), not its position, so a host that adds or
  // drops an action while focus is in the bar keeps the stop on the focused button. The index is the fallback for a
  // stop whose action is gone: it clamps to the last button. Until a button takes focus the stop is the first one.
  const [current, setCurrent] = useState<Stop>({ key: undefined, index: 0 });
  const total = actions.length + 1;
  const keyAt = (index: number): StopKey => actions[index]?.id ?? CLEAR;
  const found =
    current.key === CLEAR
      ? actions.length
      : current.key === undefined
        ? -1
        : actions.findIndex((action) => action.id === current.key);
  const active = found >= 0 ? found : Math.min(current.index, total - 1);

  if (count <= 0) return null;

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    if (!(event.target instanceof HTMLElement) || event.target.dataset["bulkIndex"] === undefined)
      return;
    // The arrows move from the button that has focus, which is the stop unless the host re-rendered under it.
    const from = Number(event.target.dataset["bulkIndex"]);
    const keys: Record<string, number> = {
      ArrowRight: (from + 1) % total,
      ArrowLeft: (from - 1 + total) % total,
      Home: 0,
      End: total - 1,
    };
    const next = keys[event.key];
    if (next === undefined) return;
    event.preventDefault();
    setCurrent({ key: keyAt(next), index: next });
    bar.current?.querySelector<HTMLElement>(`[data-bulk-index="${String(next)}"]`)?.focus();
  };
  const stop = (index: number): { tabIndex: 0 | -1; onFocus: () => void } => ({
    tabIndex: index === active ? 0 : -1,
    onFocus: () => setCurrent({ key: keyAt(index), index }),
  });

  return (
    <div
      ref={bar}
      role="toolbar"
      className="cv-bulk-bar"
      data-cmp="CMP-243"
      aria-labelledby={countId}
      onKeyDown={onKeyDown}
    >
      <span id={countId} className="cv-bulk-bar__count">
        {`${String(count)} selected`}
      </span>
      {actions.map((action, index) => (
        <Button
          key={action.id}
          data-bulk-index={index}
          {...stop(index)}
          {...(action.disabledReason === undefined
            ? {}
            : { disabledReason: action.disabledReason })}
          onClick={action.onClick}
        >
          {action.label}
        </Button>
      ))}
      <Button data-bulk-index={actions.length} {...stop(actions.length)} onClick={onClear}>
        Clear
      </Button>
    </div>
  );
}

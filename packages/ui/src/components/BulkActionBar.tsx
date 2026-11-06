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
  const [current, setCurrent] = useState(0);
  const total = actions.length + 1;
  const active = Math.min(current, total - 1);

  if (count <= 0) return null;

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
    const keys: Record<string, number> = {
      ArrowRight: (active + 1) % total,
      ArrowLeft: (active - 1 + total) % total,
      Home: 0,
      End: total - 1,
    };
    const next = keys[event.key];
    if (next === undefined) return;
    event.preventDefault();
    setCurrent(next);
    bar.current?.querySelector<HTMLElement>(`[data-bulk-index="${String(next)}"]`)?.focus();
  };
  const stop = (index: number): { tabIndex: 0 | -1; onFocus: () => void } => ({
    tabIndex: index === active ? 0 : -1,
    onFocus: () => setCurrent(index),
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

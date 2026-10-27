import { useRef } from "react";
import type { CSSProperties, JSX, KeyboardEvent, PointerEvent } from "react";
import { Icon } from "../icons/Icon.js";
import { ReasonText, useDisabledReason } from "./internal/disabledReason.js";
import { cx } from "./internal/cx.js";
import { formatNumeric, stepValue, valueText } from "./internal/numeric.js";

/** One accessible name is required: a nameless `role=slider` fails axe `aria-input-field-name` (D02 C5). */
type SliderName =
  | { "aria-label": string; "aria-labelledby"?: string }
  | { "aria-label"?: string; "aria-labelledby": string };

export type SliderProps = SliderName & {
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (value: number) => void;
  /** Numeric labels under the rail (no ticks, no snapping, D02 C8); they collapse to min and max when crowded. */
  marks?: readonly number[];
  disabled?: boolean;
  /** The visible reason a control is denied (RBAC, environment, risk): disabled-with-reason (T2). */
  disabledReason?: string;
  /** Decimal places of the step grid; default: the finest of `step` and `min`. */
  precision?: number;
  /** Unit for `aria-valuetext` ("5 %"). */
  suffix?: string;
  "aria-describedby"?: string;
  density?: "comfortable" | "compact";
};

const LARGE = 10;
/** Marks closer than this (rail %, per label character) are treated as colliding: no layout is measured. */
const CROWD_PERCENT_PER_CHAR = 3.5;

const decimals = (n: number): number => {
  const [mantissa = "", exponent = "0"] = String(n).split("e");
  return Math.max(0, (mantissa.split(".")[1] ?? "").length - Number(exponent));
};

/** Marks inside the range, ascending and unique; when the labels would overlap (a heuristic), exactly min and max. */
export const visibleMarks = (
  marks: readonly number[],
  min: number,
  max: number,
  precision: number,
): number[] => {
  const inside = [...new Set(marks)].filter((m) => m >= min && m <= max).sort((a, b) => a - b);
  const chars = Math.max(...inside.map((m) => formatNumeric(m, precision).length + 1));
  const gaps = inside.slice(1).map((m, i) => ((m - (inside[i] ?? m)) / (max - min)) * 100);
  const crowded = Math.min(...gaps) < CROWD_PERCENT_PER_CHAR * chars;
  return crowded ? [min, max] : inside;
};

const pos = (fraction: number): CSSProperties => ({ "--cv-slider-pos": fraction }) as CSSProperties;

/** CMP-010: a custom `role=slider` thumb (a native range cannot be `aria-disabled` and focusable, plan Q8). */
export function Slider({
  value,
  min,
  max,
  step,
  onChange,
  marks,
  disabled,
  disabledReason,
  precision,
  suffix,
  density,
  "aria-describedby": describedBy,
  ...name
}: SliderProps): JSX.Element {
  const reason = useDisabledReason(disabled, disabledReason);
  const locked = reason.gated || reason.disabled;
  const places = precision ?? Math.max(decimals(step), decimals(min));
  const thumb = useRef<HTMLSpanElement>(null);
  // Read once at pointer-down (no observer, no measuring in render); null when no drag is active.
  const drag = useRef<{ left: number; width: number; id: number } | null>(null);
  // Plain disabled has no tabindex at all (out of the Tab order); a gated thumb stays in it.
  const focusable = reason.disabled ? {} : { tabIndex: 0 };
  const shown = Math.min(Math.max(value, min), max);
  const fraction = max > min ? (shown - min) / (max - min) : 0;
  const shownMarks = marks && marks.length > 0 ? visibleMarks(marks, min, max, places) : [];

  const commit = (next: number): void => {
    if (next !== value) onChange(next);
  };
  const stepBy = (direction: "up" | "down", multiplier: number): number =>
    stepValue(shown, step, direction, multiplier, places, min, max);

  const handleKeyDown = (event: KeyboardEvent<HTMLSpanElement>): void => {
    // Chords belong to the browser and assistive tech; the slider keeps plain keys only.
    if (event.altKey || event.ctrlKey || event.metaKey) return;
    const next =
      event.key === "ArrowRight" || event.key === "ArrowUp"
        ? () => stepBy("up", 1)
        : event.key === "ArrowLeft" || event.key === "ArrowDown"
          ? () => stepBy("down", 1)
          : event.key === "PageUp"
            ? () => stepBy("up", LARGE)
            : event.key === "PageDown"
              ? () => stepBy("down", LARGE)
              : event.key === "Home"
                ? () => min
                : event.key === "End"
                  ? () => max
                  : null;
    if (next === null) return;
    // Handled keys never scroll the page, and a gated or disabled slider takes no action.
    event.preventDefault();
    if (!locked) commit(next());
  };

  const valueAt = (clientX: number, rect: { left: number; width: number }): number => {
    const ratio = rect.width > 0 ? Math.min(Math.max((clientX - rect.left) / rect.width, 0), 1) : 0;
    // Snap on the step grid with exact scaled-integer arithmetic, not float `min + n * step`.
    const steps = Math.round((ratio * (max - min)) / step);
    return stepValue(min, step, "up", steps, places, min, max);
  };
  const end = (event: PointerEvent<HTMLDivElement>): void => {
    if (drag.current?.id === event.pointerId) drag.current = null;
  };
  const handlePointerDown = (event: PointerEvent<HTMLDivElement>): void => {
    if (event.button !== 0) return;
    event.preventDefault();
    // A press focuses the thumb without the keyboard ring where the browser supports the option.
    thumb.current?.focus({ focusVisible: false } as FocusOptions);
    if (locked) return;
    const rail = event.currentTarget;
    const rect = rail.getBoundingClientRect();
    drag.current = { left: rect.left, width: rect.width, id: event.pointerId };
    rail.setPointerCapture(event.pointerId);
    commit(valueAt(event.clientX, drag.current));
  };
  const handlePointerMove = (event: PointerEvent<HTMLDivElement>): void => {
    if (locked || drag.current === null || drag.current.id !== event.pointerId) return;
    event.preventDefault();
    commit(valueAt(event.clientX, drag.current));
  };

  return (
    <div
      className="cv-slider"
      data-cmp="CMP-010"
      data-density={density}
      data-gated={reason.gated ? "" : undefined}
      data-disabled={reason.disabled ? "" : undefined}
    >
      <div className="cv-slider__body">
        <div
          className="cv-slider__rail"
          onPointerDown={handlePointerDown}
          onPointerMove={handlePointerMove}
          onPointerUp={end}
          onPointerCancel={end}
          onLostPointerCapture={end}
        >
          <span className="cv-slider__track" style={pos(fraction)}>
            <span className="cv-slider__fill" />
          </span>
          {/* eslint-disable-next-line jsx-a11y/interactive-supports-focus -- plain disabled is deliberately out of the Tab order (D02 a11y audit, CMP-010): no tabindex */}
          <span
            {...name}
            ref={thumb}
            role="slider"
            className="cv-slider__thumb"
            style={pos(fraction)}
            {...focusable}
            aria-orientation="horizontal"
            aria-valuenow={shown}
            aria-valuemin={min}
            aria-valuemax={max}
            aria-valuetext={valueText(shown, places, suffix)}
            aria-disabled={locked ? true : undefined}
            aria-describedby={cx(describedBy, reason.ariaDescribedBy) || undefined}
            onKeyDown={handleKeyDown}
          />
        </div>
        {shownMarks.length > 0 ? (
          <div
            className="cv-slider__marks"
            aria-hidden="true"
            // Plain disabled dims the labels on purpose (WCAG 1.4.3 exempts them); this tells axe, which cannot see opacity.
            aria-disabled={reason.disabled ? true : undefined}
          >
            {shownMarks.map((mark) => (
              <span
                key={mark}
                className="cv-slider__mark"
                style={pos(max > min ? (mark - min) / (max - min) : 0)}
              >
                {formatNumeric(mark, places)}
              </span>
            ))}
          </div>
        ) : null}
      </div>
      {reason.gated ? (
        <span className="cv-slider__glyph">
          <Icon name="lock" />
        </span>
      ) : null}
      <ReasonText id={reason.reasonId}>{reason.reason}</ReasonText>
    </div>
  );
}

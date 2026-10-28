import {
  useEffect,
  useRef,
  useState,
  type JSX,
  type KeyboardEvent,
  type MutableRefObject,
} from "react";
import { IconButton } from "../IconButton.js";
import {
  WEEKDAY_NAMES,
  addDays,
  addMonths,
  addYears,
  endOfWeek,
  clampIso,
  isWithin,
  longLabel,
  monthLabel,
  monthWeeks,
  parseIsoDate,
  startOfWeek,
} from "./isoDate.js";

export interface CalendarGridProps {
  /** The day that takes focus when the grid mounts (the dialog opens). */
  readonly initialFocus: string;
  /** The selected day; in a range, its start. */
  readonly selected: string | null;
  /**
   * A range's end (inclusive): every day from `selected` to it is selected, the days between on the band. Null in a
   * range whose end is pending: the band then runs from `selected` to the day under the pointer, else the focused
   * day (a preview, not a selection). Undefined for the single form.
   */
  readonly rangeEnd?: string | null | undefined;
  readonly today: string;
  readonly min?: string | undefined;
  readonly max?: string | undefined;
  /** The sentence naming the allowed range, under the grid; spoken on each press of an out-of-range day. */
  readonly caption?: string | undefined;
  /** The month heading's id: it names the dialog and the grid. */
  readonly headingId: string;
  /** Points at the focused day's button: the dialog's initial focus. */
  readonly focusedRef: MutableRefObject<HTMLButtonElement | null>;
  readonly onPick: (iso: string) => void;
}

/** The grid keys (WAI-ARIA APG Date Picker Dialog): the next focused day, or null for a key it leaves alone. */
export function nextFocus(iso: string, key: string, shiftKey: boolean): string | null {
  switch (key) {
    case "ArrowLeft":
      return addDays(iso, -1);
    case "ArrowRight":
      return addDays(iso, 1);
    case "ArrowUp":
      return addDays(iso, -7);
    case "ArrowDown":
      return addDays(iso, 7);
    case "Home":
      return startOfWeek(iso);
    case "End":
      return endOfWeek(iso);
    case "PageUp":
      return shiftKey ? addYears(iso, -1) : addMonths(iso, -1);
    case "PageDown":
      return shiftKey ? addYears(iso, 1) : addMonths(iso, 1);
    default:
      return null;
  }
}

/**
 * The CMP-047 calendar: a month heading between Previous and Next month buttons, then a `grid` of days, Monday
 * first, with one roving tab stop on the focused day. It mounts with the dialog and keeps its own focused day.
 */
export function CalendarGrid({
  initialFocus,
  selected,
  rangeEnd,
  today,
  min,
  max,
  caption,
  headingId,
  focusedRef,
  onPick,
}: CalendarGridProps): JSX.Element {
  const [focused, setFocused] = useState(initialFocus);
  /** Set by a grid key: the newly focused day takes DOM focus after the render (a month button keeps it). */
  const moveFocus = useRef(false);
  /** Presses of out-of-range days: each one inserts a fresh caption node into the status, so it is spoken again. */
  const [refusals, setRefusals] = useState(0);
  /** The day under the pointer: a pending range previews its band to it. */
  const [hovered, setHovered] = useState<string | null>(null);
  const { year, month } = parseIsoDate(focused) ?? { year: 1970, month: 1 };
  const weeks = monthWeeks(year, month);

  useEffect(() => {
    if (!moveFocus.current) return;
    moveFocus.current = false;
    focusedRef.current?.focus({ preventScroll: true });
  }, [focused, focusedRef]);

  const onKeyDown = (event: KeyboardEvent<HTMLTableElement>): void => {
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    const next = nextFocus(focused, event.key, event.shiftKey);
    if (next === null) return;
    event.preventDefault();
    moveFocus.current = true;
    setFocused(next);
  };

  /** The band's far end: the range's end, else (pending) the day under the pointer or the focused day. */
  const bandEnd =
    selected === null || rangeEnd === undefined ? null : (rangeEnd ?? hovered ?? focused);
  const band = bandEnd !== null && selected !== null && bandEnd > selected ? bandEnd : null;
  const inBand = (iso: string): boolean =>
    band !== null && selected !== null && clampIso(iso, selected, band) === iso;
  const isEnd = (iso: string): boolean =>
    iso === selected || (rangeEnd != null && iso === rangeEnd);
  /** aria-selected: the selected day, or every day of a complete range (a reversed one: its two ends). */
  const isSelected = (iso: string): boolean =>
    isEnd(iso) ||
    (rangeEnd != null && selected !== null && clampIso(iso, selected, rangeEnd) === iso);

  const choose = (iso: string): void => {
    // In a range a pressed day becomes the roving stop (a press focuses it), so a pending band follows it; the
    // pointer's day is dropped until the next mouseenter. The single form keeps its slice-13 roving stop.
    if (rangeEnd !== undefined) {
      setFocused(iso);
      setHovered(null);
    }
    if (isWithin(iso, min, max)) onPick(iso);
    else setRefusals((n) => n + 1);
  };

  return (
    <div className="cv-datepicker__calendar">
      <div className="cv-datepicker__header">
        <IconButton
          icon="chevron-left"
          label="Previous month"
          variant="ghost"
          onClick={() => setFocused(addMonths(focused, -1))}
        />
        <h2 id={headingId} className="cv-datepicker__month">
          {monthLabel(year, month)}
        </h2>
        <IconButton
          icon="chevron-right"
          label="Next month"
          variant="ghost"
          onClick={() => setFocused(addMonths(focused, 1))}
        />
      </div>
      <table
        role="grid"
        aria-labelledby={headingId}
        className="cv-datepicker__grid"
        onKeyDown={onKeyDown}
        onMouseLeave={() => setHovered(null)}
      >
        <thead>
          <tr>
            {WEEKDAY_NAMES.map((name) => (
              <th key={name} scope="col" className="cv-datepicker__weekday">
                <abbr title={name}>{name.slice(0, 2)}</abbr>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {weeks.map((week, row) => (
            <tr key={row}>
              {week.map((iso, column) =>
                iso === null ? (
                  <td key={column} role="gridcell" className="cv-datepicker__cell" />
                ) : (
                  <td
                    key={iso}
                    role="gridcell"
                    className="cv-datepicker__cell"
                    aria-selected={isSelected(iso) ? true : undefined}
                    data-in-range={inBand(iso) && !isEnd(iso) ? "" : undefined}
                  >
                    <button
                      ref={iso === focused ? focusedRef : undefined}
                      type="button"
                      className="cv-datepicker__day"
                      tabIndex={iso === focused ? 0 : -1}
                      aria-label={iso === today ? `${longLabel(iso)}, today` : longLabel(iso)}
                      aria-current={iso === today ? "date" : undefined}
                      aria-disabled={isWithin(iso, min, max) ? undefined : true}
                      data-selected={isEnd(iso) ? "" : undefined}
                      data-today={iso === today ? "" : undefined}
                      onClick={() => choose(iso)}
                      onMouseEnter={rangeEnd === undefined ? undefined : () => setHovered(iso)}
                    >
                      {Number(iso.slice(8))}
                    </button>
                  </td>
                ),
              )}
            </tr>
          ))}
        </tbody>
      </table>
      {caption === undefined ? null : <p className="cv-datepicker__caption">{caption}</p>}
      <span className="cv-visually-hidden" role="status">
        {refusals > 0 && caption !== undefined ? <span key={refusals}>{caption}</span> : null}
      </span>
    </div>
  );
}

import { useEffect, useId, useRef, useState, type FocusEvent, type JSX } from "react";
import { CalendarGrid } from "./internal/CalendarGrid.js";
import { ReasonText } from "./internal/disabledReason.js";
import { EntryWell } from "./internal/EntryWell.js";
import { useFieldControl } from "./internal/fieldContext.js";
import { FieldMessage } from "./internal/fieldParts.js";
import {
  clampIso,
  daySpan,
  isWithin,
  isoFromEpochMs,
  normaliseIso,
  normaliseTime,
} from "./internal/isoDate.js";
import {
  CalendarButton,
  DEFAULT_HINT,
  TIME_ERROR,
  TIME_HINT,
  composeCaption,
} from "./internal/pickerParts.js";

/** A CMP-047 range: ISO `YYYY-MM-DD` days and, with `withTime`, `HH:MM` times, all UTC. Never a `Date`. */
export interface DateRangeValue {
  readonly start: string | null;
  readonly end: string | null;
  readonly startTime?: string | null;
  readonly endTime?: string | null;
}

export interface DateRangePickerProps {
  readonly value: DateRangeValue;
  /**
   * A typed field that parsed and is allowed, an emptied field (null), or a completed calendar range (the start and
   * the end together). Never an invalid entry. An end before the start is the host's check (conventions 23).
   */
  readonly onChange: (value: DateRangeValue) => void;
  /** The group's id. */
  readonly id?: string;
  /** Names the group; inside a CMP-040 FormField the field's label does. */
  readonly "aria-label"?: string;
  readonly "aria-labelledby"?: string;
  /** Joined after the error and the format hint, before each field's "UTC" suffix. */
  readonly "aria-describedby"?: string;
  /** The Start field's label; default "Start". */
  readonly startLabel?: string;
  /** The End field's label; default "End". */
  readonly endLabel?: string;
  readonly min?: string;
  readonly max?: string;
  readonly rangeCaption?: string;
  readonly formatHint?: string;
  readonly invalid?: boolean;
  readonly errorMessage?: string;
  readonly disabled?: boolean;
  /** T2: every field read-only behind the lock, the calendar button `aria-disabled`; one reason for all. */
  readonly disabledReason?: string;
  readonly readOnly?: boolean;
  readonly density?: "comfortable" | "compact";
  readonly now?: () => number;
  /** Each field's blur. */
  readonly onBlur?: (event: FocusEvent<HTMLInputElement>) => void;
  /** An `HH:MM` (24-hour, UTC) field after each date (G11); typed only, the calendar never sets it. */
  readonly withTime?: boolean;
}

type Part = "start" | "startTime" | "end" | "endTime";
const PARTS: readonly Part[] = ["start", "startTime", "end", "endTime"];
type Errors = Readonly<Record<Part, string | null>>;
const NO_ERRORS: Errors = { start: null, startTime: null, end: null, endTime: null };

/** The two polite range sentences (D02F CMP-047's live region, proposed strings). */
export const startSentence = (start: string): string => `Start ${start}. Choose the end date.`;
export function rangeSentence(start: string, end: string): string {
  const days = daySpan(start, end);
  return `${start} to ${end}, ${days} ${days === 1 ? "day" : "days"}.`;
}

/**
 * CMP-047 DateRangePicker: a group of a Start and an End field (each the DatePicker's typed well, with a "UTC"
 * suffix) and one calendar button, flush at the End field's last well. In the calendar the first pick sets the
 * start and the second the end and closes; a second pick before the start replaces it. The band marks the days
 * between the ends (to the day under the pointer, else the focused day, while the end is pending). A polite
 * status speaks the start, then the range: at most twice per range. The fields stack when the host is narrower
 * than both. `withTime` adds an `HH:MM` UTC well after each date.
 */
export function DateRangePicker({
  value,
  onChange,
  id,
  "aria-label": ariaLabel,
  "aria-labelledby": labelledBy,
  "aria-describedby": describedBy,
  startLabel = "Start",
  endLabel = "End",
  min,
  max,
  rangeCaption,
  formatHint = DEFAULT_HINT,
  invalid = false,
  errorMessage,
  disabled,
  disabledReason,
  readOnly = false,
  density,
  now = Date.now,
  onBlur,
  withTime = false,
}: DateRangePickerProps): JSX.Element {
  const errorId = useId();
  const hintId = useId();
  const headingId = useId();
  const startId = useId();
  const endId = useId();
  const suffixIds = { start: useId(), startTime: useId(), end: useId(), endTime: useId() };
  const dayRef = useRef<HTMLButtonElement | null>(null);
  const [errors, setErrors] = useState<Errors>(NO_ERRORS);
  const [open, setOpen] = useState(false);
  const [openings, setOpenings] = useState(0);
  /** The start picked in this opening; the end is pending until the next pick. */
  const [pending, setPending] = useState<string | null>(null);
  /** The dialog's status: the start sentence while the end is pending. */
  const [startSaid, setStartSaid] = useState("");
  /** The range sentence, spoken from the group once the dialog has closed and the page is no longer inert. */
  const [queued, setQueued] = useState<string | null>(null);
  const [rangeSaid, setRangeSaid] = useState("");

  const lower = normaliseIso(min);
  const upper = normaliseIso(max);
  const caption = rangeCaption ?? composeCaption(lower, upper);
  const hint = formatHint === "" ? null : formatHint;
  const parseError = `Enter a date as ${hint ?? DEFAULT_HINT}.`;
  const rangeError = caption ?? parseError;

  const typedError =
    PARTS.map((part) => errors[part]).find(
      (error, index) => error !== null && (withTime || index % 2 === 0),
    ) ?? null;
  const control = useFieldControl(
    disabled,
    disabledReason,
    invalid || typedError !== null,
    typedError ?? errorMessage,
    { labelable: false },
  );
  const { reason } = control;
  const frozen = reason.gated || reason.disabled || readOnly;
  if (frozen && open) setOpen(false);

  useEffect(() => {
    if (open || queued === null) return;
    setRangeSaid(queued);
    setQueued(null);
  }, [open, queued]);

  const openCalendar = (): void => {
    if (frozen || open) return;
    setOpenings((n) => n + 1);
    setPending(null);
    setStartSaid("");
    setRangeSaid("");
    setOpen(true);
  };

  const pick = (iso: string): void => {
    if (pending === null || iso < pending) {
      setPending(iso);
      setStartSaid(startSentence(iso));
      return;
    }
    setOpen(false);
    setPending(null);
    setQueued(rangeSentence(pending, iso));
    if (pending !== value.start || iso !== value.end)
      onChange({ ...value, start: pending, end: iso });
  };

  const today = isoFromEpochMs(now());
  const start = normaliseIso(value.start);
  const end = normaliseIso(value.end);
  const initialFocus = start ?? clampIso(today, lower, upper);
  const wellInvalid = (part: Part): boolean =>
    control.invalid && (errors[part] !== null || typedError === null);
  const describe = (part: Part): string | undefined =>
    control.describe(
      control.ownLines && errorId,
      hint !== null && hintId,
      describedBy,
      suffixIds[part],
    );
  const echo = control.reasonFromField ? undefined : reason.reason;
  const onError = (part: Part) => (error: string | null) =>
    setErrors((prev) => (prev[part] === error ? prev : { ...prev, [part]: error }));
  const check = (iso: string): string | null => (isWithin(iso, lower, upper) ? null : rangeError);

  const calendar = (
    <CalendarButton
      label="Choose dates"
      open={open}
      onOpen={openCalendar}
      onClose={() => {
        setOpen(false);
        setPending(null);
      }}
      headingId={headingId}
      initialFocusRef={dayRef}
      reason={reason}
      readOnly={readOnly}
      density={density}
    >
      <CalendarGrid
        key={openings}
        initialFocus={initialFocus}
        selected={pending ?? start}
        rangeEnd={pending === null ? (end ?? start) : null}
        today={today}
        min={lower ?? undefined}
        max={upper ?? undefined}
        caption={caption}
        headingId={headingId}
        focusedRef={dayRef}
        onPick={pick}
      />
      <span className="cv-visually-hidden" role="status">
        {startSaid}
      </span>
    </CalendarButton>
  );

  const well = (part: Part, last: boolean): JSX.Element => {
    const isTime = part === "startTime" || part === "endTime";
    const label = part === "startTime" ? startLabel : endLabel;
    return (
      <EntryWell
        key={part}
        id={part === "start" ? startId : part === "end" ? endId : undefined}
        value={value[part] ?? null}
        parse={isTime ? normaliseTime : normaliseIso}
        parseError={isTime ? TIME_ERROR : parseError}
        check={isTime ? undefined : check}
        onCommit={(next) => onChange({ ...value, [part]: next })}
        onError={onError(part)}
        placeholder={isTime ? TIME_HINT : (hint ?? undefined)}
        size={isTime ? TIME_HINT.length : undefined}
        aria-label={isTime ? `${label} time` : undefined}
        aria-describedby={describe(part)}
        required={control.required}
        invalid={wellInvalid(part)}
        reason={reason}
        echo={echo}
        readOnly={readOnly}
        suffixId={suffixIds[part]}
        onOpen={openCalendar}
        onBlur={onBlur}
        trail={last ? calendar : null}
        className={isTime ? "cv-datepicker__time" : "cv-datepicker__date"}
      />
    );
  };

  return (
    <div
      role="group"
      id={id}
      aria-label={ariaLabel}
      aria-labelledby={control.field?.labelId ?? labelledBy}
      className="cv-field-root cv-datepicker cv-daterange"
      data-cmp="CMP-047"
      data-mode="range"
      data-density={density}
      data-time={withTime ? "" : undefined}
      data-disabled={reason.disabled ? "" : undefined}
    >
      <div className="cv-daterange__fields">
        <div className="cv-daterange__part">
          <label htmlFor={startId} className="cv-daterange__label">
            {startLabel}
          </label>
          <div className="cv-datepicker__row">
            {well("start", false)}
            {withTime ? well("startTime", false) : null}
          </div>
        </div>
        <div className="cv-daterange__part">
          <label htmlFor={endId} className="cv-daterange__label">
            {endLabel}
          </label>
          <div className="cv-datepicker__row">
            {well("end", !withTime)}
            {withTime ? well("endTime", true) : null}
          </div>
        </div>
      </div>
      {control.ownLines ? (
        <FieldMessage
          id={errorId}
          message={control.invalid ? (typedError ?? errorMessage) : undefined}
        />
      ) : null}
      {hint === null ? null : (
        <div id={hintId} className="cv-datepicker__hint">
          {withTime ? `${hint} ${TIME_HINT}` : hint}
        </div>
      )}
      {control.reasonFromField ? null : (
        <ReasonText id={reason.reasonId}>{reason.reason}</ReasonText>
      )}
      <span className="cv-visually-hidden" role="status">
        {rangeSaid}
      </span>
    </div>
  );
}

import { useId, useRef, useState, type FocusEvent, type JSX } from "react";
import { CalendarGrid } from "./internal/CalendarGrid.js";
import { ReasonText } from "./internal/disabledReason.js";
import { EntryWell } from "./internal/EntryWell.js";
import { useFieldControl } from "./internal/fieldContext.js";
import { FieldMessage } from "./internal/fieldParts.js";
import {
  clampIso,
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

export interface DatePickerProps {
  /** The committed day as ISO `YYYY-MM-DD` (UTC), or null when empty. Never a `Date`. */
  readonly value: string | null;
  /** A pick, or typed text that parsed and is within `min`-`max`, or an emptied field (null). Never an invalid entry. */
  readonly onChange: (value: string | null) => void;
  /** Outside a field only: inside a CMP-040 FormField the field's id wins. */
  readonly id?: string;
  readonly name?: string;
  readonly "aria-label"?: string;
  readonly "aria-labelledby"?: string;
  /** Joined after the error and the format hint, before the "UTC" suffix. */
  readonly "aria-describedby"?: string;
  /** The first allowed day (ISO); earlier days are out of range. */
  readonly min?: string;
  /** The last allowed day (ISO); later days are out of range. */
  readonly max?: string;
  /** The host's sentence naming `min`-`max` (G11), under the calendar; without it one is composed from the bounds. */
  readonly rangeCaption?: string;
  /** The help line and the placeholder (G11): default "YYYY-MM-DD". */
  readonly formatHint?: string;
  /** The host's verdict (CMP-040, conventions 23); typed text that does not parse is invalid here without it. */
  readonly invalid?: boolean;
  readonly errorMessage?: string;
  readonly disabled?: boolean;
  /** The visible reason a control is denied (RBAC, environment, risk): T2, and the calendar never opens. */
  readonly disabledReason?: string;
  readonly readOnly?: boolean;
  readonly density?: "comfortable" | "compact";
  /** The clock that names today, in epoch milliseconds (injectable for tests and replay); default `Date.now`. */
  readonly now?: () => number;
  /** Each field's blur (the date's, and the time's with `withTime`). */
  readonly onBlur?: (event: FocusEvent<HTMLInputElement>) => void;
  /** An `HH:MM` (24-hour, UTC) field beside the date (G11); typed only, the calendar never sets it. */
  readonly withTime?: boolean;
  /** With `withTime`: the committed time as `HH:MM` (UTC), or null when empty. */
  readonly time?: string | null;
  /** With `withTime`: a parsed time, or an emptied field (null). Never an invalid entry. */
  readonly onTimeChange?: (time: string | null) => void;
  /** With `withTime`: the time field's name; default "Time". */
  readonly timeLabel?: string;
}

/**
 * CMP-047 DatePicker (single): the CMP-007 well holding typed `YYYY-MM-DD`, parsed on blur or Enter and never
 * clamped, a "UTC" suffix and a CMP-002 ghost calendar button flush at its end. The button (or Alt+Down in the
 * field) opens a modal CMP-017 Popover named by the month heading: the WAI-ARIA APG Date Picker Dialog grid,
 * Monday first, every value UTC. Focus opens on the selected day, else today, else the nearest allowed day; a pick
 * or Esc closes it and focus returns to the calendar button. T2 (conventions 24): the field is read-only, the
 * button `aria-disabled`, and the dialog never opens. `withTime` adds an `HH:MM` UTC well after the date, and the
 * calendar button moves to its end, so the Tab order is the date, the time, then the button.
 */
export function DatePicker({
  value,
  onChange,
  id,
  name,
  "aria-label": ariaLabel,
  "aria-labelledby": labelledBy,
  "aria-describedby": describedBy,
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
  time = null,
  onTimeChange,
  timeLabel = "Time",
}: DatePickerProps): JSX.Element {
  const errorId = useId();
  const hintId = useId();
  const suffixId = useId();
  const timeSuffixId = useId();
  const headingId = useId();
  const dayRef = useRef<HTMLButtonElement | null>(null);
  const [dateError, setDateError] = useState<string | null>(null);
  const [timeError, setTimeError] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  /** One fresh calendar per opening: its focused day starts over. */
  const [openings, setOpenings] = useState(0);
  const lower = normaliseIso(min);
  const upper = normaliseIso(max);
  const caption = rangeCaption ?? composeCaption(lower, upper);
  /** The help line and the placeholder: an empty `formatHint` draws neither. */
  const hint = formatHint === "" ? null : formatHint;
  const parseError = `Enter a date as ${hint ?? DEFAULT_HINT}.`;
  const rangeError = caption ?? parseError;

  const typedError = dateError ?? (withTime ? timeError : null);
  const control = useFieldControl(
    disabled,
    disabledReason,
    invalid || typedError !== null,
    typedError ?? errorMessage,
  );
  const { reason } = control;
  const frozen = reason.gated || reason.disabled || readOnly;
  // A picker that becomes gated, disabled or read-only while open closes, and stays closed once it is free again.
  if (frozen && open) setOpen(false);

  const openCalendar = (): void => {
    if (frozen || open) return;
    setOpenings((n) => n + 1);
    setOpen(true);
  };

  const pick = (iso: string): void => {
    setOpen(false);
    if (iso !== value) onChange(iso);
  };

  const today = isoFromEpochMs(now());
  const selected = normaliseIso(value);
  const initialFocus = selected ?? clampIso(today, lower, upper);
  /** A well shows the invalid look for its own typed error, or for the picker's verdict when no well has one. */
  const wellInvalid = (own: string | null): boolean =>
    control.invalid && (own !== null || typedError === null);
  const message = typedError ?? errorMessage;
  const describe = (suffix: string): string | undefined =>
    control.describe(control.ownLines && errorId, hint !== null && hintId, describedBy, suffix);
  const echo = control.reasonFromField ? undefined : reason.reason;

  const calendar = (
    <CalendarButton
      label="Choose date"
      open={open}
      onOpen={openCalendar}
      onClose={() => setOpen(false)}
      headingId={headingId}
      initialFocusRef={dayRef}
      reason={reason}
      readOnly={readOnly}
      density={density}
    >
      <CalendarGrid
        key={openings}
        initialFocus={initialFocus}
        selected={selected}
        today={today}
        min={lower ?? undefined}
        max={upper ?? undefined}
        caption={caption}
        headingId={headingId}
        focusedRef={dayRef}
        onPick={pick}
      />
    </CalendarButton>
  );

  return (
    <div
      className="cv-field-root cv-datepicker"
      data-cmp="CMP-047"
      data-density={density}
      data-time={withTime ? "" : undefined}
    >
      <div className="cv-datepicker__row">
        <EntryWell
          id={control.field?.controlId ?? id}
          name={name}
          value={value}
          parse={normaliseIso}
          parseError={parseError}
          check={(iso) => (isWithin(iso, lower, upper) ? null : rangeError)}
          onCommit={onChange}
          onError={setDateError}
          placeholder={hint ?? undefined}
          aria-label={ariaLabel}
          aria-labelledby={labelledBy}
          aria-describedby={describe(suffixId)}
          required={control.required}
          invalid={wellInvalid(dateError)}
          reason={reason}
          echo={echo}
          readOnly={readOnly}
          suffixId={suffixId}
          onOpen={openCalendar}
          onBlur={onBlur}
          trail={withTime ? null : calendar}
          className="cv-datepicker__date"
        />
        {withTime ? (
          <EntryWell
            value={time}
            parse={normaliseTime}
            parseError={TIME_ERROR}
            onCommit={(next) => onTimeChange?.(next)}
            onError={setTimeError}
            placeholder={TIME_HINT}
            size={TIME_HINT.length}
            aria-label={timeLabel}
            aria-describedby={describe(timeSuffixId)}
            required={control.required}
            invalid={wellInvalid(timeError)}
            reason={reason}
            echo={echo}
            readOnly={readOnly}
            suffixId={timeSuffixId}
            onOpen={openCalendar}
            onBlur={onBlur}
            trail={calendar}
            className="cv-datepicker__time"
          />
        ) : null}
      </div>
      {control.ownLines ? (
        <FieldMessage id={errorId} message={control.invalid ? message : undefined} />
      ) : null}
      {hint === null ? null : (
        <div id={hintId} className="cv-datepicker__hint">
          {withTime ? `${hint} ${TIME_HINT}` : hint}
        </div>
      )}
      {control.reasonFromField ? null : (
        <ReasonText id={reason.reasonId}>{reason.reason}</ReasonText>
      )}
    </div>
  );
}

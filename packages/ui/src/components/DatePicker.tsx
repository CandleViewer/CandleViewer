import {
  useId,
  useRef,
  useState,
  type ChangeEvent,
  type FocusEvent,
  type JSX,
  type KeyboardEvent,
  type MouseEvent,
} from "react";
import { Icon } from "../icons/Icon.js";
import { CalendarGrid } from "./internal/CalendarGrid.js";
import { ReasonText } from "./internal/disabledReason.js";
import { ReasonEcho } from "./internal/ReasonEcho.js";
import { useFieldControl } from "./internal/fieldContext.js";
import { FieldMessage, useRefusalAnnounce } from "./internal/fieldParts.js";
import { clampIso, isWithin, isoFromEpochMs, normaliseIso } from "./internal/isoDate.js";
import { IconButton } from "./IconButton.js";
import { Popover } from "./Popover.js";

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
  readonly onBlur?: (event: FocusEvent<HTMLInputElement>) => void;
}

/** Text the user typed and has not committed; `base` is the value it was typed against. */
interface Edit {
  readonly text: string;
  readonly base: string | null;
  readonly error: string | null;
}

const DEFAULT_HINT = "YYYY-MM-DD";

/** The sentence for `min`-`max` when the host gives none. */
function composeCaption(min: string | null, max: string | null): string | undefined {
  if (min !== null && max !== null) return `Choose a date from ${min} to ${max}.`;
  if (min !== null) return `Choose a date on or after ${min}.`;
  if (max !== null) return `Choose a date on or before ${max}.`;
  return undefined;
}

/**
 * CMP-047 DatePicker (single): the CMP-007 well holding typed `YYYY-MM-DD`, parsed on blur or Enter and never
 * clamped, a "UTC" suffix and a CMP-002 ghost calendar button flush at its end. The button (or Alt+Down in the
 * field) opens a modal CMP-017 Popover named by the month heading: the WAI-ARIA APG Date Picker Dialog grid,
 * Monday first, every value UTC. Focus opens on the selected day, else today, else the nearest allowed day; a pick
 * or Esc closes it and focus returns to the calendar button. T2 (conventions 24): the field is read-only, the
 * button `aria-disabled`, and the dialog never opens.
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
}: DatePickerProps): JSX.Element {
  const errorId = useId();
  const hintId = useId();
  const suffixId = useId();
  const headingId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const dayRef = useRef<HTMLButtonElement | null>(null);
  const [typed, setTyped] = useState<Edit | null>(null);
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

  // An edit belongs to the value it was typed against: a host that moves the value discards it.
  const edit = typed !== null && typed.base === value ? typed : null;
  const typedError = edit?.error ?? null;
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

  /** The verdict on typed text: null when it can be committed (empty commits null). */
  const judge = (text: string): string | null => {
    const trimmed = text.trim();
    if (trimmed === "") return null;
    const iso = normaliseIso(trimmed);
    if (iso === null) return parseError;
    return isWithin(iso, lower, upper) ? null : rangeError;
  };

  const commit = (text: string): void => {
    const error = judge(text);
    if (error !== null) {
      setTyped({ text, base: value, error });
      return;
    }
    setTyped(null);
    const next = normaliseIso(text.trim());
    if (next !== value) onChange(next);
  };

  const openCalendar = (): void => {
    if (frozen || open) return;
    setOpenings((n) => n + 1);
    setOpen(true);
  };

  const refusal = useRefusalAnnounce<HTMLInputElement>(
    reason,
    {
      onKeyDown: (event: KeyboardEvent<HTMLInputElement>) => {
        if (frozen || event.nativeEvent.isComposing) return;
        if (event.key === "ArrowDown" && event.altKey) {
          event.preventDefault();
          openCalendar();
        } else if (event.key === "Enter" && edit !== null) {
          commit(edit.text);
        }
      },
      onBlur: (event: FocusEvent<HTMLInputElement>) => {
        // An edit under way when the field became gated or read-only is discarded, not committed.
        if (frozen) setTyped(null);
        else if (edit !== null) commit(edit.text);
        onBlur?.(event);
      },
    },
    (event) => event.altKey && event.key === "ArrowDown",
  );

  const onInput = (event: ChangeEvent<HTMLInputElement>): void => {
    // A shown error keeps its words until the text is valid, then clears silently (conventions 23).
    const text = event.target.value;
    const stays = typedError !== null && judge(text) !== null;
    setTyped({ text, base: value, error: stays ? typedError : null });
  };

  const pick = (iso: string): void => {
    setTyped(null);
    setOpen(false);
    if (iso !== value) onChange(iso);
  };

  /**
   * A press on the well's padding or the suffix focuses the field; a press on the button stays the button's. The
   * calendar is portaled, but React bubbles its presses here: a press anywhere in the dialog stays the dialog's.
   */
  const forward = (event: MouseEvent<HTMLDivElement>): void => {
    if (event.button !== 0 || !(event.target instanceof Element)) return;
    if (!event.currentTarget.contains(event.target)) return;
    if (event.target === inputRef.current || event.target.closest("button") !== null) return;
    event.preventDefault();
    inputRef.current?.focus();
  };

  const today = isoFromEpochMs(now());
  const selected = normaliseIso(value);
  const initialFocus = selected ?? clampIso(today, lower, upper);
  const shownInvalid = control.invalid;
  const message = typedError ?? errorMessage;
  const description = control.describe(
    control.ownLines && errorId,
    hint !== null && hintId,
    describedBy,
    suffixId,
  );

  return (
    <div className="cv-field-root cv-datepicker" data-cmp="CMP-047" data-density={density}>
      {/* The mouse handler only forwards a press to the input; the input is the keyboard and AT target. */}
      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions -- see above: not a widget */}
      <div
        className="cv-field"
        data-invalid={shownInvalid ? "" : undefined}
        data-gated={reason.gated ? "" : undefined}
        data-disabled={reason.disabled ? "" : undefined}
        data-readonly={readOnly ? "" : undefined}
        data-lead={reason.gated ? "" : undefined}
        data-trail=""
        onMouseDown={forward}
      >
        {reason.gated ? (
          <span className="cv-field__lead cv-field__lock">
            <Icon name="lock" decorative={false} label="Not available" />
          </span>
        ) : null}
        <ReasonEcho text={control.reasonFromField ? undefined : reason.reason}>
          <input
            id={control.field?.controlId ?? id}
            ref={inputRef}
            name={name}
            type="text"
            inputMode="numeric"
            autoComplete="off"
            spellCheck={false}
            className="cv-field__input"
            placeholder={hint ?? undefined}
            value={edit?.text ?? value ?? ""}
            disabled={reason.disabled}
            readOnly={readOnly || reason.gated}
            aria-label={ariaLabel}
            aria-labelledby={labelledBy}
            aria-disabled={reason.ariaDisabled}
            aria-invalid={shownInvalid ? true : undefined}
            aria-required={control.required}
            aria-describedby={description}
            onChange={onInput}
            {...refusal.handlers}
          />
        </ReasonEcho>
        {/*
          Spoken through the field's description (by reference), so hidden from the reading order. Plain disabled it
          dims with the well: inactive text (WCAG 1.4.3), marked so as the input is.
        */}
        <span
          id={suffixId}
          className="cv-field__trail cv-field__affix"
          aria-hidden="true"
          aria-disabled={reason.disabled ? true : undefined}
        >
          UTC
        </span>
        <Popover
          modal
          open={open}
          onOpenChange={(next) => (next ? openCalendar() : setOpen(false))}
          aria-labelledby={headingId}
          initialFocusRef={dayRef}
          className="cv-datepicker__dialog"
          anchor={
            <IconButton
              icon="calendar"
              label="Choose date"
              variant="ghost"
              {...(density === undefined ? {} : { density })}
              {...(reason.reason === undefined ? {} : { disabledReason: reason.reason })}
              disabled={reason.disabled || (readOnly && !reason.gated)}
            />
          }
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
        </Popover>
      </div>
      {control.ownLines ? (
        <FieldMessage id={errorId} message={shownInvalid ? message : undefined} />
      ) : null}
      {hint === null ? null : (
        <div id={hintId} className="cv-datepicker__hint">
          {hint}
        </div>
      )}
      {control.reasonFromField ? null : (
        <ReasonText id={reason.reasonId}>{reason.reason}</ReasonText>
      )}
      {refusal.status}
    </div>
  );
}

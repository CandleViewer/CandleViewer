import {
  useId,
  useRef,
  useState,
  type ChangeEvent,
  type JSX,
  type KeyboardEvent,
  type MouseEvent,
} from "react";
import { Icon } from "../icons/Icon.js";
import { ReasonText, useDisabledReason } from "./internal/disabledReason.js";
import { cx } from "./internal/cx.js";
import { FieldMessage, focusFieldInput, useRefusalAnnounce } from "./internal/fieldParts.js";
import {
  formatNumeric,
  parseNumericInput,
  stepValue,
  validateNumeric,
  valueText,
} from "./internal/numeric.js";

export type StepDirection = "up" | "down";

export interface NumericStepperInputProps {
  /** The accessible name; the step buttons are named "Decrease {label}" / "Increase {label}". */
  label: string;
  /** Names the field by an element instead; `label` still names the step buttons. */
  "aria-labelledby"?: string;
  "aria-describedby"?: string;
  id?: string;
  name?: string;
  placeholder?: string;
  value: number;
  min?: number;
  max?: number;
  /** A positive multiple of 10^-precision (a finer step throws, as `stepValue`). */
  step: number;
  /** The Page Up / Page Down step; default 10 x `step`. */
  largeStep?: number;
  /** Decimal places shown and kept: explicit, "." separator, no grouping, no locale guessing. */
  precision: number;
  /** The unit, shown in the well and spoken in `aria-valuetext` ("5 %"). */
  suffix?: string;
  /** A committed value: a step, Home or End, or typed text that parsed and is in range. Never an invalid entry. */
  onChange: (value: number) => void;
  /** After `onChange`, once per step that moved the value (arrows, Shift, Page keys, the buttons). */
  onStep?: (direction: StepDirection) => void;
  /** The host's own verdict (CMP-040); typed text that is out of range is invalid here without it. */
  invalid?: boolean;
  errorMessage?: string;
  disabled?: boolean;
  /** The visible reason a control is denied (RBAC, environment, risk): disabled-with-reason (T2). */
  disabledReason?: string;
  readOnly?: boolean;
  density?: "comfortable" | "compact";
}

/** The text the user typed and has not committed; `base` is the value it was typed against. */
interface Edit {
  readonly text: string;
  readonly base: number;
  readonly error: string | null;
}

const NOT_A_NUMBER = "Enter a number.";
const ROUNDED = "(rounded to nearest tick)";
const STEP_KEYS = new Set(["ArrowUp", "ArrowDown", "PageUp", "PageDown"]);
const isChord = (event: KeyboardEvent): boolean => event.ctrlKey || event.metaKey || event.altKey;
/** Decimal places a number needs, read from its shortest text (`1e-7` is 7, `0.05` is 2). */
const ownDecimals = (n: number): number => {
  const [mantissa = "", exponent = "0"] = String(n).split("e");
  return Math.max(0, (mantissa.split(".")[1]?.length ?? 0) - Number(exponent));
};
/** A bound is shown at the precision, or at its own decimals when it has more: never in exponent form. */
const showBound = (bound: number, precision: number): string =>
  formatNumeric(bound, Math.min(15, Math.max(precision, ownDecimals(bound))));

/**
 * CMP-008: the numeric field with `[-]` `[+]` buttons (APG spin button). The value is a number, shown fixed to
 * `precision`; typed text is parsed, rounded and range-checked on blur or Enter and is never clamped. All
 * arithmetic goes through `stepValue` (scaled integers), never `x + step`.
 */
export function NumericStepperInput({
  label,
  "aria-labelledby": labelledBy,
  "aria-describedby": describedBy,
  id,
  name,
  placeholder,
  value,
  min,
  max,
  step,
  largeStep,
  precision,
  suffix,
  onChange,
  onStep,
  invalid = false,
  errorMessage,
  disabled,
  disabledReason,
  readOnly = false,
  density,
}: NumericStepperInputProps): JSX.Element {
  const reason = useDisabledReason(disabled, disabledReason);
  const errorId = useId();
  const noteId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [typed, setTyped] = useState<Edit | null>(null);
  const [roundedTo, setRoundedTo] = useState<number | null>(null);
  // An edit belongs to the value it was typed against: a host that moves the value discards it.
  // `Object.is`, not `===`: a draft typed against a NaN value must survive (NaN !== NaN).
  const edit = typed !== null && Object.is(typed.base, value) ? typed : null;
  const rounded = edit === null && roundedTo === value;
  const frozen = reason.gated || readOnly;
  const range = { ...(min === undefined ? {} : { min }), ...(max === undefined ? {} : { max }) };

  // A value moved from outside drops the draft and a caption that was earned by an older value (A to B to A).
  const [seen, setSeen] = useState(value);
  if (!Object.is(seen, value)) {
    setSeen(value);
    setTyped(null);
    if (roundedTo !== value) setRoundedTo(null);
  }

  /** The keys a gated field refuses: the step keys, and Home or End when their bound is set. */
  const isStepKey = (event: KeyboardEvent): boolean =>
    !isChord(event) &&
    (STEP_KEYS.has(event.key) ||
      (event.key === "Home" && min !== undefined) ||
      (event.key === "End" && max !== undefined));

  const refusal = useRefusalAnnounce(
    reason,
    {
      onKeyDown: (event) => {
        if (frozen || event.nativeEvent.isComposing) return;
        // Enter commits the typed text; the form's implicit submission stays the host's.
        if (event.key === "Enter" && edit !== null) commit(edit.text);
        else keyStep(event);
      },
      onBlur: () => {
        // An edit that was under way when the field became gated or read-only is discarded, not committed.
        if (frozen) setTyped(null);
        else if (edit !== null) commit(edit.text);
      },
    },
    isStepKey,
  );

  /** A step or jump: the typed text is dropped, the caption goes, and a moved value is reported. */
  const apply = (next: number, direction?: StepDirection): void => {
    setTyped(null);
    setRoundedTo(null);
    if (next === value) return;
    onChange(next);
    if (direction !== undefined) onStep?.(direction);
  };

  /** Steps start from clean typed text (as a native number field does), else from the committed value. */
  const from = (): number => {
    const parsed =
      edit !== null && edit.error === null ? parseNumericInput(edit.text, { precision }) : null;
    return parsed?.ok === true ? parsed.value : value;
  };

  const stepBy = (direction: StepDirection, size: number, times: number): void =>
    apply(stepValue(from(), size, direction, times, precision, min, max), direction);

  function keyStep(event: KeyboardEvent<HTMLInputElement>): void {
    if (isChord(event)) return;
    const direction = event.key === "ArrowUp" || event.key === "PageUp" ? "up" : "down";
    if (event.key === "ArrowUp" || event.key === "ArrowDown") {
      stepBy(direction, step, event.shiftKey ? 10 : 1);
    } else if (event.key === "PageUp" || event.key === "PageDown") {
      // Without `largeStep` the multiplier keeps 10 x step exact (0.1 x 10 as a scaled integer, not a float).
      stepBy(direction, largeStep ?? step, largeStep === undefined ? 10 : 1);
    } else {
      // With text under way Home and End are caret keys, as in any text field.
      const bound = event.key === "Home" ? min : event.key === "End" ? max : undefined;
      if (bound === undefined || edit !== null) return;
      apply(bound);
    }
    event.preventDefault();
  }

  /** The message for a parse that cannot be committed, or null when it can. Empty text is not a number. */
  function judge(parsed: ReturnType<typeof parseNumericInput>): string | null {
    const verdict = parsed.ok ? validateNumeric(parsed.value, range) : "not-a-number";
    if (verdict === "in-range") return null;
    const bound = verdict === "below-min" ? min : verdict === "above-max" ? max : undefined;
    if (bound === undefined) return NOT_A_NUMBER;
    return `${verdict === "below-min" ? "Minimum" : "Maximum"} ${showBound(bound, precision)}`;
  }

  function commit(text: string): void {
    const parsed = parseNumericInput(text, { precision });
    const error = judge(parsed);
    if (error !== null || !parsed.ok) {
      setTyped({ text, base: value, error: error ?? NOT_A_NUMBER });
      return;
    }
    setTyped(null);
    setRoundedTo(parsed.rounded ? parsed.value : null);
    if (parsed.value !== value) onChange(parsed.value);
  }

  const onInput = (event: ChangeEvent<HTMLInputElement>): void => {
    // A shown error keeps its words (nothing new is spoken per keystroke) until the text is valid, then
    // clears silently; the next commit (blur or Enter) words it again.
    const text = event.target.value;
    const stays = edit?.error != null && judge(parseNumericInput(text, { precision })) !== null;
    setTyped({ text, base: value, error: stays ? (edit?.error ?? null) : null });
    setRoundedTo(null);
  };

  /** A press keeps the focus where it is (the buttons are not tab stops) and gives the field the focus. */
  const press = (direction: StepDirection) => (event: MouseEvent<HTMLButtonElement>) => {
    event.preventDefault();
    inputRef.current?.focus();
    if (reason.gated) refusal.announce();
    else stepBy(direction, step, 1);
  };

  const typedError = edit?.error ?? null;
  const shownInvalid = invalid || typedError !== null;
  const message = typedError ?? errorMessage;
  const hasSuffix = suffix !== undefined && suffix !== "";
  const atMin = min !== undefined && value <= min;
  const atMax = max !== undefined && value >= max;
  const description = reason.gated
    ? reason.ariaDescribedBy
    : cx(errorId, noteId, describedBy) || undefined;
  const button = (direction: StepDirection, atBound: boolean): JSX.Element => (
    <button
      type="button"
      tabIndex={-1}
      className="cv-control cv-stepper__btn"
      aria-label={`${direction === "up" ? "Increase" : "Decrease"} ${label}`}
      disabled={!reason.gated && (reason.disabled || readOnly || atBound)}
      aria-disabled={reason.ariaDisabled}
      aria-describedby={reason.ariaDescribedBy}
      onMouseDown={(event) => event.preventDefault()}
      onClick={press(direction)}
    >
      <span className="cv-stepper__glyph">
        <Icon name={direction === "up" ? "plus" : "minus"} />
      </span>
    </button>
  );

  return (
    <div className="cv-field-root" data-cmp="CMP-008" data-density={density}>
      <div className="cv-stepper">
        {/* The mouse handler only forwards a press to the input; the input is the keyboard and AT target. */}
        {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions -- see above: not a widget */}
        <div
          className="cv-field"
          data-invalid={shownInvalid ? "" : undefined}
          data-gated={reason.gated ? "" : undefined}
          data-disabled={reason.disabled ? "" : undefined}
          data-readonly={readOnly ? "" : undefined}
          data-lead={reason.gated ? "" : undefined}
          data-trail={hasSuffix ? "" : undefined}
          onMouseDown={(event) => focusFieldInput(event, inputRef)}
        >
          {reason.gated ? (
            <span className="cv-field__lead cv-field__lock">
              <Icon name="lock" decorative={false} label="Not available" />
            </span>
          ) : null}
          <input
            ref={inputRef}
            id={id}
            name={name}
            placeholder={placeholder}
            type="text"
            role="spinbutton"
            inputMode="decimal"
            autoComplete="off"
            spellCheck={false}
            className="cv-field__input cv-field__input--num"
            value={edit?.text ?? formatNumeric(value, precision)}
            disabled={reason.disabled}
            readOnly={frozen}
            aria-label={labelledBy === undefined ? label : undefined}
            aria-labelledby={labelledBy}
            aria-valuenow={Number.isFinite(value) && edit?.text !== "" ? value : undefined}
            aria-valuemin={min}
            aria-valuemax={max}
            aria-valuetext={
              edit === null
                ? valueText(value, precision, suffix)
                : edit.text === ""
                  ? undefined
                  : hasSuffix
                    ? `${edit.text} ${suffix}`
                    : edit.text
            }
            aria-readonly={readOnly && !reason.gated ? true : undefined}
            aria-disabled={reason.ariaDisabled}
            aria-invalid={shownInvalid ? true : undefined}
            aria-describedby={description}
            onChange={onInput}
            {...refusal.handlers}
          />
          {hasSuffix ? (
            <span className="cv-field__trail cv-field__affix" aria-hidden="true">
              {suffix}
            </span>
          ) : null}
        </div>
        {button("down", atMin)}
        {button("up", atMax)}
      </div>
      <FieldMessage id={errorId} message={shownInvalid ? message : undefined} />
      <div id={noteId} className="cv-field__caption" aria-live="polite">
        {rounded ? ROUNDED : null}
      </div>
      <ReasonText id={reason.reasonId}>{reason.reason}</ReasonText>
      {refusal.status}
    </div>
  );
}

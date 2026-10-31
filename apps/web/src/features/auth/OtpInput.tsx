import { forwardRef, type ChangeEvent, type JSX } from "react";

export interface OtpInputProps {
  readonly id: string;
  /** How many digits make a complete code. */
  readonly length?: number;
  readonly value: string;
  readonly onChange: (value: string) => void;
  /** Fired once per complete code, typed or pasted whole. */
  readonly onComplete: (code: string) => void;
  /** The id of the consumer's visible heading: the input's name (no fixed name in here). */
  readonly labelledBy: string;
  /** The ids of the visible instruction and, when set, the field's error. */
  readonly describedBy?: string | undefined;
  readonly invalid?: boolean;
  /** While verifying: `readOnly` + `aria-disabled`, focus kept; never the native `disabled`. */
  readonly busy?: boolean;
}

/**
 * CMP-204 OtpInput, inline in `features/auth` until #190 publishes it in `packages/ui` (#2711 BQ-09).
 * One `<input inputmode="numeric" autocomplete="one-time-code">`: no `role="group"` of cells, no
 * per-digit focus moves or announcements, digits never masked. Only digits are kept, up to `length`;
 * a paste of the whole code fills it and fires `onComplete` once. The value is never logged.
 */
export const OtpInput = forwardRef<HTMLInputElement, OtpInputProps>(function OtpInput(
  { id, length = 6, value, onChange, onComplete, labelledBy, describedBy, invalid, busy },
  ref,
): JSX.Element {
  function change(event: ChangeEvent<HTMLInputElement>): void {
    if (busy) return;
    const next = event.target.value.replace(/\D/gu, "").slice(0, length);
    onChange(next);
    // a new complete code (typed, or pasted over another), not every render of one
    if (next.length === length && next !== value) onComplete(next);
  }
  return (
    <input
      ref={ref}
      id={id}
      className="cv-otp-input"
      type="text"
      inputMode="numeric"
      autoComplete="one-time-code"
      spellCheck={false}
      value={value}
      readOnly={busy}
      aria-disabled={busy ? true : undefined}
      aria-invalid={invalid ? true : undefined}
      aria-labelledby={labelledBy}
      aria-describedby={describedBy}
      onChange={change}
    />
  );
});

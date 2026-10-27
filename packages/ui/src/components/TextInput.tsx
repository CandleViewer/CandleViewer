import {
  useId,
  useRef,
  useState,
  type ComponentPropsWithoutRef,
  type FocusEvent,
  type JSX,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
} from "react";
import { Icon } from "../icons/Icon.js";
import { ReasonText, useDisabledReason } from "./internal/disabledReason.js";
import { cx } from "./internal/cx.js";

export interface TextInputProps extends Omit<
  ComponentPropsWithoutRef<"input">,
  | "className"
  | "style"
  | "children"
  | "disabled"
  | "readOnly"
  | "prefix"
  | "size"
  | "type"
  | "aria-disabled"
  | "aria-invalid"
> {
  /** Native text-like types only; the role stays `textbox` except for `password`. */
  type?: "text" | "password" | "search" | "email" | "url" | "tel";
  /** Leading content inside the well (a glyph or text); a glyph is `aria-hidden` through `Icon`. */
  prefix?: ReactNode;
  /** Trailing content inside the well (a unit); its text joins the field's description. */
  suffix?: ReactNode;
  /** Validity is a message, never T2 (D02F conv. 23): the host decides when, the atom renders it. */
  invalid?: boolean;
  /** The sentence under the field; shown with the `danger` glyph while `invalid`. */
  errorMessage?: string;
  disabled?: boolean;
  /** The visible reason a control is denied (RBAC, environment, risk): disabled-with-reason (T2). */
  disabledReason?: string;
  readOnly?: boolean;
  /** Emits `data-density` so `theme.css` re-points the control height; absent = inherit. */
  density?: "comfortable" | "compact";
}

/** Keys that leave a gated field (focus moves, a dialog closes) and so are not a refused edit. */
const PASSIVE_KEYS = new Set(["Tab", "Escape", "Shift", "Control", "Alt", "Meta", "CapsLock"]);

/** CMP-007: the single-line text field. The label is the host's (`htmlFor`, `aria-labelledby` or `aria-label`). */
export function TextInput({
  type = "text",
  prefix,
  suffix,
  invalid = false,
  errorMessage,
  disabled,
  disabledReason,
  readOnly = false,
  density,
  onKeyDown,
  onBlur,
  "aria-describedby": describedBy,
  ...rest
}: TextInputProps): JSX.Element {
  const reason = useDisabledReason(disabled, disabledReason);
  const errorId = useId();
  const suffixId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  // One polite announcement of the reason per focus visit (D09 9.3): set by the first refused key, cleared on blur.
  const [spoken, setSpoken] = useState(false);
  const hasSuffix = suffix !== undefined && suffix !== null && suffix !== false;
  const hasPrefix = prefix !== undefined && prefix !== null && prefix !== false;
  const hasMessage = invalid && errorMessage !== undefined && errorMessage !== "";

  // Gated: the reason alone. Otherwise: error, then the caller's help, then the unit (D02F conv. 23, 24).
  const description = reason.gated
    ? reason.ariaDescribedBy
    : cx(errorId, describedBy, hasSuffix && suffixId) || undefined;

  const handleKeyDown = (event: KeyboardEvent<HTMLInputElement>): void => {
    onKeyDown?.(event);
    if (reason.gated && !PASSIVE_KEYS.has(event.key)) setSpoken(true);
  };
  const handleBlur = (event: FocusEvent<HTMLInputElement>): void => {
    setSpoken(false);
    onBlur?.(event);
  };
  // The whole well is the hit target: a press on its padding or an affix focuses the input.
  const focusInput = (event: MouseEvent<HTMLDivElement>): void => {
    if (event.target === inputRef.current) return;
    event.preventDefault();
    inputRef.current?.focus();
  };

  return (
    <div className="cv-field-root" data-cmp="CMP-007" data-density={density}>
      {/* The mouse handler only forwards a press to the input; the input is the keyboard and AT target. */}
      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions -- see above: not a widget */}
      <div
        className="cv-field"
        data-invalid={invalid ? "" : undefined}
        data-gated={reason.gated ? "" : undefined}
        data-disabled={reason.disabled ? "" : undefined}
        data-readonly={readOnly ? "" : undefined}
        data-lead={reason.gated || hasPrefix ? "" : undefined}
        data-trail={hasSuffix ? "" : undefined}
        onMouseDown={focusInput}
      >
        {reason.gated ? (
          <span className="cv-field__lead cv-field__lock">
            <Icon name="lock" decorative={false} label="Not available" />
          </span>
        ) : null}
        {hasPrefix ? <span className="cv-field__lead cv-field__affix">{prefix}</span> : null}
        <input
          {...rest}
          ref={inputRef}
          type={type}
          className="cv-field__input"
          disabled={reason.disabled}
          readOnly={readOnly || reason.gated}
          aria-disabled={reason.ariaDisabled}
          aria-invalid={invalid ? true : undefined}
          aria-describedby={description}
          onKeyDown={handleKeyDown}
          onBlur={handleBlur}
        />
        {hasSuffix ? (
          <span id={suffixId} className="cv-field__trail cv-field__affix">
            {suffix}
          </span>
        ) : null}
      </div>
      {/* In the DOM at mount, empty while valid: a polite live region announces the swapped-in text once. */}
      <div id={errorId} className="cv-field__message" aria-live="polite">
        {hasMessage ? (
          <>
            <span className="cv-field__glyph">
              <Icon name="danger" />
            </span>
            <span>{errorMessage}</span>
          </>
        ) : null}
      </div>
      <ReasonText id={reason.reasonId}>{reason.reason}</ReasonText>
      <span className="cv-visually-hidden" role="status">
        {reason.gated && spoken ? reason.reason : ""}
      </span>
    </div>
  );
}

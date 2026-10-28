import { useId, useRef, type ComponentPropsWithoutRef, type JSX, type ReactNode } from "react";
import { Icon } from "../icons/Icon.js";
import { ReasonText } from "./internal/disabledReason.js";
import { ReasonEcho } from "./internal/ReasonEcho.js";
import { useFieldControl } from "./internal/fieldContext.js";
import { FieldMessage, focusFieldInput, useRefusalAnnounce } from "./internal/fieldParts.js";

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
  /** Outside a field only: inside a CMP-040 FormField the field's id wins; set it there through `htmlFor`. */
  id?: string;
  /** Native text-like types only; the role stays `textbox` except for `password`. */
  type?: "text" | "password" | "search" | "email" | "url" | "tel";
  /** Leading content inside the well (a glyph or text); a glyph is `aria-hidden` through `Icon`. */
  prefix?: ReactNode;
  /** Trailing content inside the well (a unit); its text joins the field's description. */
  suffix?: ReactNode;
  /**
   * Validity is a message, never T2 (D02F conv. 23): the host decides when, the atom renders it. The glyph and the
   * words belong to the message, so the host (CMP-040) must pass `errorMessage`; without one only the 2px
   * boundary and `aria-invalid` show.
   */
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

/**
 * CMP-007: the single-line text field. The label is the host's (`htmlFor`, `aria-labelledby` or `aria-label`).
 * Inside a CMP-040 FormField the field names it and draws the error and reason lines; the atom draws neither.
 */
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
  onPaste,
  onCut,
  "aria-describedby": describedBy,
  ...rest
}: TextInputProps): JSX.Element {
  const control = useFieldControl(disabled, disabledReason, invalid, errorMessage);
  const { reason } = control;
  const shownInvalid = control.invalid;
  const errorId = useId();
  const suffixId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const refusal = useRefusalAnnounce(reason, { onKeyDown, onBlur, onPaste, onCut });
  const hasSuffix = suffix !== undefined && suffix !== null && suffix !== false;
  const hasPrefix = prefix !== undefined && prefix !== null && prefix !== false;

  // Gated: the reason alone. Otherwise: error, then the caller's help, then the unit (D02F conv. 23, 24).
  const description = control.describe(
    control.ownLines && errorId,
    describedBy,
    hasSuffix && suffixId,
  );

  return (
    <div className="cv-field-root" data-cmp="CMP-007" data-density={density}>
      {/* The mouse handler only forwards a press to the input; the input is the keyboard and AT target. */}
      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions -- see above: not a widget */}
      <div
        className="cv-field"
        data-invalid={shownInvalid ? "" : undefined}
        data-gated={reason.gated ? "" : undefined}
        data-disabled={reason.disabled ? "" : undefined}
        data-readonly={readOnly ? "" : undefined}
        data-lead={reason.gated || hasPrefix ? "" : undefined}
        data-trail={hasSuffix ? "" : undefined}
        onMouseDown={(event) => focusFieldInput(event, inputRef)}
      >
        {reason.gated ? (
          <span className="cv-field__lead cv-field__lock">
            <Icon name="lock" decorative={false} label="Not available" />
          </span>
        ) : null}
        {hasPrefix ? <span className="cv-field__lead cv-field__affix">{prefix}</span> : null}
        <ReasonEcho text={control.reasonFromField ? undefined : reason.reason}>
          <input
            {...rest}
            id={control.field?.controlId ?? rest.id}
            ref={inputRef}
            type={type}
            className="cv-field__input"
            disabled={reason.disabled}
            readOnly={readOnly || reason.gated}
            aria-disabled={reason.ariaDisabled}
            aria-invalid={shownInvalid ? true : undefined}
            aria-required={rest["aria-required"] ?? control.required}
            aria-describedby={description}
            {...refusal.handlers}
          />
        </ReasonEcho>
        {hasSuffix ? (
          <span id={suffixId} className="cv-field__trail cv-field__affix">
            {suffix}
          </span>
        ) : null}
      </div>
      {control.ownLines ? (
        <FieldMessage id={errorId} message={invalid ? errorMessage : undefined} />
      ) : null}
      {control.reasonFromField ? null : (
        <ReasonText id={reason.reasonId}>{reason.reason}</ReasonText>
      )}
      {refusal.status}
    </div>
  );
}

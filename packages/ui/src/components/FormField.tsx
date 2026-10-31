import {
  useContext,
  useId,
  useLayoutEffect,
  useMemo,
  useState,
  type CSSProperties,
  type JSX,
  type MouseEvent,
  type ReactNode,
} from "react";
import { useDisabledReason } from "./internal/disabledReason.js";
import { cx } from "./internal/cx.js";
import { FieldContext, type FieldContextValue } from "./internal/fieldContext.js";
import { FieldMessage } from "./internal/fieldParts.js";
import { SectionContext } from "./internal/sectionContext.js";

export type FormFieldLayout = "stacked" | "inline";

export interface FormFieldProps {
  /** The visible, persistent label: the control's accessible name, never a placeholder. */
  readonly label: string;
  /**
   * The control's id (`<label for>`); generated when absent and handed to a field atom, which takes it over any id
   * of its own, so the label always points at the control. Set a control's id here, not on the atom.
   */
  readonly htmlFor?: string;
  /** The label's id, for a control that is not natively labelable (`aria-labelledby`); generated when absent. */
  readonly labelId?: string;
  /** Sets `aria-required` on the control; no asterisk (D02F G10). */
  readonly required?: boolean;
  /** Shows "(optional)" after the label, in a form that mixes required and optional fields (D02F G10). */
  readonly optional?: boolean;
  /** The help line under the control; part of the description after the error. */
  readonly help?: string | undefined;
  /**
   * The validation message (D02F conventions 23): the host decides when (blur, submit). Shown with the `danger`
   * glyph in a polite line that is in the DOM at mount; the control takes `aria-invalid`. Never shown while T2.
   */
  readonly error?: string | undefined;
  /** Plain disabled: unavailable to everyone in this state; the child is natively disabled, the field dims. */
  readonly disabled?: boolean;
  /** The visible reason the field is denied (E09-D09 §2.2 T2, rendering 2a): the reason line under the control. */
  readonly disabledReason?: string | undefined;
  /** `stacked` (default): the label over the control. `inline`: a label column, then the control (D02F G6). */
  readonly layout?: FormFieldLayout;
  /** The inline label column's width, a CSS length the host sizes (E30-D02: 56 px compact, 72 px comfortable). */
  readonly labelWidth?: string;
  /** Emits `data-density`; absent = inherit. */
  readonly density?: "comfortable" | "compact";
  /** One control: a field atom (TextInput, Select, NumericStepperInput) wires itself through the field. */
  readonly children: ReactNode;
}

/** Elements a `<label for>` names and focuses natively. */
const LABELABLE = "input, select, textarea, button, meter, output, progress";

/**
 * CMP-040: label, control, then the reason, error and help lines (D02F CMP-040). The field owns the lines; a field
 * atom inside it draws none of its own, so each line renders once. A native control is named through
 * `<label for>`; a control that is not labelable (a div combobox) through `aria-labelledby`, and a press on the
 * label focuses it.
 */
export function FormField({
  label,
  htmlFor,
  labelId,
  required = false,
  optional = false,
  help,
  error,
  disabled,
  disabledReason,
  layout = "stacked",
  labelWidth,
  density,
  children,
}: FormFieldProps): JSX.Element {
  const ownControlId = useId();
  const ownLabelId = useId();
  const errorId = useId();
  const helpId = useId();
  const controlId = htmlFor ?? ownControlId;
  const nameId = labelId ?? ownLabelId;
  const own = useDisabledReason(disabled, disabledReason);
  const section = useContext(SectionContext);
  // Inside a gated or plain-disabled CMP-065 section the section's gate wins: one notice, many pointers.
  const fromSection = section !== null && (section.reason.gated || section.reason.disabled);
  const reason = fromSection ? section.reason : own;
  const [reported, setReported] = useState<string | undefined>(undefined);
  const [labelledBy, setLabelledBy] = useState(false);

  const hasHelp = help !== undefined && help !== "";
  // A T2 field never validates (D02F CMP-040): no message and no aria-invalid while gated.
  const message = reason.gated ? undefined : (reported ?? error);
  const invalid = message !== undefined && message !== "";
  // Error then help; while T2 the reason id alone (D02F CMP-040 a11y table, D09 §9.2); the help line stays visible.
  const describedBy = reason.gated ? reason.ariaDescribedBy : cx(errorId, hasHelp && helpId);

  const reportInvalid = section?.reportInvalid;
  useLayoutEffect(() => {
    if (reportInvalid === undefined) return undefined;
    reportInvalid(controlId, invalid);
    return () => reportInvalid(controlId, false);
  }, [reportInvalid, controlId, invalid]);

  const context = useMemo<FieldContextValue>(
    () => ({
      controlId,
      labelId: nameId,
      describedBy,
      invalid,
      required,
      reason,
      report: setReported,
      labelledBy: setLabelledBy,
    }),
    [controlId, nameId, describedBy, invalid, required, reason],
  );

  /** A label press focuses a control that `<label for>` cannot (an `aria-labelledby` child). */
  const focusControl = (event: MouseEvent<HTMLLabelElement>): void => {
    const target = event.currentTarget.ownerDocument.getElementById(controlId);
    if (target === null || target.matches(LABELABLE)) return;
    event.preventDefault();
    target.focus();
  };

  const style =
    layout === "inline" && labelWidth !== undefined
      ? ({ "--cv-formfield-label-width": labelWidth } as CSSProperties)
      : undefined;

  return (
    <div
      className="cv-formfield"
      data-cmp="CMP-040"
      data-layout={layout}
      data-density={density}
      data-disabled={reason.disabled ? "" : undefined}
      style={style}
    >
      {/* The label is not a widget: a press only forwards focus to the control, which is the keyboard target. */}
      {/* eslint-disable-next-line jsx-a11y/click-events-have-key-events, jsx-a11y/no-noninteractive-element-interactions -- see above */}
      <label
        id={nameId}
        htmlFor={labelledBy ? undefined : controlId}
        className="cv-formfield__label"
        onClick={focusControl}
      >
        {label}
        {optional ? " " : null}
        {optional ? <span className="cv-formfield__optional">(optional)</span> : null}
      </label>
      <div className="cv-formfield__body">
        <FieldContext.Provider value={context}>{children}</FieldContext.Provider>
        {reason.gated && !fromSection && !reason.fromNotice ? (
          <div id={reason.reasonId} className="cv-formfield__line">
            {reason.reason}
          </div>
        ) : null}
        <FieldMessage id={errorId} message={message} />
        {hasHelp ? (
          <div id={helpId} className="cv-formfield__line">
            {help}
          </div>
        ) : null}
      </div>
    </div>
  );
}

import { createContext, useContext, useLayoutEffect } from "react";
import { useDisabledReason, type DisabledReasonAttrs } from "./disabledReason.js";
import { cx } from "./cx.js";

/**
 * What CMP-040 FormField hands its one control (D02F CMP-040, G10, conventions 23-24). Internal: the field atoms
 * (TextInput, Select, NumericStepperInput) read it, so the label, the description chain and the lines are wired
 * once, by the field, and each line renders once.
 */
export interface FieldContextValue {
  /** The control's id: `<label for>` points at it, and a label press focuses it. */
  readonly controlId: string;
  /** The label's id: the name of a control that is not natively labelable (`aria-labelledby`). */
  readonly labelId: string;
  /** The field's part of `aria-describedby`: the reason alone while T2, else the error then the help. */
  readonly describedBy: string | undefined;
  /** The field has an error to show (never while T2: a gated field never validates). */
  readonly invalid: boolean;
  readonly required: boolean;
  /** The field's own gate: T2 with its reason line, or plain disabled. */
  readonly reason: DisabledReasonAttrs;
  /** A control's own message (a stepper's parse error, an atom's `errorMessage`), shown in the field's line. */
  readonly report: (message: string | undefined) => void;
  /** A control that is not natively labelable takes `aria-labelledby`; the label then drops `for`. */
  readonly labelledBy: (yes: boolean) => void;
}

export const FieldContext = createContext<FieldContextValue | null>(null);

export interface FieldControl {
  /** Null outside a FormField: the atom keeps its own lines. */
  readonly field: FieldContextValue | null;
  /** The gate in force: the field's when it sets one, else the control's own. */
  readonly reason: DisabledReasonAttrs;
  /** The reason line is the field's: the atom renders no reason node and no echo of its own. */
  readonly reasonFromField: boolean;
  /** The atom draws its own message line (outside a field). */
  readonly ownLines: boolean;
  readonly invalid: boolean;
  /** Joins the field's ids before the atom's own (error, help, then the caller's and the unit's). */
  readonly describe: (
    ...own: ReadonlyArray<string | false | null | undefined>
  ) => string | undefined;
  readonly required: true | undefined;
}

/**
 * The control side of the field contract. `message` is the control's own sentence while it is invalid; inside a
 * field it goes to the field's one line instead of the atom's.
 */
export function useFieldControl(
  disabled: boolean | undefined,
  disabledReason: string | undefined,
  invalid: boolean,
  message: string | undefined,
  options: { readonly labelable: boolean } = { labelable: true },
): FieldControl {
  const field = useContext(FieldContext);
  const own = useDisabledReason(disabled, disabledReason);
  const fromField = field !== null && (field.reason.gated || field.reason.disabled);
  const reason = fromField ? field.reason : own;
  const shown =
    invalid && !reason.gated && message !== undefined && message !== "" ? message : undefined;
  const report = field?.report;
  const labelledBy = field?.labelledBy;
  const { labelable } = options;

  useLayoutEffect(() => {
    if (report === undefined) return undefined;
    report(shown);
    return () => report(undefined);
  }, [report, shown]);

  useLayoutEffect(() => {
    if (labelledBy === undefined || labelable) return undefined;
    labelledBy(true);
    return () => labelledBy(false);
  }, [labelledBy, labelable]);

  return {
    field,
    reason,
    reasonFromField: fromField,
    ownLines: field === null,
    // Outside a field the atom's own verdict stands as it always has; inside one a T2 field never validates.
    invalid: field === null ? invalid : !reason.gated && (invalid || field.invalid),
    describe: (...own) =>
      reason.gated ? reason.ariaDescribedBy : cx(field?.describedBy, ...own) || undefined,
    required: field?.required === true ? true : undefined,
  };
}

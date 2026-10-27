import { useEffect, useId, useRef, type ComponentPropsWithoutRef, type JSX } from "react";
import { Icon } from "../icons/Icon.js";
import { ChoiceRow } from "./internal/ChoiceRow.js";
import { cx } from "./internal/cx.js";
import { useDisabledReason } from "./internal/disabledReason.js";
import { useControllable } from "./internal/useControllable.js";

export interface CheckboxProps extends Omit<
  ComponentPropsWithoutRef<"input">,
  | "className"
  | "style"
  | "type"
  | "disabled"
  | "children"
  | "aria-disabled"
  | "aria-checked"
  | "onChange"
  | "checked"
  | "defaultChecked"
> {
  /** The visible label; it is part of the click target. */
  label: string;
  checked?: boolean;
  defaultChecked?: boolean;
  /** Shows the `minus` glyph and the DOM `indeterminate` state (mixed); the next activation emits `onChange(true)`. */
  indeterminate?: boolean;
  onChange?: (checked: boolean) => void;
  disabled?: boolean;
  /** The visible reason a control is denied (RBAC, environment, risk): disabled-with-reason (T2). */
  disabledReason?: string;
  /** Emits `data-density` so `theme.css` re-points the row height; absent = inherit. */
  density?: "comfortable" | "compact";
}

/** CMP-005: a native checkbox whose box and glyph are drawn by CSS and the registry Icon. */
export function Checkbox({
  label,
  checked: controlled,
  defaultChecked = false,
  indeterminate = false,
  onChange,
  disabled,
  disabledReason,
  density,
  id,
  "aria-describedby": describedBy,
  ...rest
}: CheckboxProps): JSX.Element {
  const generated = useId();
  const controlId = id ?? generated;
  const reason = useDisabledReason(disabled, disabledReason);
  const [checked, setChecked] = useControllable(controlled, defaultChecked);
  const ref = useRef<HTMLInputElement>(null);
  // Every render: a prop change must reach the DOM property. The change handler re-asserts it too, because a
  // native click clears it and some clicks (gated, or a value React already holds) cause no render.
  useEffect(() => {
    // The ref is always set when an effect runs.
    ref.current!.indeterminate = indeterminate;
  });
  const box = (
    <span
      className="cv-checkbox"
      data-state={indeterminate ? "mixed" : checked ? "checked" : "unchecked"}
    >
      <input
        {...rest}
        ref={ref}
        id={controlId}
        type="checkbox"
        className="cv-checkbox__input"
        checked={checked}
        aria-describedby={cx(describedBy, reason.ariaDescribedBy) || undefined}
        aria-disabled={reason.ariaDisabled}
        disabled={reason.disabled}
        onChange={(e) => {
          e.currentTarget.indeterminate = indeterminate;
          // Controlled by `checked`: React restores the box after a no-op change, so a gated box keeps its value.
          if (reason.gated) return;
          const next = indeterminate ? true : !checked;
          setChecked(next);
          onChange?.(next);
        }}
      />
      <span className="cv-checkbox__plate" aria-hidden="true" />
      {checked || indeterminate ? (
        <span className="cv-checkbox__glyph">
          <Icon name={indeterminate ? "minus" : "check"} />
        </span>
      ) : null}
    </span>
  );
  return (
    <ChoiceRow
      cmp="CMP-005"
      control={box}
      controlId={controlId}
      label={label}
      reason={reason}
      disabled={disabled}
      density={density}
    />
  );
}

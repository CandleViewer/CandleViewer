import { useId, type ComponentPropsWithoutRef, type JSX } from "react";
import { Icon } from "../icons/Icon.js";
import { ChoiceRow } from "./internal/ChoiceRow.js";
import { cx } from "./internal/cx.js";
import { useDisabledReason } from "./internal/disabledReason.js";
import { useControllable } from "./internal/useControllable.js";

export interface ToggleProps extends Omit<
  ComponentPropsWithoutRef<"button">,
  | "className"
  | "style"
  | "disabled"
  | "children"
  | "aria-disabled"
  | "aria-checked"
  | "aria-label"
  | "aria-labelledby"
  | "role"
  | "onChange"
  | "onClick"
  | "defaultChecked"
> {
  /** The switch's name: visible beside the track, or `aria-label` when `labelPosition` is hidden. */
  label: string;
  labelPosition?: "left" | "right" | "hidden";
  checked?: boolean;
  defaultChecked?: boolean;
  /** Emits the opposite value; a critical switch only emits, the confirm wrapper (CMP-044) is the consumer's. */
  onChange?: (checked: boolean) => void;
  disabled?: boolean;
  /** The visible reason a control is denied (RBAC, environment, risk): disabled-with-reason (T2). */
  disabledReason?: string;
  /** Stronger weight: a leading `warning` glyph and a bold label (D02 D4, proposed). */
  critical?: boolean;
  /** Emits `data-density` so `theme.css` re-points the row height; absent = inherit. */
  density?: "comfortable" | "compact";
}

/** CMP-004: a binary on/off switch (`role="switch"`); Space and Enter toggle. `size` is dropped (D02 C3). */
export function Toggle({
  label,
  labelPosition = "right",
  checked: controlled,
  defaultChecked = false,
  onChange,
  disabled,
  disabledReason,
  critical = false,
  density,
  id,
  "aria-describedby": describedBy,
  ...rest
}: ToggleProps): JSX.Element {
  const generated = useId();
  const controlId = id ?? generated;
  const reason = useDisabledReason(disabled, disabledReason);
  const [checked, setChecked] = useControllable(controlled, defaultChecked);
  const hidden = labelPosition === "hidden";
  const track = (
    <button
      {...rest}
      id={controlId}
      type="button"
      role="switch"
      className="cv-switch"
      data-checked={checked ? "" : undefined}
      aria-checked={checked}
      aria-label={hidden ? label : undefined}
      aria-describedby={cx(describedBy, reason.ariaDescribedBy) || undefined}
      aria-disabled={reason.ariaDisabled}
      disabled={reason.disabled}
      onClick={() => {
        // Enter and Space arrive as clicks: a gated switch stays focusable but changes nothing.
        if (reason.gated) return;
        setChecked(!checked);
        onChange?.(!checked);
      }}
    >
      <span className="cv-switch__knob" />
    </button>
  );
  return (
    <ChoiceRow
      cmp="CMP-004"
      control={track}
      controlId={controlId}
      label={hidden ? undefined : label}
      labelPosition={hidden ? undefined : labelPosition}
      lead={critical ? <Icon name="warning" /> : undefined}
      reason={reason}
      disabled={disabled}
      density={density}
      critical={critical}
    />
  );
}

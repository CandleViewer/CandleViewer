import type { JSX, ReactNode } from "react";
import { Icon } from "../../icons/Icon.js";
import { ReasonText, type DisabledReasonAttrs } from "./disabledReason.js";

export interface ChoiceRowProps {
  readonly cmp: string;
  /** The control (switch track or checkbox box); the row owns label, lock and reason. */
  readonly control: ReactNode;
  readonly controlId: string;
  /** Visible label; omit when the control carries its own `aria-label`. */
  readonly label?: string | undefined;
  readonly labelPosition?: "left" | "right" | undefined;
  /** Decorative node leading the label (the critical `warning` glyph). */
  readonly lead?: ReactNode | undefined;
  readonly reason: DisabledReasonAttrs;
  readonly disabled: boolean | undefined;
  readonly density: "comfortable" | "compact" | undefined;
  readonly critical?: boolean | undefined;
}

/**
 * Shared by CMP-004 and CMP-005: label (part of the target), control, trailing lock (T2) and reason text. With the
 * reason's node the host's (2a, `reason.external`), the lock leads the label instead, named "Not available", and
 * no reason text renders here.
 */
export function ChoiceRow({
  cmp,
  control,
  controlId,
  label,
  labelPosition = "right",
  lead,
  reason,
  disabled,
  density,
  critical,
}: ChoiceRowProps): JSX.Element {
  const namedLock = reason.external ? (
    <span className="cv-choice__lock">
      <Icon name="lock" decorative={false} label="Not available" />
    </span>
  ) : null;
  const labelNode =
    label === undefined ? null : (
      <span className="cv-choice__label">
        {namedLock}
        {lead}
        {label}
      </span>
    );
  // No visible label (an aria-label control): the cell itself is the target, so no empty <label> is emitted.
  const Target = label === undefined ? "span" : "label";
  return (
    <div
      className="cv-choice"
      data-cmp={cmp}
      data-density={density}
      data-gated={reason.gated ? "" : undefined}
      data-disabled={reason.disabled || (disabled === true && !reason.gated) ? "" : undefined}
      data-critical={critical === true ? "" : undefined}
    >
      {/* One wrapping label: the ring, the gap and the label text all activate the control. */}
      <Target
        className="cv-choice__target"
        {...(label === undefined ? {} : { htmlFor: controlId })}
      >
        {labelPosition === "left" ? labelNode : null}
        <span className="cv-choice__control">{control}</span>
        {labelPosition === "right" ? labelNode : null}
      </Target>
      {reason.gated && !reason.external ? (
        <span className="cv-choice__lock">
          <Icon name="lock" />
        </span>
      ) : null}
      {/* Without a visible label the named lock trails the control (it never leads an `aria-label`). */}
      {label === undefined ? namedLock : null}
      {reason.external ? null : <ReasonText id={reason.reasonId}>{reason.reason}</ReasonText>}
    </div>
  );
}

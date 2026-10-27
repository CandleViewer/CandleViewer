import type { ComponentPropsWithoutRef, JSX, MouseEvent, ReactNode } from "react";
import { GatedGlyph } from "./internal/GatedGlyph.js";
import { ReasonText, useDisabledReason } from "./internal/disabledReason.js";
import { cx } from "./internal/cx.js";

export interface ButtonProps extends Omit<
  ComponentPropsWithoutRef<"button">,
  "className" | "style" | "disabled" | "children" | "aria-disabled"
> {
  /** Buy and sell arrive with the icon registry (#271). */
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md" | "lg";
  children: ReactNode;
  loading?: boolean;
  disabled?: boolean;
  /** The visible reason a control is denied (RBAC, environment, risk): disabled-with-reason (T2). */
  disabledReason?: string;
  fullWidth?: boolean;
  /** Emits `data-density` so `theme.css` re-points the control height; absent = inherit. */
  density?: "comfortable" | "compact";
}

/** CMP-001: the primary interactive trigger. Danger only emits `onClick`; the confirm wrapper is CMP-044. */
export function Button({
  variant = "secondary",
  size = "md",
  children,
  loading = false,
  disabled,
  disabledReason,
  fullWidth = false,
  density,
  onClick,
  type = "button",
  "aria-describedby": describedBy,
  ...rest
}: ButtonProps): JSX.Element {
  const reason = useDisabledReason(disabled, disabledReason);
  const handleClick = (event: MouseEvent<HTMLButtonElement>): void => {
    // Enter and Space reach here as clicks: a gated or busy button stays focusable but does nothing.
    if (reason.gated || loading) {
      event.preventDefault();
      return;
    }
    onClick?.(event);
  };
  return (
    <>
      <button
        {...rest}
        type={type}
        className={cx("cv-control", "cv-button")}
        data-cmp="CMP-001"
        data-variant={variant}
        data-size={size}
        data-density={density}
        data-full-width={fullWidth ? "" : undefined}
        data-gated={reason.gated ? "" : undefined}
        disabled={reason.disabled}
        aria-disabled={reason.ariaDisabled}
        aria-busy={loading ? true : undefined}
        aria-describedby={cx(describedBy, reason.ariaDescribedBy) || undefined}
        onClick={handleClick}
      >
        <span className="cv-button__label">{children}</span>
        {loading ? <span className="cv-spinner" aria-hidden="true" /> : null}
        {reason.gated ? <GatedGlyph className="cv-button__glyph" /> : null}
      </button>
      <ReasonText id={reason.reasonId}>{reason.reason}</ReasonText>
    </>
  );
}

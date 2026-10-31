import type { ComponentPropsWithoutRef, JSX, MouseEvent, ReactNode } from "react";
import { Icon } from "../icons/Icon.js";
import type { IconName } from "../icons/registry.js";
import { ReasonText, useDisabledReason, useGatedAnnounce } from "./internal/disabledReason.js";
import { ReasonEcho } from "./internal/ReasonEcho.js";
import { cx } from "./internal/cx.js";
import { useFocusRing } from "./FocusRing.js";
import { Spinner } from "./Spinner.js";

export interface ButtonProps extends Omit<
  ComponentPropsWithoutRef<"button">,
  "className" | "style" | "disabled" | "children" | "aria-disabled"
> {
  /** Buy and sell keep their word and lead with an arrow (05 §4.1): colour is never the only signal. */
  variant?: "primary" | "secondary" | "ghost" | "danger" | "buy" | "sell";
  /** A decorative glyph before the label. Buy and sell default to `arrow-up` / `arrow-down`, never none. */
  iconLeft?: IconName;
  /** A decorative glyph after the label; a gated button shows its lock in this slot instead. */
  iconRight?: IconName;
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
  iconLeft,
  iconRight,
  onClick,
  type = "button",
  "aria-describedby": describedBy,
  ...rest
}: ButtonProps): JSX.Element {
  const reason = useDisabledReason(disabled, disabledReason);
  const announceGated = useGatedAnnounce();
  const ring = useFocusRing();
  const side = variant === "buy" || variant === "sell";
  const leading =
    iconLeft ?? (variant === "buy" ? "arrow-up" : variant === "sell" ? "arrow-down" : undefined);
  // Buy and sell keep the label visible while busy, so their spinner sits in the trailing slot (D1).
  const inlineSpinner = loading && side;
  const handleClick = (event: MouseEvent<HTMLButtonElement>): void => {
    // Enter and Space reach here as clicks: a gated or busy button stays focusable but does nothing.
    if (reason.gated || loading) {
      event.preventDefault();
      if (reason.gated) announceGated(reason.reason);
      return;
    }
    onClick?.(event);
  };
  return (
    <>
      <ReasonEcho text={reason.reason}>
        <button
          {...rest}
          type={type}
          className={cx("cv-control", ring.className, "cv-button")}
          data-cmp="CMP-001"
          data-variant={variant}
          data-size={size}
          data-density={density}
          data-side={side ? "" : undefined}
          data-full-width={fullWidth ? "" : undefined}
          data-gated={reason.gated ? "" : undefined}
          disabled={reason.disabled}
          aria-disabled={reason.ariaDisabled}
          aria-busy={loading ? true : undefined}
          aria-describedby={cx(describedBy, reason.ariaDescribedBy) || undefined}
          onClick={handleClick}
        >
          {leading === undefined ? null : (
            <span className="cv-button__icon">
              <Icon name={leading} />
            </span>
          )}
          <span className="cv-button__label">{children}</span>
          {iconRight === undefined || reason.gated || inlineSpinner ? null : (
            <span className="cv-button__icon">
              <Icon name={iconRight} />
            </span>
          )}
          {loading ? <Spinner size="sm" /> : null}
          {reason.gated ? (
            <span className="cv-button__glyph">
              <Icon name="lock" />
            </span>
          ) : null}
        </button>
      </ReasonEcho>
      <ReasonText id={reason.reasonId}>{reason.reason}</ReasonText>
    </>
  );
}

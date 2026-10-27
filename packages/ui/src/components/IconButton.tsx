import type { ComponentPropsWithoutRef, JSX, MouseEvent } from "react";
import { Icon, type IconSizeFor } from "../icons/Icon.js";
import type { IconName } from "../icons/registry.js";
import { ReasonText, useDisabledReason } from "./internal/disabledReason.js";
import { cx } from "./internal/cx.js";
import { useFocusRing } from "./FocusRing.js";

interface IconButtonBase<N extends IconName> extends Omit<
  ComponentPropsWithoutRef<"button">,
  "className" | "style" | "disabled" | "children" | "aria-disabled" | "aria-label" | "aria-pressed"
> {
  icon: N;
  /** The accessible name (`aria-label`): required, because an icon-only control has no visible text. */
  label: string;
  /** The glyph's optical size: md or lg only for a "16 px minimum" glyph (`IconSizeFor`). */
  size?: IconSizeFor<N>;
  disabled?: boolean;
  /** The visible reason a control is denied (RBAC, environment, risk): disabled-with-reason (T2). */
  disabledReason?: string;
  /** Emits `data-density` so `theme.css` re-points the control height; absent = inherit. */
  density?: "comfortable" | "compact";
}

/** Toggle mode (`pressed`) exists on secondary and ghost only: a pressed primary or danger reads as another variant. */
export type IconButtonProps<N extends IconName = IconName> = IconButtonBase<N> &
  (
    | { variant?: "secondary" | "ghost"; pressed?: boolean }
    | { variant: "primary" | "danger"; pressed?: never }
  );

/**
 * CMP-002: an icon-only trigger. No buy or sell (the word cannot fit); danger only emits `onClick`, the
 * confirm wrapper is CMP-044. The reason echo on hover and focus is CMP-016's; until it lands the reason is
 * the accessible description. The name tooltip for sighted mouse users (D10) is CMP-016's too.
 */
export function IconButton<N extends IconName>({
  icon,
  label,
  variant = "secondary",
  size = "md",
  pressed,
  disabled,
  disabledReason,
  density,
  onClick,
  type = "button",
  "aria-describedby": describedBy,
  ...rest
}: IconButtonProps<N>): JSX.Element {
  const reason = useDisabledReason(disabled, disabledReason);
  const ring = useFocusRing();
  const handleClick = (event: MouseEvent<HTMLButtonElement>): void => {
    // Enter and Space reach here as clicks: a gated button stays focusable but does nothing.
    if (reason.gated) {
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
        className={cx("cv-control", ring.className, "cv-icon-button")}
        data-cmp="CMP-002"
        data-variant={variant}
        data-size={size}
        data-density={density}
        data-gated={reason.gated ? "" : undefined}
        disabled={reason.disabled}
        aria-label={label}
        aria-pressed={pressed}
        aria-disabled={reason.ariaDisabled}
        aria-describedby={cx(describedBy, reason.ariaDescribedBy) || undefined}
        onClick={handleClick}
      >
        <Icon name={icon} size={size} />
        {reason.gated ? (
          <span className="cv-icon-button__badge">
            <Icon name="lock" size="sm" />
          </span>
        ) : null}
      </button>
      <ReasonText id={reason.reasonId}>{reason.reason}</ReasonText>
    </>
  );
}

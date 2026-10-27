import type { ComponentPropsWithoutRef, JSX, MouseEvent } from "react";
import { Icon, type IconSizeFor } from "../icons/Icon.js";
import type { IconName } from "../icons/registry.js";
import { ReasonText, useDisabledReason } from "./internal/disabledReason.js";
import { ReasonEcho } from "./internal/ReasonEcho.js";
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
 * confirm wrapper is CMP-044. A CMP-016 echo shows the name on hover and keyboard focus (D10), and on a gated
 * button the name, then the reason (one tooltip). It is `aria-hidden`: the name stays the `aria-label` and the reason
 * the accessible description. Plain disabled cannot take focus, so it has none.
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
  // `reason.reason` is set exactly when gated: the name, then the reason, joined by " · ".
  const echo = reason.disabled
    ? undefined
    : reason.reason === undefined
      ? label
      : `${label} · ${reason.reason}`;
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
      <ReasonEcho text={echo}>
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
      </ReasonEcho>
      <ReasonText id={reason.reasonId}>{reason.reason}</ReasonText>
    </>
  );
}

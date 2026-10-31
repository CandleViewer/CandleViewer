import type { ComponentPropsWithoutRef, JSX, KeyboardEvent, MouseEvent } from "react";
import { Icon, type IconSizeFor } from "../icons/Icon.js";
import type { IconName } from "../icons/registry.js";
import { ReasonText, useDisabledReason, useGatedAnnounce } from "./internal/disabledReason.js";
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
  /**
   * The id of the node in which the host already shows `disabledReason` (E09-D09 §2.2 "one notice, many pointers":
   * a read-only panel's notice): the button is described by it and renders no hidden copy; the lock badge and the
   * echo stay (2b).
   */
  disabledReasonId?: string;
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
  disabledReasonId,
  density,
  onClick,
  onKeyDown,
  type = "button",
  "aria-describedby": describedBy,
  ...rest
}: IconButtonProps<N>): JSX.Element {
  const reason = useDisabledReason(disabled, disabledReason, disabledReasonId);
  const announceGated = useGatedAnnounce();
  const ring = useFocusRing();
  // `reason.reason` is set exactly when gated: the name, then the reason, joined by " · "; under a gate notice the
  // notice carries the reason, so the echo is the name alone.
  const echo = reason.disabled
    ? undefined
    : reason.reason === undefined || reason.fromNotice
      ? label
      : `${label} · ${reason.reason}`;
  const handleClick = (event: MouseEvent<HTMLButtonElement>): void => {
    // Enter and Space reach here as clicks: a gated button stays focusable but does nothing.
    if (reason.gated) {
      event.preventDefault();
      announceGated(reason.reason);
      return;
    }
    onClick?.(event);
  };
  // A held Enter repeats its keydown, and each repeat clicks a native button: a gated one swallows the repeats, so
  // its reason is said once per press (E09-D09 §9.3), never once per repeat. The caller's handler sees every key.
  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>): void => {
    onKeyDown?.(event);
    if (reason.gated && event.key === "Enter" && event.repeat) event.preventDefault();
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
          onKeyDown={handleKeyDown}
        >
          <Icon name={icon} size={size} />
          {reason.gated ? (
            <span className="cv-icon-button__badge">
              {/* E05-D02 CMP-079 a11y: the badge is CMP-019 `decorative=false`, an img named "Not available". */}
              <Icon name="lock" size="sm" decorative={false} label="Not available" />
            </span>
          ) : null}
        </button>
      </ReasonEcho>
      {reason.external ? null : <ReasonText id={reason.reasonId}>{reason.reason}</ReasonText>}
    </>
  );
}

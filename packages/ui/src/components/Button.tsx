import type { ComponentPropsWithoutRef, JSX, KeyboardEvent, MouseEvent, ReactNode } from "react";
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
  /**
   * The id of the node in which the host already shows `disabledReason` (E09-D09 §2.2 rendering 2a: a caption under
   * the button, or a read-only panel's one notice): the button is described by it alone and renders no copy and no
   * echo of its own, and its lock leads the label, named "Not available" (E09-D09 §10 `glyph.name`).
   */
  disabledReasonId?: string;
  /**
   * Form validity, the validity look (E09-D09 §9.1: the host decides; E16-D04 §1.3): the button stays a Tab stop
   * with `aria-disabled`, its fill and label at `opacity.disabled` and no lock, described by the host's reason node
   * with this id (the reason at full opacity under or beside it). A press does nothing and says nothing here: the
   * host answers it. Never T2: a `disabledReason`, or native `disabled`, wins.
   */
  unavailableReasonId?: string;
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
  disabledReasonId,
  unavailableReasonId,
  fullWidth = false,
  density,
  iconLeft,
  iconRight,
  onClick,
  onKeyDown,
  type = "button",
  "aria-describedby": describedBy,
  ...rest
}: ButtonProps): JSX.Element {
  const reason = useDisabledReason(disabled, disabledReason, disabledReasonId);
  const announceGated = useGatedAnnounce();
  // 2a with the host's reason node: the lock leads the label, named; no copy and no echo here.
  const inline = reason.external;
  // The validity look: only when neither T2 nor native disabled applies.
  const unavailableId = unavailableReasonId?.trim() || undefined;
  const unavailable = unavailableId !== undefined && !reason.gated && !reason.disabled;
  const ring = useFocusRing();
  const side = variant === "buy" || variant === "sell";
  const leading =
    iconLeft ?? (variant === "buy" ? "arrow-up" : variant === "sell" ? "arrow-down" : undefined);
  // Buy and sell keep the label visible while busy, so their spinner sits in the trailing slot (D1).
  const inlineSpinner = loading && side;
  const handleClick = (event: MouseEvent<HTMLButtonElement>): void => {
    // Enter and Space reach here as clicks: a gated, busy or unavailable button stays focusable but does nothing.
    if (reason.gated || loading || unavailable) {
      event.preventDefault();
      if (reason.gated) announceGated(reason.reason);
      return;
    }
    onClick?.(event);
  };
  // A held Enter repeats its keydown, and each repeat clicks a native button: a gated one swallows the repeats, so
  // its reason is said once per press (E09-D09 §9.3), never once per repeat. The caller's handler sees every key.
  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>): void => {
    onKeyDown?.(event);
    if ((reason.gated || unavailable) && event.key === "Enter" && event.repeat)
      event.preventDefault();
  };
  return (
    <>
      <ReasonEcho text={inline ? undefined : reason.reason}>
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
          data-unavailable={unavailable ? "" : undefined}
          disabled={reason.disabled}
          aria-disabled={reason.ariaDisabled ?? (unavailable ? true : undefined)}
          aria-busy={loading ? true : undefined}
          aria-describedby={
            cx(describedBy, reason.ariaDescribedBy, unavailable && unavailableId) || undefined
          }
          onClick={handleClick}
          onKeyDown={handleKeyDown}
        >
          {inline ? (
            <span className="cv-button__glyph">
              <Icon name="lock" decorative={false} label="Not available" />
            </span>
          ) : null}
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
          {reason.gated && !inline ? (
            <span className="cv-button__glyph">
              <Icon name="lock" />
            </span>
          ) : null}
        </button>
      </ReasonEcho>
      {inline ? null : <ReasonText id={reason.reasonId}>{reason.reason}</ReasonText>}
    </>
  );
}

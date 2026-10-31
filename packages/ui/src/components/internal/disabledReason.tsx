import { useId, type JSX } from "react";
import { announcePolite } from "../../theme/a11y.js";

export interface DisabledReasonAttrs {
  /** True when a non-empty reason is given: the control is gated (T2), not natively disabled. */
  readonly gated: boolean;
  /** Native `disabled`: only for a plain disabled control, so a gated one stays focusable. */
  readonly disabled: boolean;
  readonly reasonId: string;
  readonly reason: string | undefined;
  readonly ariaDisabled: true | undefined;
  readonly ariaDescribedBy: string | undefined;
}

/** The T2 contract (D02 conv. 3, D09 2.2): a reason wins over `disabled`; `aria-disabled`, never `disabled`. */
export function useDisabledReason(
  disabled: boolean | undefined,
  disabledReason: string | undefined,
): DisabledReasonAttrs {
  const reasonId = useId();
  // Whitespace-only is no reason: a sighted user would see nothing, a screen reader a blank description.
  const trimmed = disabledReason?.trim();
  const gated = trimmed !== undefined && trimmed !== "";
  return {
    gated,
    disabled: disabled === true && !gated,
    reasonId,
    reason: gated ? trimmed : undefined,
    ariaDisabled: gated ? true : undefined,
    ariaDescribedBy: gated ? reasonId : undefined,
  };
}

/**
 * D09 2.2: a refused activation re-shows the reason with one polite announcement. The region is cleared, then set
 * in a microtask: an unchanged sentence would not announce again on a repeat press, and a microtask (unlike a
 * frame) runs deterministically under fake timers.
 */
export function announceGatedReason(reason: string | undefined): void {
  if (reason === undefined) return;
  announcePolite("");
  queueMicrotask(() => announcePolite(reason));
}

/**
 * The reason as a plain text node, in the DOM at mount and visually hidden; nothing renders without one. It is the
 * accessible description; `ReasonEcho` shows a sighted user the same text on hover and focus.
 */
export function ReasonText({
  id,
  children,
}: {
  readonly id: string;
  readonly children: string | undefined;
}): JSX.Element | null {
  if (children === undefined) return null;
  return (
    <span id={id} className="cv-visually-hidden">
      {children}
    </span>
  );
}

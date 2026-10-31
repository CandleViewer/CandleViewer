import type { JSX, ReactElement } from "react";
import { useGateNoticeFor } from "./disabledReason.js";
import { Tooltip, type TooltipTriggerProps } from "../Tooltip.js";

/**
 * The T2 reason echo (E09-D09 §2.2 2b, §9.2; D02 slice 4 H10): a CMP-016 `mode="echo"` over a gated control, so a
 * sighted user sees the reason on hover and on keyboard focus. The reason node from `useDisabledReason` stays the
 * accessible description; the echo is `aria-hidden`, never read twice, and `Esc` hides it with focus kept.
 * Without text (not gated) it renders no node, and the control's tree stays the same, so a gate that comes and goes
 * never remounts the control or drops its focus. `children` is the one focusable element. Under a CMP-079 gate notice
 * carrying the same sentence the echo stays empty: the sentence shows once, in the notice.
 */
export function ReasonEcho({
  text,
  children,
}: {
  readonly text: string | undefined;
  readonly children: ReactElement<TooltipTriggerProps>;
}): JSX.Element {
  const noticed = useGateNoticeFor(text) !== undefined;
  return (
    <Tooltip content={noticed ? "" : (text ?? "")} mode="echo">
      {children}
    </Tooltip>
  );
}

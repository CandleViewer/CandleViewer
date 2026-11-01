/**
 * Apply's validity look (E09-D09 §9.1; E16-D03 §1.3; E16-D06 T2-07): a control disabled by form validity stays a
 * Tab stop, described by its reason at full opacity, and a press answers with the error summary, never the action.
 *
 * The seam for #484 PR 3's CMP-001 `unavailableReasonId` (the dimmed fill and label, `aria-disabled`; BQ-7): until
 * that lands, the button keeps CMP-001's enabled look, its description is the reason node and `onRefused` answers a
 * press. Swap in the prop here, once, when it lands. T2 is not this: a `disabledReason` (the view-as leg, first on
 * every write) wins, and CMP-001 then refuses the press itself and says its reason once (E09-D09 §9.3).
 */
import type { JSX, ReactNode } from "react";
import { Button } from "@candleviewer/ui";

export interface ValidityButtonProps {
  readonly children: ReactNode;
  readonly variant?: "primary" | "secondary";
  /** The validity reason's node (the caption under the button); its words say why. */
  readonly reasonId: string;
  /** Set while the form is not ready: the press calls `onRefused`. */
  readonly reason: string | undefined;
  readonly onPress: () => void;
  readonly onRefused: () => void;
  /** T2 (the view-as leg) and the one panel notice it points at. */
  readonly disabledReason?: string | undefined;
  readonly disabledReasonId?: string | undefined;
  readonly loading?: boolean;
}

export function ValidityButton({
  children,
  variant = "primary",
  reasonId,
  reason,
  onPress,
  onRefused,
  disabledReason,
  disabledReasonId,
  loading = false,
}: ValidityButtonProps): JSX.Element {
  const gated = disabledReason !== undefined && disabledReason !== "";
  return (
    <Button
      variant={variant}
      loading={loading}
      {...(gated
        ? {
            disabledReason,
            ...(disabledReasonId === undefined ? {} : { disabledReasonId }),
          }
        : reason === undefined
          ? {}
          : { "aria-describedby": reasonId })}
      data-validity={!gated && reason !== undefined ? "" : undefined}
      onClick={() => (reason === undefined ? onPress() : onRefused())}
    >
      {children}
    </Button>
  );
}

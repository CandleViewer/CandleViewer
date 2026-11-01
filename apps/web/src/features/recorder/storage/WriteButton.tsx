/**
 * A write on SCR-142 (E16-D04 §1.3, §9; E16-D06 T2-08, T2-09, T2-11; G-T2.1–G-T2.5): CMP-001 that is T2 while the
 * Owner views as another user, through CMP-079 with `rbac.view_as` (the view-as leg first, E09-D09 §2.1 step 3): it
 * keeps its role and full label with the lock leading it, `aria-disabled` (never `disabled`), described by the one
 * panel notice and no reason line of its own; a press re-shows the reason once and does nothing. While its job runs
 * it is CMP-001 `loading` (busy, never T2). A refusal sits under it as CMP-027 at the point of action (T4).
 */
import type { JSX } from "react";
import { Button, InlineError, RbacGate, type ButtonProps } from "@candleviewer/ui";
import type { Refused } from "./useStorageJob";

/** The view-as leg as a write's T2 needs it: the target (`rbac.view_as`'s `{user}`) and the one notice's id. */
export interface WriteGate {
  readonly user: string;
  readonly noticeId: string;
}

export interface WriteButtonProps extends Omit<ButtonProps, "disabledReason" | "disabledReasonId"> {
  /** The view-as leg, when the Owner views as another user. */
  readonly gate: WriteGate | null;
  /** This control's name for a refusal: the words show under the control that was pressed. */
  readonly at?: string | undefined;
  readonly refusal?: Refused | null | undefined;
}

export function WriteButton({ gate, at, refusal, ...button }: WriteButtonProps): JSX.Element {
  const control = (
    <Button {...button} {...(gate === null ? {} : { disabledReasonId: gate.noticeId })} />
  );
  const shown = refusal !== null && refusal !== undefined && refusal.at === at;
  return (
    <span style={{ display: "inline-grid", justifyItems: "start", gap: "var(--space-stack-xs)" }}>
      {gate === null ? (
        control
      ) : (
        <RbacGate allowed={false} reason="rbac.view_as" fills={{ user: gate.user }}>
          {control}
        </RbacGate>
      )}
      {shown ? <InlineError message={refusal.text} live="off" /> : null}
    </span>
  );
}

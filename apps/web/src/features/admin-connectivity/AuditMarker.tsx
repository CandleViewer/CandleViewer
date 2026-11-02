import type { JSX } from "react";
import { COPY } from "./copy";

/** The two audited actions of SCR-147 (E08-D09 §20.1). */
export type AuditAction = "reconnect" | "budget";

const MARKER = { reconnect: COPY["W-55"], budget: COPY["W-63"] } as const;

/**
 * CMP-093's marker, label only (E08-S12 BQ-4): "Recorded in the audit log · Reconnect forced (pending
 * registration)". While the audit registry lists no code, a marker never names one (E42-D02 D5; D09-G7, G8), so
 * this prints the label and no code. `id` lets the wrapped control's `aria-describedby` point at it.
 */
export function AuditMarker({
  action,
  id,
}: {
  readonly action: AuditAction;
  readonly id?: string;
}): JSX.Element {
  return (
    <p className="cv-connectivity__marker" data-cmp="CMP-093" data-marker={action} id={id}>
      {MARKER[action]}
    </p>
  );
}

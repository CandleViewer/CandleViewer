import { cloneElement, useId, type JSX, type ReactElement } from "react";
import { AUDIT_ACTION_LABELS } from "./AuditRow.js";
import { cx } from "./internal/cx.js";
import { useGateNoticeFor } from "./internal/disabledReason.js";

/**
 * The marker's leads (E42-D02 D5, §4.3): a recorded action's, and a step-up action's ("Recorded · needs your
 * confirmation"). A marker never names a code the registry does not hold: with none it is the lead alone.
 */
export const AUDIT_MARKER_COPY = {
  recorded: "Recorded in the audit log",
  confirm: "Recorded · needs your confirmation",
} as const;

/** What the endpoint the control calls records (E42-D04 D28: registered codes only, never the ticket's names). */
export interface AuditMarker {
  /** The registered codes the endpoint writes, in order; none for an action whose code is not registered yet. */
  readonly codes: readonly string[];
  /**
   * The SCR-135 label of the action. Default: each code's own label (`AUDIT_ACTION_LABELS`), a code without one
   * reading as itself.
   */
  readonly label?: string;
  /** A step-up action, as the signed export: "Recorded · needs your confirmation — …" (D02 §4.3). */
  readonly confirm?: boolean;
}

const labelOf = (code: string): string | undefined =>
  Object.hasOwn(AUDIT_ACTION_LABELS, code) ? AUDIT_ACTION_LABELS[code] : undefined;

/**
 * The marker's words (D02 §4.3): "Recorded in the audit log · Flag changed (flags.change)", the label first and the
 * registered code after it; several codes joined by " + "; a step-up action's "Recorded · needs your confirmation —
 * Audit log exported (admin.audit_export)"; with no code, the lead alone.
 */
export function auditMarkerText(marker: AuditMarker): string {
  const lead = marker.confirm === true ? AUDIT_MARKER_COPY.confirm : AUDIT_MARKER_COPY.recorded;
  if (marker.codes.length === 0) return lead;
  const label = marker.label?.trim();
  const body =
    label === undefined || label === ""
      ? marker.codes
          .map((code) => {
            const own = labelOf(code);
            return own === undefined ? code : `${own} (${code})`;
          })
          .join(" + ")
      : `${label} (${marker.codes.join(" + ")})`;
  return `${lead}${marker.confirm === true ? " — " : " · "}${body}`;
}

/** The one control CMP-093 wraps: an atom that takes the T2 contract (CMP-001, CMP-002, …). */
export type AuditActionTriggerChild = ReactElement<{
  "aria-describedby"?: string;
  disabledReason?: string;
  disabledReasonId?: string;
}>;

export interface AuditActionTriggerProps {
  /** What the endpoint records when the control acts; the component itself records nothing. */
  readonly marker: AuditMarker;
  /**
   * T2 (E09-D09 §2.2): the control is disabled with this reason, shown under it (rendering 2a) and its only
   * description, while the marker stays visible. CMP-079 RbacGate hands it down when it wraps this component; a
   * reason on the control itself counts too.
   */
  readonly disabledReason?: string;
  /**
   * The host's one notice that already shows the reason ("one notice, many pointers"): no line here then. A CMP-079
   * RbacGate in its `notice` form around this component points it at the gate's notice the same way (BQ-9); an id
   * given here wins over that notice.
   */
  readonly disabledReasonId?: string;
  /** `end` lines the reason and the marker up under the control's end, as in a page header's actions. */
  readonly align?: "start" | "end";
  readonly children: AuditActionTriggerChild;
}

/**
 * CMP-093 AuditActionTrigger: one state-changing control and the marker line saying what its endpoint records
 * (E42-D02 D5, §4.3; E42-D04 §8, §12.1). Enabled, the marker joins the control's `aria-describedby`. Gated (T2), the
 * reason line shows under the control and is its only description, the lock leading its label (2a), and the marker
 * stays visible, rejoining the description once the control is enabled (E09-D09 §2.2). The component makes no
 * request and writes nothing: the endpoint writes the audit record (`14` §0.5 item 8). No role, no live region.
 */
export function AuditActionTrigger({
  marker,
  disabledReason,
  disabledReasonId,
  align = "start",
  children,
}: AuditActionTriggerProps): JSX.Element {
  const markerId = useId();
  const reasonId = useId();
  const own = children.props;
  const reason = (disabledReason ?? own.disabledReason)?.trim() || undefined;
  // Under CMP-079's notice form the panel's one notice is the reason node (BQ-9, G-T2.5): no line of its own. An
  // explicit host id still wins over the notice.
  const noticeId = useGateNoticeFor(reason);
  const hostId = (disabledReasonId ?? own.disabledReasonId)?.trim() || noticeId || undefined;
  const control =
    reason === undefined
      ? cloneElement(children, { "aria-describedby": cx(own["aria-describedby"], markerId) })
      : cloneElement(children, {
          disabledReason: reason,
          disabledReasonId: hostId ?? reasonId,
        });
  return (
    <div className="cv-audit-action" data-cmp="CMP-093" data-align={align}>
      {control}
      {reason !== undefined && hostId === undefined ? (
        <p id={reasonId} className="cv-audit-action__reason">
          {reason}
        </p>
      ) : null}
      <p id={markerId} className="cv-audit-action__marker">
        {auditMarkerText(marker)}
      </p>
    </div>
  );
}

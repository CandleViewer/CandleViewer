/**
 * SCR-135's footer (E42-S04; E42-D04 §4's tamper-line table, D10, AL-10 to AL-12): the page's
 * tamper line, as `footerModel` reads it, the check's own line (`checkLine`) and
 * [Run tamper check] inside CMP-093, its marker `admin.audit_verify` (D28: the endpoint records;
 * this footer records nothing). The FAILED line carries the octagon and stays silent: the banner
 * speaks (§7). While a run is in flight the button is busy, never T2; after a `429` it is T2
 * `admin.rate_limited` until `Retry-After` (AL-12); on My activity T2 `rbac.owner_only` (AL-25);
 * while viewing as another user T2 `rbac.view_as`, described by the page's one notice (BQ-9).
 * Before the first answer a CMP-015 line stands in (AL-1).
 */
import type { CSSProperties, JSX } from "react";
import { AuditActionTrigger, Button, Icon, Skeleton } from "@candleviewer/ui";
import { AUDIT_COPY as COPY } from "./copy";
import type { FooterLine, Line } from "./integrity";

const FOOTER: CSSProperties = { display: "grid", gap: "var(--space-stack-sm)" };
const LINE: CSSProperties = {
  margin: 0,
  display: "flex",
  alignItems: "center",
  gap: "var(--space-stack-sm)",
};
/** The check's marker (D28): the endpoint writes `admin.audit_verify`; the client writes nothing. */
const CHECK_MARKER = { codes: ["admin.audit_verify"] } as const;

export interface TamperFooterProps {
  /** AL-1: no answer yet, a CMP-015 line in the tamper line's place. */
  readonly loading: boolean;
  readonly line: FooterLine | null;
  /** `tamper.incidents_unavailable` under the line after a failed incident read (AL-10). */
  readonly incidents: Line | null;
  /** The last run's line (AL-11, AL-12). */
  readonly check: Line | null;
  /** A run is in flight: the button is busy (CMP-001 `loading`), never T2. */
  readonly running: boolean;
  /** T2: the one reason the button is gated by, if any. */
  readonly reason?: string | undefined;
  /** The page's one notice that already shows `reason` (view-as, BQ-9). */
  readonly reasonId?: string | undefined;
  readonly onRun: () => void;
}

export function TamperFooter({
  loading,
  line,
  incidents,
  check,
  running,
  reason,
  reasonId,
  onRun,
}: TamperFooterProps): JSX.Element {
  const gate = reason === undefined ? {} : { disabledReason: reason };
  const host = reason === undefined || reasonId === undefined ? {} : { disabledReasonId: reasonId };
  return (
    <div style={FOOTER} data-tamper-footer="">
      {loading ? (
        <Skeleton shape="text" count={1} />
      ) : line === null ? null : (
        <p style={LINE} data-line={line.key}>
          {line.failed ? <Icon name="danger" /> : null}
          {line.text}
        </p>
      )}
      {incidents === null ? null : (
        <p style={LINE} data-line={incidents.key}>
          {incidents.text}
        </p>
      )}
      <AuditActionTrigger marker={CHECK_MARKER} {...gate} {...host}>
        <Button
          variant="secondary"
          loading={running}
          onKeyDown={(event) => {
            // one run per press: a held key's repeats are dropped (§12)
            if (event.repeat && (event.key === "Enter" || event.key === " "))
              event.preventDefault();
          }}
          onClick={() => {
            if (!running) onRun();
          }}
        >
          {COPY.labels.act.runTamperCheck}
        </Button>
      </AuditActionTrigger>
      {check === null ? null : (
        <p style={LINE} data-line={check.key}>
          {check.text}
        </p>
      )}
    </div>
  );
}

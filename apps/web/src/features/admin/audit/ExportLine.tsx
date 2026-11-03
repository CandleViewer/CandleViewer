/**
 * The export line (E42-S04; E42-D04 §8 X4 to X10, AL-20 to AL-23), under the page header while this
 * session's export exists:
 * - queued or running: CMP-023 and "{n} %" once `progress_pct` is served, never "0 %" before
 *   (D02 D4), and the short job id; a failed poll keeps the last % with `export.poll_failed`,
 *   silent (X12). The bar announces nothing (`aria-live` off): the page says the 25 % steps.
 * - succeeded: `export.ready` (rows and window, size, the short `sha256` with Copy of the whole
 *   digest, `key_id`, the deletion time) with [Download], and `export.trust`. The download's own
 *   lines follow: `export.limited` (Download T2 `admin.rate_limited` until `Retry-After`),
 *   `export.download_failed` (Download enabled, its "Try again"), the view-as refusal, and SCR-006
 *   with one re-send for a `403 step_up_required`, as a download has no dialog to return to.
 * - failed, cancelled, lost, expired, not built: one line each, no file (AL-23, AL-20); a `404` or
 *   `410` on the download replaces the ready line, and focus moves to it when it was in the ready
 *   line or fell with it, never from where the user went meanwhile (A-1135P2-15).
 */
import { useEffect, useId, useRef, type CSSProperties, type JSX } from "react";
import { Button, CopyButton, ProgressBar } from "@candleviewer/ui";
import { StepUpChallengeGate } from "../../stepUp/StepUpChallengeGate";
import { AUDIT_COPY as COPY, num, size, utc } from "./copy";
import type { ExportPhase } from "./exportJob";

const LINE: CSSProperties = { margin: 0 };
const BLOCK: CSSProperties = { display: "grid", gap: "var(--space-stack-sm)" };
const ROW: CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  alignItems: "center",
  gap: "var(--space-stack-sm)",
};

/** "yyyy-mm-dd hh:mm" of a served instant, or as served when it is none. */
const at = (iso: string): string => {
  const ms = Date.parse(iso);
  return Number.isFinite(ms) ? utc.dateHm(ms) : iso;
};

/** A failed job's line by its served `error` (X7); an unlisted code reads as the internal error. */
export function failText(error: string | null): string {
  const fail = COPY.export.fail;
  return error !== null && Object.hasOwn(fail, error)
    ? (fail[error] ?? fail["internal_error"] ?? "")
    : (fail["internal_error"] ?? "");
}

/** The line a phase reads as, for the page's one polite saying of it; none while it waits. */
export function exportLineText(phase: ExportPhase): string | null {
  switch (phase.kind) {
    case "running":
      return COPY.export.running(phase.pct, phase.jobId.slice(0, 8));
    case "succeeded": {
      const r = phase.result;
      return COPY.export.ready.lead(num(r.row_count), at(r.from), at(r.to), size(r.size_bytes));
    }
    case "failed":
      return failText(phase.error);
    case "cancelled":
      return COPY.export.cancelled;
    case "lost":
      return COPY.export.lost;
    case "expired":
      return COPY.export.expired(at(phase.at));
    case "not_built":
      return COPY.export.notBuilt;
    default:
      return null;
  }
}

export interface ExportLineProps {
  readonly phase: ExportPhase;
  /** T2 on Download: the one reason, view-as first. */
  readonly downloadReason?: string | undefined;
  /** The page's one notice that already shows `downloadReason` (view-as, BQ-9). */
  readonly downloadReasonId?: string | undefined;
  /** The view-as sentence, for a refused download's `inflight.not_sent`. */
  readonly viewAsReason?: string | undefined;
  readonly onDownload: () => void;
  /** The gate re-sent the held download once. */
  readonly onDownloadResent: (response: Response) => void;
}

export function ExportLine({
  phase,
  downloadReason,
  downloadReasonId,
  viewAsReason,
  onDownload,
  onDownloadResent,
}: ExportLineProps): JSX.Element | null {
  const runningId = useId();
  const replaced = useRef<HTMLParagraphElement>(null);
  const was = useRef(phase.kind);
  /** Focus is in the ready line (its Download, its Copy). */
  const inside = useRef(false);
  // A `404` or `410` on the download replaces the ready line: focus moves to the line (AL-23).
  useEffect(() => {
    const before = was.current;
    was.current = phase.kind;
    if (before !== "succeeded" || (phase.kind !== "lost" && phase.kind !== "expired")) return;
    const active = document.activeElement;
    if (inside.current || active === null || active === document.body) replaced.current?.focus();
    inside.current = false;
  }, [phase.kind]);

  switch (phase.kind) {
    case "running": {
      const text = COPY.export.running(phase.pct, phase.jobId.slice(0, 8));
      return (
        <div style={BLOCK} data-export-line="running">
          {phase.pct === null ? null : (
            <ProgressBar value={phase.pct} aria-labelledby={runningId} />
          )}
          <p id={runningId} style={LINE}>
            {text}
          </p>
          {phase.pollFailed ? <p style={LINE}>{COPY.export.pollFailed}</p> : null}
        </div>
      );
    }
    case "succeeded": {
      const r = phase.result;
      const { download } = phase;
      const busy = download.kind === "downloading";
      const reason =
        downloadReason ?? (download.kind === "limited" ? COPY.admin.rateLimited : undefined);
      const gate =
        reason === undefined
          ? {
              onClick: () => {
                if (!busy) onDownload();
              },
            }
          : {
              disabledReason: reason,
              ...(downloadReasonId === undefined || downloadReason === undefined
                ? {}
                : { disabledReasonId: downloadReasonId }),
            };
      return (
        <div
          style={BLOCK}
          data-export-line="ready"
          onFocus={() => {
            inside.current = true;
          }}
          onBlur={(event) => {
            const to = event.relatedTarget;
            inside.current = to instanceof Node && event.currentTarget.contains(to);
          }}
        >
          <p style={ROW}>
            <span>
              {COPY.export.ready.lead(num(r.row_count), at(r.from), at(r.to), size(r.size_bytes))}
            </span>
            <span>· {COPY.export.ready.digest(r.sha256.slice(0, 8))}</span>
            <CopyButton value={r.sha256} label={`${COPY.labels.act.copy} sha256`} />
            <span>· {COPY.export.ready.key(r.key_id)}</span>
            <span>· {COPY.export.ready.deleted(at(r.expires_at))}</span>
            <Button
              variant="secondary"
              loading={busy}
              onKeyDown={(event) => {
                if (event.repeat && (event.key === "Enter" || event.key === " ")) {
                  event.preventDefault();
                }
              }}
              {...gate}
            >
              {COPY.labels.act.download}
            </Button>
          </p>
          <p style={LINE}>{COPY.export.trust}</p>
          {download.kind === "limited" ? (
            <p style={LINE}>{COPY.export.limited(utc.hm(download.until))}</p>
          ) : null}
          {download.kind === "failed" ? <p style={LINE}>{COPY.export.downloadFailed}</p> : null}
          {download.kind === "not_sent" ? (
            <p style={LINE}>{COPY.inflight.notSent(viewAsReason ?? "")}</p>
          ) : null}
          {download.kind === "step_up" ? (
            <StepUpChallengeGate
              key={download.hold.challenge.challengeId}
              challenge={download.hold.challenge}
              held={download.hold.held}
              onResent={onDownloadResent}
              readBack={() => undefined}
              outcomeWhere={COPY.labels.h.auditLog}
            />
          ) : null}
        </div>
      );
    }
    case "failed":
    case "cancelled":
    case "not_built":
      return (
        <p style={LINE} data-export-line={phase.kind}>
          {exportLineText(phase)}
        </p>
      );
    case "lost":
    case "expired":
      return (
        <p ref={replaced} tabIndex={-1} style={LINE} data-export-line={phase.kind}>
          {exportLineText(phase)}
        </p>
      );
    default:
      return null;
  }
}

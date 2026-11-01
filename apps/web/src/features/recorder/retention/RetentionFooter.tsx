/**
 * SCR-141's footer (E16-D03 §2 footer, §8; E16-D06 RG-12, SR-20 to SR-23, BG-02, BG-05, T2-07, T2-08, F-09, F-12,
 * §16.4 rows 10, 17, 18): the outcome line a save puts focus on; the job line — "Next retention run: daily at 03:00 UTC"
 * at rest, then this client's sweep by `Job.status`, progress as text first with a CMP-023 bar whose value text is the
 * same words, a lost sweep's line once its poll answers `404`, and under it a refused poll's T4 while the sweep runs;
 * the Apply-now box (busy while that sweep runs: a press toggles nothing); the unsaved-edits caption; Cancel ("Close"
 * after a save); Apply with its validity reason under it. The sweep is said once as it starts and once as it ends,
 * never per poll (F-09), each end with all its lines: through regions here from the footer's first paint, a failure
 * assertively (BG-05). A refused poll is said once, politely.
 */
import { useEffect, useId, useRef, useState, type JSX, type Ref } from "react";
import { Button, Callout, Checkbox, ProgressBar, Text } from "@candleviewer/ui";
import type { JobView } from "../useJobPoll";
import type { WriteGate } from "./GlobalDefaults";
import { RETENTION_DECK } from "./retentionCopy";
import { jobText, type JobState } from "./retentionText";
import { ValidityButton } from "./ValidityButton";

/** A count in a sweep's result, when the server gave one. */
const count = (result: object, key: string): number | null => {
  const value: unknown = (result as Readonly<Record<string, unknown>>)[key];
  return typeof value === "number" ? value : null;
};

/** The footer's state from this client's sweep poll (BQ-11: the id is the one this client's PUT answered). */
export function jobStateOf(view: JobView | null): JobState {
  if (view === null) return { kind: "rest" };
  switch (view.phase) {
    case "running":
      return view.job?.status === "running"
        ? { kind: "running", pct: view.pct }
        : { kind: "queued" };
    case "succeeded": {
      const result: unknown = view.job?.result;
      if (typeof result !== "object" || result === null)
        return { kind: "succeeded", freedBytes: null };
      // `RetentionSweepResult` (`22`): a locked volume swept nothing; failed partitions stay pending.
      return {
        kind: "succeeded",
        freedBytes: count(result, "freed_bytes"),
        locked: "skipped_locked" in result && result.skipped_locked === true,
        failed: count(result, "failed") ?? 0,
      };
    }
    case "failed":
      return { kind: "failed", code: view.job?.error ?? "failed" };
    case "cancelled":
      return { kind: "cancelled" };
    default:
      // Lost (`404`): #5309's poll keeps the refusal; a sweep has no deck line, so the generic T4's code.
      return {
        kind: "lost",
        code: view.route === null || view.route.kind === "step_up" ? null : view.route.code,
      };
  }
}

/** What the regions say for a state: the start (queued or running) as "queued", once; each end once. */
const moment = (state: JobState): string =>
  state.kind === "queued" || state.kind === "running" ? "start" : state.kind;

interface Spoken {
  readonly n: number;
  readonly text: string;
}

export interface RetentionFooterProps {
  /** The set is being read: Cancel only (D03 §4 `SCR-141/loading`). */
  readonly loading: boolean;
  /** This client's sweep, while it has one. */
  readonly jobId: string | null;
  readonly job: JobState;
  /** §16.4 row 10: the last poll of this sweep was refused (the T4 with its code token); null otherwise. */
  readonly pollRefused: string | null;
  /** A save's outcome line, focused once (FM-12). */
  readonly saved: boolean;
  readonly outcomeRef: Ref<HTMLParagraphElement>;
  readonly applyNow: boolean;
  readonly onApplyNow: (on: boolean) => void;
  readonly dirty: boolean;
  readonly onCancel: () => void;
  /** Apply's validity reason; undefined when it is ready. */
  readonly reason: string | undefined;
  readonly onApply: () => void;
  readonly onRefused: () => void;
  readonly saving: boolean;
  readonly gate: WriteGate | null;
}

export function RetentionFooter({
  loading,
  jobId,
  job,
  pollRefused,
  saved,
  outcomeRef,
  applyNow,
  onApplyNow,
  dirty,
  onCancel,
  reason,
  onApply,
  onRefused,
  saving,
  gate,
}: RetentionFooterProps): JSX.Element {
  const id = useId();
  const [polite, setPolite] = useState<Spoken>({ n: 0, text: "" });
  const [assertive, setAssertive] = useState<Spoken>({ n: 0, text: "" });
  // What the footer showed at its first paint is not news: only a change seen while it is open is said.
  const said = useRef(jobId === null ? null : `${jobId}:${moment(job)}`);
  const now = jobId === null ? null : `${jobId}:${moment(job)}`;
  useEffect(() => {
    if (now === null || now === said.current) return;
    said.current = now;
    if (job.kind === "rest") return;
    // The start as "queued"; an end with every line it shows (a failure and what to check, A-5353-08).
    const words = jobText(moment(job) === "start" ? { kind: "queued" } : job).join(" ");
    if (job.kind === "failed") setAssertive((s) => ({ n: s.n + 1, text: words }));
    else setPolite((s) => ({ n: s.n + 1, text: words }));
  }, [now, job]);
  // A refused poll is said once as it arrives; the next answer clears it, and the poll goes on.
  useEffect(() => {
    if (pollRefused !== null) setPolite((s) => ({ n: s.n + 1, text: pollRefused }));
  }, [pollRefused]);

  const sweeping = job.kind === "queued" || job.kind === "running";
  const [line = "", detail] = jobText(job);
  const t2 = gate === null ? {} : { disabledReason: gate.reason, disabledReasonId: gate.noticeId };
  const [cancel, apply, close] = RETENTION_DECK["retention.footer.buttons"];
  const reasonId = `${id}-reason`;

  return (
    <div style={{ display: "grid", gap: "var(--space-stack-xs)", inlineSize: "100%" }}>
      {loading ? null : (
        <div style={{ display: "grid", gap: "var(--space-stack-xs)" }}>
          {saved ? (
            <p ref={outcomeRef} tabIndex={-1} style={{ margin: 0 }}>
              {RETENTION_DECK["retention.outcome.saved"][0]}
            </p>
          ) : null}
          {job.kind === "running" ? (
            <>
              <span id={`${id}-job`} className="cv-visually-hidden">
                {line}
              </span>
              <ProgressBar aria-labelledby={`${id}-job`} value={job.pct} valueText={line} />
            </>
          ) : job.kind === "succeeded" ? (
            // A pass that swept nothing, or left partitions pending, is no plain success.
            <Callout tone={detail === undefined ? "success" : "warning"} live="off" title={line}>
              {detail}
            </Callout>
          ) : job.kind === "failed" ? (
            <Callout tone="danger" live="off" title={line}>
              {detail}
            </Callout>
          ) : (
            <Text as="p">{line}</Text>
          )}
          {pollRefused === null || !sweeping ? null : (
            <Text as="p" variant="caption" tone="secondary">
              {pollRefused}
            </Text>
          )}
          <span className="cv-visually-hidden" role="status" aria-live="polite" aria-atomic="true">
            {polite.text === "" ? null : <span key={polite.n}>{polite.text}</span>}
          </span>
          <span className="cv-visually-hidden" role="alert" aria-atomic="true">
            {assertive.text === "" ? null : <span key={assertive.n}>{assertive.text}</span>}
          </span>
        </div>
      )}
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          alignItems: "start",
          justifyContent: "flex-end",
          gap: "var(--space-inset-sm)",
        }}
      >
        {loading ? null : (
          <span style={{ marginInlineEnd: "auto" }}>
            <Checkbox
              label={RETENTION_DECK["retention.apply_now"][0]}
              // Busy (T2-08): unticked while this client's sweep runs, and a press toggles nothing.
              checked={sweeping ? false : applyNow}
              aria-busy={sweeping ? true : undefined}
              {...t2}
              onChange={(on) => {
                if (!sweeping) onApplyNow(on);
              }}
            />
          </span>
        )}
        {dirty && !loading ? (
          <Text variant="caption" tone="secondary">
            {RETENTION_DECK["retention.dirty"][0]}
          </Text>
        ) : null}
        <Button variant="secondary" onClick={onCancel}>
          {saved && !dirty ? close : cancel}
        </Button>
        {loading ? null : (
          <span
            style={{ display: "inline-grid", justifyItems: "end", gap: "var(--space-stack-xs)" }}
          >
            <ValidityButton
              reasonId={reasonId}
              reason={reason}
              loading={saving}
              onPress={onApply}
              onRefused={onRefused}
              {...(gate === null
                ? {}
                : { disabledReason: gate.reason, disabledReasonId: gate.noticeId })}
            >
              {apply}
            </ValidityButton>
            {/* The validity reason at full opacity under Apply, in the DOM from the first paint (T2-07). */}
            <Text id={reasonId} variant="caption" tone="secondary">
              {gate === null ? reason : undefined}
            </Text>
          </span>
        )}
      </div>
    </div>
  );
}

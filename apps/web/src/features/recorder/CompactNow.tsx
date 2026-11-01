/**
 * "Compact now" and the card's compact line (E16-D02 §3.2, §6.6; E16-D06 SR-13, BG-02, T2-08, §16.4 rows 9 and
 * 15): `compactRecorder`, non-destructive, no confirmation. While its job runs the button is CMP-001 `loading`
 * ("Compacting · 42 %", focusable, a press starts nothing, no lock: busy, not T2), the percentage never spoken.
 * The terminal state is the card's line, polite, once; a refusal shows under the button with its code, polite,
 * once, and the button stays enabled (T4); a poll the server refused (§16.4 row 10) shows its T4 there too, the job
 * still busy.
 */
import { useId, useState, type JSX } from "react";
import { Button } from "@candleviewer/ui";
import { DECK, TEXT, fill } from "./copy";
import { formatHourMinute, parseMs } from "./model";
import { recorderApi } from "./recorderApi";
import { refusalText } from "./refusal";
import { pollRefusalText, useJobPoll, type JobView } from "./useJobPoll";

/** The card's line for a finished compaction (§3.2): result, failure with its code, cancel, or lost. */
function lineOf(view: JobView | null): string | null {
  if (view === null || view.phase === "running") return null;
  if (view.phase === "unknown") return DECK["storage.compact.unknown"][0];
  if (view.phase === "cancelled") return DECK["storage.compact.cancelled"][0];
  if (view.phase === "failed") {
    return fill(DECK["storage.compact.failed"][0], { "`<code>`": view.job?.error ?? "failed" });
  }
  const at = parseMs(view.job?.finished_at) ?? null;
  return at === null
    ? null
    : fill(DECK["storage.compact.succeeded"][0], { "{HH:MM}": formatHourMinute(at) });
}

export function CompactNow(): JSX.Element {
  const id = useId();
  const [jobId, setJobId] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [refused, setRefused] = useState<string | null>(null);
  const job = useJobPoll(jobId, "compact");
  const running = sending || job?.phase === "running";
  const start = async (): Promise<void> => {
    setSending(true);
    setRefused(null);
    const res = await recorderApi.compact();
    setSending(false);
    if (res.ok && res.data?.job_id !== undefined) setJobId(res.data.job_id);
    else if (res.route !== null) setRefused(refusalText(res.route, "compact"));
  };
  // §16.4 row 10: a refused poll's T4 shows here while the job runs; the next answer clears it.
  const pollRefused = job?.pollRefusal == null ? null : pollRefusalText(job.pollRefusal);
  const line = lineOf(job) ?? pollRefused;
  return (
    <span style={{ display: "inline-grid", gap: "var(--space-stack-xs)" }}>
      <Button
        variant="secondary"
        loading={running}
        aria-describedby={`${id}-line`}
        onClick={() => void start()}
      >
        {running && job !== null
          ? fill(TEXT.compact.busy, { "{pct}": Math.round(job.pct) })
          : TEXT.compact.button}
      </Button>
      {/* The polite lines, there from the start so each arrival is said once (BG-02). */}
      <span id={`${id}-line`} role="status" aria-live="polite" aria-atomic="true">
        {refused ?? line}
      </span>
    </span>
  );
}

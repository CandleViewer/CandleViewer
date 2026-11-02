/**
 * "Compact now" and the card's compact line (E16-D02 §3.2, §6.6; E16-D06 SR-13, BG-02, T2-08, §16.4 rows 9 and
 * 15): `compactRecorder`, non-destructive, no confirmation. While its job runs the button is CMP-001 `loading`
 * ("Compacting · 42 %", focusable, a press starts nothing, no lock: busy, not T2), the percentage never spoken.
 * The terminal state is the card's line, polite, once; a refusal shows under the button with its code, polite,
 * once, and the button stays enabled (T4); a poll the server refused (§16.4 row 10) shows its T4 there too, the job
 * still busy. Each is said through the shell's announcer, never a live region in the page, which the row detail's
 * modal drawer would make inert (C-5347-d07, the A-5347-04 class); the line under the button is its description.
 */
import { useEffect, useId, useState, type JSX } from "react";
import { Button } from "@candleviewer/ui";
import { announce, forget } from "../app-shell/announcer";
import { DECK, TEXT, fill } from "./copy";
import { formatHourMinute, parseMs } from "./model";
import { sayPolitely } from "./pageAnnouncer";
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
    else if (res.route !== null) {
      const text = refusalText(res.route, "compact");
      setRefused(text);
      sayPolitely(text); // a press's answer: said again on the next press
    }
  };
  // §16.4 row 10: a refused poll's T4 shows here while the job runs; the next answer clears it.
  const pollRefused = job?.pollRefusal == null ? null : pollRefusalText(job.pollRefusal);
  const ended = lineOf(job);
  const line = ended ?? pollRefused;
  // The terminal line once per job and phase; a refused poll's T4 once per refusal, its key forgotten when an answer
  // clears it. The page's unmount clears every `recorder:` key.
  const phase = job?.phase ?? null;
  useEffect(() => {
    if (jobId === null || phase === null || ended === null) return;
    announce("polite", ended, `recorder:compact:${jobId}:${phase}`);
  }, [jobId, phase, ended]);
  useEffect(() => {
    if (jobId === null || pollRefused === null) return undefined;
    const key = `recorder:compact:${jobId}:poll`;
    announce("polite", pollRefused, key);
    return () => forget(key);
  }, [jobId, pollRefused]);
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
      {/* The line, drawn under the button and describing it; the shell's region says it (C-5347-d07). */}
      <span id={`${id}-line`}>{refused ?? line}</span>
    </span>
  );
}

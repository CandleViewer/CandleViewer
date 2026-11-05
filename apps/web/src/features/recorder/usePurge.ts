/**
 * The page's purge (E16-D02 §3, §3.2, §6.5; E16-D06 BG-02, BG-05, SR-09 to SR-12, §16.4 row 10): the dialog's opening
 * (a symbol preselected, or none from the card and the level-3 banner) and the job this client started, followed on
 * PR 2's 2 s job poll (`useJobPoll`, #485/#486 BQ-7), whose view is the new job's from its first frame (C-5347-01).
 * While it is queued or running every Purge data… and Purge… is busy (CMP-001 `loading`): a press opens nothing. A
 * reload forgets the job id; the server's 409 `job_running` then answers a second purge at the dialog's confirm
 * (§6.5). Each line is said once through the shell's announcer, never by a node in the page, so it is heard under
 * the row detail's modal drawer too (A-5347-04): the running line, a refused poll's T4 and each polite outcome here;
 * a failure is one of the page's assertive set, which the page's batch announcer says (`failure`, BG-05, BG-06).
 */
import { useCallback, useEffect, useState } from "react";
import { announce, forget } from "../app-shell/announcer";
import { PURGE_TEXT } from "./detailCopy";
import { purgeResult, purgeSpeech, type PurgeViewState } from "./PurgeView";
import { jobErrorCode, type PurgeJob } from "./purge";
import { pollRefusalText, useJobPoll } from "./useJobPoll";

export interface PagePurge {
  /** A purge this client started is queued or running. */
  readonly busy: boolean;
  /** The latest purge's state (running, or its outcome); null before one. */
  readonly state: PurgeViewState | null;
  /** The dialog's preselected symbol while it is open (null: the first offered); undefined while closed. */
  readonly dialogFor: string | null | undefined;
  /** Opens the dialog; nothing while busy (a press on a busy control opens nothing, D02 §6.5). */
  readonly open: (symbol?: string) => void;
  readonly close: () => void;
  /** The server accepted a purge: its job is followed from now. */
  readonly started: (job: PurgeJob) => void;
  /** The job reached a terminal state: the page's figures are read again (C-5347-03). */
  readonly ended: boolean;
  /** A failed purge's assertive line, once per job (its key), for the page's batch announcer; null otherwise. */
  readonly failure: { readonly key: string; readonly text: string } | null;
}

export function usePurge(): PagePurge {
  const [job, setJob] = useState<PurgeJob | null>(null);
  const [dialogFor, setDialogFor] = useState<string | null | undefined>(undefined);
  const view = useJobPoll(job?.jobId ?? null, "purge");
  const busy = job !== null && (view === null || view.phase === "running");

  let state: PurgeViewState | null = null;
  if (job !== null) {
    const phase = view?.phase ?? "running";
    const refusal = view?.pollRefusal ?? null;
    if (phase === "running") {
      state = {
        phase,
        symbol: job.symbol,
        beforeMs: job.beforeMs,
        pct: view?.pct ?? 0,
        pollRefused: refusal === null ? null : pollRefusalText(refusal),
      };
    } else if (phase === "failed") {
      state = { phase, symbol: job.symbol, code: jobErrorCode(view?.job?.error) };
    } else if (phase === "succeeded") {
      const result = purgeResult(view?.job ?? null);
      // Partitions left undeleted: the failed line with its PROPOSED code, never a clean "Purged" (C-5347-04).
      state =
        result.failed > 0
          ? { phase: "failed", symbol: job.symbol, code: PURGE_TEXT.partial }
          : { phase, symbol: job.symbol, freedBytes: result.freedBytes };
    } else {
      state = { phase, symbol: job.symbol };
    }
  }

  // Each polite line once per job and phase, through the shell's polite region (inert-exempt, pre-rendered at load).
  const jobId = job?.jobId ?? null;
  const speech = state === null ? null : purgeSpeech(state);
  const polite = speech?.politeness === "polite" ? speech.text : null;
  const phase = state?.phase ?? null;
  useEffect(() => {
    if (jobId === null || phase === null || polite === null) return;
    announce("polite", polite, `recorder:purge:${jobId}:${phase}`);
  }, [jobId, phase, polite]);
  const failure =
    jobId !== null && speech?.politeness === "assertive"
      ? { key: `purge:${jobId}:failed`, text: speech.text }
      : null;
  // A refused poll's T4, once per refusal: the key is forgotten when an answer clears it, so a later one is said.
  const refused = state?.phase === "running" ? state.pollRefused : null;
  useEffect(() => {
    if (jobId === null || refused === null) return undefined;
    const key = `recorder:purge:${jobId}:poll`;
    announce("polite", refused, key);
    return () => forget(key);
  }, [jobId, refused]);

  const open = useCallback(
    (symbol?: string): void => {
      if (!busy) setDialogFor(symbol ?? null);
    },
    [busy],
  );
  const close = useCallback((): void => setDialogFor(undefined), []);
  const started = useCallback((next: PurgeJob): void => {
    setJob(next);
    setDialogFor(undefined);
  }, []);
  const ended = state !== null && state.phase !== "running";
  return { busy, state, dialogFor, open, close, started, ended, failure };
}

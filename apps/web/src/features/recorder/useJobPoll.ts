/**
 * The 2 s job poll (E16-D02 §3.2, §6.6; D03:296's cadence; BQ-10): `GET /admin/jobs/{jobId}` until the job ends.
 * `queued` and `running` keep it busy (the progress is the button's words, never announced per tick, BG-02); a
 * terminal status, or a lost job (`404`, `job_unknown` after an API restart: the deck's `unknown` line, or the
 * generic T4 where an action has no deck row), ends it. A poll answered with a refusal (E16-D06 §16.4 row 10: a
 * `503 audit_unavailable`) carries the generic T4 for the host to show under its line; it, and a poll with no usable
 * answer, keep the last line and poll again. A new job starts at 0 %, never on the last one's end. #484 PR 3's purge
 * reuses it (BQ-7).
 */
import { useEffect, useState } from "react";
import { PAGE_TEXT } from "./pageCopy";
import { recorderApi, type Job, type JobAction, type RefusalRoute } from "./recorderApi";

export const JOB_POLL_MS = 2_000;

export type JobPhase = "running" | "succeeded" | "failed" | "cancelled" | "unknown";

export interface JobView {
  readonly phase: JobPhase;
  readonly pct: number;
  /** The server's job once it answered: `finished_at`, `error` (a stable code), `result`. */
  readonly job: Job | null;
  /** A lost job's refusal (`unknown`): the deck's sentence, or the generic T4 for the host to word; else null. */
  readonly route: RefusalRoute | null;
  /**
   * §16.4 row 10: the last poll was answered with a refusal (any error but a lost job's `404`), the generic T4 with
   * its code token for the host to show under its line, polite once. The poll goes on, the line stands, and the next
   * answer clears it.
   */
  readonly pollRefusal: RefusalRoute | null;
}

const TERMINAL: ReadonlySet<string> = new Set(["succeeded", "failed", "cancelled"]);
const RUNNING: JobView = { phase: "running", pct: 0, job: null, route: null, pollRefusal: null };

/** §16.4 row 10's T4 for a refused poll: the sentence, the code token after it in parentheses. */
export function pollRefusalText(route: RefusalRoute): string {
  const code = route.kind === "step_up" ? "step_up_required" : route.code;
  return code === null ? PAGE_TEXT.refused.poll : `${PAGE_TEXT.refused.poll} (${code})`;
}

/** Polls `jobId` every 2 s while it runs; null without a job. */
export function useJobPoll(jobId: string | null, action: JobAction): JobView | null {
  // Held with its job's id: a new job's first frames are running at 0 %, never the last job's end (C-5347-01).
  const [held, setHeld] = useState<{ readonly id: string; readonly view: JobView } | null>(null);
  useEffect(() => {
    if (jobId === null) return undefined;
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const show = (next: (prev: JobView) => JobView): void =>
      setHeld((prev) => ({ id: jobId, view: next(prev?.id === jobId ? prev.view : RUNNING) }));
    const poll = async (): Promise<void> => {
      const res = await recorderApi.job(jobId, action);
      if (!live) return;
      // Lost: jobs live in the API's memory, so a restart mid-job answers 404 for good; re-polling would never end.
      if (res.route?.kind === "deck" || res.status === 404) {
        const route = res.route;
        show((prev) => ({ phase: "unknown", pct: prev.pct, job: null, route, pollRefusal: null }));
        return;
      }
      const job = res.data;
      if (res.ok && job !== null) {
        const status = job.status ?? "running";
        const phase: JobPhase = TERMINAL.has(status) ? (status as JobPhase) : "running";
        show(() => ({ phase, pct: job.progress_pct ?? 0, job, route: null, pollRefusal: null }));
        if (phase !== "running") return;
      } else if (res.status >= 400 && res.route !== null) {
        const refusal = res.route;
        show((prev) => ({ ...prev, pollRefusal: refusal }));
      }
      timer = setTimeout(() => void poll(), JOB_POLL_MS);
    };
    void poll();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [jobId, action]);
  if (jobId === null) return null;
  return held?.id === jobId ? held.view : RUNNING;
}

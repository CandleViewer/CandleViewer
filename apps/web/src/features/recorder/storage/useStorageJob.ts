/**
 * SCR-142's job controller (E16-D04 §6, §8; E16-D06 SR-13, SR-24 to SR-28, §16.4; BQ-7, BQ-11): one per action this
 * section starts (compaction, import). It sends the write (its one `Idempotency-Key` is the client's, C-2.10; nothing
 * is re-sent on a failure), follows the job id the `202` answered on the shared 2 s poll (`useJobPoll`, #484's,
 * never forked, which holds its view with the job's id: a new job reads running at 0 % from its first render), and
 * says the start and each terminal line once through the section's polite region; an assertive line (a failed
 * import) is its card's alert instead (SR-26). A refusal shows at the control that was pressed and is said once
 * through the shell announcer; so is a poll the server refused (§16.4 row 10), under the job's line until an answer
 * clears it. A lost job (any `404`) ends the poll on its `unknown` line. A compaction reports `kind:
 * retention_sweep`: the action that issued the id names the job, never `kind` (BQ-11).
 */
import { useCallback, useEffect, useRef, useState } from "react";
import type { ApiResult, JobAccepted, RefusalRoute } from "../recorderApi";
import { pollRefusalText, useJobPoll, type JobView } from "../useJobPoll";
import { refusalFor, startedLine, type OutcomeView, type StorageJobKind } from "./storageJobs";

/** A refusal at the point of action: its words and the control (`at`) they sit under. */
export interface Refused {
  readonly text: string;
  readonly at: string;
}

export interface StorageJob<R> {
  /** This client's job, while it has one: the poll's view. */
  readonly view: JobView | null;
  /** What the job was asked for. */
  readonly request: R | null;
  /** Sending, queued or running: the controls are busy (D04 §1.3), never T2. */
  readonly busy: boolean;
  readonly refusal: Refused | null;
  /**
   * §16.4 row 10: the last poll was refused, the generic T4 with its code token, shown under the job's line (the
   * line kept) and said once; null once an answer comes, and whenever the job is not running (C-486P3-01).
   */
  readonly pollRefused: string | null;
  /** The terminal line, once the job has ended. */
  readonly outcome: OutcomeView | null;
  /** Sends `request` from the control `at`; a busy job starts nothing. */
  readonly start: (
    at: string,
    request: R,
    send: (request: R) => Promise<ApiResult<JobAccepted>>,
  ) => Promise<void>;
}

interface Run<R> {
  readonly id: string;
  readonly request: R;
}

/** A send that threw: no answer, the app's words (C-486P3-09). */
const NO_ANSWER: ApiResult<JobAccepted> = {
  ok: false,
  status: 0,
  code: null,
  data: null,
  stepUp: null,
  route: { kind: "t4", code: null, field: null, status: 0 },
};

export function useStorageJob<R>(
  kind: StorageJobKind,
  outcomeOf: (view: JobView, request: R) => OutcomeView | null,
  speak: (text: string) => void,
  say: (text: string) => void,
): StorageJob<R> {
  const [run, setRun] = useState<Run<R> | null>(null);
  const [sending, setSending] = useState(false);
  const [refusal, setRefusal] = useState<Refused | null>(null);
  // The poll's view of the job this client follows, held with its id (#5309's `useJobPoll`, C-486P3-01).
  const view = useJobPoll(run?.id ?? null, kind);
  const outcome =
    run === null || view === null || view.phase === "running" ? null : outcomeOf(view, run.request);
  const busy = sending || view?.phase === "running";
  const pollRefused =
    view?.phase === "running" && view.pollRefusal !== null
      ? pollRefusalText(view.pollRefusal)
      : null;
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  // Each terminal line once (SR-13, SR-25): polite through the section's region, with its detail; an assertive one
  // is its card's.
  const said = useRef<string | null>(null);
  const ended = run === null || outcome === null ? null : `${run.id}:${view?.phase ?? ""}`;
  useEffect(() => {
    if (ended === null || outcome === null || said.current === ended) return;
    said.current = ended;
    if (outcome.assertive) return;
    speak(outcome.detail === undefined ? outcome.text : `${outcome.text}. ${outcome.detail}`);
  }, [ended, outcome, speak]);

  // §16.4 row 10: a refused poll's T4 is said once, through the shell announcer, until an answer clears it.
  const refusedSaid = useRef<string | null>(null);
  useEffect(() => {
    if (pollRefused !== null && pollRefused !== refusedSaid.current) say(pollRefused);
    refusedSaid.current = pollRefused;
  }, [pollRefused, say]);

  const start = useCallback(
    async (
      at: string,
      request: R,
      send: (request: R) => Promise<ApiResult<JobAccepted>>,
    ): Promise<void> => {
      setRefusal(null);
      setRun(null);
      setSending(true);
      let res: ApiResult<JobAccepted>;
      try {
        res = await send(request);
      } catch {
        res = NO_ANSWER; // never a control left busy (C-486P3-09)
      } finally {
        if (alive.current) setSending(false);
      }
      if (!alive.current) return;
      const id = res.ok ? res.data?.job_id : undefined;
      if (id !== undefined) {
        setRun({ id, request });
        speak(startedLine(kind));
        return;
      }
      // A refusal, or a 2xx with no job id: the generic T4 words at the control (C-486P3-09), said once.
      const route: RefusalRoute = res.route ?? {
        kind: "t4",
        code: null,
        field: null,
        status: res.status,
      };
      const text = refusalFor(kind, route);
      setRefusal({ text, at });
      say(text);
    },
    [kind, speak, say],
  );

  return { view, request: run?.request ?? null, busy, refusal, pollRefused, outcome, start };
}

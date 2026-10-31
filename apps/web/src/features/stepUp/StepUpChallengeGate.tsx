import { useCallback, useEffect, useRef, useState, type JSX } from "react";
import {
  STEP_UP_EXPIRED,
  STEP_UP_LOCKED,
  STEP_UP_EXPIRY_WARNING,
  STEP_UP_NOT_SENT,
  STEP_UP_READ_ONLY,
  StepUpDialog,
  StepUpNotice,
  stepUpOutcomePending,
  type StepUpCredentials,
  type StepUpFailure,
} from "./StepUpDialog";
import { apiFetch } from "../../lib/http/csrfFetch";
import {
  STEP_UP_PATH,
  isStaleChallenge,
  msUntilExpiry,
  sendHeld,
  type HeldRequest,
  type StepUpChallenge,
  type StepUpGranted,
  type StepUpRequestBody,
} from "./challenge";

/** The third consecutive invalid code downgrades the session to read-only (`session_read_only`). */
export const MAX_STEP_UP_FAILURES = 3;
/**
 * A refused password or code (`401 mfa_invalid`): the E09-D06 `failure-1-of-3` / `failure-2-of-3`
 * frame text without its attempts count, which the server does not send yet.
 */
export const STEP_UP_INVALID = "Incorrect code.";
/**
 * The step-up itself got no answer, or a `429` / `5xx`: nothing was judged, nothing is counted and
 * the held request stays held. The existing text of the change-password screen; it fits a
 * network error, and a `429` / `5xx` has no designed copy yet (E09-D06 gap).
 */
export const STEP_UP_UNREACHABLE = "Cannot reach the server. Try again.";
/**
 * How long the held request's re-send may take before its outcome counts as unknown. The app has no
 * shared HTTP timeout; this matches its other auth waits (`REFRESH_WAIT_MS`, `BOOTSTRAP_TIMEOUT_MS`).
 */
export const RESEND_TIMEOUT_MS = 10_000;
/**
 * How long before `challenge_expires_at` the dialog warns (A11Y-F-0010, WCAG 2.2.1: at least 20 s
 * to act). The warning never extends the challenge; it only offers a fresh one.
 */
export const STEP_UP_WARN_MS = 30_000;
/** A timer past 2^31 ms would fire at once. */
const MAX_DELAY_MS = 2 ** 31 - 1;

export interface StepUpChallengeGateProps {
  readonly challenge: StepUpChallenge;
  /** The refused request, held unchanged; sent again at most once, after a matching `200`. */
  readonly held: HeldRequest;
  /**
   * The answer to the re-send, whatever its status. A re-send refused by a fresh
   * `403 step_up_required` is a new challenge; the caller may open one more gate for it and must not
   * open a further one (the invite screen caps it at one new cycle), so a server that keeps
   * challenging never loops the user.
   */
  readonly onResent: (response: Response) => void;
  /**
   * Reads the affected state back when the re-send got no answer (a network error or a timeout):
   * the action may have executed, so it is neither reported as not sent nor re-sent (E09-D06 §2.4).
   */
  readonly readBack: () => unknown;
  /** Where the read-back shows the outcome, for "Outcome pending, see …" (E09-D06 §2 item 4). */
  readonly outcomeWhere: string;
  /**
   * Asks the server for a FRESH challenge (A11Y-F-0010): the caller submits its action again as a
   * new request (new `Idempotency-Key`), whose `403 step_up_required` carries a new `challenge_id`
   * with the same factors. This challenge is never extended and its held request is dropped
   * unsent first. Gets the invalid codes counted so far, to seed the next gate's `priorFailures`.
   * Without it, no renewal is offered.
   */
  readonly onRenew?: (failures: number) => void;
  /** Invalid codes already counted against earlier challenges (the server's count stays truth). */
  readonly priorFailures?: number;
}

type Stage = "dialog" | "not-sent" | "expired" | "locked" | "read-only" | "pending" | "done";

/** Clamps a timer delay; an unreadable expiry fires at once. */
const delay = (ms: number): number =>
  Number.isNaN(ms) ? 0 : Math.min(Math.max(ms, 0), MAX_DELAY_MS);

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null;

/** A refusal after which the challenge cannot be answered: the held request is dropped unsent. */
function endsChallenge(status: number, body: unknown): boolean {
  const code = isRecord(body) ? body["code"] : undefined;
  if (status === 401) return code !== "mfa_invalid"; // idle lock, absolute expiry, revocation
  if (status === 403) return code === "session_read_only";
  return isStaleChallenge(status, body);
}

/**
 * Answers one `403 step_up_required` challenge (#2725): SCR-006 restates `action_summary`, the step-up
 * sends `challenge_id`, and the held request is re-sent once after a `200` for the challenged class.
 * Esc / Cancel, `challenge_expires_at`, a class mismatch, the third failure, idle lock, absolute expiry
 * and a stale-challenge `400` drop it unsent and leave "Not sent" (E09-D06 §2 item 7). The expiry
 * is warned of `STEP_UP_WARN_MS` ahead and announced when it passes; the third failure and
 * `session_read_only` say why and what follows (A11Y-F-0010, A11Y-F-0012).
 */
export function StepUpChallengeGate({
  challenge,
  held,
  onResent,
  readBack,
  outcomeWhere,
  onRenew,
  priorFailures = 0,
}: StepUpChallengeGateProps): JSX.Element | null {
  const [stage, setStage] = useState<Stage>("dialog");
  const [submitting, setSubmitting] = useState(false);
  const [failure, setFailure] = useState<StepUpFailure | null>(null);
  /** Set once the held request is dropped or re-sent: it is never sent (again) after that. */
  const settled = useRef(false);
  const failures = useRef(priorFailures);
  const [warning, setWarning] = useState<string | null>(null);

  const end = useCallback((next: Stage): void => {
    if (settled.current) return;
    settled.current = true;
    setStage(next);
  }, []);
  const drop = useCallback((): void => end("not-sent"), [end]);

  useEffect(() => {
    settled.current = false;
    return () => {
      settled.current = true; // unmounted: nothing may send it any more
    };
  }, []);

  useEffect(() => {
    const ms = msUntilExpiry(challenge);
    const expiry = setTimeout(() => end("expired"), delay(ms));
    const warn = setTimeout(() => setWarning(STEP_UP_EXPIRY_WARNING), delay(ms - STEP_UP_WARN_MS));
    return () => {
      clearTimeout(expiry);
      clearTimeout(warn);
    };
  }, [challenge, end]);

  /** Abandons this challenge (its request is never sent) and asks the caller for a fresh one. */
  function renew(): void {
    // an answer in flight is awaited: its 401 must be counted before the count is carried
    if (submitting) return;
    settled.current = true;
    setStage("done");
    onRenew?.(failures.current);
  }

  function fail(message: string, credentials: boolean): void {
    setSubmitting(false);
    setFailure((prev) => ({ message, credentials, seq: (prev?.seq ?? 0) + 1 }));
  }

  async function resend(): Promise<void> {
    settled.current = true;
    let answer: Response;
    try {
      answer = await sendHeld(held, AbortSignal.timeout(RESEND_TIMEOUT_MS));
    } catch {
      // A network error or the timeout: the action may have executed (E09-D06 §2 item 4).
      setStage("pending");
      try {
        await readBack();
      } catch {
        // The notice already points at where the outcome shows; a failed read-back changes nothing.
      }
      return;
    }
    setStage("done");
    onResent(answer);
  }

  async function submit({ password, code }: StepUpCredentials): Promise<void> {
    setSubmitting(true);
    const request: StepUpRequestBody = { password, code, challenge_id: challenge.challengeId };
    let response: Response;
    try {
      response = await apiFetch(STEP_UP_PATH, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      });
    } catch {
      if (!settled.current) fail(STEP_UP_UNREACHABLE, false);
      return;
    }
    const body: unknown = await response.json().catch(() => null);
    if (settled.current) return; // dropped meanwhile (Esc, expiry): never re-sent
    if (response.ok) {
      const granted = body as Partial<StepUpGranted> | null;
      // Elevation is server-side session state: the client keeps no copy of it.
      if (granted?.action_class !== challenge.actionClass) return drop();
      return resend();
    }
    if (response.status === 403 && isRecord(body) && body["code"] === "session_read_only") {
      // the answer to a third invalid code, or a lock from before this attempt (another tab or
      // gate), which checked neither factor and so never calls this code wrong
      return end(failures.current + 1 >= MAX_STEP_UP_FAILURES ? "locked" : "read-only");
    }
    if (endsChallenge(response.status, body)) return drop();
    if (response.status === 429 || response.status >= 500) return fail(STEP_UP_UNREACHABLE, false);
    if (response.status === 401) {
      failures.current += 1;
      if (failures.current >= MAX_STEP_UP_FAILURES) return end("locked");
    }
    fail(STEP_UP_INVALID, true);
  }

  const renewable = onRenew === undefined ? undefined : renew;
  if (stage === "not-sent") return <StepUpNotice message={STEP_UP_NOT_SENT} />;
  if (stage === "expired") {
    return <StepUpNotice message={STEP_UP_EXPIRED} assertive onRenew={renewable} />;
  }
  if (stage === "locked") return <StepUpNotice message={STEP_UP_LOCKED} assertive />;
  if (stage === "read-only") return <StepUpNotice message={STEP_UP_READ_ONLY} assertive />;
  if (stage === "pending") return <StepUpNotice message={stepUpOutcomePending(outcomeWhere)} />;
  if (stage === "done") return null;
  return (
    <StepUpDialog
      actionSummary={challenge.actionSummary}
      target={challenge.target}
      submitting={submitting}
      failure={failure}
      warning={warning}
      onRenew={renewable}
      onSubmit={(credentials) => void submit(credentials)}
      onCancel={drop}
    />
  );
}

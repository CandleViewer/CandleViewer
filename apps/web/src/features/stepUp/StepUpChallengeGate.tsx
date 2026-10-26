import { useCallback, useEffect, useRef, useState, type JSX } from "react";
import {
  STEP_UP_NOT_SENT,
  StepUpDialog,
  StepUpNotice,
  stepUpOutcomePending,
  type StepUpCredentials,
  type StepUpFailure,
} from "./StepUpDialog";
import { recordStepUp } from "../../lib/auth/meCache";
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
}

type Stage = "dialog" | "not-sent" | "pending" | "done";

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
 * and a stale-challenge `400` drop it unsent and leave "Not sent" (E09-D06 §2 item 7).
 */
export function StepUpChallengeGate({
  challenge,
  held,
  onResent,
  readBack,
  outcomeWhere,
}: StepUpChallengeGateProps): JSX.Element | null {
  const [stage, setStage] = useState<Stage>("dialog");
  const [submitting, setSubmitting] = useState(false);
  const [failure, setFailure] = useState<StepUpFailure | null>(null);
  /** Set once the held request is dropped or re-sent: it is never sent (again) after that. */
  const settled = useRef(false);
  const failures = useRef(0);

  const drop = useCallback((): void => {
    if (settled.current) return;
    settled.current = true;
    setStage("not-sent");
  }, []);

  useEffect(() => {
    settled.current = false;
    return () => {
      settled.current = true; // unmounted: nothing may send it any more
    };
  }, []);

  useEffect(() => {
    const ms = msUntilExpiry(challenge);
    const timer = setTimeout(drop, Number.isNaN(ms) ? 0 : Math.min(Math.max(ms, 0), MAX_DELAY_MS));
    return () => clearTimeout(timer);
  }, [challenge, drop]);

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
      if (granted?.action_class !== challenge.actionClass) return drop();
      if (typeof granted.elevated_until === "string") {
        recordStepUp(granted.elevated_until, granted.step_up_expires_at ?? null);
      }
      return resend();
    }
    if (endsChallenge(response.status, body)) return drop();
    if (response.status === 429 || response.status >= 500) return fail(STEP_UP_UNREACHABLE, false);
    if (response.status === 401) {
      failures.current += 1;
      if (failures.current >= MAX_STEP_UP_FAILURES) return drop();
    }
    fail(STEP_UP_INVALID, true);
  }

  if (stage === "not-sent") return <StepUpNotice message={STEP_UP_NOT_SENT} />;
  if (stage === "pending") return <StepUpNotice message={stepUpOutcomePending(outcomeWhere)} />;
  if (stage === "done") return null;
  return (
    <StepUpDialog
      actionSummary={challenge.actionSummary}
      target={challenge.target}
      submitting={submitting}
      failure={failure}
      onSubmit={(credentials) => void submit(credentials)}
      onCancel={drop}
    />
  );
}

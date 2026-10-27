import { useEffect, useRef, useState, type JSX } from "react";
import { getMeClaims } from "../../lib/auth/meCache";
import { SessionLockDialog, type LockFailure, type LockPhase } from "./SessionLockDialog";
import { SessionTimeoutWarning } from "./SessionTimeoutWarning";
import { sessionApi, type SessionApi, type SessionClock, type UnlockOutcome } from "./sessionApi";

/** CMP-098 shows this long before the server's idle deadline (E09-D06 §3). */
export const WARN_MS = 60_000;
/** A read that got no answer is tried again after this long: never a tight loop. */
const RETRY_MS = 30_000;

/** E09-D06 `wrong-password`; the other two are PROPOSED (#1640 copy-pending table). */
const FAILURE_COPY: Partial<Record<UnlockOutcome["kind"], string>> = {
  invalid: "Incorrect password. Try again.",
  throttled: "Too many attempts. Wait a minute, then try again.",
  unreachable: "Couldn't reach the server. Try again.",
};

type View =
  | { readonly kind: "none" }
  | { readonly kind: "warning"; readonly deadlineMs: number }
  | { readonly kind: "locked"; readonly phase: LockPhase; readonly failure: LockFailure | null };

interface Actions {
  extend(): void;
  dismiss(): void;
  unlock(password: string): void;
}

export interface SessionLockHostProps {
  readonly api?: SessionApi;
  /** Only a signed-in shell reads its session. */
  readonly enabled?: boolean;
}

/**
 * #1640: times CMP-098 and SCR-005 from `GET /auth/session` (`idle_deadline` against `server_time`,
 * never a client clock). It reads the session when the warning and the deadline fall due, never on an
 * interval, and records activity only through CMP-098's Stay signed in (`POST /auth/session/extend`)
 * and SCR-005's unlock: input, WS traffic and reads never extend (#2300 scenario 5).
 */
export function SessionLockHost({
  api = sessionApi,
  enabled = getMeClaims().authenticated,
}: SessionLockHostProps): JSX.Element | null {
  const [view, setView] = useState<View>({ kind: "none" });
  const [idleMinutes, setIdleMinutes] = useState(15);
  const [now, setNow] = useState(() => Date.now());
  const actions = useRef<Actions | null>(null);

  useEffect(() => {
    if (!enabled) return undefined;
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    /** The deadline the warning on screen is for, and the one Esc dismissed. */
    let warned: string | null = null;
    let dismissed: string | null = null;
    let failures = 0;
    const at = (ms: number, task: () => void): void => {
      clearTimeout(timer);
      timer = setTimeout(task, Math.max(ms, 0));
    };
    const read = (): void => void api.read().then(apply);
    function apply(clock: SessionClock | null): void {
      if (!live) return;
      if (clock === null) return at(RETRY_MS, read);
      const { session } = clock;
      setIdleMinutes(Math.round(session.idle_timeout_s / 60));
      if (session.locked) {
        clearTimeout(timer);
        setView((v) =>
          v.kind === "locked" ? v : { kind: "locked", phase: "locked", failure: null },
        );
        return;
      }
      const left = Date.parse(session.idle_deadline) - Date.parse(clock.server_time);
      if (left > WARN_MS || dismissed === session.idle_deadline) {
        setView({ kind: "none" });
        at(left > WARN_MS ? left - WARN_MS : left, read);
        return;
      }
      warned = session.idle_deadline;
      setNow(Date.now());
      setView({ kind: "warning", deadlineMs: Date.now() + left });
      at(left, read);
    }
    function settle(outcome: UnlockOutcome): void {
      if (!live) return;
      if (outcome.kind === "unlocked") return apply(outcome.clock);
      if (outcome.kind === "revoked") return api.endSession();
      if (outcome.kind === "not_locked") return read();
      failures += 1;
      const message = FAILURE_COPY[outcome.kind] ?? "";
      setView({ kind: "locked", phase: "error", failure: { message, seq: failures } });
    }
    actions.current = {
      extend: () => void api.extend().then((clock) => (clock === null ? read() : apply(clock))),
      dismiss: () => {
        dismissed = warned;
        setView({ kind: "none" });
      },
      unlock: (password) => {
        setView({ kind: "locked", phase: "verifying", failure: null });
        void api.unlock(password).then(settle);
      },
    };
    read();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [enabled, api]);

  const warning = view.kind === "warning";
  useEffect(() => {
    if (!warning) return undefined;
    const tick = setInterval(() => setNow(Date.now()), 1_000);
    return () => clearInterval(tick);
  }, [warning]);

  if (view.kind === "warning") {
    return (
      <SessionTimeoutWarning
        expiresInSec={(view.deadlineMs - now) / 1000}
        onExtend={() => actions.current?.extend()}
        onDismiss={() => actions.current?.dismiss()}
      />
    );
  }
  if (view.kind === "locked") {
    return (
      <SessionLockDialog
        idleMinutes={idleMinutes}
        phase={view.phase}
        failure={view.failure}
        onUnlock={(password) => actions.current?.unlock(password)}
      />
    );
  }
  return null;
}

import { useEffect, useRef, useState, type JSX } from "react";
import { getMeClaims } from "../../lib/auth/meCache";
import { SessionLockDialog, type LockFailure, type LockPhase } from "./SessionLockDialog";
import { sessionApi, type SessionApi, type SessionClock, type UnlockOutcome } from "./sessionApi";

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
  | { readonly kind: "locked"; readonly phase: LockPhase; readonly failure: LockFailure | null };

export interface SessionLockHostProps {
  readonly api?: SessionApi;
  /** Only a signed-in shell reads its session. */
  readonly enabled?: boolean;
}

/**
 * #1640: shows SCR-005 from `GET /auth/session` (`idle_deadline` against `server_time`, never a
 * client clock). It reads the session when the deadline falls due, never on an interval; reads are
 * not activity (#2300 scenario 5). Only SCR-005's unlock lifts the lock.
 */
export function SessionLockHost({
  api = sessionApi,
  enabled = getMeClaims().authenticated,
}: SessionLockHostProps): JSX.Element | null {
  const [view, setView] = useState<View>({ kind: "none" });
  const [idleMinutes, setIdleMinutes] = useState(15);
  const unlock = useRef<((password: string) => void) | null>(null);

  useEffect(() => {
    if (!enabled) return undefined;
    let live = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
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
      setView({ kind: "none" });
      at(Date.parse(session.idle_deadline) - Date.parse(clock.server_time), read);
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
    unlock.current = (password) => {
      setView({ kind: "locked", phase: "verifying", failure: null });
      void api.unlock(password).then(settle);
    };
    read();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [enabled, api]);

  if (view.kind !== "locked") return null;
  return (
    <SessionLockDialog
      idleMinutes={idleMinutes}
      phase={view.phase}
      failure={view.failure}
      onUnlock={(password) => unlock.current?.(password)}
    />
  );
}

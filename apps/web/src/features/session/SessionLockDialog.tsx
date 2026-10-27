import { useEffect, useId, useRef, useState, type FormEvent, type JSX } from "react";
import { actions, card, hidden, primary, scrim, title, useModalKeys } from "./chrome";

/** E09-D06 frames `locked-default`, `verifying`, `wrong-password` (and the other refusals). */
export type LockPhase = "locked" | "verifying" | "error";

export interface LockFailure {
  readonly message: string;
  /** A new `seq` clears the password and refocuses it. */
  readonly seq: number;
}

export interface SessionLockDialogProps {
  /** `session.idle_timeout_s` in minutes. */
  readonly idleMinutes: number;
  readonly phase: LockPhase;
  readonly failure?: LockFailure | null;
  readonly onUnlock: (password: string) => void;
}

const field = {
  minBlockSize: "var(--size-target-min)",
  padding: "var(--space-2) var(--space-3)",
  background: "var(--color-surface-sunken)",
  color: "var(--color-text-primary)",
  border: "1px solid var(--color-border-default)",
  borderRadius: "var(--radius-md)",
} as const;

/**
 * SCR-005 idle lock (E09-D06 §3, §5, §6): `role="alertdialog"`, announced once, focus on the
 * password, Tab trapped, Esc does not dismiss. Presentational: the host sends the unlock.
 */
export function SessionLockDialog({
  idleMinutes,
  phase,
  failure = null,
  onUnlock,
}: SessionLockDialogProps): JSX.Element {
  const id = useId();
  const dialog = useRef<HTMLDivElement>(null);
  const passwordField = useRef<HTMLInputElement>(null);
  const [password, setPassword] = useState("");
  const verifying = phase === "verifying";
  const seq = failure?.seq;
  useModalKeys(dialog);

  useEffect(() => passwordField.current?.focus(), []);
  useEffect(() => {
    if (seq === undefined) return;
    setPassword("");
    passwordField.current?.focus();
  }, [seq]);

  function submit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    if (!verifying && password.length > 0) onUnlock(password);
  }

  const body =
    phase === "locked"
      ? `You were inactive for ${idleMinutes} minutes. Your layout is preserved. Unsent ticket inputs are preserved while locked; discarded on sign-out or expiry.`
      : verifying
        ? "Verifying your password..."
        : "Sign in again to continue.";
  return (
    <div style={scrim}>
      <div
        ref={dialog}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={`${id}-t`}
        aria-describedby={`${id}-d`}
        aria-busy={verifying}
        style={card}
      >
        <h2 id={`${id}-t`} style={title}>
          Session locked
        </h2>
        <p id={`${id}-d`} style={hidden}>
          {`Screen locked after ${idleMinutes} minutes idle. Market data continues. Order entry is disabled. Enter your password to resume.`}
        </p>
        <p style={{ margin: 0, color: "var(--color-text-secondary)" }}>{body}</p>
        <p role="status" style={hidden}>
          {verifying ? "Verifying..." : ""}
        </p>
        <form
          onSubmit={submit}
          style={{ display: "flex", flexDirection: "column", gap: "var(--space-2)" }}
        >
          <label htmlFor={`${id}-p`}>Password</label>
          <input
            ref={passwordField}
            id={`${id}-p`}
            name="password"
            type="password"
            autoComplete="current-password"
            placeholder="Enter your password"
            required
            readOnly={verifying}
            aria-invalid={phase === "error" ? true : undefined}
            aria-describedby={failure === null ? undefined : `${id}-e`}
            style={
              phase === "error"
                ? { ...field, borderColor: "var(--color-status-warning-default)" }
                : field
            }
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          {failure === null ? null : (
            <p
              id={`${id}-e`}
              role="alert"
              style={{ margin: 0, color: "var(--color-status-warning-default)" }}
            >
              {failure.message}
            </p>
          )}
          <div style={actions}>
            <button type="submit" style={primary} disabled={verifying}>
              {verifying ? "Verifying..." : "Unlock"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

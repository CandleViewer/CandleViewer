import { useEffect, useId, useRef, useState, type FormEvent, type JSX } from "react";
import {
  actions,
  card,
  hidden,
  primary,
  scrim,
  secondary,
  title,
  useFocusReturn,
  useModalKeys,
} from "./chrome";

/** E09-D06 frames `locked-default`, `verifying`, `wrong-password` (and the other refusals). */
export type LockPhase = "locked" | "verifying" | "error";

export interface LockFailure {
  readonly message: string;
  /** A new `seq` of a refused password (`credentials`, the default) clears it and refocuses it. */
  readonly seq: number;
  /** `false` for a throttle or no answer: what was typed stays, the field is not marked invalid. */
  readonly credentials?: boolean;
}

export interface SessionLockDialogProps {
  /** `session.idle_timeout_s` in minutes. */
  readonly idleMinutes: number;
  readonly phase: LockPhase;
  readonly failure?: LockFailure | null;
  readonly onUnlock: (password: string) => void;
  /** "Sign out instead": opens the confirm sub-dialog (E09-D06 `sign-out-instead`). */
  readonly onSignOut?: () => void;
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
  onSignOut,
}: SessionLockDialogProps): JSX.Element {
  const id = useId();
  const dialog = useRef<HTMLDivElement>(null);
  const passwordField = useRef<HTMLInputElement>(null);
  const [password, setPassword] = useState("");
  const verifying = phase === "verifying";
  const seq = failure?.seq;
  const refused = failure !== null && failure.credentials !== false;
  // order matters: on unmount the focus guard goes before focus returns to the opener
  useModalKeys(dialog, undefined, true);
  useFocusReturn();

  useEffect(() => passwordField.current?.focus(), []);
  useEffect(() => {
    if (seq === undefined || !refused) return;
    setPassword("");
    passwordField.current?.focus();
  }, [seq, refused]);

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
    // `data-keymap-context="Locked"` stops global hotkeys (KeymapHost)
    <div style={scrim} data-keymap-context="Locked">
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
            aria-invalid={refused ? true : undefined}
            aria-describedby={failure === null ? undefined : `${id}-e`}
            style={
              refused ? { ...field, borderColor: "var(--color-status-warning-default)" } : field
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
            {onSignOut === undefined ? null : (
              <button type="button" style={secondary} disabled={verifying} onClick={onSignOut}>
                Sign out instead
              </button>
            )}
            <button type="submit" style={primary} disabled={verifying}>
              {verifying ? "Verifying..." : "Unlock"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

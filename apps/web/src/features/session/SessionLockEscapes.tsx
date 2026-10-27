import { useEffect, useId, useRef, type JSX } from "react";
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

export interface SignOutConfirmProps {
  /** `POST /auth/logout` is on the wire: both actions wait. */
  readonly busy: boolean;
  /** The logout revoked nothing (no answer, `503`): PROPOSED `lock.unreachable` (#1640). */
  readonly failed: boolean;
  readonly onConfirm: () => void;
  readonly onBack: () => void;
}

/**
 * SCR-005 `sign-out-instead` (E09-D06): the confirm sub-dialog, no password field. Focus starts on
 * "Back to unlock"; Esc goes back too (a safe no-op); Tab is trapped.
 */
export function SignOutConfirm({
  busy,
  failed,
  onConfirm,
  onBack,
}: SignOutConfirmProps): JSX.Element {
  const id = useId();
  const dialog = useRef<HTMLDivElement>(null);
  const back = useRef<HTMLButtonElement>(null);
  useModalKeys(dialog, busy ? undefined : onBack, true);
  useEffect(() => back.current?.focus(), []);
  return (
    <div style={scrim} data-keymap-context="Locked">
      <div
        ref={dialog}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={`${id}-t`}
        aria-describedby={`${id}-d`}
        aria-busy={busy}
        style={card}
      >
        <h2 id={`${id}-t`} style={title}>
          Sign out?
        </h2>
        <p id={`${id}-d`} style={{ margin: 0, color: "var(--color-text-secondary)" }}>
          Unsent ticket inputs will be discarded. Open orders stay live on the exchange with their
          native stop-loss.
        </p>
        {failed ? (
          <p role="alert" style={{ margin: 0, color: "var(--color-status-warning-default)" }}>
            Couldn&apos;t reach the server. Try again.
          </p>
        ) : null}
        <div style={actions}>
          <button ref={back} type="button" style={secondary} disabled={busy} onClick={onBack}>
            Back to unlock
          </button>
          <button type="button" style={primary} disabled={busy} onClick={onConfirm}>
            Sign out
          </button>
        </div>
      </div>
    </div>
  );
}

const badge = {
  alignSelf: "flex-start",
  padding: "var(--space-1) var(--space-2)",
  borderRadius: "var(--radius-badge)",
  border: "1px solid var(--color-status-warning-default)",
  color: "var(--color-status-warning-default)",
  fontSize: "var(--font-size-xs)",
  fontWeight: "var(--font-weight-semibold)",
} as const;

/**
 * SCR-005 `absolute-expiry-signed-out` (E09-D06): the unlock found the 12 h lifetime elapsed
 * (`session_revoked`, `revoked_reason: expired`). Announced once (§6); the one action is SCR-001.
 */
export function SessionExpiredCard({ onSignIn }: { readonly onSignIn: () => void }): JSX.Element {
  const id = useId();
  const dialog = useRef<HTMLDivElement>(null);
  const signIn = useRef<HTMLButtonElement>(null);
  useModalKeys(dialog, undefined, true);
  useFocusReturn();
  useEffect(() => signIn.current?.focus(), []);
  return (
    <div style={scrim} data-keymap-context="Locked">
      <div
        ref={dialog}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={`${id}-t`}
        aria-describedby={`${id}-d`}
        style={card}
      >
        <h2 id={`${id}-t`} style={title}>
          Session expired
        </h2>
        <p id={`${id}-d`} style={hidden}>
          Session expired. Signed out. Sign in again.
        </p>
        <p style={badge}>NOT SENT · DISCARDED · DISARMED</p>
        <p style={{ margin: 0, color: "var(--color-text-secondary)" }}>
          Your session reached its maximum lifetime and you were signed out. Not sent. Discarded.
          One-click disarmed.
        </p>
        <div style={actions}>
          <button ref={signIn} type="button" style={primary} onClick={onSignIn}>
            Sign in
          </button>
        </div>
      </div>
    </div>
  );
}

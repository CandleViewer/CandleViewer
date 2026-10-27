import { useEffect, useId, useRef, type JSX } from "react";
import { formatRemaining } from "../auth/authApi";
import { actions, card, primary, scrim, title, useModalKeys } from "./chrome";

export interface SessionTimeoutWarningProps {
  /** Seconds to the server's idle deadline. Shown, never announced per tick (E09-D06 §6). */
  readonly expiresInSec: number;
  /** "Stay signed in": the explicit `POST /auth/session/extend` (the only activity signal). */
  readonly onExtend: () => void;
  /** Esc: dismiss, does NOT extend (15 CMP-098). */
  readonly onDismiss: () => void;
}

/**
 * CMP-098 SessionTimeoutWarning (E09-D06 frame `session-timeout-warning-60s`): `role="alertdialog"`
 * announced once, focus to the Extend control. "Lock now" is not built: no contract call locks a
 * session (#1640 survey, gap 1).
 */
export function SessionTimeoutWarning({
  expiresInSec,
  onExtend,
  onDismiss,
}: SessionTimeoutWarningProps): JSX.Element {
  const id = useId();
  const dialog = useRef<HTMLDivElement>(null);
  const extend = useRef<HTMLButtonElement>(null);
  useModalKeys(dialog, onDismiss);
  useEffect(() => {
    const opener = document.activeElement;
    extend.current?.focus();
    return () => {
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus();
    };
  }, []);
  return (
    <div style={scrim}>
      <div
        ref={dialog}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={`${id}-t`}
        aria-describedby={`${id}-d`}
        style={card}
      >
        <h2 id={`${id}-t`} style={title}>
          Your session will lock soon
        </h2>
        <p id={`${id}-d`} style={{ margin: 0 }}>
          No activity detected. The workspace locks in 60 seconds. Live data keeps updating.
        </p>
        <p
          style={{
            margin: 0,
            fontFamily: "var(--font-family-mono)",
            fontSize: "var(--font-size-xl)",
            color: "var(--color-status-warning-default)",
          }}
        >
          Lock in {formatRemaining(expiresInSec)}
        </p>
        <div style={actions}>
          <button ref={extend} type="button" style={primary} onClick={onExtend}>
            Stay signed in
          </button>
        </div>
      </div>
    </div>
  );
}

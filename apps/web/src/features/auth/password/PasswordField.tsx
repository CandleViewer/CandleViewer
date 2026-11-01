import { useState, type JSX, type KeyboardEvent, type Ref } from "react";
import { Icon } from "@candleviewer/ui";

/** W-30: the reveal's constant name; `aria-pressed` alone carries its state (C-17, A-9). */
export const REVEAL_NAME = "Show password";
/** CMP-201's own caps-lock string (#2701 ledger addendum A row A20). */
export const CAPS_LOCK = "Caps Lock is on.";

export interface PasswordFieldProps {
  readonly id: string;
  readonly label: string;
  readonly value: string;
  readonly onChange: (value: string) => void;
  readonly autoComplete: "current-password" | "new-password";
  readonly revealed: boolean;
  readonly onRevealedChange: (revealed: boolean) => void;
  /** The field's own error sentence (a W-string), or none. */
  readonly error?: string | null | undefined;
  /** A second sentence under the field, such as W-13 after a refusal cleared it. */
  readonly note?: string | null | undefined;
  /** Ids of nodes that also describe the field (the checklist and the meter). */
  readonly describedBy?: string | undefined;
  readonly readOnly?: boolean | undefined;
  readonly onBlur?: (() => void) | undefined;
  readonly inputRef?: Ref<HTMLInputElement> | undefined;
}

/**
 * CMP-201 PasswordField, the SCR-004 build (E09-D05 §5.1): one reveal per field, the caps-lock
 * warning on the focused field only, paste, drop and autofill never suppressed and no `maxlength`
 * below the contract's 512. The value is never echoed outside the input.
 */
export function PasswordField(props: PasswordFieldProps): JSX.Element {
  const { id, label, value, onChange, autoComplete, revealed, onRevealedChange } = props;
  const { error, note, describedBy, readOnly, onBlur, inputRef } = props;
  const [capsLock, setCapsLock] = useState(false);
  const errorId = `${id}-error`;
  const noteId = `${id}-note`;
  const capsId = `${id}-caps`;
  const ids = [error ? errorId : undefined, note ? noteId : undefined, describedBy, capsId]
    .filter(Boolean)
    .join(" ");
  const readCaps = (event: KeyboardEvent<HTMLInputElement>): void =>
    setCapsLock(event.getModifierState("CapsLock"));

  return (
    <div style={{ display: "grid", gap: "var(--space-stack-xs)" }}>
      <label htmlFor={id}>{label}</label>
      <div style={{ display: "flex", alignItems: "center", gap: "var(--space-inset-xs)" }}>
        <input
          id={id}
          ref={inputRef}
          type={revealed ? "text" : "password"}
          autoComplete={autoComplete}
          autoCapitalize="off"
          spellCheck={false}
          value={value}
          readOnly={readOnly}
          aria-invalid={error ? true : undefined}
          aria-describedby={ids}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={readCaps}
          onKeyUp={readCaps}
          onBlur={() => {
            setCapsLock(false);
            onBlur?.();
          }}
        />
        <button
          type="button"
          aria-pressed={revealed}
          onClick={() => onRevealedChange(!revealed)}
          style={{ minInlineSize: "24px", minBlockSize: "24px" }}
        >
          <Icon name={revealed ? "hide" : "show"} size="sm" />
          <span className="cv-visually-hidden">{REVEAL_NAME}</span>
        </button>
      </div>
      {/* pre-rendered, so the warning is spoken when it appears (CMP-201: polite) */}
      <p id={capsId} role="status" aria-live="polite" style={{ margin: 0 }}>
        {capsLock ? CAPS_LOCK : ""}
      </p>
      {error ? (
        <p id={errorId} style={{ margin: 0, color: "var(--color-text-primary)" }}>
          <span style={{ color: "var(--color-status-danger-strong)" }}>
            <Icon name="error" size="sm" />
          </span>{" "}
          {error}
        </p>
      ) : null}
      {note ? (
        <p id={noteId} style={{ margin: 0, color: "var(--color-text-secondary)" }}>
          {note}
        </p>
      ) : null}
    </div>
  );
}

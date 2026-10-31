import { forwardRef, type JSX } from "react";

/**
 * SCR-002's recovery-code entry (E09-D12 §5.2, D03:150–151), used only when `__CV_MFA_RECOVERY_UI__` is
 * on (#2711 BQ-08 (a)): with the switch off nothing references this module and a production build drops
 * it (pinned by `test/features/auth-mfa-recovery.bundle.test.ts`). Deck strings (`E09-D12-copy.json`
 * `auth.mfa.use_recovery`, `auth.recovery.*`), key_status PROPOSED.
 */
export const RECOVERY_COPY = {
  use: "Use a recovery code instead",
  label: "Recovery code",
  invalid: "That recovery code isn't valid.",
  back: "Back to authenticator code",
} as const;

export interface RecoveryCodeFieldProps {
  readonly value: string;
  readonly onChange: (value: string) => void;
  readonly describedBy?: string | undefined;
  readonly invalid?: boolean;
  /** While verifying: `readOnly` + `aria-disabled`, focus kept. */
  readonly busy?: boolean;
}

/**
 * One labelled text field; never autofilled, never logged. `#__PURE__`: `forwardRef` is a call Rollup
 * would otherwise keep as a possible side effect, so with the switch off the body stayed in the bundle as
 * dead code (#2711 security lens L-1); marked pure, an unreferenced module drops out whole.
 */
export const RecoveryCodeField = /* #__PURE__ */ forwardRef<
  HTMLInputElement,
  RecoveryCodeFieldProps
>(function RecoveryCodeField({ value, onChange, describedBy, invalid, busy }, ref): JSX.Element {
  return (
    <>
      <label htmlFor="mfa-recovery">{RECOVERY_COPY.label}</label>
      <input
        ref={ref}
        id="mfa-recovery"
        type="text"
        autoComplete="off"
        autoCapitalize="none"
        spellCheck={false}
        value={value}
        readOnly={busy}
        aria-disabled={busy ? true : undefined}
        aria-invalid={invalid ? true : undefined}
        aria-describedby={describedBy}
        onChange={(e) => {
          if (!busy) onChange(e.target.value);
        }}
      />
    </>
  );
});

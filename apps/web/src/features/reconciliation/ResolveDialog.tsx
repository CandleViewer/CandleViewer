import { useEffect, useId, useRef, useState, type FormEvent, type JSX } from "react";
import { Button, Dialog, FormField, RbacGate, TextInput } from "@candleviewer/ui";
import { announce } from "../app-shell/announcer";
import { StepUpChallengeGate } from "../stepUp/StepUpChallengeGate";
import type { HeldRequest, StepUpChallenge } from "../stepUp/challenge";
import {
  REASON_MAX,
  readResolve,
  reasonValid,
  resolveRequest,
  sendResolve,
  type ResolveOutcome,
} from "./resolve";

/**
 * The words of the Resolve… flow. `acct.resolve` and `rbac.owner_only` with its verb are the
 * deck's (D03:324, D04:452); the rest is PROPOSED: no merged frame draws the reason field or the
 * outcomes (G-W3 of E29-D06, BQ-10 of 6575172489), each sentence in E09-D09's grammar.
 */
export const RESOLVE_COPY = {
  control: "Resolve…",
  ownerOnlyVerb: "resolve the lock",
  title: "Resolve the lock",
  reason: "Reason",
  help: "3 to 280 characters, kept in the audit record.",
  invalid: "Enter a reason of 3 to 280 characters.",
  submit: "Resolve",
  cancel: "Cancel",
  outcomes: {
    nothing_to_resolve: "Nothing to resolve: this account is not locked.",
    forbidden: "Not sent: only the owner can resolve the lock.",
    not_found: "Not sent: this account is not available.",
    invalid: "Enter a reason of 3 to 280 characters.",
    not_available: "Not sent: resolving is not available yet.",
    unavailable: "Cannot reach the server. Try again.",
  },
} as const;

/** Neutral, as nothing else is known when the answer lands (review fold a11y m5; PROPOSED). */
export const resolvedText = (label: string): string => `Lock resolved for ${label}.`;

export type Role = "owner" | "manager" | "viewer";

export interface ResolveControlProps {
  readonly accountId: string;
  /** "Sub-2 · LIVE": the account as its line names it. */
  readonly accountLabel: string;
  readonly role: Role;
  /** The view-as target while a context is held: `rbac.view_as` comes first (E29-D03 §4.4). */
  readonly viewingAs?: string | null;
  readonly send?: typeof sendResolve;
}

/**
 * "Resolve…" on a stale lock's line (E29-D03 §4.4): the Owner's opens the dialog; a Manager's or
 * Viewer's is T2 `rbac.owner_only` in 2a, and while viewing as anyone `rbac.view_as` comes first
 * (CMP-079 with the CMP-001 atom, `aria-disabled`, never `disabled`).
 */
export function ResolveControl(props: ResolveControlProps): JSX.Element {
  const [open, setOpen] = useState(false);
  const target = props.viewingAs ?? null;
  const button = (
    <Button variant="secondary" size="sm" onClick={() => setOpen(true)}>
      {RESOLVE_COPY.control}
    </Button>
  );
  if (target !== null) {
    return (
      <RbacGate allowed={false} reason="rbac.view_as" fills={{ user: target }}>
        {button}
      </RbacGate>
    );
  }
  if (props.role !== "owner") {
    return (
      <RbacGate
        allowed={false}
        reason="rbac.owner_only"
        fills={{ verb: RESOLVE_COPY.ownerOnlyVerb }}
      >
        {button}
      </RbacGate>
    );
  }
  return (
    <>
      {button}
      <ResolveDialog
        open={open}
        accountId={props.accountId}
        accountLabel={props.accountLabel}
        onClose={() => setOpen(false)}
        {...(props.send === undefined ? {} : { send: props.send })}
      />
    </>
  );
}

export interface ResolveDialogProps {
  readonly open: boolean;
  readonly accountId: string;
  readonly accountLabel: string;
  readonly onClose: () => void;
  readonly send?: typeof sendResolve;
}

interface Challenge {
  readonly challenge: StepUpChallenge;
  readonly held: HeldRequest;
}

/**
 * The reason and the step-up (BQ-10): the Owner writes why, Resolve sends it once with a fresh
 * `Idempotency-Key`. A `403 step_up_required` closes this dialog (one modal at a time) and opens
 * `features/stepUp`'s gate, which re-sends the held request unchanged after the second factor; its
 * answer is said through the shell announcer. A resolve is said politely once and closes the
 * dialog; any other outcome stays in the dialog as an alert, the reason kept.
 */
export function ResolveDialog({
  open,
  accountId,
  accountLabel,
  onClose,
  send = sendResolve,
}: ResolveDialogProps): JSX.Element {
  const id = useId();
  const [reason, setReason] = useState("");
  const [invalid, setInvalid] = useState(false);
  const [outcome, setOutcome] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [stepUp, setStepUp] = useState<Challenge | null>(null);
  // Review fold m2: a send whose answer was `unavailable` is retried as the same request, with
  // its `Idempotency-Key`, for this dialog session; a definite answer or a new reason ends it.
  const retry = useRef<{ readonly reason: string; readonly held: HeldRequest } | null>(null);

  // Opening again drops a challenge left unanswered (the gate said "Not sent") and the last outcome.
  useEffect(() => {
    if (!open) return;
    setStepUp(null);
    setOutcome(null);
  }, [open]);

  const close = (): void => {
    retry.current = null; // the dialog session ends
    setReason("");
    setInvalid(false);
    setOutcome(null);
    onClose();
  };
  const settle = (result: ResolveOutcome, inDialog: boolean, held?: HeldRequest): void => {
    setBusy(false);
    retry.current =
      result.kind === "unavailable" && held !== undefined ? { reason: reason.trim(), held } : null;
    if (result.kind === "resolved") {
      announce("polite", resolvedText(accountLabel), `reconciliation:resolved:${accountId}`);
      close();
      return;
    }
    if (result.kind === "step_up") {
      setStepUp({ challenge: result.challenge, held: result.held });
      onClose();
      return;
    }
    const text = RESOLVE_COPY.outcomes[result.kind];
    if (inDialog) setOutcome(text);
    else announce("assertive", text, `reconciliation:resolve:${accountId}:${result.kind}`);
  };
  const onSubmit = (e: FormEvent): void => {
    e.preventDefault();
    if (busy) return;
    const ok = reasonValid(reason);
    setInvalid(!ok);
    setOutcome(null);
    if (!ok) {
      document.getElementById(`${id}-reason`)?.focus(); // a11y m5: back to the field that is wrong
      return;
    }
    const kept = retry.current;
    const held =
      kept !== null && kept.reason === reason.trim()
        ? kept.held
        : resolveRequest(accountId, reason);
    setBusy(true);
    void send(held).then((result) => settle(result, true, held));
  };

  return (
    <>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          if (!next) close();
        }}
        title={RESOLVE_COPY.title}
        description={accountLabel}
        busy={busy}
        footer={
          <>
            <Button variant="secondary" onClick={close}>
              {RESOLVE_COPY.cancel}
            </Button>
            <Button variant="primary" type="submit" form={`${id}-form`} loading={busy}>
              {RESOLVE_COPY.submit}
            </Button>
          </>
        }
      >
        <form id={`${id}-form`} onSubmit={onSubmit} noValidate>
          <FormField
            label={RESOLVE_COPY.reason}
            htmlFor={`${id}-reason`}
            required
            help={RESOLVE_COPY.help}
            error={invalid ? RESOLVE_COPY.invalid : undefined}
          >
            <TextInput
              id={`${id}-reason`}
              value={reason}
              maxLength={REASON_MAX}
              autoComplete="off"
              onChange={(e) => {
                retry.current = null; // a new reason is a new decision
                setReason(e.target.value);
              }}
            />
          </FormField>
          <p role="alert">{outcome ?? ""}</p>
        </form>
      </Dialog>
      {stepUp === null ? null : (
        <StepUpChallengeGate
          key={stepUp.challenge.challengeId}
          challenge={stepUp.challenge}
          held={stepUp.held}
          onResent={(response) => {
            const held = stepUp.held;
            void readResolve(response, held).then((result) => {
              setStepUp(null);
              // a second challenge on the re-send is not opened again (the invite screen's cap)
              settle(result.kind === "step_up" ? { kind: "forbidden" } : result, false);
            });
          }}
          readBack={() => undefined}
          outcomeWhere="the account's line"
        />
      )}
    </>
  );
}

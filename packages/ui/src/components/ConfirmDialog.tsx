import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type JSX,
  type KeyboardEvent,
  type ReactNode,
  type RefObject,
} from "react";
import { Button } from "./Button.js";
import { Dialog, type DialogCloseReason, type DialogRole, type DialogSize } from "./Dialog.js";
import { ErrorState, type ErrorStateAction } from "./ErrorState.js";
import { FormField } from "./FormField.js";
import { TextInput } from "./TextInput.js";

/** `standard` confirms on one activation; `typed` first asks for an exact token (the hold gates are slice 6's). */
export type ConfirmDialogVariant = "standard" | "typed";
/** The gate the confirm passed, for the host's audit event (E05-S03 plan §3 item 4). */
export type ConfirmGate = "click" | "typed";
/** `danger` for a destructive confirm, the side for an order confirm, `primary` for a context switch (H24). */
export type ConfirmButtonVariant = "danger" | "buy" | "sell" | "primary";
/** Why the dialog cancelled: its Cancel, or the dialog's own `Esc`, scrim press (a `dialog`) or close button. */
export type ConfirmCancelReason = DialogCloseReason | "cancel";

export interface ConfirmMeta {
  readonly variant: ConfirmDialogVariant;
  readonly gate: ConfirmGate;
  /** Milliseconds from the dialog opening to the confirm. */
  readonly elapsedMs: number;
}

/** A partial failure: CMP-027's inline error above the footer, with its Retry. */
export interface ConfirmFailure {
  readonly message: string;
  readonly retry?: ErrorStateAction | undefined;
  readonly details?: string | undefined;
}

export interface ConfirmDialogProps {
  /** Controlled: the host closes the dialog after its outcome, or on `onCancel`. */
  open: boolean;
  /** Called once per accepted activation, past the guard and every gate. */
  onConfirm: (meta: ConfirmMeta) => void;
  /** Cancel, `Esc`, the close button (a `dialog`) or a scrim press (a `dialog`); nothing was sent. */
  onCancel: (reason: ConfirmCancelReason) => void;
  /** The verb and the object, as a question: "Freeze sub_001?". */
  title: string;
  /** The subtitle under the title. */
  message?: ReactNode | undefined;
  /** Default `alertdialog`; `dialog`, with its close button, for an order confirm (SCR-076). */
  role?: DialogRole | undefined;
  /** CMP-043's widths; default `md`. */
  size?: DialogSize | undefined;
  /** The host's name over the title (SCR-076's "Confirm order - BTCUSDT - LIVE - Main"). */
  "aria-label"?: string | undefined;
  /** What the confirm does: the dialog's description, in a "What this does" box. */
  restatement?: ReactNode | undefined;
  /** The restatement's visible group label; `""` renders the restatement as plain text (an order confirm). */
  restatementLabel?: string | undefined;
  /** A fan-out confirm's leg table, the host's. */
  legs?: ReactNode | undefined;
  /** The host's lines above the footer (a step-up line, an audit marker). */
  children?: ReactNode | undefined;
  /** Names the effect ("Freeze sub_001 — cancel 3 working orders"), never "Confirm". */
  confirmLabel: string;
  /** Default "Cancel". */
  cancelLabel?: string | undefined;
  /** Default `danger`. */
  confirmVariant?: ConfirmButtonVariant | undefined;
  /** Default `standard`. */
  variant?: ConfirmDialogVariant | undefined;
  /** `typed`: the exact token (the object's own name, or `FLATTEN` / `LIVE`); paste is allowed. */
  typedConfirmValue?: string | undefined;
  /** `typed`: the field's visible label and Confirm's description; default "Type {token} to confirm". */
  typedInstruction?: string | undefined;
  /** The summary is still loading: Confirm is natively disabled (availability, not T2). */
  summaryLoading?: boolean | undefined;
  /** Activations that begin within this many ms of opening are ignored (default 400; E30-D03 D3 (2)). */
  confirmDelayMs?: number | undefined;
  /** After Confirm: the Confirm `loading`, the field read-only, `aria-busy` on the card. */
  busy?: boolean | undefined;
  /** A partial failure with its Retry, above the footer. */
  failure?: ConfirmFailure | undefined;
  /** The confirm's leg was removed mid-dialog: Confirm takes CMP-001's T2 form, focus stays (H30). */
  confirmDisabledReason?: string | undefined;
  /** Where focus returns when the opener is gone; never `body`. */
  fallbackFocusRef?: RefObject<HTMLElement | null> | undefined;
  /** The clock, ms (`Date.now` by default); injectable for tests. */
  now?: (() => number) | undefined;
}

interface Spoken {
  readonly n: number;
  readonly text: string;
}

const warn = (message: string): void => {
  if (import.meta.env?.DEV) console.warn(`ConfirmDialog: ${message}`);
};

const isActivationKey = (key: string): boolean => key === "Enter" || key === " ";

/** A held key repeats: the repeat never activates (the first press is the one that counts). */
const ignoreRepeat = (event: KeyboardEvent<HTMLButtonElement>): void => {
  if (event.repeat && isActivationKey(event.key)) event.preventDefault();
};

/**
 * CMP-044: a confirm gate on CMP-043 (APG Alert Dialog; APG Dialog (Modal) for an order confirm). Focus opens
 * on Cancel and Tab runs in DOM order from there: Confirm, the close button (a `dialog`), the body. Confirm
 * ignores any press (Enter, Space or a pointer) that begins in the first `confirmDelayMs` after opening, and
 * every key repeat. `typed`: Confirm stays natively disabled until the summary has loaded and the field matches
 * the token exactly (form validity, not T2); `Enter` in the field never confirms. A reason given mid-dialog
 * turns Confirm into CMP-001's T2 form in place, with one assertive announcement when it held focus.
 */
export function ConfirmDialog({
  open,
  onConfirm,
  onCancel,
  title,
  message,
  role = "alertdialog",
  size = "md",
  "aria-label": label,
  restatement,
  restatementLabel = "What this does",
  legs,
  children,
  confirmLabel,
  cancelLabel = "Cancel",
  confirmVariant = "danger",
  variant = "standard",
  typedConfirmValue,
  typedInstruction,
  summaryLoading = false,
  confirmDelayMs = 400,
  busy = false,
  failure,
  confirmDisabledReason,
  fallbackFocusRef,
  now = Date.now,
}: ConfirmDialogProps): JSX.Element | null {
  const id = useId();
  const confirmId = `${id}-confirm`;
  const restatementId = `${id}-restatement`;
  const restatementLabelId = `${id}-restatement-label`;
  const instructionId = `${id}-instruction`;
  const cancelRef = useRef<HTMLSpanElement | null>(null);
  /** When the dialog opened, by `now`; null while closed. */
  const openedAt = useRef<number | null>(null);
  /** When the press that will become Confirm's click began (pointer down, or the first key down). */
  const pressedAt = useRef<number | null>(null);
  const [typed, setTyped] = useState("");
  const [polite, setPolite] = useState<Spoken>({ n: 0, text: "" });
  const [assertive, setAssertive] = useState<Spoken>({ n: 0, text: "" });
  const clock = useRef(now);
  clock.current = now;

  const trimmedReason = confirmDisabledReason?.trim();
  const reason = trimmedReason === undefined || trimmedReason === "" ? undefined : trimmedReason;
  const isTyped = variant === "typed";
  const token = typedConfirmValue ?? "";
  const matched = !isTyped || (token !== "" && typed === token);
  const ready = !summaryLoading && matched;
  const instruction = typedInstruction ?? `Type ${token} to confirm`;

  useLayoutEffect(() => {
    openedAt.current = open ? clock.current() : null;
    pressedAt.current = null;
    if (open) {
      setTyped("");
      setPolite({ n: 0, text: "" });
      setAssertive({ n: 0, text: "" });
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    if (confirmLabel.trim().toLowerCase() === "confirm")
      warn('confirmLabel names the effect, never "Confirm" (H24).');
    if (isTyped && token === "") warn("variant typed needs a non-empty typedConfirmValue.");
  }, [open, confirmLabel, isTyped, token]);

  // H30: gated mid-dialog while Confirm held focus, one assertive announcement; focus stays.
  const wasGated = useRef(reason !== undefined);
  useEffect(() => {
    const before = wasGated.current;
    wasGated.current = reason !== undefined;
    if (reason === undefined || before || !open) return;
    if (document.activeElement?.id === confirmId)
      setAssertive((s) => ({ n: s.n + 1, text: reason }));
  }, [reason, open, confirmId]);

  const startPress = (): void => {
    pressedAt.current = clock.current();
  };

  const confirm = (): void => {
    const at = clock.current();
    const started = pressedAt.current ?? at;
    pressedAt.current = null;
    const opened = openedAt.current;
    // The guard: a press that began before `confirmDelayMs` had passed does nothing, whenever it lands.
    if (opened === null || started - opened < confirmDelayMs) return;
    if (!ready || busy || reason !== undefined) return;
    onConfirm({ variant, gate: isTyped ? "typed" : "click", elapsedMs: at - opened });
  };

  const footer = (
    <>
      {/* The initial focus target: Dialog focuses the first tab stop inside a ref that is none. */}
      <span ref={cancelRef} className="cv-confirm__cancel">
        <Button onKeyDown={ignoreRepeat} onClick={() => onCancel("cancel")}>
          {cancelLabel}
        </Button>
      </span>
      <Button
        id={confirmId}
        variant={confirmVariant}
        disabled={!ready}
        {...(reason === undefined ? {} : { disabledReason: reason })}
        {...(isTyped ? { "aria-describedby": instructionId } : {})}
        loading={busy}
        onKeyDown={(event) => {
          if (!isActivationKey(event.key)) return;
          if (event.repeat) {
            event.preventDefault();
            return;
          }
          startPress();
        }}
        onPointerDown={startPress}
        onPointerCancel={() => {
          pressedAt.current = null;
        }}
        onBlur={() => {
          pressedAt.current = null;
        }}
        onClickCapture={() => {
          // T2: Enter, Space or a press re-shows the reason with one polite announcement (D09 §9.3).
          if (reason !== undefined) setPolite((s) => ({ n: s.n + 1, text: reason }));
        }}
        onClick={confirm}
      >
        {confirmLabel}
      </Button>
      {reason === undefined ? null : (
        // Visible for a sighted user; the accessible description is CMP-001's own reason node.
        <p className="cv-confirm__reason" aria-hidden="true">
          {reason}
        </p>
      )}
    </>
  );

  const hasRestatement = restatement !== undefined && restatement !== null && restatement !== false;
  const grouped = restatementLabel !== "";

  return (
    <Dialog
      open={open}
      onOpenChange={(next, why) => {
        if (!next) onCancel(why);
      }}
      title={title}
      {...(message === undefined ? {} : { description: message })}
      size={size}
      role={role}
      {...(label === undefined ? {} : { "aria-label": label })}
      {...(hasRestatement ? { "aria-describedby": restatementId } : {})}
      initialFocusRef={cancelRef}
      {...(fallbackFocusRef === undefined ? {} : { fallbackFocusRef })}
      busy={busy}
      footer={footer}
    >
      <div
        className="cv-confirm"
        data-cmp="CMP-044"
        data-variant={variant}
        data-busy={busy ? "" : undefined}
      >
        {hasRestatement ? (
          <div
            id={restatementId}
            className="cv-confirm__restatement"
            role={grouped ? "group" : undefined}
            aria-labelledby={grouped ? restatementLabelId : undefined}
          >
            {grouped ? (
              <p id={restatementLabelId} className="cv-confirm__restatement-label">
                {restatementLabel}
              </p>
            ) : null}
            {restatement}
          </div>
        ) : null}
        {legs}
        {children}
        {isTyped ? (
          <FormField label={instruction} labelId={instructionId}>
            <TextInput
              value={typed}
              readOnly={busy}
              autoComplete="off"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck={false}
              onChange={(event) => setTyped(event.currentTarget.value)}
              onKeyDown={(event) => {
                // Enter in the field never confirms, nor submits a host form (E42-D02 D18).
                if (event.key === "Enter") event.preventDefault();
              }}
            />
          </FormField>
        ) : null}
        {failure === undefined ? null : (
          <ErrorState
            form="inline"
            message={failure.message}
            {...(failure.retry === undefined ? {} : { retry: failure.retry })}
            {...(failure.details === undefined ? {} : { details: failure.details })}
          />
        )}
        <span role="status" className="cv-visually-hidden">
          {polite.text === "" ? null : <span key={polite.n}>{polite.text}</span>}
        </span>
        <span role="alert" className="cv-visually-hidden">
          {assertive.text === "" ? null : <span key={assertive.n}>{assertive.text}</span>}
        </span>
      </div>
    </Dialog>
  );
}

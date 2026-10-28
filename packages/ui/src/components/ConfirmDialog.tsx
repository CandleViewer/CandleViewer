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
  /**
   * Called at most once per opening, past the guard and every gate; a new `failure` message or `busy` going
   * false re-allows one more (a host's Retry path). The host still sets `busy` at once.
   */
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
  /**
   * Activations that begin within this many ms of opening are ignored (default and floor 400; E30-D03 D3 (2)).
   * A smaller or non-finite value is raised to 400 with a dev warning: no prop turns the guard off (C-4.14).
   * The window rearms when Confirm becomes available (a typed match, the summary loaded, a reason cleared) and
   * when the title or Confirm's label changes while open.
   */
  confirmDelayMs?: number | undefined;
  /** After Confirm: the Confirm `loading`, the field read-only, `aria-busy` on the card. */
  busy?: boolean | undefined;
  /** A partial failure with its Retry, above the footer. */
  failure?: ConfirmFailure | undefined;
  /** The confirm's leg was removed mid-dialog: Confirm takes CMP-001's T2 form, focus stays (H30). */
  confirmDisabledReason?: string | undefined;
  /** Where focus returns when the opener is gone; never `body`. */
  fallbackFocusRef?: RefObject<HTMLElement | null> | undefined;
  /** The clock, ms (monotonic `performance.now` by default); injectable for tests. */
  now?: (() => number) | undefined;
}

interface Spoken {
  readonly n: number;
  readonly text: string;
}

const warn = (message: string): void => {
  if (import.meta.env?.DEV) console.warn(`ConfirmDialog: ${message}`);
};

/** The guard's floor and default, ms (E30-D03 D3 (2)). */
const CONFIRM_DELAY_FLOOR_MS = 400;

const monotonic = (): number => performance.now();

const isActivationKey = (key: string): boolean => key === "Enter" || key === " ";

/**
 * Key handlers for a footer button: a held key's repeats never activate, and a `Space` released on the
 * button activates only when its own non-repeat `Space` press began there (browsers click on `Space` keyup).
 */
const useKeyGuard = (
  onPress?: () => void,
): {
  onKeyDown: (event: KeyboardEvent<HTMLButtonElement>) => void;
  onKeyUp: (event: KeyboardEvent<HTMLButtonElement>) => void;
} => {
  const spaceDown = useRef(false);
  return {
    onKeyDown: (event) => {
      if (!isActivationKey(event.key)) return;
      if (event.repeat) {
        event.preventDefault();
        return;
      }
      if (event.key === " ") spaceDown.current = true;
      onPress?.();
    },
    onKeyUp: (event) => {
      if (event.key !== " ") return;
      if (!spaceDown.current) event.preventDefault();
      spaceDown.current = false;
    },
  };
};

/**
 * CMP-044: a confirm gate on CMP-043 (APG Alert Dialog; APG Dialog (Modal) for an order confirm). Focus opens
 * on Cancel and Tab runs in DOM order from there: Confirm, the close button (a `dialog`), the body. Confirm
 * ignores any press (Enter, Space or a pointer) that begins in the first `confirmDelayMs` after opening (or
 * after it rearms), the click that ends such a press however late, and every key repeat; it fires once. `typed`: Confirm stays natively disabled until the summary has loaded and the field matches
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
  now = monotonic,
}: ConfirmDialogProps): JSX.Element | null {
  const id = useId();
  const confirmId = `${id}-confirm`;
  const restatementId = `${id}-restatement`;
  const restatementLabelId = `${id}-restatement-label`;
  const instructionId = `${id}-instruction`;
  const cancelRef = useRef<HTMLSpanElement | null>(null);
  /** When the dialog opened, by `now`; null while closed. */
  const openedAt = useRef<number | null>(null);
  /** When the guard window last (re)started: the opening, Confirm becoming available, a new intent. */
  const armedAt = useRef<number | null>(null);
  /**
   * A press began on Confirm inside the guard window: the click that ends it is rejected, whenever it lands
   * and whatever blur or pointercancel came between. Cleared by that click or by a press begun after the window.
   */
  const tripped = useRef(false);
  /** onConfirm already ran for this opening (the single-fire latch). */
  const fired = useRef(false);
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
  const available = ready && reason === undefined;
  const delayMs = Number.isFinite(confirmDelayMs)
    ? Math.max(confirmDelayMs, CONFIRM_DELAY_FLOOR_MS)
    : CONFIRM_DELAY_FLOOR_MS;
  const failureKey = failure === undefined ? null : failure.message;

  useLayoutEffect(() => {
    openedAt.current = open ? clock.current() : null;
    armedAt.current = openedAt.current;
    tripped.current = false;
    fired.current = false;
    if (open) {
      setTyped("");
      setPolite({ n: 0, text: "" });
      setAssertive({ n: 0, text: "" });
    }
  }, [open]);

  // Rearm the guard when Confirm becomes available or its intent changes under an open dialog.
  useLayoutEffect(() => {
    if (open && available) armedAt.current = clock.current();
  }, [open, available, title, confirmLabel]);

  // A new failure, or the host's busy ending, re-allows one confirm (a Retry-less host's second try).
  const wasBusy = useRef(busy);
  useLayoutEffect(() => {
    const before = wasBusy.current;
    wasBusy.current = busy;
    if (before && !busy) fired.current = false;
  }, [busy]);
  useLayoutEffect(() => {
    fired.current = false;
  }, [failureKey]);

  useEffect(() => {
    if (!open) return;
    if (confirmLabel.trim().toLowerCase() === "confirm")
      warn('confirmLabel names the effect, never "Confirm" (H24).');
    if (isTyped && token === "") warn("variant typed needs a non-empty typedConfirmValue.");
    if (delayMs !== confirmDelayMs)
      warn(`confirmDelayMs below ${String(CONFIRM_DELAY_FLOOR_MS)} ms is raised to it.`);
  }, [open, confirmLabel, isTyped, token, delayMs, confirmDelayMs]);

  // H30: gated mid-dialog while Confirm held focus, one assertive announcement; focus stays.
  const wasGated = useRef(reason !== undefined);
  useEffect(() => {
    const before = wasGated.current;
    wasGated.current = reason !== undefined;
    if (reason === undefined || before || !open) return;
    if (document.activeElement?.id === confirmId)
      setAssertive((s) => ({ n: s.n + 1, text: reason }));
  }, [reason, open, confirmId]);

  const inWindow = (at: number): boolean =>
    armedAt.current === null || at - armedAt.current < delayMs;

  const startPress = (): void => {
    tripped.current = inWindow(clock.current());
  };

  const confirm = (): void => {
    const at = clock.current();
    const opened = openedAt.current;
    // The guard: a press that began in the window does nothing, whenever it lands; so does a click in it.
    const rejected = tripped.current || inWindow(at);
    tripped.current = false;
    if (opened === null || rejected || fired.current) return;
    // `busy` and T2 are Button's too (it drops the click); kept here as defence in depth.
    if (!ready || busy || reason !== undefined) return;
    fired.current = true;
    onConfirm({ variant, gate: isTyped ? "typed" : "click", elapsedMs: at - opened });
  };

  const cancelKeys = useKeyGuard();
  const confirmKeys = useKeyGuard(startPress);

  const footer = (
    <>
      {/* The initial focus target: Dialog focuses the first tab stop inside a ref that is none. */}
      <span ref={cancelRef} className="cv-confirm__cancel">
        <Button {...cancelKeys} onClick={() => onCancel("cancel")}>
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
        {...confirmKeys}
        onPointerDown={startPress}
        onClickCapture={() => {
          // T2: Enter, Space or a press re-shows the reason with one polite announcement (D09 §9.3).
          if (reason !== undefined) setPolite((s) => ({ n: s.n + 1, text: reason }));
        }}
        onClick={confirm}
      >
        {confirmLabel}
      </Button>
      {reason === undefined ? null : (
        // H30 (a): the host's reason under the footer (15 CMP-044 States), besides CMP-001's echo; the
        // accessible description is CMP-001's own reason node.
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

import {
  useState,
  type ClipboardEvent,
  type FocusEvent,
  type JSX,
  type KeyboardEvent,
  type MouseEvent,
  type RefObject,
} from "react";
import { Icon } from "../../icons/Icon.js";
import type { DisabledReasonAttrs } from "./disabledReason.js";

/**
 * Behaviour shared by the field atoms that draw the `.cv-field` well (TextInput, NumericStepperInput, Select),
 * so the message line, the gated refusal and the hit target stay in one place.
 */

/**
 * The message line: always in the DOM (a polite live region announces swapped-in text once), the `danger` glyph
 * then the sentence while a message is given. Validity without a sentence is the host's to supply (CMP-040).
 */
export function FieldMessage({
  id,
  message,
}: {
  readonly id: string;
  readonly message: string | undefined;
}): JSX.Element {
  const shown = message !== undefined && message !== "";
  return (
    <div id={id} className="cv-field__message" aria-live="polite">
      {shown ? (
        <>
          <span className="cv-field__glyph">
            <Icon name="danger" />
          </span>
          <span>{message}</span>
        </>
      ) : null}
    </div>
  );
}

/** A press on the well's padding or an affix focuses the field; the primary button only, so selection and menus work. */
export function focusFieldInput(
  event: MouseEvent<HTMLElement>,
  inputRef: RefObject<HTMLElement | null>,
): void {
  if (event.button !== 0 || event.target === inputRef.current) return;
  event.preventDefault();
  inputRef.current?.focus();
}

/** Keys that edit while the field is gated: refused, and announced once per focus visit. Arrows, Home/End, copy stay free. */
const REFUSED_KEYS = new Set(["Enter", "Backspace", "Delete"]);
const isRefusedKey = (event: KeyboardEvent, extra: ReadonlySet<string>): boolean =>
  REFUSED_KEYS.has(event.key) ||
  (event.key.length === 1 && !event.ctrlKey && !event.metaKey) ||
  // A key that would act on a widget (a Select's arrows) is refused plain only: a chord is the host's.
  (extra.has(event.key) && !event.ctrlKey && !event.metaKey && !event.altKey && !event.shiftKey);

const NO_KEYS: ReadonlySet<string> = new Set();

export interface RefusalCallers<E extends HTMLElement = HTMLInputElement> {
  readonly onKeyDown?: ((event: KeyboardEvent<E>) => void) | undefined;
  readonly onBlur?: ((event: FocusEvent<E>) => void) | undefined;
  readonly onPaste?: ((event: ClipboardEvent<E>) => void) | undefined;
  readonly onCut?: ((event: ClipboardEvent<E>) => void) | undefined;
}

/**
 * T2 refusal: while gated a refused key (and paste or cut) changes nothing, Enter never submits the host form, and
 * the reason is announced once per focus visit through a polite status node that exists only while gated.
 * Tab and Esc are never touched. The caller's handlers run first. `extra` adds the keys a non-text widget
 * refuses: a set of plain keys (a Select's arrows and Home/End) or a predicate (the stepper's step keys).
 * `refuse()` is the same refusal for a press that is not a key.
 */
export function useRefusalAnnounce<E extends HTMLElement = HTMLInputElement>(
  reason: DisabledReasonAttrs,
  callers: RefusalCallers<E>,
  extra: ReadonlySet<string> | ((event: KeyboardEvent<E>) => boolean) = NO_KEYS,
): {
  readonly handlers: Required<RefusalCallers<E>>;
  readonly refuse: () => void;
  readonly status: JSX.Element | null;
} {
  const [spoken, setSpoken] = useState(false);
  const { gated } = reason;
  return {
    handlers: {
      onKeyDown: (event) => {
        callers.onKeyDown?.(event);
        const refused =
          typeof extra === "function" ? isRefusedKey(event, NO_KEYS) || extra(event) : isRefusedKey(event, extra);
        if (!gated || !refused) return;
        // readonly stops the edit, not implicit form submission or an unlisted default: stop them here.
        event.preventDefault();
        setSpoken(true);
      },
      onBlur: (event) => {
        setSpoken(false);
        callers.onBlur?.(event);
      },
      onPaste: (event) => {
        callers.onPaste?.(event);
        if (gated) setSpoken(true);
      },
      onCut: (event) => {
        callers.onCut?.(event);
        if (gated) setSpoken(true);
      },
    },
    refuse: () => {
      if (gated) setSpoken(true);
    },
    status: gated ? (
      <span className="cv-visually-hidden" role="status">
        {spoken ? reason.reason : ""}
      </span>
    ) : null,
  };
}

import {
  useLayoutEffect,
  useRef,
  useState,
  type ChangeEvent,
  type FocusEvent,
  type JSX,
  type KeyboardEvent,
  type MouseEvent,
  type ReactNode,
} from "react";
import { Icon } from "../../icons/Icon.js";
import type { DisabledReasonAttrs } from "./disabledReason.js";
import { useRefusalAnnounce } from "./fieldParts.js";
import { ReasonEcho } from "./ReasonEcho.js";

export interface EntryWellProps {
  readonly id?: string | undefined;
  readonly name?: string | undefined;
  /** The committed value in its canonical form, or null when empty. */
  readonly value: string | null;
  /** Typed text (trimmed, not empty) in its canonical form, or null when it does not parse. */
  readonly parse: (text: string) => string | null;
  /** The sentence for text that does not parse. */
  readonly parseError: string;
  /** The sentence for a parsed value the host does not allow (out of range), or null. */
  readonly check?: ((value: string) => string | null) | undefined;
  /** A parsed, allowed entry, or null for an emptied field. Never an invalid entry. */
  readonly onCommit: (value: string | null) => void;
  /** The typed error now shown (or null), for the picker's one message line. */
  readonly onError: (error: string | null) => void;
  readonly placeholder?: string | undefined;
  /** The input's width in characters (a time field); without it the input fills the well. */
  readonly size?: number | undefined;
  readonly "aria-label"?: string | undefined;
  readonly "aria-labelledby"?: string | undefined;
  readonly "aria-describedby"?: string | undefined;
  readonly required?: true | undefined;
  /** The well's invalid look and `aria-invalid`. */
  readonly invalid: boolean;
  readonly reason: DisabledReasonAttrs;
  /** The T2 echo over the input; undefined when the field's line carries the reason. */
  readonly echo: string | undefined;
  readonly readOnly: boolean;
  /** The "UTC" suffix's id: the input's description references it. */
  readonly suffixId: string;
  /** Alt+ArrowDown in the field (the calendar). */
  readonly onOpen?: (() => void) | undefined;
  readonly onBlur?: ((event: FocusEvent<HTMLInputElement>) => void) | undefined;
  /** Drawn flush at the well's end, after the suffix (the calendar button). */
  readonly trail?: ReactNode;
  readonly className?: string | undefined;
}

/** Text the user typed and has not committed; `base` is the value it was typed against. */
interface Edit {
  readonly text: string;
  readonly base: string | null;
  readonly error: string | null;
}

/**
 * One CMP-047 typed well (a date or a time): the CMP-007 well with a "UTC" suffix, text parsed on blur or Enter and
 * never clamped (conventions 23). Unparsable or disallowed text keeps its words and its error and commits nothing;
 * an emptied field commits null. T2 (conventions 24): the CMP-019 lock leads the value, the input is read-only and
 * a refused key speaks the reason once per visit.
 */
export function EntryWell({
  id,
  name,
  value,
  parse,
  parseError,
  check,
  onCommit,
  onError,
  placeholder,
  size,
  "aria-label": ariaLabel,
  "aria-labelledby": labelledBy,
  "aria-describedby": describedBy,
  required,
  invalid,
  reason,
  echo,
  readOnly,
  suffixId,
  onOpen,
  onBlur,
  trail,
  className,
}: EntryWellProps): JSX.Element {
  const ref = useRef<HTMLInputElement>(null);
  const [typed, setTyped] = useState<Edit | null>(null);
  const frozen = reason.gated || reason.disabled || readOnly;
  // An edit belongs to the value it was typed against: a host that moves the value discards it.
  const edit = typed !== null && typed.base === value ? typed : null;
  const error = edit?.error ?? null;

  const report = useRef(onError);
  // The latest callback, kept outside render; declared before the effect below so it runs first.
  useLayoutEffect(() => {
    report.current = onError;
  });
  useLayoutEffect(() => {
    report.current(error);
  }, [error]);
  useLayoutEffect(() => () => report.current(null), []);

  /** The verdict on typed text: null when it can be committed (empty commits null). */
  const judge = (text: string): string | null => {
    const trimmed = text.trim();
    if (trimmed === "") return null;
    const parsed = parse(trimmed);
    if (parsed === null) return parseError;
    return check?.(parsed) ?? null;
  };

  const commit = (text: string): void => {
    const verdict = judge(text);
    if (verdict !== null) {
      setTyped({ text, base: value, error: verdict });
      return;
    }
    setTyped(null);
    const trimmed = text.trim();
    const next = trimmed === "" ? null : parse(trimmed);
    if (next !== value) onCommit(next);
  };

  const refusal = useRefusalAnnounce<HTMLInputElement>(
    reason,
    {
      onKeyDown: (event: KeyboardEvent<HTMLInputElement>) => {
        if (frozen || event.nativeEvent.isComposing) return;
        if (event.key === "ArrowDown" && event.altKey && onOpen !== undefined) {
          event.preventDefault();
          onOpen();
        } else if (event.key === "Enter" && edit !== null) {
          // A host form's implicit submit would read the value before this commit renders.
          event.preventDefault();
          commit(edit.text);
        }
      },
      onBlur: (event: FocusEvent<HTMLInputElement>) => {
        // An edit under way when the field became gated or read-only is discarded, not committed.
        if (frozen) setTyped(null);
        else if (edit !== null) commit(edit.text);
        onBlur?.(event);
      },
    },
    (event) => event.altKey && event.key === "ArrowDown",
  );

  const onInput = (event: ChangeEvent<HTMLInputElement>): void => {
    // A shown error keeps its words until the text is valid, then clears silently (conventions 23).
    const text = event.target.value;
    const stays = error !== null && judge(text) !== null;
    setTyped({ text, base: value, error: stays ? error : null });
  };

  /**
   * A press on the well's padding or the suffix focuses the field; a press on a button stays the button's. A
   * portaled calendar's presses bubble here through React: a press outside this well's DOM is left alone.
   */
  const forward = (event: MouseEvent<HTMLDivElement>): void => {
    if (event.button !== 0 || !(event.target instanceof Element)) return;
    if (!event.currentTarget.contains(event.target)) return;
    if (event.target === ref.current || event.target.closest("button") !== null) return;
    event.preventDefault();
    ref.current?.focus();
  };

  return (
    <>
      {/* The mouse handler only forwards a press to the input; the input is the keyboard and AT target. */}
      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions -- see above: not a widget */}
      <div
        className={className === undefined ? "cv-field" : `cv-field ${className}`}
        data-invalid={invalid ? "" : undefined}
        data-gated={reason.gated ? "" : undefined}
        data-disabled={reason.disabled ? "" : undefined}
        data-readonly={readOnly ? "" : undefined}
        data-lead={reason.gated ? "" : undefined}
        data-trail=""
        onMouseDown={forward}
      >
        {reason.gated ? (
          <span className="cv-field__lead cv-field__lock">
            <Icon name="lock" decorative={false} label="Not available" />
          </span>
        ) : null}
        <ReasonEcho text={echo}>
          <input
            id={id}
            ref={ref}
            name={name}
            type="text"
            inputMode="numeric"
            autoComplete="off"
            spellCheck={false}
            className="cv-field__input"
            size={size}
            placeholder={placeholder}
            value={edit?.text ?? value ?? ""}
            disabled={reason.disabled}
            readOnly={readOnly || reason.gated}
            aria-label={ariaLabel}
            aria-labelledby={labelledBy}
            aria-disabled={reason.ariaDisabled}
            aria-invalid={invalid ? true : undefined}
            aria-required={required}
            aria-describedby={describedBy}
            onChange={onInput}
            {...refusal.handlers}
          />
        </ReasonEcho>
        {/*
          Spoken through the field's description (by reference), so hidden from the reading order. Plain disabled it
          dims with the well: inactive text (WCAG 1.4.3), marked so as the input is.
        */}
        <span
          id={suffixId}
          className="cv-field__trail cv-field__affix"
          aria-hidden="true"
          aria-disabled={reason.disabled ? true : undefined}
        >
          UTC
        </span>
        {trail}
      </div>
      {refusal.status}
    </>
  );
}

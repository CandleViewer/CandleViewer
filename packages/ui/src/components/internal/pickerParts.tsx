import type { JSX, ReactNode, RefObject } from "react";
import { IconButton } from "../IconButton.js";
import { Popover } from "../Popover.js";
import type { DisabledReasonAttrs } from "./disabledReason.js";

/** Shared by CMP-047's two forms (DatePicker, DateRangePicker). */

export const DEFAULT_HINT = "YYYY-MM-DD";
export const TIME_HINT = "HH:MM";
export const TIME_ERROR = `Enter a time as ${TIME_HINT}, 24-hour UTC.`;

/** The sentence for `min`-`max` when the host gives none. */
export function composeCaption(min: string | null, max: string | null): string | undefined {
  if (min !== null && max !== null) return `Choose a date from ${min} to ${max}.`;
  if (min !== null) return `Choose a date on or after ${min}.`;
  if (max !== null) return `Choose a date on or before ${max}.`;
  return undefined;
}

export interface CalendarButtonProps {
  readonly label: string;
  readonly open: boolean;
  readonly onOpen: () => void;
  readonly onClose: () => void;
  readonly headingId: string;
  readonly initialFocusRef: RefObject<HTMLElement | null>;
  readonly reason: DisabledReasonAttrs;
  readonly readOnly: boolean;
  readonly density?: "comfortable" | "compact" | undefined;
  readonly children: ReactNode;
}

/**
 * The CMP-002 ghost calendar button, flush at a well's end, and the modal CMP-017 Popover it opens, named by the
 * month heading. T2: the button is `aria-disabled` with the reason; read-only or plain disabled: natively disabled.
 */
export function CalendarButton({
  label,
  open,
  onOpen,
  onClose,
  headingId,
  initialFocusRef,
  reason,
  readOnly,
  density,
  children,
}: CalendarButtonProps): JSX.Element {
  return (
    <Popover
      modal
      open={open}
      onOpenChange={(next) => (next ? onOpen() : onClose())}
      aria-labelledby={headingId}
      initialFocusRef={initialFocusRef}
      className="cv-datepicker__dialog"
      anchor={
        <IconButton
          icon="calendar"
          label={label}
          variant="ghost"
          {...(density === undefined ? {} : { density })}
          {...(reason.reason === undefined ? {} : { disabledReason: reason.reason })}
          disabled={reason.disabled || (readOnly && !reason.gated)}
        />
      }
    >
      {children}
    </Popover>
  );
}

import { createContext } from "react";
import type { DisabledReasonAttrs } from "./disabledReason.js";

/**
 * What CMP-065 FormSection hands the CMP-040 FormFields inside it (D02F CMP-065, conventions 24). Internal: the
 * fields read the section's gate (one notice, many pointers) and report whether they show an error, so a collapsed
 * section can count its problems and open on submit.
 */
export interface SectionContextValue {
  /** The section's gate: T2, whose `reasonId` is the one notice's id, or plain disabled (`<fieldset disabled>`). */
  readonly reason: DisabledReasonAttrs;
  /** A field reports whether it shows an error, keyed by its control id; it reports `false` on unmount. */
  readonly reportInvalid: (key: string, invalid: boolean) => void;
}

export const SectionContext = createContext<SectionContextValue | null>(null);

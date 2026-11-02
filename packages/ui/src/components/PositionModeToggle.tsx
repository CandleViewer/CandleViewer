import type { JSX } from "react";

/** The account's position mode (Bybit `positionIdx` 0 is one-way; 1 and 2 are hedge). */
export type PositionMode = "one-way" | "hedge";

/** The words E29-D04 §2.5 draws (frames `CMP-129/display-one-way`, `CMP-129/display-hedge`). */
const WORDS: Readonly<Record<PositionMode, string>> = { "one-way": "One-way", hedge: "Hedge" };

export interface PositionModeToggleProps {
  /** The mode from `ExchangeAccount.position_mode` (REST), read by the host. */
  readonly value: PositionMode;
  /**
   * Only `display` is built (E29-S01, BQ-23): the mode as text in SCR-063's account group header, no control, no
   * reason. The `toggle` variant (CMP-003 behind a CMP-044 confirm) has no E29 surface and ships with the ticket
   * that hosts it (E29-D06 §11).
   */
  readonly variant?: "display";
}

/**
 * CMP-129 PositionModeToggle, `display` variant (E29-D04 §2.5, D04H §C.4): the word "One-way" or "Hedge" as plain
 * text. It takes no Tab stop, exposes no control role and never speaks: its accessible name is the word itself,
 * read in its host's line. A mode change is a cut (Mo-8); nothing moves.
 */
export function PositionModeToggle({ value }: PositionModeToggleProps): JSX.Element {
  return (
    <span className="cv-position-mode" data-cmp="CMP-129" data-variant="display" data-mode={value}>
      {WORDS[value]}
    </span>
  );
}

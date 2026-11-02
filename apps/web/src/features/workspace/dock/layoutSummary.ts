/**
 * The polite summaries a layout commit says (E15-D15 SR-01, SR-05, SR-09, SR-10), one per commit.
 * The centre drop's words are not in SR-05 ("its grammar for the centre drop"): PROPOSED here.
 */
import type { Zone } from "@candleviewer/dock";

const SIDE: Readonly<Record<Exclude<Zone, "centre">, string>> = {
  left: "to the left of",
  right: "to the right of",
  top: "above",
  bottom: "below",
};

export const layoutSummary = {
  /** SR-01: "Layout changed to Order-flow, 4 panels." */
  presetApplied: (name: string, panes: number): string =>
    `Layout changed to ${name}, ${panes} ${panes === 1 ? "panel" : "panels"}.`,
  /** SR-05: "Positions moved below Chart." */
  moved: (name: string, target: string, zone: Zone): string =>
    zone === "centre"
      ? `${name} moved to a tab with ${target}.`
      : `${name} moved ${SIDE[zone]} ${target}.`,
  /** SR-09. */
  maximised: (name: string): string => `${name} maximised.`,
  restored: (name: string): string => `${name} restored.`,
  poppedOut: (name: string): string => `${name} popped out to its own window.`,
  returned: (name: string): string => `${name} returned to the workspace.`,
  /** SR-10: "Tape closed." */
  closed: (name: string): string => `${name} closed.`,
};

/**
 * The statechart inspector's words (E42-S08). Keyed strings are verbatim from E42-D05 §15
 * (`machine.*`, `admin.*`) and §11's anatomy (its column and control names). The rest have no deck
 * key: each is marked PROPOSED (owner E42-D05) and listed in `14`'s As-built line.
 */
export const INSPECTOR_COPY = {
  /** `machine.current`. */
  current: "current",
  /** The chart's text list (§4.2), the normative non-visual equivalent of the drawing. */
  chart: {
    /** PROPOSED: the list's two headings. */
    states: "States",
    transitions: "Transitions",
    /** PROPOSED: a parallel root's top-level states are its regions, all active together. */
    parallelRoot: "The top-level states run in parallel.",
    /**
     * PROPOSED: the source of the root's own transitions. The library takes the deepest source
     * first, so a root arm applies only where the active state does not handle the event itself.
     */
    anyState: "Any state that doesn't handle it itself",
    /** PROPOSED: a state's markers, each read as "(initial)". */
    initial: "initial",
    final: "final",
    parallel: "parallel",
    /** PROPOSED: the words after the arrow, which is hidden from assistive technology. */
    to: "to",
    on: (event: string): string => `on ${event}`,
    always: "(always)",
    after: (delay: string): string => `after ${delay}`,
    done: (service: string): string => `when ${service} is done`,
    error: (service: string): string => `when ${service} fails`,
    /** PROPOSED: an arm with no target, such as a guard's refusal arm. */
    noChange: "no state change",
  },
} as const;

// E22-S01 (#714) PR-B: the pause model of D02 §5 (P1-P14) and D04 §9 (FP-01..FP-12) as a plain
// reducer, not a statechart (D04 §4; the tape is a hot path, C-2.20). Every pause is one list state
// with four layers; the list is live only when no layer holds. A resume is an insertion under a
// divider, never a replay (D4-05); the controller performs it from the `insert` the step returns.
//
// The layers: `soft` (hover intent, P1-P3), `scroll` (away from the live edge, P4-P5), `hard` (`P`
// or the button, P6-P7) and `focus` (a row holds the roving cursor, P8-P9). A row focus wins over
// the hover and park exits (P2 / P3 guards) and takes a soft or scroll pause over (P8).

export type PauseCause = "hover" | "scroll" | "key" | "button" | "focus";
export type ResumeCause = "leave" | "park" | "jump" | "key" | "button" | "esc" | "blur";

export interface PauseLayers {
  readonly soft: boolean;
  readonly scroll: boolean;
  readonly hard: boolean;
  readonly focus: boolean;
  /** P3: after a park the soft pause re-arms only on the next `pointermove` or re-entry. */
  readonly softArmed: boolean;
}

export const LIVE: PauseLayers = {
  soft: false,
  scroll: false,
  hard: false,
  focus: false,
  softArmed: true,
};

export const isPaused = (s: PauseLayers): boolean => s.soft || s.scroll || s.hard || s.focus;

/**
 * What a step asks the controller to do with the buffered prints: `live` inserts them and returns
 * to the live edge; `anchored` inserts them above the window and keeps the focused print at its
 * on-screen offset (FP-04); `none` leaves them buffered.
 */
export type Insert = "none" | "live" | "anchored";

export interface Step {
  readonly next: PauseLayers;
  readonly insert: Insert;
  /** Set when the step entered a pause from live (the `tape.paused` seam, BQ-212). */
  readonly paused?: PauseCause | undefined;
  /** Set when the step inserted (`tape.resumed`). */
  readonly resumed?: ResumeCause | undefined;
}

export type PauseEvent =
  | { readonly type: "hover" } // P1: pointermove after >= 150 ms at rest over the list
  | { readonly type: "leave" } // P2: the pointer leaves the list
  | { readonly type: "park" } // P3: 30 s without pointermove
  | { readonly type: "rearm" } // P3: the next pointermove or re-entry
  | { readonly type: "scrollAway" } // P4
  | { readonly type: "jumpLive"; readonly focused: boolean } // P5 / K4
  | { readonly type: "toggleHard"; readonly cause: "key" | "button" } // P6 / P7
  | { readonly type: "rowFocus" } // P8
  | { readonly type: "escape" } // P9 / P13
  | { readonly type: "blur" }; // P9 / FP-07

const stay = (s: PauseLayers): Step => ({ next: s, insert: "none" });

const from = (s: PauseLayers, next: PauseLayers, cause: PauseCause): Step =>
  isPaused(s) ? { next, insert: "none" } : { next, insert: "none", paused: cause };

const resume = (next: PauseLayers, cause: ResumeCause): Step => ({
  next,
  insert: "live",
  resumed: cause,
});

export function step(s: PauseLayers, e: PauseEvent): Step {
  switch (e.type) {
    case "hover":
      if (s.soft || !s.softArmed || isPaused(s)) return stay(s);
      return from(s, { ...s, soft: true }, "hover");
    case "rearm":
      return s.softArmed ? stay(s) : stay({ ...s, softArmed: true });
    case "leave":
      // P2: not hard-paused and no row holds focus; leaving re-arms the hover pause
      if (!s.soft || s.focus || s.hard) return stay({ ...s, softArmed: true });
      return isPaused({ ...s, soft: false })
        ? stay({ ...s, soft: false, softArmed: true })
        : resume({ ...LIVE }, "leave");
    case "park":
      if (!s.soft || s.focus || s.hard) return stay(s);
      return isPaused({ ...s, soft: false })
        ? stay({ ...s, soft: false, softArmed: false })
        : resume({ ...LIVE, softArmed: false }, "park");
    case "scrollAway":
      if (s.focus || s.scroll) return stay(s);
      // a scroll pause takes over a soft one: no park timer runs here (P5)
      return from(s, { ...s, soft: false, scroll: true }, "scroll");
    case "jumpLive":
      // K4: on a focused row the cursor moves and the pause holds (FP-08); else P5 ends a scroll pause
      if (e.focused || !s.scroll) return stay(s);
      return s.hard ? stay({ ...s, scroll: false }) : resume({ ...LIVE }, "jump");
    case "toggleHard":
      if (!s.hard) return from(s, { ...s, hard: true }, e.cause); // P6 (sticky from focus, FP-03)
      // FP-04: under focus the hard layer goes, the buffered prints go in, the focus pause holds
      if (s.focus) return { next: { ...s, hard: false }, insert: "anchored", resumed: e.cause };
      return resume({ ...LIVE }, e.cause); // P7
    case "rowFocus":
      if (s.focus) return stay(s);
      // P8: pauses first, then selects; a soft or scroll entry hands its exit to the focus pause
      return from(s, { ...s, soft: false, scroll: false, focus: true }, "focus");
    case "escape":
      if (!s.focus) return stay(s); // nothing to cancel: the key is not swallowed (`05` §3.3 rule 3)
      if (s.hard) return stay(s); // P13 / FP-06: the selection is released, the pause holds
      return resume({ ...LIVE }, "esc"); // P9 / FP-05
    case "blur":
      if (!s.focus) return stay(s);
      if (s.hard) return stay({ ...s, focus: false }); // FP-07: the hard layer holds, nothing inserted
      return resume({ ...LIVE }, "blur");
  }
}

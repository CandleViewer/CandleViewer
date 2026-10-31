/**
 * SCR-048's engine copy (E11-S02), verbatim from `docs/design/E11/E11-D04.md` §12 and §19 (the
 * strip timeline §12.2, the card table §12.1). Keyed by state, never composed from the engine's
 * `message`; add a row only with its source.
 */
import type { ReducedCapability } from "./state";

export const CHART_ERROR_COPY = {
  strip: {
    title: "Graphics context lost — restoring…",
    /** §12.2: "attempt 2 of 3 · next try in 4 s"; the countdown is a 1 Hz text swap. */
    body: (attempt: number, maxAttempts: number, seconds: number): string =>
      `attempt ${attempt} of ${maxAttempts} · next try in ${seconds} s`,
    announce: "Graphics context lost, restoring",
  },
  /** The restore failed / fatal row (§12.1 row 3). */
  stopped: {
    heading: "This chart stopped rendering.",
    body: "The graphics context could not be restored after three attempts. Your data is intact — open the data table or retry. Other panels are unaffected.",
    retry: "Retry",
    retryLine: "Automatic retries stopped",
    retryFailed: "Retry failed — try again or change the renderer",
  },
  /**
   * A fatal shader program or a worker that could not be restarted (§12.1 row 3) made no restore
   * attempts, so the "three attempts" sentence is not theirs: the body is the cards' shared closing
   * sentence (§12.4) alone. The heading and the rest are `stopped`'s.
   */
  fatalBody: "Other panels are unaffected.",
  noWebgl2: {
    heading: "This chart can't use WebGL2 on this machine.",
    /** The body is built by `noWebgl2Body` from the reduced list (§12.1, BQ-91). */
    retry: "Retry WebGL2",
    continue: "Continue with basic rendering",
    retryFailed: "Still unavailable — basic rendering stays on",
  },
  /** E11-D02 D16's corner badge: text, not an icon alone. */
  badge: "Basic rendering — WebGL unavailable",
  restored: "Chart restored",
  copyReference: "Copy reference",
  /** §12.3: "internal_error · ref urn:cv:req:0193f2bb-5031". */
  referenceLine: (code: string, ref: string): string => `${code} · ref ${ref}`,
} as const;

/**
 * One fragment per §23 G-3 value: §19's two merged ones and #2701 ledger A51's three, verbatim
 * (BQ-91). A value without a row is not named.
 */
export const REDUCED_FRAGMENTS: Readonly<Record<ReducedCapability, string>> = {
  "footprint-text": "footprint cells show colour only",
  heatmap: "the heatmap is off",
  bubbles: "bubbles are off",
  "profile-shading": "profile shading is off",
  "gpu-effects": "GPU effects are off",
};

/** "a", "a and b", "a, b and c" — §19's join, which has no serial comma. */
function joinAnd(parts: readonly string[]): string {
  const head = parts.slice(0, -1);
  const tail = parts.at(-1) ?? "";
  return head.length === 0 ? tail : `${head.join(", ")} and ${tail}`;
}

/**
 * §19's no-WebGL2 body around the reduced list: the fragments in the order given (the state model
 * orders them by the vocabulary). With `footprint-text` and `heatmap` it is §19's sentence verbatim.
 */
export function noWebgl2Body(reduced: readonly ReducedCapability[]): string {
  const named = reduced.filter((c) => Object.hasOwn(REDUCED_FRAGMENTS, c));
  const lost = joinAnd(named.map((c) => REDUCED_FRAGMENTS[c]));
  const works = "Basic rendering is on: candles, lines, axes, the crosshair and drawings work";
  return `${works}${lost === "" ? "" : `; ${lost}`}. Everything else in the workspace is unaffected.`;
}

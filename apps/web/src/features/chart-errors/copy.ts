/**
 * SCR-048's engine copy (E11-S02), verbatim from `docs/design/E11/E11-D04.md` §12 and §19 (the
 * strip timeline §12.2, the card table §12.1). Keyed by state, never composed from the engine's
 * `message`; add a row only with its source.
 */
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
    body: "Basic rendering is on: candles, lines, axes, the crosshair and drawings work; footprint cells show colour only and the heatmap is off. Everything else in the workspace is unaffected.",
    retry: "Retry WebGL2",
    continue: "Continue with basic rendering",
    retryFailed: "Still unavailable — basic rendering stays on",
  },
  restored: "Chart restored",
  copyReference: "Copy reference",
  /** §12.3: "internal_error · ref urn:cv:req:0193f2bb-5031". */
  referenceLine: (code: string, ref: string): string => `${code} · ref ${ref}`,
} as const;

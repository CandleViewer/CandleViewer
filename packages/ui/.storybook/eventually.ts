/**
 * A play's wait for what a component draws on a timer (a hover echo or a tooltip after CMP-016's 300 ms), with a
 * budget counted in time the page could run, not wall time (#5274). The storybook project runs several story files
 * at once, in iframes of one page that share one main thread: a long task in one file (axe over a large story, a
 * heavy first render) holds every other file's timers, React's renders and `waitFor`'s own deadline alike. When the
 * thread frees, Chromium runs the expired timers from its separate timer queues in no promised order, so `waitFor`
 * could give up on its last failed check with the echo due but not yet drawn: `null` at about 3.03 s. Here a poll
 * that comes back late is charged only its own 50 ms, so a hold spends none of the budget.
 */
const POLL_MS = 50;

/** Polls `find` until it returns a value; throws once `budgetMs` of the page's run time has gone without one. */
export async function eventually<T>(
  what: string,
  find: () => T | null,
  budgetMs = 3000,
): Promise<T> {
  let budget = budgetMs;
  let longestHold = 0;
  for (;;) {
    const found = find();
    if (found !== null) return found;
    if (budget <= 0) {
      throw new Error(
        `${what}: not there after ${budgetMs} ms of run time (the longest hold was ` +
          `${Math.round(longestHold)} ms)`,
      );
    }
    const before = performance.now();
    await new Promise<void>((resolve) => {
      setTimeout(resolve, POLL_MS);
    });
    const waited = performance.now() - before;
    longestHold = Math.max(longestHold, waited - POLL_MS);
    budget -= Math.min(waited, POLL_MS);
  }
}

/** The page's one shown CMP-016 surface matching `selector` once its text includes `words`, else null. */
export function shownWith(selector: string, words: string): Element | null {
  const shown = document.querySelector(`${selector}:not([hidden])`);
  return shown?.textContent?.includes(words) === true ? shown : null;
}

/**
 * SCR-124's copy (E42-S03), verbatim from E42-D03 §14's `va.*` keys and §10; nothing here is
 * composed past its fills. `{user}` is the target's display name, else its username (`22`
 * `ViewAsContext`). "(proposed)" marks a string D03 itself proposed. The `_ro` strings stand while
 * no protective control is mounted in the web (V-4's inset), so the banner drops that clause.
 */
export const VA_COPY = {
  /** The banner's region name (D03 §10 Keys: `aria-label="View-as"`). */
  region: "View-as",
  /** D03 §10 anatomy: `[ Exit view-as ]`. */
  exit: "Exit view-as",
  /** `va.banner_ro` (proposed; V-4). */
  bannerRo: "Viewing as {user} (read-only). Ends in {m:ss}.",
  /** `va.notified` (D02:713; shown: CG-26's notice is served). */
  notified: "{user} has been notified.",
  /** `va.announce_ro` (proposed; V-4): assertive, once per page load. */
  announceRo: "Viewing as {user}, read-only. Exit view-as.",
  /** `va.announce_5min` (proposed): polite, once. */
  announce5min: "View-as ends in 5 minutes.",
  /** `va.announce_1min` (proposed): assertive, once. */
  announce1min: "View-as ends in 1 minute.",
  /** `va.ended` and `va.announce_ended` (V-8): assertive, once. */
  ended: "Viewing as {user} ended. Exit to return to your own view.",
  /** `va.back` (V-9): polite, once the owner's own view has loaded. */
  back: "Back to your own view",
  /** `va.exit_failed` (proposed; V-14): under Exit, assertive once. */
  exitFailed: "Couldn't end view-as — try again.",
  /**
   * The held boot's document title (PROPOSED, owner D03; WCAG 2.4.2): the app's "<page> -
   * CandleViewer" form (`routes/titles.ts`, which the held page does not load).
   */
  heldTitle: "View-as ended - CandleViewer",
} as const;

/** A `{user}` string filled with the target's name. */
export const fillUser = (text: string, user: string): string => text.split("{user}").join(user);

export interface BannerSentences {
  /** `va.banner_ro`'s first sentence: "Viewing as alex (read-only)." */
  readonly lead: string;
  /** The second sentence around its countdown: "Ends in " and ".". */
  readonly endsBefore: string;
  readonly endsAfter: string;
}

/**
 * `va.banner_ro` split for its countdown (a CMP-035, not text): its two sentences, the second
 * around `{m:ss}`. Split before the fill, so a name holding ". " cannot move the cut.
 */
export function bannerSentences(user: string): BannerSentences {
  const cut = VA_COPY.bannerRo.indexOf(". ");
  const [endsBefore = "", endsAfter = ""] = VA_COPY.bannerRo.slice(cut + 2).split("{m:ss}");
  return { lead: fillUser(VA_COPY.bannerRo.slice(0, cut + 1), user), endsBefore, endsAfter };
}

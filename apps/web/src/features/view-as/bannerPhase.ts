/**
 * SCR-124's banner phases (E42-S03; E42-D03 §10 V-4 to V-8, §13), pure. The countdown runs to
 * the server's `expires_at` on the server's clock (`offsetMs`); at 5:00 and 1:00 only its glyph
 * changes, to the `warning` triangle and then the `danger` octagon, while its text stays
 * `color.text.primary`. The phase moves on the clock at those two marks only, so the banner
 * re-renders there and never per tick; an ended context is the server's word (`state: expired`),
 * never the countdown reaching 0.
 */
import type { IconName } from "@candleviewer/ui";
import type { HeldViewAs } from "../../shell/bootstrap/store";
import { VA_COPY } from "./copy";

export type BannerPhase = "normal" | "five" | "one" | "ended";

/** V-5 and V-6: the marks, in seconds left. */
export const FIVE_MINUTES_S = 300;
export const ONE_MINUTE_S = 60;

/** Whole seconds left on the server's clock, rounded up as CMP-035 rounds them, never negative. */
export function secondsLeft(held: HeldViewAs, clientNowMs: number): number {
  return Math.max(0, Math.ceil((held.expiresAtMs - (clientNowMs + held.offsetMs)) / 1000));
}

export function bannerPhase(held: HeldViewAs, clientNowMs: number): BannerPhase {
  if (held.state === "expired") return "ended";
  const left = secondsLeft(held, clientNowMs);
  if (left <= ONE_MINUTE_S) return "one";
  return left <= FIVE_MINUTES_S ? "five" : "normal";
}

/** The glyph before the countdown (D03 §10): none, then the triangle, then the octagon. */
export const PHASE_GLYPH: Readonly<Record<BannerPhase, IconName | null>> = {
  normal: null,
  five: "warning",
  one: "danger",
  ended: null,
};

/** Milliseconds until the clock next moves the phase (at 5:00, then 1:00); `null` past the last. */
export function nextPhaseInMs(held: HeldViewAs, clientNowMs: number): number | null {
  if (held.state === "expired") return null;
  const msLeft = held.expiresAtMs - (clientNowMs + held.offsetMs);
  for (const mark of [FIVE_MINUTES_S, ONE_MINUTE_S])
    if (msLeft > mark * 1000) return msLeft - mark * 1000;
  return null;
}

export interface BannerAnnouncement {
  readonly politeness: "polite" | "assertive";
  /** The shell announcer's key: each is said once per page load. */
  readonly key: string;
  /** A `VA_COPY` string, its `{user}` still to fill. */
  readonly text: string;
}

/**
 * What the banner says when its phase goes from `prev` (`null`: it just mounted) to `next` (D03
 * §13: one assertive on entry; 5 min polite; 1 min and ended assertive; no countdown ticks). A mark
 * already passed when it mounted is not said; past both at once (a tab back from sleep), the later.
 */
export function bannerAnnouncement(
  prev: BannerPhase | null,
  next: BannerPhase,
): BannerAnnouncement | null {
  if (prev === next) return null;
  if (next === "ended")
    return { politeness: "assertive", key: "view-as:ended", text: VA_COPY.ended };
  if (prev === null)
    return { politeness: "assertive", key: "view-as:entry", text: VA_COPY.announceRo };
  if (next === "one")
    return { politeness: "assertive", key: "view-as:1min", text: VA_COPY.announce1min };
  if (next === "five" && prev === "normal")
    return { politeness: "polite", key: "view-as:5min", text: VA_COPY.announce5min };
  return null;
}

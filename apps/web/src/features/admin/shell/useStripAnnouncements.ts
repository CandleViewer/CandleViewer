import { useEffect, useRef } from "react";
import { ADMIN_COPY, sortAdminStrip, type AdminStripItem } from "@candleviewer/ui";
import {
  announce,
  clearAnnouncements,
  lastWrittenAt,
  REGION_BUDGET_MS,
} from "../../app-shell/announcer";
import { useAdminSelector, type AdminReadState } from "../overview/readStore";
import { denial, STRIP_READS, stripUnread } from "../overview/strip";

/** Every strip line's announcer key starts with this: the visit's end clears them all. */
const STRIP_PREFIX = "admin:strip:";
/**
 * One announcer key per item: said once, until the item leaves the strip or the visit ends. The
 * colon ends the id, so clearing one item's key never reaches another whose id it prefixes; strip
 * ids carry no colon (today's four: no_mfa, key_expiry, keys_invalid, tier).
 */
const keyOf = (id: string): string => `${STRIP_PREFIX}${id}:`;

/** A read has yet to answer once: the strip is filling, and what it settles on is the arrival. */
const filling = (s: AdminReadState): boolean => STRIP_READS.some((id) => s[id].phase === "idle");

/**
 * What is said for an item: its pill's accessible name (CMP-087's `StripItem`; E42-D03 §6 Keys:
 * "Attention:" leads a warning and the env badge is part of the name), so the owner hears what
 * Tab will read. PROPOSED (§14's `announce.*` has no key for a new warning item): the sentence is
 * the lane's own, as `ADMIN_COPY.graceAnnounce` is. It copies `StripItem`'s naming rule, which
 * lives in packages/ui and is not shared (that would change the package): the tests pin the two.
 */
function wordsOf(item: AdminStripItem): string {
  const lead = item.severity !== "info" && !item.label.startsWith(ADMIN_COPY.attention);
  const badge = item.env === undefined ? "" : ` ${ADMIN_COPY.env[item.env]}`;
  return `${lead ? `${ADMIN_COPY.attention} ` : ""}${item.label}${badge}`;
}

/** What one stay in the area has said and has still to say. */
interface Visit {
  /**
   * The ids on the strip at the last answer, and the earlier ones whose own source is unread (they
   * have not left); `null` until the strip first settles.
   */
  present: ReadonlySet<string> | null;
  /** The items on the strip at the last answer: a line is said in the words its pill reads now. */
  now: ReadonlyMap<string, AdminStripItem>;
  /** The ids of new items not yet said, in the order queued: the strip's order within a read. */
  waiting: string[];
  timer: ReturnType<typeof setTimeout> | null;
  /** The polite region's last write when the timer was armed: nobody wrote since, the wait is spent. */
  armedFor: number | null;
}

/** Nothing waiting says anything more. */
function cancel(visit: Visit): void {
  if (visit.timer !== null) clearTimeout(visit.timer);
  visit.timer = null;
  visit.waiting = [];
}

/**
 * The visit is over: its lines go from the region, its record with them (nothing an admin read
 * answered outlives a denial, S-5330-03), and a later visit may say these items again. No stale
 * text outlives the condition (`announcer.tsx`).
 */
function end(visit: Visit): void {
  cancel(visit);
  clearAnnouncements(STRIP_PREFIX);
  visit.now = new Map();
  visit.present = null;
}

/**
 * Says the next waiting item once the polite region has been quiet a whole budget, whoever wrote
 * last (E17-D02 §11: at most one ambient line per 5 s, so a line never cuts another's), else tries
 * again when it has been. As the shell's other banners keep theirs, a wait is at most one budget
 * and a wait nobody broke is spent, so a wall-clock step cannot stretch it. A second item waits
 * out the first one's budget in turn.
 */
function sayNext(visit: Visit): void {
  visit.timer = null;
  // The first waiting item the strip has, as its pill reads it now: a count may have moved while it
  // waited. One off the strip says nothing and holds no other up; it is said once it is back.
  const next = visit.waiting.map((id) => visit.now.get(id)).find((item) => item !== undefined);
  if (next === undefined) return;
  const last = lastWrittenAt("polite");
  const wait =
    last === visit.armedFor ? 0 : Math.min(last + REGION_BUDGET_MS - Date.now(), REGION_BUDGET_MS);
  if (wait > 0) {
    visit.armedFor = last;
    visit.timer = setTimeout(() => sayNext(visit), wait);
    return;
  }
  visit.waiting = visit.waiting.filter((id) => id !== next.id);
  announce("polite", wordsOf(next), keyOf(next.id));
  sayNext(visit);
}

/**
 * A new "Needs your action" item is said once, politely, through the shell's announcer (E42-S01;
 * E42-D03 §6 Keys: the strip is not live, "the shell announces a new item once"; E42-D02:312 and the
 * hand-off's Table 5: polite, once per item). The area owns no live region of its own.
 *
 * What is new. PROPOSED reading (§6 says only "a new item"): the items on the strip once its reads
 * have all answered are the owner's arrival and say nothing, however the answers interleave; after
 * that an `id` not on the strip before is new, an item whose source was still unread then included.
 * An item is one `id`, so a count that moves on an item already there is no new item, and one that
 * left and comes back is new again. An item has left only if its own source was read and it is not
 * there: a failed or not-built read, or a slice that errored inside an answer that otherwise
 * succeeded, draws none of its items (an item can't be marked old), so those are unread, not gone
 * (`stripUnread`), and their return is no news. A strip left undrawn (a source unread, nothing
 * else to show) says nothing either.
 *
 * Pacing. New items are said in the strip's order within a read (`sortAdminStrip`), one polite line
 * each, behind any writer's last line, in the words their pills read when their turn comes. A line
 * is said only while its item is on the strip: one off it at its turn (its source unread, or it
 * left) says nothing, and holds no other up. Leaving the area, or a `403` that withdraws it, drops
 * every line still waiting; a line goes from the region with its item, and every one with the
 * visit, so the next visit starts afresh.
 *
 * Never polite: a critical item (`announce.withdrawal`, `announce.tamper`, §14) is said
 * assertively, which is not built (CG-7, CG-8: no critical item has a source), so it is skipped.
 */
export function useStripAnnouncements(strip: readonly AdminStripItem[] | undefined): void {
  const arriving = useAdminSelector(filling);
  const unread = useAdminSelector(stripUnread);
  const withdrawn = useAdminSelector(denial) !== null;
  const visitRef = useRef<Visit>({
    present: null,
    now: new Map(),
    waiting: [],
    timer: null,
    armedFor: null,
  });

  useEffect(() => {
    const visit = visitRef.current;
    if (withdrawn) {
      end(visit); // the page these items pointed from is gone (SCR-154 N-2)
      return;
    }
    if (arriving) return; // what the strip settles on is the arrival
    const items = strip ?? [];
    visit.now = new Map(items.map((item) => [item.id, item]));
    const before = visit.present;
    if (before === null) {
      visit.present = new Set(visit.now.keys());
      return;
    }
    // Absent, an item has left only if its own source was read; else it is not known to have.
    const unreadIds = new Set(unread);
    const kept = new Set(visit.now.keys());
    for (const id of before) {
      if (visit.now.has(id) || unreadIds.has(id)) kept.add(id);
      else clearAnnouncements(keyOf(id)); // its condition ended: its line goes, and it is new again
    }
    visit.present = kept;
    // Never politely (handoff:298): a critical item's assertive line is not built (CG-7, CG-8)
    const fresh = items.filter((item) => item.severity !== "critical" && !before.has(item.id));
    visit.waiting.push(...sortAdminStrip(fresh).map((item) => item.id));
    if (visit.timer === null) sayNext(visit);
  }, [strip, arriving, unread, withdrawn]);

  useEffect(() => {
    const visit = visitRef.current;
    return () => end(visit);
  }, []);
}

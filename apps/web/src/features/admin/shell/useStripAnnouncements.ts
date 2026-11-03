import { useEffect, useRef } from "react";
import { ADMIN_COPY, sortAdminStrip, type AdminStripItem } from "@candleviewer/ui";
import { announce, forget, lastWrittenAt, REGION_BUDGET_MS } from "../../app-shell/announcer";
import { useAdminSelector, type AdminReadState } from "../overview/readStore";
import { denial, STRIP_READS } from "../overview/strip";

/** One announcer key per item: said once, until the item leaves the strip or the visit ends. */
const keyOf = (id: string): string => `admin:strip:${id}`;

/**
 * Where the strip's reads stand. `loading` until each has answered once (the strip is still
 * filling); `complete` when every one answered `ok` (the strip is all there is to see); else
 * `partial`: a failed or not-built source draws none of its items, so its absences mean nothing.
 */
type Reads = "loading" | "partial" | "complete";
function readsOf(s: AdminReadState): Reads {
  if (STRIP_READS.some((id) => s[id].phase === "idle")) return "loading";
  return STRIP_READS.every((id) => s[id].phase === "ok") ? "complete" : "partial";
}

/**
 * What is said for an item: its pill's accessible name (CMP-087's `StripItem`; E42-D03 §6 Keys:
 * "Attention:" leads a warning and the env badge is part of the name), so the owner hears what
 * Tab will read.
 */
function wordsOf(item: AdminStripItem): string {
  const lead = item.severity !== "info" && !item.label.startsWith(ADMIN_COPY.attention);
  const badge = item.env === undefined ? "" : ` ${ADMIN_COPY.env[item.env]}`;
  return `${lead ? `${ADMIN_COPY.attention} ` : ""}${item.label}${badge}`;
}

/** What one stay in the area has said and has still to say. */
interface Visit {
  /** The ids on the strip at the last answer; `null` until the arrival, the strip first settled. */
  present: ReadonlySet<string> | null;
  /** New items not yet said, oldest first. */
  waiting: AdminStripItem[];
  /** The ids whose line this visit wrote: the visit's end forgets their keys. */
  said: Set<string>;
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

/** The visit is over: a later one may say these items again. */
function end(visit: Visit): void {
  cancel(visit);
  for (const id of visit.said) forget(keyOf(id));
  visit.said.clear();
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
  const next = visit.waiting[0];
  if (next === undefined) return;
  const last = lastWrittenAt("polite");
  const wait =
    last === visit.armedFor ? 0 : Math.min(last + REGION_BUDGET_MS - Date.now(), REGION_BUDGET_MS);
  if (wait > 0) {
    visit.armedFor = last;
    visit.timer = setTimeout(() => sayNext(visit), wait);
    return;
  }
  visit.waiting.shift();
  announce("polite", wordsOf(next), keyOf(next.id));
  visit.said.add(next.id);
  sayNext(visit);
}

/**
 * A new "Needs your action" item is said once, politely, through the shell's announcer (E42-S01;
 * E42-D03 §6 Keys: the strip is not live, "the shell announces a new item once"; E42-D02:312 and the
 * hand-off's Table 5: polite, once per item). The area owns no live region of its own.
 *
 * What is new. An item is one `id` on the strip, so a count that moves on an item already there is
 * no new item. The items on the strip once its reads have all answered are the owner's arrival and
 * say nothing, however the answers interleave. After that an `id` not on the strip before is new,
 * and one that left and comes back is new again. Only an answer that read both sources says an item
 * left: a failed read draws none of its items (an item can't be marked old), and its recovery is
 * no news. A strip left undrawn (a source unread, nothing else to show) says nothing either. The
 * one absence the strip cannot tell from an item gone is a slice that errored inside an answer
 * that otherwise succeeded, while another item stands.
 *
 * Pacing. New items are said oldest first, one polite line each, behind any writer's last line.
 * Leaving the area, or a `403` that withdraws it, drops every line still waiting, and leaving
 * forgets the keys, so the next visit starts afresh.
 *
 * Not built: a critical item's assertive line (`announce.withdrawal`, `announce.tamper`, §14). No
 * critical item has a source yet (CG-7, CG-8), so every item here is a warning and polite.
 */
export function useStripAnnouncements(strip: readonly AdminStripItem[] | undefined): void {
  const reads = useAdminSelector(readsOf);
  const withdrawn = useAdminSelector(denial) !== null;
  const visitRef = useRef<Visit>({
    present: null,
    waiting: [],
    said: new Set(),
    timer: null,
    armedFor: null,
  });

  useEffect(() => {
    const visit = visitRef.current;
    if (withdrawn) {
      cancel(visit); // the page these items pointed from is gone (SCR-154 N-2)
      return;
    }
    if (reads === "loading") return; // what the strip settles on is the arrival
    const items = strip ?? [];
    const ids = new Set(items.map((item) => item.id));
    const before = visit.present;
    if (before === null) {
      visit.present = ids;
      return;
    }
    if (strip !== undefined && reads === "complete") {
      for (const id of before) {
        if (ids.has(id)) continue;
        forget(keyOf(id)); // its condition ended: coming back, it is new
        visit.said.delete(id);
      }
      visit.waiting = visit.waiting.filter((item) => ids.has(item.id));
      visit.present = ids;
    } else {
      visit.present = new Set([...before, ...ids]);
    }
    visit.waiting.push(...sortAdminStrip(items.filter((item) => !before.has(item.id))));
    if (visit.timer === null) sayNext(visit);
  }, [strip, reads, withdrawn]);

  useEffect(() => {
    const visit = visitRef.current;
    return () => end(visit);
  }, []);
}

/**
 * The Positions feed's announcements (E29-S01 #911), owned by the panel for the route's life
 * (`PositionsPanel.tsx`), never by a tab: a tab switch unmounts the tab, so what was said, and the
 * feed itself, would start again on return (RT-07 and RT-11 said twice, E29-D05 §8.1 "once per
 * episode"). They speak whichever tab shows: a crossing into Critical is news on the Fills tab too.
 *
 * - **RT-05, RT-12:** each crossing once; its `seq` never repeats, and a re-run of the effect (a
 *   StrictMode mount) says nothing again.
 * - **RT-07, RT-11:** each account's episode once (`accountAnnouncements`), held until the directory
 *   lists the account, so its label, never an id stub, names it (D03:327-330).
 * - **S-01 and its result:** a first load's loading lines, and each Retry's, said once (D02:388,
 *   "announced once"; the deck marks `blotter.ui.loading` `announce: "none"`, a conflict routed to
 *   E29-D02's and E29-D06's owners); when that load ends with the book read, its result, once, in
 *   CMP-049's words (D04:273, D05:285, `15`:530's "load results"), which CMP-049 cannot say: it
 *   mounts with the rows. A narrowing's reload says neither: its directory read may withdraw an
 *   account the lines would name, and F-02's line says what changed.
 * - **RT-15:** could not load, once per failure (the tab's lines show with no live role); and each
 *   account withdrawn, once, its lines in one message, except the line a focus move already spoke
 *   (E29-D05 §5.4, F-02: "the line is heard once").
 */
import { useEffect, useRef } from "react";
import type { AccountSignal } from "./accountSignals";
import {
  accountAnnouncements,
  crossingAnnouncements,
  sayAll,
  type PanelAnnouncer,
  type SaidEpisodes,
} from "./announce";
import { accountWords, failedLines, loadingLine, resultWords, withdrawnLine } from "./gridModel";
import { applyFilters, type FilterChip } from "./model/filters";
import type { Environment } from "./model/rowMapping";
import type { PositionsSnapshot, Withdrawn } from "./positionsStore";

/** S-01 with its accounts known: the rows are not read yet, and nothing failed (D02 §10.1). */
export function showsLoading(snap: PositionsSnapshot): boolean {
  return (
    snap.source === "none" &&
    snap.status !== "no_accounts" &&
    snap.status !== "snapshot_failed" &&
    snap.status !== "revoked"
  );
}

export interface FeedAnnouncementsInputs {
  readonly snap: PositionsSnapshot;
  /** The panel's filter chips: a load's result is the rows they leave in view. */
  readonly chips: readonly FilterChip[];
  readonly accounts: ReadonlyMap<string, AccountSignal>;
  readonly environment: Environment | null;
  readonly announcer: PanelAnnouncer;
  /** The withdrawn lines a focus move spoke (F-02): RT-15 stays silent for them. */
  readonly spokenByFocus: { has(entry: Withdrawn): boolean };
}

export function useFeedAnnouncements({
  snap,
  chips,
  accounts,
  environment,
  announcer,
  spokenByFocus,
}: FeedAnnouncementsInputs): void {
  // RT-05 and RT-12: each crossing once, by its `seq`.
  const crossingSeq = useRef(0);
  useEffect(() => {
    const fresh = snap.crossings.filter((c) => c.seq > crossingSeq.current);
    if (fresh.length === 0) return;
    crossingSeq.current = Math.max(...fresh.map((c) => c.seq));
    const rows = new Map(snap.rows.map((r) => [r.key, r]));
    sayAll(
      announcer,
      crossingAnnouncements(
        fresh,
        (key) => rows.get(key),
        (key) => snap.liq.get(key),
      ),
    );
  }, [snap, announcer]);

  // RT-07 and RT-11: each episode once, by the account's label once the directory lists it.
  const said = useRef<SaidEpisodes>(new Map());
  useEffect(() => {
    const directory = new Map(snap.accounts.map((a) => [a.id, a]));
    const withdrawn = new Set(snap.withdrawn.map((w) => w.accountId));
    const next = accountAnnouncements(
      said.current,
      accounts,
      (id) => accountWords(id, directory),
      (id) => directory.has(id) && !withdrawn.has(id),
    );
    said.current = next.said;
    sayAll(announcer, next.batch);
  }, [accounts, snap.accounts, snap.withdrawn, announcer]);

  // S-01 and its result: owed for a start's load and each Retry's, never a narrowing's reload.
  const load = useRef<"owed" | "said" | "done">("owed");
  useEffect(() => {
    if (snap.status === "idle" || snap.status === "snapshot_failed" || snap.status === "revoked") {
      load.current = "owed"; // what loads next is a start's or a Retry's
    } else if (showsLoading(snap)) {
      if (load.current !== "owed" || snap.accounts.length === 0) return;
      load.current = "said";
      announcer.say("polite", snap.accounts.map(loadingLine).join(" "));
    } else if (snap.source !== "none") {
      if (load.current === "said") {
        const inView = applyFilters(snap.rows, chips).length;
        announcer.say("polite", resultWords(snap.rows.length, inView, chips.length));
      }
      load.current = "done"; // the book is read: a reload from here is a narrowing's
    }
  }, [snap, chips, announcer]);

  // RT-15: could not load, once per failure.
  const wasFailed = useRef(false);
  useEffect(() => {
    const failed = snap.status === "snapshot_failed";
    if (failed && !wasFailed.current) {
      announcer.say("polite", failedLines(snap.accounts, environment).join(" "));
    }
    wasFailed.current = failed;
  }, [snap, environment, announcer]);

  // RT-15: each account withdrawn, once; the lines of one change in one message.
  const saidWithdrawn = useRef(new WeakSet<Withdrawn>());
  useEffect(() => {
    const fresh = snap.withdrawn.filter((w) => !saidWithdrawn.current.has(w));
    if (fresh.length === 0) return;
    for (const entry of fresh) saidWithdrawn.current.add(entry);
    const directory = new Map(snap.accounts.map((a) => [a.id, a]));
    const text = fresh
      .filter((entry) => !spokenByFocus.has(entry))
      .map((entry) => withdrawnLine(entry, directory))
      .join(" ");
    announcer.say("polite", text);
  }, [snap.withdrawn, snap.accounts, spokenByFocus, announcer]);
}

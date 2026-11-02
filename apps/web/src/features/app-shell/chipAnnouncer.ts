import { useEffect, useRef } from "react";
import type { ChipView } from "../../lib/ws/state/chipState";
import {
  announce,
  clearAnnouncements,
  forget,
  lastWrittenAt,
  REGION_BUDGET_MS,
  type Politeness,
} from "./announcer";

/** A stale episode ends after this much continuous freshness, so a flap is one episode (T5's spirit). */
export const EXIT_HOLD_MS = 5_000;
/** The shell announcer keys this writer uses. */
export const CHIP_PREFIX = "chip:";
/** A stale episode's keys (its entry and its T2 sentence), cleared when the episode ends. */
const EPISODE_PREFIX = `${CHIP_PREFIX}stale`;

/**
 * What the chip's container says (PROPOSED for #325's §10 H): E17-D02 §11 / E17-D01 §7 give the
 * T2 sentence ("Price feeds stale 15 s on 4 symbols, including BTCUSDT (open position). New orders
 * off.", here without "(open position)": the shell holds no positions, and without "New orders
 * off.": no gate enforces it yet, E17-D01 §6 R1-S1) and the polite row-5 pattern ("Book
 * resyncing." / "Book live."); Delayed's entry is §10 A's chip word without its factor, as a
 * sentence: the worker posts the new class before the `connection_quality` frame that carries the
 * multiplier, so the factor is not known when the entry is said.
 */
export const CHIP_SAID = {
  staleEntry: "Price feed stale.",
  staleExit: "Price feed live.",
  t2(ageMs: number, symbols: readonly string[]): string {
    const s = Math.floor(ageMs / 1000);
    const [first] = symbols;
    if (first === undefined) return `Price feeds stale ${s} s.`;
    if (symbols.length === 1) return `Price feed stale ${s} s on ${first}.`;
    return `Price feeds stale ${s} s on ${symbols.length} symbols, including ${first}.`;
  },
  delayedEntry: "Reduced rate.",
  delayedExit: "Full rate restored.",
} as const;

/** The announcer and the clock this writer uses: the shell's, or a test's. */
export interface ChipSpeech {
  announce(politeness: Politeness, text: string, key: string): boolean;
  forget(key: string): void;
  /** Forgets the keys starting with `prefix` and empties a region holding one (`clearAnnouncements`). */
  clear(prefix: string): void;
  lastWrittenAt(politeness: Politeness): number;
  now(): number;
  setTimeout(run: () => void, ms: number): unknown;
  clearTimeout(id: unknown): void;
}

/** Reads the globals on every call, so fake timers installed after import still apply. */
export const SHELL_SPEECH: ChipSpeech = {
  announce,
  forget,
  clear: clearAnnouncements,
  lastWrittenAt,
  now: () => Date.now(),
  setTimeout: (run, ms) => setTimeout(run, ms),
  // `id` is what this object's `setTimeout` returned; the cast only restores that type.
  clearTimeout: (id) => clearTimeout(id as ReturnType<typeof setTimeout>),
};

export interface ChipAnnouncer {
  /**
   * The chip's view after a render: a change of phase may say one sentence, never a tick. `current`
   * reads the chip as of now (the render may be a second old when one of the writer's timers falls
   * due); without it the last view seen stands.
   */
  see(view: ChipView, current?: () => ChipView): void;
  dispose(): void;
}

type Phase = "transport" | "live" | "delayed" | "stale" | "upstream";
type StaleView = Extract<ChipView, { readonly status: "stale" }>;

const isFresh = (p: Phase | null): boolean => p === "live" || p === "delayed";

function phaseOf(view: ChipView): Phase {
  if (view.status === "stale") return view.cause === "upstream" ? "upstream" : "stale";
  if (view.status === "reconnecting" || view.status === "offline") return "transport";
  return view.status;
}

/** A stale episode: one or more stale views, with less than EXIT_HOLD_MS of freshness between. */
interface Episode {
  /**
   * Its entry was said, or what stands for it (its T2 sentence; CMP-092's row for the feed down):
   * its exit is said too.
   */
  said: boolean;
  /** Its T2 sentence was said or is waiting: never twice in one episode. */
  escalated: boolean;
}

/**
 * The writer of E17-D02 §11 rows 4 and 5 for CMP-076's states (E17-D01 §7), through the shell
 * announcer, on a change of phase only: a stale episode politely on entry and on exit (after
 * EXIT_HOLD_MS of freshness, so a flap stays one episode), its T2 sentence once, assertively;
 * Delayed politely on entry and exit. The exchange's feed down is entered by CMP-092's row (§6
 * routing row 8) and left by this writer's exit (row 5, "once on exit"); the transport is CMP-077's
 * (rows 1, 12–14), and the chip says none of it; its first view is only the baseline. An ended
 * episode's sentences leave the regions once its exit is written (or dropped); a Disconnected
 * episode ends the chip's in silence and clears them. Each region keeps §11's budget: a sentence
 * waits until REGION_BUDGET_MS after that region's last write, whoever wrote it, and is dropped if
 * its state has gone by then. The exit reads the chip again when its EXIT_HOLD_MS fall due and when
 * its turn comes, never from a render up to a second old: a chip stale again then continues the
 * episode in silence. Plain code on injected timers, never a statechart.
 */
export function createChipAnnouncer(io: ChipSpeech = SHELL_SPEECH): ChipAnnouncer {
  let last: ChipView | null = null;
  /** How to read the chip as of now, from the latest `see` that gave one. */
  let reread: (() => ChipView) | undefined;
  let episode: Episode | null = null;
  let exitTimer: unknown = null;
  let delayedSaid = false;
  /** A sentence waiting for its region's budget, with what runs when its turn is over. */
  const waiting = new Map<
    Politeness,
    { readonly timer: unknown; readonly after: (() => void) | undefined }
  >();

  const phase = (): Phase | null => (last === null ? null : phaseOf(last));
  /** The chip as of now: read again when the container says how, else the last view seen. */
  const current = (): ChipView | null => reread?.() ?? last;
  const phaseNow = (): Phase | null => {
    const view = current();
    return view === null ? null : phaseOf(view);
  };

  /**
   * Says `text()` now, or once the region's budget allows if `holds()` still does then; `after`
   * runs when its turn comes, whether it was said or dropped.
   */
  function say(
    politeness: Politeness,
    key: string,
    text: () => string,
    holds: () => boolean,
    after?: () => void,
  ) {
    const speak = (): void => {
      waiting.delete(politeness);
      if (holds()) {
        io.forget(CHIP_PREFIX + key); // said again in a later episode
        io.announce(politeness, text(), CHIP_PREFIX + key);
      }
      after?.();
    };
    const prior = waiting.get(politeness);
    if (prior !== undefined) {
      // A newer sentence replaces one still waiting. Its turn is over, so its `after` runs, before
      // the new sentence's key is said: the episode it ended still clears its own.
      io.clearTimeout(prior.timer);
      waiting.delete(politeness);
      prior.after?.();
    }
    const ms = io.lastWrittenAt(politeness) + REGION_BUDGET_MS - io.now();
    if (ms <= 0) speak();
    else waiting.set(politeness, { timer: io.setTimeout(speak, ms), after });
  }

  function cancelExit(): void {
    if (exitTimer !== null) io.clearTimeout(exitTimer);
    exitTimer = null;
  }

  function enterStale(view: StaleView): void {
    const ep: Episode = { said: false, escalated: false };
    episode = ep;
    delayedSaid = false; // the episode supersedes a Delayed it covers
    if (view.cause === "upstream") {
      ep.said = true; // CMP-092's row says its entry (§6 routing row 8); its exit is this writer's
      return;
    }
    if (view.strong) {
      escalate(view); // the T2 sentence stands for the entry
      return;
    }
    say(
      "polite",
      "stale",
      () => CHIP_SAID.staleEntry,
      () => {
        const holds = episode === ep && phase() === "stale";
        if (holds) ep.said = true;
        return holds;
      },
    );
  }

  function escalate(view: StaleView): void {
    const ep = episode;
    if (ep === null || ep.escalated) return;
    ep.escalated = true;
    say(
      "assertive",
      "stale-t2",
      () => {
        const now = last?.status === "stale" && last.strong ? last : view; // the latest symbols
        return CHIP_SAID.t2(now.t2AgeMs ?? now.ageMs ?? 0, now.t2Symbols);
      },
      () => {
        const holds = episode === ep && phase() === "stale";
        if (holds) ep.said = true;
        return holds;
      },
    );
  }

  function leaveStale(): void {
    if (episode === null || exitTimer !== null) return;
    const ep = episode;
    exitTimer = io.setTimeout(() => {
      exitTimer = null;
      if (episode !== ep) return;
      // The last render may be a second old: a chip stale again since has not had its 5 s of
      // freshness, and "Price feed live." must not be said as it reads Stale. The episode goes on.
      const now = current();
      if (now !== null && !isFresh(phaseOf(now))) return announcer.see(now);
      episode = null;
      const ended = (): void => io.clear(EPISODE_PREFIX); // after the exit is written: it stays
      if (!ep.said) return ended();
      say(
        "polite",
        "live",
        () => CHIP_SAID.staleExit,
        () => episode === null && isFresh(phaseNow()),
        ended,
      );
    }, EXIT_HOLD_MS);
  }

  const announcer: ChipAnnouncer = {
    see(view, again) {
      if (again !== undefined) reread = again;
      const was = phase();
      last = view;
      const now = phaseOf(view);
      if (was === null) {
        // The baseline: an episode already under way is not announced, nor is its exit.
        if (view.status === "stale") episode = { said: false, escalated: view.strong };
        return;
      }
      if (now === "transport") {
        // A Disconnected episode (CMP-077's) ends the stale one and Delayed in silence, and every
        // sentence of the chip's leaves the regions ("Price feed live." included: no longer true).
        cancelExit();
        if (was !== "transport") io.clear(CHIP_PREFIX);
        episode = null;
        delayedSaid = false;
        return;
      }
      if (now === "stale" || now === "upstream") {
        cancelExit();
        if (view.status !== "stale") return; // for the type: both phases are stale views
        if (episode === null) enterStale(view);
        else if (view.strong) escalate(view);
        return;
      }
      // live or delayed
      leaveStale();
      if (episode !== null) return; // a Delayed inside an episode (or its 5 s) says nothing
      if (now === "delayed" && was === "live") {
        delayedSaid = false;
        say(
          "polite",
          "delayed",
          () => CHIP_SAID.delayedEntry,
          () => {
            const holds = phase() === "delayed";
            if (holds) delayedSaid = true;
            return holds;
          },
        );
      } else if (now === "live" && was === "delayed" && delayedSaid) {
        delayedSaid = false;
        say(
          "polite",
          "full-rate",
          () => CHIP_SAID.delayedExit,
          () => phase() === "live",
        );
      }
    },
    dispose() {
      cancelExit();
      for (const { timer } of waiting.values()) io.clearTimeout(timer);
      waiting.clear();
    },
  };
  return announcer;
}

/**
 * CMP-076's container's writer: one announcer per mount (StrictMode's second one included), fed
 * each render's view after the commit. The chip itself still owns no live region (§5).
 */
export function useChipAnnouncements(view: ChipView, current: () => ChipView): void {
  const announcer = useRef<ChipAnnouncer | null>(null);
  useEffect(() => {
    const a = createChipAnnouncer();
    announcer.current = a;
    return () => {
      a.dispose();
      announcer.current = null;
    };
  }, []);
  useEffect(() => {
    announcer.current?.see(view, current);
  });
}

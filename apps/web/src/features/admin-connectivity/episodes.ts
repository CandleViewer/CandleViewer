import { PRECEDENCE, THRESHOLDS } from "./selectState";
import { STATES, wordOf, type StateId } from "./states";

/** The shell announcer's ceiling: at most one polite line per 5 s per region (E17-D02 §11). */
export const REGION_BUDGET_MS = 5_000;

export type Politeness = "polite" | "assertive";

/** One row's state at one sample: a section, a state, and which subject (an account) holds it. */
export interface Observation {
  readonly region: string;
  readonly state: StateId;
  /** An opaque subject key, only ever counted: never printed, never an id from the wire. */
  readonly subject: string;
}

/** Writes one line into the shell's live-region pair; `key` is said once. Injected, never imported. */
export type Say = (politeness: Politeness, text: string, key: string) => void;

export interface EpisodeCoalescer {
  /** One sample (1 Hz): states held now. The same states again announce nothing. */
  observe(held: readonly Observation[]): void;
  /** Writes what is due (the join window passed, the region's budget free); call on a timer too. */
  flush(): void;
  reset(): void;
}

interface Episode {
  readonly id: number;
  lastSeen: number;
  readonly subjects: Set<string>;
}

interface Pending {
  readonly region: string;
  readonly state: StateId;
  readonly episode: number;
  readonly firstAt: number;
  readonly subjects: Set<string>;
}

/**
 * The pure episode and 5 s coalescer (E08-D09 §5.2, D09-Q9, PROPOSED; E08-S12 BQ-11). An episode starts when a
 * state is entered and ends once it has been exited for `episodeCloseMs`; a re-entry inside that window continues
 * it and says nothing. Entries of one state for several subjects inside `episodeJoinMs` join one line
 * ("Throttled: 2 accounts"). Polite lines go out at most once per `REGION_BUDGET_MS` (the shell's one polite region), later entries
 * joining the next line; the assertive line (entering Disconnected) is never held back or dropped.
 * Usage, ages and countdowns are never lines at all: only a state word and a count are ever said.
 */
export function createEpisodeCoalescer(opts: {
  readonly now: () => number;
  readonly say: Say;
}): EpisodeCoalescer {
  const episodes = new Map<string, Episode>();
  const pending = new Map<string, Pending>();
  let lastPoliteAt = -Infinity;
  let nextId = 0;

  const keyOf = (region: string, state: StateId): string => `${region}|${state}`;

  const lineOf = (p: Pending): string => {
    const word = wordOf(p.state);
    return p.subjects.size > 1 ? `${word}: ${p.subjects.size} accounts` : word;
  };

  function flush(): void {
    const t = opts.now();
    const polite: Pending[] = [];
    for (const [key, p] of pending) {
      if (STATES[p.state].announce === "assertive") {
        opts.say("assertive", lineOf(p), `connectivity:${p.state}:${p.episode}`);
        pending.delete(key);
      } else polite.push(p);
    }
    if (polite.length === 0) return;
    const oldest = Math.min(...polite.map((p) => p.firstAt));
    if (t - oldest < THRESHOLDS.episodeJoinMs || t - lastPoliteAt < REGION_BUDGET_MS) return;
    const ordered = [...polite].sort(
      (a, b) => PRECEDENCE.indexOf(a.state) - PRECEDENCE.indexOf(b.state),
    );
    opts.say(
      "polite",
      ordered.map(lineOf).join(". "),
      `connectivity:${ordered.map((p) => `${p.state}.${p.episode}`).join("+")}`,
    );
    lastPoliteAt = t;
    for (const p of polite) pending.delete(keyOf(p.region, p.state));
  }

  return {
    observe(held) {
      const t = opts.now();
      for (const [key, ep] of episodes) {
        if (t - ep.lastSeen >= THRESHOLDS.episodeCloseMs) {
          episodes.delete(key);
          pending.delete(key);
        }
      }
      for (const o of held) {
        const key = keyOf(o.region, o.state);
        const open = episodes.get(key);
        if (open !== undefined) {
          open.lastSeen = t;
          open.subjects.add(o.subject);
          pending.get(key)?.subjects.add(o.subject);
          continue;
        }
        nextId += 1;
        episodes.set(key, { id: nextId, lastSeen: t, subjects: new Set([o.subject]) });
        if (STATES[o.state].announce !== "never") {
          pending.set(key, {
            region: o.region,
            state: o.state,
            episode: nextId,
            firstAt: t,
            subjects: new Set([o.subject]),
          });
        }
      }
      flush();
    },
    flush,
    reset() {
      episodes.clear();
      pending.clear();
      lastPoliteAt = -Infinity;
    },
  };
}

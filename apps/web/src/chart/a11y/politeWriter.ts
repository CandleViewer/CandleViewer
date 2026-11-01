/**
 * The ambient live-region writer (E47-S01 B1, `05` §6.2): per field, latest wins, at most one polite write per
 * cadence, over the shell's one announcer (no region of its own). Discrete events (a disconnect, a data gap) take the
 * assertive path at once and are never coalesced.
 *
 * Allocation: `set` stores the caller's string in a preallocated slot and arms at most one timer per cadence window,
 * so a 20 Hz stream allocates nothing per tick here.
 */
import { useEffect, useRef } from "react";
import {
  REGION_BUDGET_MS,
  announce,
  forget,
  lastWrittenAt,
  type Politeness,
} from "../../features/app-shell/announcer";
import { shouldAnnounce, type A11yPreferences } from "../../features/a11y-preferences/model";
import { usePreferences } from "../../features/a11y-preferences/PreferencesContext";

/**
 * `05` §6.2's default: one update per 2 s per field. The settings document has no cadence field yet (E06-D03 names
 * `a11y.ambientCadenceMs`); until it does, callers pass the value and this is the default.
 */
export const AMBIENT_CADENCE_MS = 2_000;

export type AnnouncePrefs = Pick<A11yPreferences, "announce_prices" | "verbosity">;

export interface AmbientWriterOptions {
  /** The fields, in reading order (e.g. last, bid, ask, mark, unrealised P&L). */
  readonly fields: readonly string[];
  /** The user's announcement preferences, read at each `set`. */
  readonly prefs: () => AnnouncePrefs;
  readonly cadenceMs?: number;
  /** Writes one message; defaults to the shell announcer. */
  readonly say?: (politeness: Politeness, text: string) => void;
  readonly now?: () => number;
}

export interface AmbientWriter {
  /** The field's latest text; `significant` lets it through under `announce_prices: "significant"`. */
  set(field: string, text: string, significant?: boolean): void;
  /** A discrete event, assertive and at once; pending ambient values are dropped as stale. */
  alert(text: string): void;
  /** Cancels the pending write; the writer stays silent afterwards. */
  dispose(): void;
}

let seq = 0;
/** The shell announcer says a key once; a fresh key per message, forgotten at once, keeps it re-sayable. */
export function sayToShell(politeness: Politeness, text: string): void {
  seq += 1;
  const key = `chart-a11y:${seq}`;
  announce(politeness, text, key);
  forget(key);
}

export function createAmbientWriter(options: AmbientWriterOptions): AmbientWriter {
  const { fields, prefs, cadenceMs = AMBIENT_CADENCE_MS, say = sayToShell } = options;
  const now = options.now ?? ((): number => Date.now());
  const latest: (string | null)[] = fields.map(() => null);
  let timer: ReturnType<typeof setTimeout> | null = null;
  let lastOwnWrite = -Infinity;
  let disposed = false;

  const flush = (): void => {
    timer = null;
    if (disposed) return;
    const parts: string[] = [];
    for (let i = 0; i < latest.length; i++) {
      const text = latest[i];
      if (text !== null && text !== undefined) parts.push(text);
      latest[i] = null;
    }
    if (parts.length === 0) return;
    say("polite", parts.join(". "));
    lastOwnWrite = now();
  };

  const schedule = (): void => {
    if (timer !== null) return;
    const t = now();
    // Another writer's message is not cut inside the shell's per-region budget (E17-D02 §11).
    const other = lastWrittenAt("polite");
    const foreign = other > lastOwnWrite ? other + REGION_BUDGET_MS : -Infinity;
    const due = Math.max(lastOwnWrite + cadenceMs, foreign, t);
    timer = setTimeout(flush, due - t);
  };

  return {
    set(field, text, significant = false) {
      if (disposed) return;
      const slot = fields.indexOf(field);
      if (slot < 0) throw new RangeError(`unknown ambient field "${field}"`);
      // Eligibility only; the cadence itself is this writer's timer, so the latest value is never lost.
      if (!shouldAnnounce(prefs(), { significant, cadenceElapsed: true })) return;
      latest[slot] = text;
      schedule();
    },
    alert(text) {
      if (disposed) return;
      latest.fill(null);
      say("assertive", text);
    },
    dispose() {
      disposed = true;
      if (timer !== null) clearTimeout(timer);
      timer = null;
    },
  };
}

/**
 * The writer for a component's lifetime, reading the preferences live; disposed on unmount (no write after it).
 * `fields` is read once, at mount.
 */
export function useAmbientWriter(
  fields: readonly string[],
  cadenceMs: number = AMBIENT_CADENCE_MS,
): AmbientWriter {
  const { prefs } = usePreferences();
  const prefsRef = useRef<AnnouncePrefs>(prefs);
  prefsRef.current = prefs;
  const writer = useRef<AmbientWriter | null>(null);
  const fieldsRef = useRef(fields);
  useEffect(() => {
    const created = createAmbientWriter({
      fields: fieldsRef.current,
      prefs: () => prefsRef.current,
      cadenceMs,
    });
    writer.current = created;
    return () => {
      created.dispose();
      if (writer.current === created) writer.current = null;
    };
  }, [cadenceMs]);
  const facade = useRef<AmbientWriter>({
    set: (field, text, significant) => writer.current?.set(field, text, significant),
    alert: (text) => writer.current?.alert(text),
    dispose: () => writer.current?.dispose(),
  });
  return facade.current;
}

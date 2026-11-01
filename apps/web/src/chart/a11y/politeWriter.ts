/**
 * The ambient live-region writer (E47-S01 B1, `05` §6.2): per field, latest wins, at most one polite write per
 * cadence, over the shell's one announcer (no region of its own). Discrete events (a disconnect, a data gap) take the
 * assertive path at once and are never coalesced.
 *
 * Allocation: `set` stores the caller's string in a preallocated slot and arms at most one timer per cadence window,
 * so a 20 Hz stream allocates nothing per tick here.
 */
import { useEffect, useInsertionEffect, useRef } from "react";
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
  /** The cadence, or a reader of it: a reader lets the cadence change without losing pending values. */
  readonly cadenceMs?: number | (() => number);
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

/** The table's polite line through the shell announcer. */
export const politeToShell = (text: string): void => sayToShell("polite", text);

export function createAmbientWriter(options: AmbientWriterOptions): AmbientWriter {
  const { fields, prefs, say = sayToShell } = options;
  const option = options.cadenceMs;
  const cadence =
    typeof option === "function" ? option : (): number => option ?? AMBIENT_CADENCE_MS;
  const now = options.now ?? ((): number => Date.now());
  const latest: (string | null)[] = fields.map(() => null);
  /** What each field last said: an unchanged value is not said again (a flat market stays quiet). */
  const spoken: (string | null)[] = fields.map(() => null);
  let timer: ReturnType<typeof setTimeout> | null = null;
  let lastOwnWrite = -Infinity;
  let disposed = false;

  const flush = (): void => {
    timer = null;
    if (disposed) return;
    const parts: string[] = [];
    for (let i = 0; i < latest.length; i++) {
      const text = latest[i];
      if (text !== null && text !== undefined) {
        parts.push(text);
        spoken[i] = text;
      }
      latest[i] = null;
    }
    if (parts.length === 0) return;
    // PROPOSED joiner pending E47-D06 (#1305): fields read as sentences (". "); the bar sentence uses ", ".
    say("polite", parts.join(". "));
    lastOwnWrite = now();
  };

  const schedule = (): void => {
    if (timer !== null) return;
    const t = now();
    // Another writer's message is not cut inside the shell's per-region budget (E17-D02 §11).
    const other = lastWrittenAt("polite");
    const foreign = other > lastOwnWrite ? other + REGION_BUDGET_MS : -Infinity;
    const due = Math.max(lastOwnWrite + cadence(), foreign, t);
    timer = setTimeout(flush, due - t);
  };

  return {
    set(field, text, significant = false) {
      if (disposed) return;
      const slot = fields.indexOf(field);
      if (slot < 0) throw new RangeError(`unknown ambient field "${field}"`);
      // Eligibility only; the cadence itself is this writer's timer, so the latest value is never lost.
      if (!shouldAnnounce(prefs(), { significant, cadenceElapsed: true })) return;
      if (text === spoken[slot]) {
        latest[slot] = null; // latest wins, and the latest is what was last said
        return;
      }
      latest[slot] = text;
      schedule();
    },
    alert(text) {
      if (disposed) return;
      latest.fill(null);
      spoken.fill(null); // after a disconnect, the next value is news again
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
 * The writer for a component's lifetime, reading the preferences and the cadence live; disposed on unmount (no
 * write after it). Created on first use, so a child's mount effect that writes before this hook's effect runs is
 * heard, and a cadence change keeps the pending values. `fields` is read once, at first use.
 */
export function useAmbientWriter(
  fields: readonly string[],
  cadenceMs: number = AMBIENT_CADENCE_MS,
): AmbientWriter {
  const { prefs } = usePreferences();
  const prefsRef = useRef<AnnouncePrefs>(prefs);
  const cadenceRef = useRef(cadenceMs);
  // Refs follow the render in an effect (render stays pure); insertion effects run before any layout effect.
  useInsertionEffect(() => {
    prefsRef.current = prefs;
    cadenceRef.current = cadenceMs;
  });
  const fieldsRef = useRef(fields);
  const writer = useRef<AmbientWriter | null>(null);
  const unmounted = useRef(false);
  useEffect(() => {
    unmounted.current = false; // StrictMode's second mount: the next write creates a fresh writer
    return () => {
      unmounted.current = true;
      writer.current?.dispose();
      writer.current = null;
    };
  }, []);
  const facade = useRef<AmbientWriter | null>(null);
  facade.current ??= ((): AmbientWriter => {
    const get = (): AmbientWriter | null => {
      if (unmounted.current) return null;
      writer.current ??= createAmbientWriter({
        fields: fieldsRef.current,
        prefs: () => prefsRef.current,
        cadenceMs: () => cadenceRef.current,
      });
      return writer.current;
    };
    return {
      set: (field, text, significant) => get()?.set(field, text, significant),
      alert: (text) => get()?.alert(text),
      dispose: () => writer.current?.dispose(),
    };
  })();
  return facade.current;
}

/**
 * The shell's one announcer (E10-S01 S3, #304): E17-D02 §11's "one live-region pair (polite +
 * assertive) pre-rendered empty at load, owned by the app shell; components write into it".
 * `ShellLayout` renders `ShellAnnouncer` once; writers call `announce`, never a region of their own.
 *
 * A key is announced once, whoever writes it, until `forget(key)` or `clearAnnouncements()` (which
 * also empties both regions, so no stale text outlives the condition). The connection rows use
 * `CONNECTION_KEYS`; their one writer is CMP-077's container (`ConnectionRegionSlot`, #306 slice
 * 4b), which owns no second live region and ends its episode with
 * `clearAnnouncements(CONNECTION_PREFIX)`, leaving other writers' keys and text alone.
 */
import { useSyncExternalStore, type JSX } from "react";
import { HIDDEN } from "./SkipLink";

export type Politeness = "polite" | "assertive";

/** §11 row 1 (entering Disconnected) and row 14 (retry stopped), one key per row per episode. */
export const CONNECTION_KEYS = {
  disconnected: "connection:disconnected",
  retryStopped: "connection:retry-stopped",
} as const;
/** Every connection key starts with this: `CONNECTION_KEYS` and the region's row 2 keys. */
export const CONNECTION_PREFIX = "connection:";

type Message = { readonly text: string; readonly seq: number; readonly key: string };
type Regions = Readonly<Record<Politeness, Message | null>>;
const EMPTY: Regions = { polite: null, assertive: null };

let regions: Regions = EMPTY;
let seq = 0;
const said = new Set<string>();
const listeners = new Set<() => void>();
const emit = (): void => listeners.forEach((listener) => listener());

/** Announces `text` unless `key` was already said; `true` when it was written. */
export function announce(politeness: Politeness, text: string, key: string): boolean {
  if (said.has(key)) return false;
  said.add(key);
  seq += 1; // a new node per message, so the same words in a later episode are read again
  regions = { ...regions, [politeness]: { text, seq, key } };
  emit();
  return true;
}

/** Lets `key` be said again (e.g. row 14 once per entry). */
export function forget(key: string): void {
  said.delete(key);
}

/**
 * Ends an episode: forgets the keys and empties the regions. With `prefix`, only the keys that start
 * with it, and a region only while its message is one of them; without, every key and both regions.
 */
export function clearAnnouncements(prefix?: string): void {
  const ours = (key: string): boolean => prefix === undefined || key.startsWith(prefix);
  for (const key of [...said]) if (ours(key)) said.delete(key);
  const keep = (m: Message | null): Message | null => (m !== null && ours(m.key) ? null : m);
  const next: Regions = { polite: keep(regions.polite), assertive: keep(regions.assertive) };
  if (next.polite === regions.polite && next.assertive === regions.assertive) return;
  regions = next.polite === null && next.assertive === null ? EMPTY : next;
  emit();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
const snapshot = (): Regions => regions;

export function ShellAnnouncer(): JSX.Element {
  const current = useSyncExternalStore(subscribe, snapshot, snapshot);
  const region = (politeness: Politeness): JSX.Element => {
    const message = current[politeness];
    return (
      <div aria-live={politeness} aria-atomic="true" style={HIDDEN}>
        {message === null ? null : (
          <p key={message.seq} data-seq={message.seq}>
            {message.text}
          </p>
        )}
      </div>
    );
  };
  return (
    <>
      {region("polite")}
      {region("assertive")}
    </>
  );
}

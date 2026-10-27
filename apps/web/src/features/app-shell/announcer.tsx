/**
 * The shell's one announcer (E10-S01 S3, #304): E17-D02 §11's "one live-region pair (polite +
 * assertive) pre-rendered empty at load, owned by the app shell; components write into it".
 * `ShellLayout` renders `ShellAnnouncer` once; writers call `announce`, never a region of their own.
 *
 * A key is announced once, whoever writes it, until `forget(key)` or `clearAnnouncements()` (which
 * also empties both regions, so no stale text outlives the condition). The connection rows use
 * `CONNECTION_KEYS`; their episode ends on the return to live, where the writer clears.
 * **CMP-077's callout (#306 slice 4b) must write §11 rows 1 and 14 through `announce` with these
 * keys and must not own a second live region for them**; the chip container writes the same rows.
 */
import { useSyncExternalStore, type JSX } from "react";
import { HIDDEN } from "./SkipLink";

export type Politeness = "polite" | "assertive";

/** §11 row 1 (entering Disconnected) and row 14 (retry stopped), one key per row per episode. */
export const CONNECTION_KEYS = {
  disconnected: "connection:disconnected",
  retryStopped: "connection:retry-stopped",
} as const;

type Regions = Readonly<Record<Politeness, { readonly text: string; readonly seq: number } | null>>;
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
  regions = { ...regions, [politeness]: { text, seq } };
  emit();
  return true;
}

/** Lets `key` be said again (e.g. row 14 once per entry). */
export function forget(key: string): void {
  said.delete(key);
}

/** Ends every episode: forgets the keys and empties both regions. */
export function clearAnnouncements(): void {
  said.clear();
  if (regions === EMPTY) return;
  regions = EMPTY;
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

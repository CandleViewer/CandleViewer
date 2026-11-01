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

export type Politeness = "polite" | "assertive";

/** §11 row 1 (entering Disconnected) and row 14 (retry stopped), one key per row per episode. */
export const CONNECTION_KEYS = {
  disconnected: "connection:disconnected",
  retryStopped: "connection:retry-stopped",
} as const;
/** Every connection key starts with this: `CONNECTION_KEYS` and the region's row 2 keys. */
export const CONNECTION_PREFIX = "connection:";
/** E17-D02 §11: at most one message per 5 s per region, so a later writer never cuts the last one. */
export const REGION_BUDGET_MS = 5_000;

type Message = { readonly text: string; readonly seq: number; readonly key: string };
type Regions = Readonly<Record<Politeness, Message | null>>;
const EMPTY: Regions = { polite: null, assertive: null };

let regions: Regions = EMPTY;
let writtenAt: Readonly<Record<Politeness, number>> = { polite: -Infinity, assertive: -Infinity };
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
  writtenAt = { ...writtenAt, [politeness]: Date.now() };
  emit();
  return true;
}

/** When a region was last written (epoch ms): a writer waits out REGION_BUDGET_MS from here. */
export function lastWrittenAt(politeness: Politeness): number {
  return writtenAt[politeness];
}

/** However often others speak, a line waiting its turn gives way to them for this long in all (9a's cap). */
export const REGION_TURN_CAP_MS = 15_000;

/**
 * 9a's turn in the assertive region (E17-D02 §11), for any writer: `speak` runs once the region has been quiet
 * REGION_BUDGET_MS since its last message, whoever wrote it, so a later writer never cuts it; re-armed by a write
 * meanwhile, each wait at most the budget and REGION_TURN_CAP_MS in all. Returns the cancel.
 */
export function afterAssertiveBudget(speak: () => void): () => void {
  let id: ReturnType<typeof setTimeout> | undefined;
  let waited = 0; // counted by the timers, so a wall-clock step cannot stretch the cap
  const attempt = (armedAt?: number): void => {
    const last = lastWrittenAt("assertive");
    if (last === armedAt) return speak(); // nobody spoke during the wait: the budget is spent
    const since = last + REGION_BUDGET_MS - Date.now();
    const waitMs = Math.min(since, REGION_BUDGET_MS, REGION_TURN_CAP_MS - waited);
    if (waitMs <= 0) return speak();
    waited += waitMs;
    id = setTimeout(() => attempt(last), waitMs);
  };
  attempt();
  return () => clearTimeout(id);
}

/** Lets `key` be said again (e.g. row 14 once per entry). */
export function forget(key: string): void {
  said.delete(key);
}

/**
 * Ends an episode: forgets the keys and empties the regions. With `prefix`, only the keys that start
 * with it, and a region only while its message is one of them; without, every key and both regions,
 * and the write times too.
 */
export function clearAnnouncements(prefix?: string): void {
  if (prefix === undefined) writtenAt = { polite: -Infinity, assertive: -Infinity };
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
      // live under a CMP-043 modal too (E05-D02 H23)
      <div
        aria-live={politeness}
        aria-atomic="true"
        className="cv-visually-hidden"
        data-cv-inert-exempt=""
      >
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

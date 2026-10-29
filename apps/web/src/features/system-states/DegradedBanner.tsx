import { useEffect, useMemo, useRef, useState, type CSSProperties, type JSX } from "react";
import { useShellState } from "../../shell/useShellState";
import {
  announce,
  clearAnnouncements,
  forget,
  lastWrittenAt,
  REGION_BUDGET_MS,
} from "../app-shell/announcer";
import { DegradedModeBanner } from "./DegradedModeBanner";
import { selectDegradedIssues, type DegradedIssue } from "./degradedIssues";

type IssueId = DegradedIssue["id"];

export const POLITE_GAP_MS = 5_000; // §11: ≤1 ambient (polite) announcement per 5 s per region
/** CMP-092's keys in the shell announcer: one per set of rows said together. */
const SAID_PREFIX = "degraded:";
/** However often others speak, an entry gives way to them for this long in all (9a's cap). */
const ENTRY_CAP_MS = 15_000;

/** Visually hidden, still in the accessibility tree (the clip pattern). */
const HIDDEN: CSSProperties = { position: "absolute", clipPath: "inset(50%)", width: 1, height: 1 };

/** `n` keys the written node: a new write replaces it, so the same sentence is announced again. */
type Said = { readonly text: string; readonly n: number };
const SILENT: Said = { text: "", n: 0 };
const NO_DISMISSALS: ReadonlyMap<IssueId, number> = new Map();

const fullText = (i: DegradedIssue): string =>
  i.stillWorks === null ? i.message : `${i.message} ${i.stillWorks}`;

/**
 * 9a's turn (`OfflineOverlay`): `speak` runs once the shell's assertive region has been quiet
 * REGION_BUDGET_MS (E17-D02 §11), CMP-092's own last words included, so a row's sentence never
 * cuts another's; re-armed by a write meanwhile, each wait at most the budget, ENTRY_CAP_MS in all.
 */
function afterAssertiveBudget(speak: () => void): () => void {
  let id: ReturnType<typeof setTimeout> | undefined;
  let waited = 0; // counted by the timers, so a wall-clock step cannot stretch the cap
  const attempt = (armedAt?: number): void => {
    const last = lastWrittenAt("assertive");
    if (last === armedAt) return speak(); // nobody spoke during the wait: the budget is spent
    const since = last + REGION_BUDGET_MS - Date.now();
    const waitMs = Math.min(since, REGION_BUDGET_MS, ENTRY_CAP_MS - waited);
    if (waitMs <= 0) return speak();
    waited += waitMs;
    id = setTimeout(() => attempt(last), waitMs);
  };
  attempt();
  return () => clearTimeout(id);
}

/**
 * SCR-153's banner slot content (E10-S04 slice 3, #306; E17-D02 §8, §11). Reads `useShellState()`
 * through the memoized `selectDegradedIssues`; swap to #4754's `useShellSelector` in a follow-up.
 * Dismissal hides a row while its `assertedSeq` is the dismissed one, so a re-asserting frame brings
 * it back; the entry is dropped once the condition clears. Announcements on a row's entry only, as
 * its class says (`announce`): assertive "{message} {stillWorks}" through the shell announcer at
 * its turn, the rows that entered meanwhile in one message in the §6 order; polite the message,
 * ≤1 per 5 s; exit: unspecified (no merged string). The polite region is this component's own,
 * pre-rendered empty at load (§11) with no role (as the announcer's); moving it onto the announcer
 * is a follow-up. Both are cleared when the last row goes.
 */
export function DegradedBanner(): JSX.Element {
  const issues = selectDegradedIssues(useShellState().degraded);
  const [dismissed, setDismissed] = useState(NO_DISMISSALS);
  const visible = useMemo(
    () => issues.filter((i) => dismissed.get(i.id) !== i.assertedSeq),
    [issues, dismissed],
  );
  useEffect(() => {
    setDismissed((prev) => {
      const held = [...prev].filter(([id]) => issues.some((i) => i.id === id));
      return held.length === prev.size ? prev : new Map(held);
    });
  }, [issues]);
  const onDismiss = (id: IssueId): void => {
    const seq = visible.find((i) => i.id === id)?.assertedSeq;
    if (seq !== undefined) setDismissed((prev) => new Map(prev).set(id, seq));
  };

  const [polite, setPolite] = useState(SILENT);
  const shown = useRef<ReadonlySet<IssueId>>(new Set());
  const visibleNow = useRef(visible);
  const urgent = useRef<ReadonlySet<IssueId>>(new Set()); // assertive entries awaiting their turn
  const pending = useRef<DegradedIssue[]>([]);
  const lastPolite = useRef(-Infinity);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const turn = useRef<(() => void) | null>(null); // the pending assertive turn's cancel

  useEffect(() => {
    visibleNow.current = visible;
    if (visible.length === 0) {
      // No row: no stale sentence is left in the regions for a reading cursor to find.
      clearAnnouncements(SAID_PREFIX);
      setPolite((s) => (s.text === "" ? s : { text: "", n: s.n }));
    }
    const entered = visible.filter((i) => !shown.current.has(i.id));
    shown.current = new Set(visible.map((i) => i.id));
    const assertive = entered.filter((i) => i.announce === "assertive").map((i) => i.id);
    if (assertive.length > 0) urgent.current = new Set([...urgent.current, ...assertive]);
    const ambient = entered.filter((i) => i.announce !== "assertive");
    if (ambient.length === 0) return;
    pending.current.push(...ambient);
    const flush = (): void => {
      timer.current = null;
      // A row that left while queued is not announced late.
      const still = pending.current.filter((p) => visibleNow.current.some((v) => v.id === p.id));
      pending.current = [];
      if (still.length === 0) return;
      lastPolite.current = Date.now();
      setPolite((s) => ({ text: still.map((i) => i.message).join(" "), n: s.n + 1 }));
    };
    const wait = lastPolite.current + POLITE_GAP_MS - Date.now();
    if (wait <= 0) flush();
    else timer.current ??= setTimeout(flush, wait);
  }, [visible]);
  // The assertive entries' turn: one per pending set, so a frame that re-asserts a held row never
  // restarts it and 9a's cap holds in all; it reads the rows as they are when it fires, and an
  // unmount (StrictMode's too) cancels it.
  useEffect(() => {
    if (urgent.current.size === 0 || turn.current !== null) return;
    let spoken = false;
    const cancel = afterAssertiveBudget(() => {
      spoken = true;
      turn.current = null;
      // In the §6 order; a row that left while it waited is not announced late.
      const said = visibleNow.current.filter((i) => urgent.current.has(i.id));
      urgent.current = new Set();
      if (said.length === 0) return;
      const key = SAID_PREFIX + said.map((i) => i.id).join("+");
      forget(key); // each entry is said once by the logic above; the key scopes the clearing
      announce("assertive", said.map(fullText).join(" "), key);
    });
    if (!spoken) turn.current = cancel;
  }, [visible]);
  useEffect(
    () => () => {
      clearTimeout(timer.current ?? undefined);
      timer.current = null;
      turn.current?.();
      turn.current = null;
    },
    [],
  );

  return (
    <>
      <div aria-live="polite" aria-atomic="true" style={HIDDEN}>
        {polite.text === "" ? null : <span key={polite.n}>{polite.text}</span>}
      </div>
      {visible.length > 0 ? <DegradedModeBanner issues={visible} onDismiss={onDismiss} /> : null}
    </>
  );
}

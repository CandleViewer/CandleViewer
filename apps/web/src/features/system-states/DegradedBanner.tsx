import { useEffect, useMemo, useRef, useState, type CSSProperties, type JSX } from "react";
import { useShellState } from "../../shell/useShellState";
import { DegradedModeBanner } from "./DegradedModeBanner";
import { selectDegradedIssues, type DegradedIssue } from "./degradedIssues";

type IssueId = DegradedIssue["id"];

export const POLITE_GAP_MS = 5_000; // §11: ≤1 ambient (polite) announcement per 5 s per region

/** Visually hidden, still in the accessibility tree (the clip pattern). */
const HIDDEN: CSSProperties = { position: "absolute", clipPath: "inset(50%)", width: 1, height: 1 };

/** `n` keys the written node: a new write replaces it, so the same sentence is announced again. */
type Said = { readonly text: string; readonly n: number };
const SILENT: Said = { text: "", n: 0 };
const NO_DISMISSALS: ReadonlyMap<IssueId, number> = new Map();

const blockingText = (i: DegradedIssue): string =>
  i.stillWorks === null ? i.message : `${i.message} ${i.stillWorks}`;

/**
 * SCR-153's banner slot content (E10-S04 slice 3, #306; E17-D02 §8, §11). Reads `useShellState()`
 * through the memoized `selectDegradedIssues`; swap to #4754's `useShellSelector` in a follow-up.
 * Dismissal hides a row while its `assertedSeq` is the dismissed one, so a re-asserting frame brings
 * it back; the entry is dropped once the condition clears. Announcements on a row's entry only:
 * blocking assertive "{message} {stillWorks}", info / warning polite (the message, ≤1 per 5 s);
 * exit: unspecified (no merged string). This pair is pre-rendered empty at load (§11), cleared
 * when the last row goes, and has no role (as #4754's announcer), so it never collides with a
 * screen's own `status` / `alert`. Moving onto #4754's announcer is a follow-up.
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

  const [assertive, setAssertive] = useState(SILENT);
  const [polite, setPolite] = useState(SILENT);
  const shown = useRef<ReadonlySet<IssueId>>(new Set());
  const visibleNow = useRef(visible);
  const pending = useRef<DegradedIssue[]>([]);
  const lastPolite = useRef(-Infinity);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    visibleNow.current = visible;
    if (visible.length === 0) {
      // No row: no stale sentence is left in the regions for a reading cursor to find.
      setAssertive((s) => (s.text === "" ? s : { text: "", n: s.n }));
      setPolite((s) => (s.text === "" ? s : { text: "", n: s.n }));
    }
    const entered = visible.filter((i) => !shown.current.has(i.id));
    shown.current = new Set(visible.map((i) => i.id));
    const blocking = entered.filter((i) => i.severity === "blocking");
    if (blocking.length > 0) {
      setAssertive((s) => ({ text: blocking.map(blockingText).join(" "), n: s.n + 1 }));
    }
    const ambient = entered.filter((i) => i.severity !== "blocking");
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
  useEffect(
    () => () => {
      clearTimeout(timer.current ?? undefined);
      timer.current = null;
    },
    [],
  );

  return (
    <>
      <div aria-live="polite" aria-atomic="true" style={HIDDEN}>
        {polite.text === "" ? null : <span key={polite.n}>{polite.text}</span>}
      </div>
      <div aria-live="assertive" aria-atomic="true" style={HIDDEN}>
        {assertive.text === "" ? null : <span key={assertive.n}>{assertive.text}</span>}
      </div>
      {visible.length > 0 ? <DegradedModeBanner issues={visible} onDismiss={onDismiss} /> : null}
    </>
  );
}

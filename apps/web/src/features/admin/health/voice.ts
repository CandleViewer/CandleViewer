/**
 * SCR-143's voice (E42-D05 §5.3 Keys, §13; D02:690), through the shell's announcer and no live
 * region of the page's own. A component entering degraded, warning or down, or the clock drifting,
 * is said once, assertive (`health.announce`); its return to healthy once, polite; key
 * `admin:health:{name}:{state}`. The arrival says nothing. A failed report read is said once per
 * read, polite (HL-11, HL-12). A line waits out the 5 s budget (E17-D02 §11) of its region and of
 * its component's last line; a state that flips back meanwhile says nothing, so a flap collapses.
 * A word the client cannot read (`not_received`) says nothing and ends the episode. "as of" and
 * ages never speak.
 */
import { useEffect, useRef } from "react";
import { announce, forget, lastWrittenAt, REGION_BUDGET_MS } from "../../app-shell/announcer";
import { HEALTH_COPY as COPY } from "./copy";

export type Voiced = { readonly name: string; readonly label: string; readonly state: string };
/** A failed report read: its words, and the store's count of answers, one line per read. */
export type ReportFailure = { readonly text: string; readonly answers: number };

type Line = { politeness: "polite" | "assertive"; text: string; key: string; state: string };
interface Visit {
  /** Each component's state as last said or as the page arrived; null until the arrival. */
  heard: Map<string, string> | null;
  /** The newest unsaid line per component, and the report's. */
  waiting: Map<string, Line>;
  /** When each component's last line was said, and every key said this visit. */
  saidAt: Map<string, number>;
  said: Set<string>;
  timer: ReturnType<typeof setTimeout> | null;
}

const BAD: ReadonlySet<string> = new Set(["degraded", "warning", "down", COPY.clock.word]);
const GOOD: ReadonlySet<string> = new Set(["healthy", "ok"]);
const keyOf = (name: string, state: string): string => `admin:health:${name}:${state}`;
/** The report line's slot: no component name has a space. */
const REPORT = "report line";

function lineFor(prev: string, { name, label, state }: Voiced): Line | null {
  const key = keyOf(name, state);
  if (BAD.has(state))
    return { politeness: "assertive", text: COPY.announce(label, state), key, state };
  if (!GOOD.has(state) || !BAD.has(prev)) return null;
  return { politeness: "polite", text: COPY.recovered(label), key, state };
}

/** Says each waiting line whose region and component have been quiet a budget; else waits. */
function flush(visit: Visit): void {
  visit.timer = null;
  let wait = Infinity;
  for (const [name, line] of visit.waiting) {
    const quiet = Math.max(lastWrittenAt(line.politeness), visit.saidAt.get(name) ?? -Infinity);
    const left = quiet + REGION_BUDGET_MS - Date.now();
    if (left > 0) {
      wait = Math.min(wait, left);
      continue;
    }
    visit.waiting.delete(name);
    const prev = visit.heard?.get(name);
    if (prev !== undefined) forget(keyOf(name, prev)); // its next episode is said again
    if (name !== REPORT) visit.heard?.set(name, line.state);
    visit.saidAt.set(name, Date.now());
    if (announce(line.politeness, line.text, line.key)) visit.said.add(line.key);
  }
  if (wait !== Infinity) visit.timer = setTimeout(() => flush(visit), wait);
}

export function useHealthVoice(states: readonly Voiced[], report: ReportFailure | undefined): void {
  const ref = useRef<Visit>({
    heard: null,
    waiting: new Map(),
    saidAt: new Map(),
    said: new Set(),
    timer: null,
  });

  useEffect(() => {
    const visit = ref.current;
    if (states.length === 0) return;
    if (visit.heard === null) {
      visit.heard = new Map(states.map((s) => [s.name, s.state]));
      return;
    }
    for (const next of states) {
      const prev = visit.heard.get(next.name);
      const line = prev === undefined || prev === next.state ? null : lineFor(prev, next);
      if (prev === undefined || (line === null && prev !== next.state)) {
        // A new component, or a change with nothing to say (`not_received` is one): its last
        // episode is over, so a return to it is said again (A-1084P1-d01).
        if (prev !== undefined) forget(keyOf(next.name, prev));
        visit.heard.set(next.name, next.state);
      }
      if (line === null) visit.waiting.delete(next.name);
      else visit.waiting.set(next.name, line);
    }
    if (visit.timer === null) flush(visit);
  }, [states]);

  const { text, answers } = report ?? {};
  useEffect(() => {
    if (text === undefined) return;
    const visit = ref.current;
    const key = `admin:health:report:${answers ?? 0}`;
    visit.waiting.set(REPORT, { politeness: "polite", text, key, state: key });
    if (visit.timer === null) flush(visit);
  }, [text, answers]);

  useEffect(() => {
    const visit = ref.current;
    return () => {
      if (visit.timer !== null) clearTimeout(visit.timer);
      for (const key of visit.said) forget(key);
    };
  }, []);
}

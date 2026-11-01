/**
 * Routes the engine's `candleviewer:announce` CustomEvent (`{ politeness, text, key }`, BQ-198: the
 * engine owns no live region) to the shell's one announcer (E11-S07, BQ-21). Mount it as a child of
 * `<Chart>`. Each engine message replaces the last for its key ("latest state"), so the key is
 * forgotten first; the engine already coalesces on E06-D03 D5's cadence.
 */
import { useEffect, type ReactNode } from "react";
import { useChartContainer } from "../../chart";
import { announce, forget, type Politeness } from "../app-shell/announcer";

export const ANNOUNCE_EVENT = "candleviewer:announce";

interface Detail {
  readonly politeness: Politeness;
  readonly text: string;
  readonly key: string;
}

const isDetail = (d: unknown): d is Detail => {
  if (typeof d !== "object" || d === null) return false;
  const r = d as Partial<Record<keyof Detail, unknown>>;
  return (
    (r.politeness === "polite" || r.politeness === "assertive") &&
    typeof r.text === "string" &&
    r.text !== "" &&
    typeof r.key === "string" &&
    r.key !== ""
  );
};

export function ChartAnnounceRoute(): ReactNode {
  const container = useChartContainer();
  useEffect(() => {
    if (container === null) return undefined;
    const onAnnounce = (e: Event): void => {
      const detail: unknown = (e as CustomEvent<unknown>).detail;
      if (!isDetail(detail)) return;
      forget(detail.key);
      announce(detail.politeness, detail.text, detail.key);
    };
    container.addEventListener(ANNOUNCE_EVENT, onAnnounce);
    return () => container.removeEventListener(ANNOUNCE_EVENT, onAnnounce);
  }, [container]);
  return null;
}

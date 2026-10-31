import { useEffect, useState, type JSX } from "react";
import { useWsState } from "../../lib/ws/client/useWsState";
import { connectionPresentation } from "../../lib/ws/state/connectionPresentation";
import { useShellSelector } from "../../shell/useShellSelector.js";
import { ConnectionStatus } from "./ConnectionStatus";

/**
 * CMP-076's container (#304 S3, S10), `ShellConnectionSlot`'s content. It reads the link through
 * `useWsState()` and `connectionPresentation` (BQ-02), so the chip, the status bar and the CMP-077
 * region split the link the same way, a fatal close reads "Offline — retry stopped", and the age
 * runs from the real last-data time (`outage.lastDataMs`). `useWsState()` is referentially stable
 * between transitions, so only a transition, the latency value and the 1 Hz age re-render it.
 * It announces nothing: E17-D02 §11 rows 1 and 14 are CMP-077's (`ConnectionRegionSlot`), and the
 * chip has no row of its own (row 5's Delayed entry is the host panel's; ages are row 10's "never").
 */
export function ConnectionStatusSlot(): JSX.Element {
  const ws = useWsState();
  const latencyMs = useShellSelector((s) => s.latency.valueMs);
  const { chip, lastGoodTs } = connectionPresentation(ws);
  // Read at render: a transition renders with the clock of that moment, never the last tick's.
  const [, setTick] = useState(0);
  const nowMs = Date.now();

  const ticking = chip.status !== "live" && lastGoodTs !== null;
  useEffect(() => {
    if (!ticking) return undefined;
    const id = setInterval(() => setTick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, [ticking]);

  return <ConnectionStatus {...chip} lastGoodTs={lastGoodTs} latencyMs={latencyMs} nowMs={nowMs} />;
}

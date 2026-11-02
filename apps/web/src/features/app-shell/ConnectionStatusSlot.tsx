import { useEffect, useReducer, useState, type JSX } from "react";
import { getActiveClient } from "../../lib/ws/client/activeClient";
import { useWsState } from "../../lib/ws/client/useWsState";
import {
  NO_CHIP_MEMORY,
  selectChip,
  stepChipMemory,
  type ChipInput,
  type ChipView,
  type TopicReading,
} from "../../lib/ws/state/chipState";
import type { WsState } from "../../lib/ws/state/types";
import type { ShellState } from "../../shell/bootstrap/store.js";
import { useShellSelector } from "../../shell/useShellSelector.js";
import { ConnectionStatus, type ConnectionStatusProps } from "./ConnectionStatus";

const NO_TOPICS: readonly TopicReading[] = Object.freeze([]);

/** §2 row 13: SCR-153's fact (`degradedIssues`, routing row 8), the one CMP-092 shows. */
const upstreamDownOf = (s: ShellState): boolean =>
  s.degraded.asserted.exchangeFeedDown !== undefined;

/** §9: the last `connection_quality`'s `applied.throttle_multiplier`, when it slows anything down. */
function multiplierOf(s: ShellState): number | undefined {
  const n: unknown = s.systemByKind.connection_quality?.applied?.throttle_multiplier;
  return typeof n === "number" && Number.isFinite(n) && n > 1 ? n : undefined;
}

/** What `selectChip` reads, at the time of the call: the topics and the clock are read, never pushed. */
function chipInput(ws: WsState, upstreamDown: boolean, multiplier: number | undefined): ChipInput {
  return {
    ws,
    upstreamDown,
    throttleMultiplier: ws.quality === "saturated" ? multiplier : undefined,
    topics: getActiveClient()?.topics() ?? NO_TOPICS,
    nowMs: Date.now(),
  };
}

type ChipProps = Omit<ConnectionStatusProps, "latencyMs" | "nowMs">;

/** CMP-076's props for a view (E17-D02 §5's names); an absent value is no prop at all. */
function propsOf(view: ChipView): ChipProps {
  switch (view.status) {
    case "live":
      return { status: "live", lastGoodTs: null };
    case "delayed":
      return {
        status: "delayed",
        lastGoodTs: null,
        ...(view.throttleMultiplier !== undefined && {
          throttleMultiplier: view.throttleMultiplier,
        }),
      };
    case "stale":
      return {
        status: "stale",
        lastGoodTs: view.lastGoodTs,
        strong: view.strong,
        serverStale: view.cause === "server",
        upstreamDown: view.cause === "upstream",
        ...(view.ageMs !== undefined && { staleAgeMs: view.ageMs }),
      };
    case "reconnecting":
    case "offline":
      return {
        status: view.status,
        lastGoodTs: view.lastGoodTs,
        firstConnect: view.firstConnect,
        ...(view.attempt !== undefined && { attempt: view.attempt }),
      };
  }
}

/**
 * CMP-076's container (#304 S3, S10; #5345), `ShellConnectionSlot`'s content: E17-D02 §3's
 * selector (`selectChip`) over the link (`useWsState`, so the chip, the status bar and the CMP-077
 * region split it the same way), SCR-153's fact that the exchange's public feed is down (§2 row
 * 13), the `connection_quality` multiplier (row 5) and the live public topics the WS client reads
 * (rows 10–12, 16). The topics are read, never pushed: no frame renders it. Its clock runs at 1 Hz
 * while the link is up (a silent topic crosses T1 with no event) or an age is drawn; a store
 * change re-renders it at once, so the exchange's feed down reads within the frame of its message.
 * It announces nothing: E17-D02 §11 rows 1 and 14 are CMP-077's (`ConnectionRegionSlot`).
 */
export function ConnectionStatusSlot(): JSX.Element {
  const ws = useWsState();
  const latencyMs = useShellSelector((s) => s.latency.valueMs);
  const upstreamDown = useShellSelector(upstreamDownOf);
  const multiplier = useShellSelector(multiplierOf);
  const [memory, setMemory] = useState(NO_CHIP_MEMORY);
  const [ticks, tick] = useReducer((n: number) => n + 1, 0);
  // Read at render: a transition renders with the clock and the topics of that moment.
  const input = chipInput(ws, upstreamDown, multiplier);
  const view = selectChip(input, memory);
  // The two holds follow the sources and the clock (`ticks`); an unchanged step keeps the state.
  useEffect(() => {
    setMemory((m) => stepChipMemory(m, chipInput(ws, upstreamDown, multiplier)));
  }, [ws, upstreamDown, multiplier, ticks]);

  const aged = view.status !== "live" && view.status !== "delayed" && view.lastGoodTs !== null;
  const clocked = ws.link.kind === "up" || aged;
  useEffect(() => {
    if (!clocked) return undefined;
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [clocked]);

  return <ConnectionStatus {...propsOf(view)} latencyMs={latencyMs} nowMs={input.nowMs} />;
}

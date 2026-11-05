// E24-S03 (#778) slice 2: CMP-126 on the symbol's one countdown entry and the app's synced tick, in the header
// and the sub-pane alike, so both show one value from one timer; the rate and charges are formatted, never computed.
import type { JSX } from "react";
import { FundingCountdown, type SecondTick } from "@candleviewer/ui";
import { clockAlarmFor, syncedTick, useSyncedClockSkew } from "../../../lib/state/syncedTick";
import { loadFundingCharges } from "../charges";
import {
  useCountdownFeed,
  useCountdownSnapshot,
  type CountdownClock,
  type CountdownFeedOptions,
  type CountdownSnapshot,
} from "../countdownFeed";
import { buildReadout, type FundingReadout } from "../predicted";
import { FundingMethodologyHost } from "./FundingMethodologyHost";
import { staleLine } from "./copy";
import { PredictedReadout, readoutRate } from "./PredictedReadout";

/** D03 S54-31: the charge carries the ticker's stale marker, "Stale 7s · last 15:55:41". */
const staleNote = (s: CountdownSnapshot["stale"]): string | undefined =>
  s.tier === "fresh" ? undefined : staleLine(s.ageS, s.lastTsMs);

export interface FundingCountdownViewProps {
  readonly symbol: string;
  readonly snapshot: CountdownSnapshot;
  readonly tick: SecondTick;
  /** The measured skew, `undefined` while unmeasured: either past 2 000 ms or unmeasured is the alarm (m3). */
  readonly clockSkewMs: number | undefined;
  /** `false` where another instance on the screen speaks AN-1 / AN-2 (D03 §13). */
  readonly announce?: boolean | undefined;
  /**
   * E24-S04: what the accruing rate shows. Absent, the ticker's rate alone: still "predicted (estimated)", never
   * bare (BQ-2), with no interval or annualised figure until the history feed supplies them.
   */
  readonly readout?: FundingReadout | undefined;
  readonly annualised?: boolean | undefined;
  readonly className?: string | undefined;
}

export function FundingCountdownView({
  symbol,
  snapshot,
  tick,
  clockSkewMs,
  announce = true,
  readout,
  annualised = false,
  className,
}: FundingCountdownViewProps): JSX.Element {
  const note = staleNote(snapshot.stale);
  const shown =
    readout ??
    buildReadout({
      tickerRate: snapshot.rate,
      historyReady: false,
      predicted: null,
      intervalMinutes: null,
    });
  return (
    <FundingMethodologyHost>
      <FundingCountdown
        symbol={symbol}
        tick={tick}
        rate={readoutRate(shown, annualised)}
        rateExtra={<PredictedReadout readout={shown} annualised={annualised} />}
        nextFundingTimeMs={snapshot.nextFundingTimeMs ?? undefined}
        charges={snapshot.charges.map((c) => ({ ...c, staleNote: note }))}
        clockAlarm={clockAlarmFor(clockSkewMs)}
        clockSkewMs={clockSkewMs}
        announce={announce}
        {...(className === undefined ? {} : { className })}
      />
    </FundingMethodologyHost>
  );
}

export interface ConnectedFundingCountdownProps {
  readonly symbol: string;
  readonly tick?: SecondTick | undefined;
  readonly loadCharges?: CountdownFeedOptions["loadCharges"] | undefined;
  readonly clock?: CountdownClock | undefined;
  readonly className?: string | undefined;
}

export function ConnectedFundingCountdown({
  symbol,
  tick = syncedTick,
  loadCharges = loadFundingCharges,
  clock,
  className,
}: ConnectedFundingCountdownProps): JSX.Element {
  const feed = useCountdownFeed(symbol, { tick, loadCharges, clock });
  const snapshot = useCountdownSnapshot(feed);
  const clockSkewMs = useSyncedClockSkew(tick);
  return (
    <FundingCountdownView
      symbol={symbol}
      snapshot={snapshot}
      tick={tick}
      clockSkewMs={clockSkewMs}
      className={className}
    />
  );
}

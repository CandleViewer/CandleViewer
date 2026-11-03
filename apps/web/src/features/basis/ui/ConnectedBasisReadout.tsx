// E24-S08 (#783) slice 1: the basis readout on the app's WS client, with the source held in component
// state (owner ruling on #778, §19.110: no local-storage fallback; TODO in `settings.ts`). Mount it in
// SCR-054's header row (D03 §3); until that screen lands the slice is dark.
import { useState, type JSX } from "react";
import type { BasisClock } from "../basisFeed";
import { useBasisSnapshot } from "../basisFeed";
import { DEFAULT_BASIS_SOURCE, type BasisSource } from "../settings";
import { useBasisFeed } from "../useBasisFeed";
import { BasisReadout } from "./BasisReadout";

export interface ConnectedBasisReadoutProps {
  readonly symbol: string;
  readonly paneId: string;
  readonly clock?: BasisClock | undefined;
}

export function ConnectedBasisReadout({
  symbol,
  paneId,
  clock,
}: ConnectedBasisReadoutProps): JSX.Element {
  const feed = useBasisFeed(symbol, { paneId, clock });
  const snapshot = useBasisSnapshot(feed);
  const [source, setSource] = useState<BasisSource>(DEFAULT_BASIS_SOURCE);
  return (
    <BasisReadout symbol={symbol} snapshot={snapshot} source={source} onSourceChange={setSource} />
  );
}

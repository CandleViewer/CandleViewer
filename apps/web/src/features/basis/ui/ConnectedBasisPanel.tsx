// E24-S08 (#783): the basis panel on the app's WS client. The source is component state (owner ruling on
// #778, §19.110: no local-storage fallback; TODO in `settings.ts`) and the toggle is reported on the
// analytics seam. Mount it in SCR-054's header row (D03 §3); until that screen lands the slice is dark.
import { useCallback, useState, type JSX } from "react";
import { createBasisAnalytics, type BasisAnalytics } from "../analytics";
import { useBasisSnapshot, type BasisClock } from "../basisFeed";
import { DEFAULT_BASIS_SOURCE, type BasisSource } from "../settings";
import { useBasisFeed } from "../useBasisFeed";
import { BasisPanel } from "./BasisPanel";

export interface ConnectedBasisPanelProps {
  readonly symbol: string;
  readonly paneId: string;
  readonly clock?: BasisClock | undefined;
  readonly analytics?: BasisAnalytics | undefined;
}

const defaultAnalytics = createBasisAnalytics();

export function ConnectedBasisPanel({
  symbol,
  paneId,
  clock,
  analytics = defaultAnalytics,
}: ConnectedBasisPanelProps): JSX.Element {
  const feed = useBasisFeed(symbol, { paneId, clock, analytics });
  const snapshot = useBasisSnapshot(feed);
  const [source, setSource] = useState<BasisSource>(DEFAULT_BASIS_SOURCE);
  const change = useCallback(
    (next: BasisSource): void => {
      setSource(next);
      analytics.sourceToggled(next);
    },
    [analytics],
  );
  const retry = useCallback((): void => feed?.retry(), [feed]);
  return (
    <BasisPanel
      symbol={symbol}
      snapshot={snapshot}
      source={source}
      onSourceChange={change}
      onRetry={retry}
    />
  );
}

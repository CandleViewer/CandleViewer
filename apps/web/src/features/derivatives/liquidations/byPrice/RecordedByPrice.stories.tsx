import type { JSX } from "react";
import { Callout, formatRbacReason } from "@candleviewer/ui";
import * as copy from "./copy";
import { ByPriceLegendRow } from "./ByPriceLegendRow";
import { ByPriceTable } from "./ByPriceTable";
import { RecordedByPriceToggle } from "./RecordedByPriceToggle";
import { layerOf, type ToggleAccess } from "./model";
import { EMPTY, EXAMPLE, FLAGGED, FULL, NEVER_RECORDED, NOT_RECORDED, NOW } from "./samples";
import type { ByPriceAnswer } from "./byPriceRead";
import type { ByPriceView } from "./useLiquidationsByPrice";

// E24-S07 (#782) slice 2: the recorded layer's switch, legend row and table in every state, on `samples.ts` (`22`'s
// example). The plot attach is slice 3 (#534); nothing mounts these yet (BQ 11). Plain CSF.
export default {
  title: "Chart primitives/OiFundingLiqPane/RecordedByPrice",
  component: ByPriceLegendRow,
  excludeStories: ["viewOf"],
};

const noop = (): void => undefined;

export const viewOf = (
  answer: ByPriceAnswer | null,
  over: Partial<ByPriceView> = {},
): ByPriceView => ({
  phase: answer === null ? "loading" : "ready",
  layer: answer === null ? null : layerOf(answer),
  stale: false,
  loadedAtMs: answer === null ? null : NOW,
  retry: noop,
  ...over,
});

const Row = ({ view }: { readonly view: ByPriceView }): JSX.Element => (
  // "Price pane legend" is story-local, not deck copy: the CMP-199 host owns the real list's name
  <ul aria-label="Price pane legend">
    <ByPriceLegendRow view={view} nowMs={NOW} />
  </ul>
);

type SwitchProps = { readonly access: ToggleAccess; readonly checked?: boolean };
const Switch = ({ access, checked = false }: SwitchProps): JSX.Element => (
  <RecordedByPriceToggle symbol="BTCUSDT" checked={checked} access={access} onChange={noop} />
);

/** AC "off by default": the switch off, nothing read, no legend row. */
export const Off = { render: () => <Switch access={{ kind: "persisted" }} /> };
/** On, saved to `deriv.liq_by_price` (an Owner or a Manager). */
export const On = { render: () => <Switch access={{ kind: "persisted" }} checked /> };
/** D03 D-7: a Viewer switches it for the session only (T1). */
export const ViewerSession = { render: () => <Switch access={{ kind: "session" }} checked /> };
/** G-T2.5: under view-as, T2 `rbac.view_as`, described by the panel's one notice. */
export const ViewAs = {
  render: () => (
    <div>
      <Callout
        id="by-price-notice"
        title={formatRbacReason("rbac.view_as", { user: "alex" })}
        live="off"
      />
      <Switch access={{ kind: "view-as", user: "alex", noticeId: "by-price-notice" }} />
    </div>
  ),
};

/** D03 S54-56: the whole UTC day so far is covered; the label carries "(today, UTC)". */
export const Full = { render: () => <Row view={viewOf(FULL)} /> };
/** BQ 5: `22`'s example, the store from 06:30 UTC: the partial chip and its sentence, never a full-day claim. */
export const PartialCoverage = { render: () => <Row view={viewOf(EXAMPLE)} /> };
export const NotRecorded = { render: () => <Row view={viewOf(NOT_RECORDED)} /> };
export const NeverRecorded = { render: () => <Row view={viewOf(NEVER_RECORDED)} /> };
export const NoneRecorded = { render: () => <Row view={viewOf(EMPTY)} /> };
/** BQ 7's positive fixture: the flag set to true draws the estimated word. */
export const FlaggedEstimated = { render: () => <Row view={viewOf(FLAGGED)} /> };
export const Loading = { render: () => <Row view={viewOf(null)} /> };
export const Failed = {
  render: () => <Row view={viewOf(null, { phase: "failed", loadedAtMs: null })} />,
};
/** BQ 7's negative: an answer without `estimated` is refused and draws nothing. */
export const Refused = {
  render: () => <Row view={viewOf(null, { phase: "refused", loadedAtMs: null })} />,
};
export const Stale = {
  render: () => <Row view={viewOf(FULL, { stale: true, loadedAtMs: NOW - 60_000 })} />,
};

/** D02 §11: the table alternative, largest first as served. */
export const Table = {
  render: () => (
    <ByPriceTable
      layer={layerOf(FULL)}
      emptyState={<p>{copy.noneRecordedSince("00:00 UTC")}</p>}
      announce={noop}
    />
  ),
};
export const TableEmpty = {
  render: () => (
    <ByPriceTable
      layer={layerOf(NOT_RECORDED)}
      emptyState={<p>{copy.notRecordedBefore("15 Sep 08:00 UTC")}</p>}
      announce={noop}
    />
  ),
};

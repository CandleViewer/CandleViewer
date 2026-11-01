/**
 * SCR-142's region (c) (E16-D04 §4, §5 `SCR-142/tier-unreachable-questdb`; E16-D06 FM-14, F-05, T2-12; AC 1, AC 4):
 * the three tier cards, CMP-050 with one CMP-036 row per figure, every figure with its unit, health as its word with
 * its glyph (never colour alone), a figure the contract does not serve as "—" beside its shipped fallback. A tier
 * that is down keeps its card: CMP-027 inline with Retry, its last figures tagged stale, no page banner and no alert.
 * The cards' actions are the panel's (Purge data… on QuestDB and Parquet, Compact Parquet… on Parquet).
 */
import type { JSX, ReactNode } from "react";
import { Card, Icon, InlineError, KeyValueRow, Tag } from "@candleviewer/ui";
import { TEXT } from "../copy";
import { STORAGE_DECK } from "./storageCopy";
import type { TierId, TierRow, TierView } from "./storageModel";

export interface TierCardsProps {
  readonly views: readonly TierView[];
  /** The sample is stale: every card's figures are tagged so. */
  readonly stale: boolean;
  /** A down tier's Retry (a re-poll). */
  readonly onRetry: (tier: TierId) => void;
  /** The card's actions under its rows. */
  readonly actions?: ((tier: TierId) => ReactNode) | undefined;
  /** Holds each card, so a successful Retry can restore focus to its heading (FM-14). */
  readonly hostRef: (tier: TierId) => (element: HTMLDivElement | null) => void;
}

/**
 * A row's value as read: the figure, its glyph and word, or "—" beside the fallback the design names. A value that is
 * not current (its health read failed, or the topic it came from is stale) keeps its text, tagged "stale"
 * (C-486P3-07, C-486P3-08).
 */
function valueOf(row: TierRow): ReactNode {
  const tag =
    row.stale === true ? (
      <>
        {" "}
        <Tag label={TEXT.staleTag} />
      </>
    ) : null;
  if (row.value !== null) {
    return row.icon === undefined ? (
      <>
        {row.value}
        {tag}
      </>
    ) : (
      <>
        <Icon name={row.icon} /> {row.value}
        {tag}
      </>
    );
  }
  return row.fallback === undefined ? null : (
    <>
      <span aria-hidden="true">— </span>
      {row.fallback}
    </>
  );
}

const [RETRY] = STORAGE_DECK["storage.tier.retry"];

export function TierCards({
  views,
  stale,
  onRetry,
  actions,
  hostRef,
}: TierCardsProps): JSX.Element {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 24rem), 1fr))",
        gap: "var(--space-stack-md)",
      }}
    >
      {views.map((view) => {
        const tagged = stale || view.health.down;
        const action = actions?.(view.tier);
        return (
          <div key={view.tier} ref={hostRef(view.tier)}>
            <Card
              headingLevel={3}
              title={
                <>
                  {view.title}
                  {tagged ? (
                    <>
                      {" "}
                      <Tag label={TEXT.staleTag} />
                    </>
                  ) : null}
                </>
              }
            >
              <div style={{ display: "grid", gap: "var(--space-stack-sm)" }}>
                <dl style={{ margin: 0, display: "grid", gap: "var(--space-stack-xs)" }}>
                  {view.rows.map((row) => (
                    <KeyValueRow key={row.label} label={row.label} value={valueOf(row)} />
                  ))}
                </dl>
                {view.unreachable === null ? null : (
                  <InlineError
                    message={view.unreachable}
                    live="off"
                    retry={{ label: RETRY, onClick: () => onRetry(view.tier) }}
                  />
                )}
                {action === undefined || action === null ? null : (
                  <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-inset-xs)" }}>
                    {action}
                  </div>
                )}
              </div>
            </Card>
          </div>
        );
      })}
    </div>
  );
}

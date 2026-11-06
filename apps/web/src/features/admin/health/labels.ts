/**
 * `health.label.*` (E42-D05 §15 and D4; DJ): the plain label of each component the server names,
 * for the tile heading "{plain label} ({name})". A name no table knows renders as itself, so a
 * backend addition shows before this table knows it (`23` §15.9).
 */
const LABELS: Readonly<Record<string, string>> = {
  bybit_public_ws: "Public WS",
  bybit_private_ws: "Private WS",
  bybit_rest: "Bybit REST",
  recorder: "Recorder",
  postgres: "Postgres",
  questdb: "QuestDB",
  parquet_store: "Parquet",
  hot_tier_write_behind: "Market-data writes",
  rule_engine: "Rule engine",
  oms: "Order manager",
  ingestion: "Ingestion",
  disk: "Disk",
  secrets: "Key store",
  bars: "Bar builder",
  bars_writer: "Bar writer",
};

/** The plain label, or the name itself; never an inherited key ("constructor" names nothing). */
export const plainLabel = (name: string): string =>
  (Object.hasOwn(LABELS, name) ? LABELS[name] : undefined) ?? name;

/** The tile heading: "Private WS (bybit_private_ws)", or the bare name for one no table knows. */
export function headingOf(name: string): string {
  const plain = plainLabel(name);
  return plain === name ? name : `${plain} (${name})`;
}

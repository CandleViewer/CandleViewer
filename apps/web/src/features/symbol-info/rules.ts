/**
 * The contract band's view-model (E08-D06 §3, §4.1, §4.4, §5): rows from `InstrumentDetail`, each a value, its unit,
 * the `policy.py` sentence and an example computed by the shared rule source (`policy`, E08-S02), never a number
 * for a field the contract does not serve (D06 §4: "not available yet"). Pure: no React, no clock, no network.
 */
import { policy, type generated } from "@candleviewer/protocol";
import * as copy from "./copy";
import {
  formatAtStep,
  formatRule,
  group,
  minimal,
  parseDecimal,
  toPositional,
  type Malformed,
} from "./format";

type Schemas = generated.rest.components["schemas"];
export type InstrumentDetail = Schemas["InstrumentDetail"];
export type RiskTier = NonNullable<InstrumentDetail["risk_limit_tiers"]>[number];

export type RuleKey = Exclude<keyof typeof copy.LABELS, "risk_limit_tiers">;
/** The `22` field names whose change D-13 marks. */
export type RuleField =
  | "status"
  | "tick_size"
  | "qty_step"
  | "min_order_qty"
  | "max_order_qty"
  | "min_notional_value"
  | "max_leverage"
  | "leverage_step"
  | "funding_interval_minutes";

export type RuleValue =
  /** A value: `text` in F3's form, its `unit` for the unit column, the sentence and the example under it. */
  | {
      readonly kind: "value";
      readonly text: string;
      readonly unit: string | null;
      readonly sentence: string | null;
      readonly example: string | null;
    }
  /** "—": absent, the adapter's default (`min_notional_value` of 0, CR-1) or unreadable (`malformed`). */
  | { readonly kind: "dash"; readonly malformed: Malformed | null }
  /** The contract has no field for it yet (CR-1): "not available yet". */
  | { readonly kind: "not_available_yet" };

export interface RuleRow {
  readonly key: RuleKey;
  readonly label: string;
  readonly value: RuleValue;
  /** The `22` field(s) the row shows, which `diffRules` compares. */
  readonly field: RuleField | null;
  /** "can change" (D-3, the funding interval). */
  readonly tag: string | null;
}

/** A field the drawer could not read, to report once per field per session. */
export interface MalformedField {
  readonly field: string;
  readonly kind: Malformed;
}

export interface TierRow {
  readonly tier: number | null;
  readonly riskLimitValue: string | null;
  readonly maxLeverage: string | null;
}

export type TiersView =
  | { readonly kind: "not_available_yet" }
  | {
      readonly kind: "table";
      readonly caption: string;
      readonly rows: readonly TierRow[];
      readonly total: number;
      /** D-8: 3 rows collapsed, at most 8 expanded, then an inner scroll region. */
      readonly collapsedCount: number;
      readonly expandedCount: number;
      readonly scrolls: boolean;
      readonly showAll: string | null;
    };

export interface Status {
  /** The word, or `null` for a value the client does not know (D-5: not trading). */
  readonly word: string | null;
  readonly trading: boolean;
  readonly code: string | null;
}

export interface RulesView {
  readonly symbol: string;
  readonly identity: string | null;
  readonly status: Status;
  readonly rows: readonly RuleRow[];
  readonly tiers: TiersView;
  /** D-2: "Rules revision 7 · checked 2 h ago". */
  readonly provenance: string;
  readonly revision: number | null;
  /** D-3: one notice, E08-D05's words, with `stale_since`. */
  readonly overdue: string | null;
  readonly malformed: readonly MalformedField[];
}

/** D-5: Trading is trading; every other value, a value the client does not know included, is not. */
export function statusOf(status: string | undefined): Status {
  const known = Object.hasOwn(copy.STATUS_WORDS, status ?? "");
  return {
    word: known ? copy.STATUS_WORDS[status as keyof typeof copy.STATUS_WORDS] : null,
    trading: status === "Trading",
    code: status ?? null,
  };
}

const DASH_ABSENT: RuleValue = { kind: "dash", malformed: null };

/** The positional text of a value in minimal form, or `null` when unreadable. */
function positional(input: string | undefined): string | null {
  if (input === undefined) return null;
  const parsed = parseDecimal(input);
  return parsed.ok ? toPositional(minimal(parsed.dec)) : null;
}

/** A rule value row: its minimal text, unit and sentence; "—" when absent or unreadable. */
function rule(
  input: string | undefined,
  unit: string | null,
  sentence: ((shown: string) => string) | null,
  example: string | null = null,
  zeroIsDash = false,
): RuleValue {
  const shown = formatRule(input);
  if (shown.text === null) return { kind: "dash", malformed: shown.malformed };
  if (zeroIsDash && positional(input) === "0") return DASH_ABSENT;
  return {
    kind: "value",
    text: shown.text,
    unit,
    sentence: sentence === null ? null : sentence(shown.text),
    example,
  };
}

/** Tick × 1000.4 (nearest rounds down to tick × 1000) and step × 1000.9 (floors to step × 1000): E08-D06 §5's pair. */
function scaled(input: string, factor: bigint): string | null {
  const parsed = parseDecimal(input);
  if (!parsed.ok || parsed.dec.unscaled <= 0n) return null;
  return toPositional({ unscaled: parsed.dec.unscaled * factor, scale: parsed.dec.scale + 1 });
}

function priceExample(tick: string | undefined): string | null {
  const step = positional(tick);
  const from = step === null ? null : scaled(step, 10004n);
  if (step === null || from === null) return null;
  const rounded = policy.roundPrice(from, step);
  return copy.EXAMPLES.nearest(
    formatAtStep(from, step).text ?? from,
    formatAtStep(rounded, step).text ?? rounded,
  );
}

function qtyExample(stepInput: string | undefined): string | null {
  const step = positional(stepInput);
  const from = step === null ? null : scaled(step, 10009n);
  if (step === null || from === null) return null;
  const rounded = policy.roundQty(from, step);
  return copy.EXAMPLES.down(
    formatAtStep(from, step).text ?? from,
    formatAtStep(rounded, step).text ?? rounded,
  );
}

/** "1.0 × 0.001 = 0.001 → refused", only when the shared rule source does refuse that order. */
function valueExample(detail: InstrumentDetail): string | null {
  const tick = positional(detail.tick_size);
  const step = positional(detail.qty_step);
  const minQty = positional(detail.min_order_qty);
  const minValue = positional(detail.min_notional_value);
  if (tick === null || step === null || minQty === null || minValue === null || minValue === "0") {
    return null;
  }
  const refused = policy
    .validate("1.0", minQty, {
      symbol: detail.symbol,
      status: "trading",
      tickSize: tick,
      qtyStep: step,
      minOrderQty: minQty,
      maxOrderQty: positional(detail.max_order_qty) ?? "999999999999",
      minNotional: minValue,
    })
    .some((violation) => violation.code === "NOTIONAL_BELOW_MIN");
  return refused ? copy.EXAMPLES.refused("1.0", group(minQty), group(minQty)) : null;
}

function funding(minutes: number | undefined): RuleValue {
  if (typeof minutes !== "number" || !Number.isInteger(minutes) || minutes <= 0) return DASH_ABSENT;
  return {
    kind: "value",
    text: copy.fundingInterval(minutes),
    unit: null,
    sentence: null,
    example: null,
  };
}

function tiersView(symbol: string, tiers: readonly RiskTier[] | undefined): TiersView {
  if (tiers === undefined || tiers.length === 0) return { kind: "not_available_yet" };
  const rows = tiers.map((t): TierRow => ({
    tier: t.tier ?? null,
    riskLimitValue: formatRule(t.risk_limit_value).text,
    maxLeverage: formatRule(t.max_leverage).text,
  }));
  const total = rows.length;
  return {
    kind: "table",
    caption: copy.tiersCaption(symbol),
    rows,
    total,
    collapsedCount: Math.min(3, total),
    expandedCount: Math.min(8, total),
    scrolls: total > 8,
    showAll: total > 3 ? copy.showAllTiers(total) : null,
  };
}

/** "BTC / USDT · USDT perpetual · settled in USDT · listed 2020-04-01"; a missing part is dropped. */
export function identityLine(detail: InstrumentDetail): string | null {
  const parts: string[] = [];
  if (detail.base_coin !== undefined && detail.quote_coin !== undefined) {
    parts.push(`${detail.base_coin} / ${detail.quote_coin}`);
  }
  if (detail.contract_type === "LinearPerpetual" && detail.quote_coin !== undefined) {
    parts.push(`${detail.quote_coin} perpetual`);
  }
  if (detail.settle_coin !== undefined) parts.push(`settled in ${detail.settle_coin}`);
  const launched = detail.launch_time === undefined ? NaN : Date.parse(detail.launch_time);
  if (Number.isFinite(launched)) {
    parts.push(`listed ${new Date(launched).toISOString().slice(0, 10)}`);
  }
  return parts.length === 0 ? null : parts.join(copy.IDENTITY_SEPARATOR);
}

/** D-2's words: `updated_at` is when the server fetched the catalogue, so it reads "checked", never "changed". */
export function provenanceLine(detail: InstrumentDetail, nowMs: number): string {
  const parts: string[] = [];
  if (typeof detail.revision === "number") parts.push(copy.revisionText(detail.revision));
  const fetched = detail.updated_at === undefined ? NaN : Date.parse(detail.updated_at);
  parts.push(Number.isFinite(fetched) ? copy.checked(nowMs - fetched) : copy.CHECKED_UNKNOWN);
  return parts.join(copy.IDENTITY_SEPARATOR);
}

export function buildRules(detail: InstrumentDetail, nowMs: number): RulesView {
  const quote = detail.quote_coin ?? null;
  const base = detail.base_coin ?? null;
  const status = statusOf(detail.status);
  const rows: RuleRow[] = [
    {
      key: "status",
      label: copy.LABELS.status,
      field: "status",
      tag: null,
      value:
        status.word === null
          ? DASH_ABSENT
          : { kind: "value", text: status.word, unit: null, sentence: null, example: null },
    },
    {
      key: "tick_size",
      label: copy.LABELS.tick_size,
      field: "tick_size",
      tag: null,
      value: rule(detail.tick_size, quote, copy.SENTENCES.tick, priceExample(detail.tick_size)),
    },
    {
      key: "qty_step",
      label: copy.LABELS.qty_step,
      field: "qty_step",
      tag: null,
      value: rule(detail.qty_step, base, copy.SENTENCES.step, qtyExample(detail.qty_step)),
    },
    {
      key: "min_order_qty",
      label: copy.LABELS.min_order_qty,
      field: "min_order_qty",
      tag: null,
      value: rule(detail.min_order_qty, base, copy.SENTENCES.minQty),
    },
    {
      key: "max_order_qty",
      label: copy.LABELS.max_order_qty,
      field: "max_order_qty",
      tag: null,
      value: rule(detail.max_order_qty, base, copy.SENTENCES.maxQty),
    },
    {
      key: "max_mkt_order_qty",
      label: copy.LABELS.max_mkt_order_qty,
      field: null,
      tag: null,
      value: { kind: "not_available_yet" },
    },
    {
      key: "min_notional_value",
      label: copy.LABELS.min_notional_value,
      field: "min_notional_value",
      tag: null,
      value: rule(
        detail.min_notional_value,
        quote,
        copy.SENTENCES.minValue,
        valueExample(detail),
        true,
      ),
    },
    {
      key: "max_leverage",
      label: copy.LABELS.max_leverage,
      field: "max_leverage",
      tag: null,
      value: rule(detail.max_leverage, "×", null, null),
    },
    {
      key: "funding_interval",
      label: copy.LABELS.funding_interval,
      field: "funding_interval_minutes",
      tag: copy.FUNDING_CAN_CHANGE,
      value: funding(detail.funding_interval_minutes),
    },
  ];
  // The leverage step's line sits under the leverage row; it is the row's own sentence.
  const leverageStep = formatRule(detail.leverage_step);
  const leverage = rows.find((r) => r.key === "max_leverage");
  if (leverage?.value.kind === "value" && leverageStep.text !== null) {
    const at = rows.indexOf(leverage);
    rows[at] = {
      ...leverage,
      value: { ...leverage.value, sentence: copy.SENTENCES.leverageStep(leverageStep.text) },
    };
  }
  const malformed: MalformedField[] = [];
  const watched: readonly [string, string | undefined][] = [
    ["tick_size", detail.tick_size],
    ["qty_step", detail.qty_step],
    ["min_order_qty", detail.min_order_qty],
    ["max_order_qty", detail.max_order_qty],
    ["min_notional_value", detail.min_notional_value],
    ["max_leverage", detail.max_leverage],
    ["leverage_step", detail.leverage_step],
  ];
  for (const [field, input] of watched) {
    const { malformed: kind } = formatRule(input);
    if (kind !== null) malformed.push({ field, kind });
  }
  const stale = detail.stale_since === undefined ? null : detail.stale_since;
  const staleAt = stale === null ? NaN : Date.parse(stale);
  return {
    symbol: detail.symbol,
    identity: identityLine(detail),
    status,
    rows,
    tiers: tiersView(detail.symbol, detail.risk_limit_tiers),
    provenance: provenanceLine(detail, nowMs),
    revision: typeof detail.revision === "number" ? detail.revision : null,
    overdue: Number.isFinite(staleAt) ? copy.overdue(nowMs - staleAt) : null,
    malformed,
  };
}

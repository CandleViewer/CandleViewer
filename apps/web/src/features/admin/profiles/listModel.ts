/**
 * SCR-130's rows (E28-S01; E28-D02 §5.1, E28-D03 §3.1): one row per profile, each account's default
 * first and its alternates nested after it. Every word and figure is a served field or the deck's
 * words for a served code: the client computes no cap, verdict or size (D02 D5), and a warning is
 * the served `warnings[]` code, never re-derived (`22` `ProfileWarning`).
 */
import type { AccountProfile, ExchangeAccount, ProfileWarning } from "./api";
import { PROFILES_COPY as C } from "./copy";

export interface ProfileRow {
  /** The profile id: unique across accounts. */
  readonly key: string;
  readonly accountId: string;
  readonly accountLabel: string;
  /** `LIVE`, `DEMO` or `TESTNET`: the profile's served `environment`, as text (C-2.11). */
  readonly environment: string;
  readonly profile: AccountProfile;
  readonly isDefault: boolean;
  /** The account's first row (its default), which names the account; alternates follow it. */
  readonly leadsAccount: boolean;
  readonly name: string;
  /** "sub_001 default (v2)", or an alternate's "alternates: Main 0.5R (v1)". */
  readonly profileText: string;
  readonly trading: string;
  readonly symbols: string;
  readonly leverage: string;
  readonly sizing: string;
  readonly dailyLoss: string;
  readonly maxPosition: string;
  readonly changed: string;
  /** The served warnings' words, then CD-3 when trading is off: text, never a colour. */
  readonly notes: readonly string[];
}

type Profile = AccountProfile["profile"];

const withUnit = (value: string | null | undefined, unit: string): string | null =>
  value === null || value === undefined ? null : `${value} ${unit}`;

function joinCaps(...parts: (string | null)[]): string {
  const set = parts.filter((p): p is string => p !== null);
  return set.length === 0 ? C.noCap : set.join(" · ");
}

/** The sizing rule and its one amount, with its unit (`ProfileSizing`). */
export function sizingText(p: Profile): string {
  const s = p.sizing;
  const mode = C.modes[s.mode];
  const amount =
    s.mode === "risk_based"
      ? (withUnit(s.risk_per_trade_pct, C.units.pct) ??
        withUnit(s.risk_per_trade_usd, C.units.usdt))
      : s.mode === "fixed_notional"
        ? withUnit(s.notional_usd, C.units.usdt)
        : s.mode === "pct_equity"
          ? withUnit(s.pct, C.units.pct)
          : (s.qty ?? null);
  return amount === null ? mode : `${mode} ${amount}`;
}

/** The symbol state: CD-2 or "{n} allowed" (`all_symbols`, `allowed_symbols`; decision D11). */
export function symbolsText(p: Profile): string {
  if (p.all_symbols) return C.allSymbols;
  return p.allowed_symbols.length === 0 ? C.noSymbols : C.allowedCount(p.allowed_symbols.length);
}

/** A served warning's words: the deck's for the two a read serves, else the served `message` (C-6.3). */
export function warningText(w: ProfileWarning): string | null {
  if (w.code === "all_symbols") return C.allSymbolsWarning;
  if (w.code === "no_symbols") return null; // the symbol cell already reads CD-2 ("Allows no symbol yet")
  return w.message;
}

/** `updated_at`'s UTC date, as `e28.value.changed_since` reads it; an unreadable date is not guessed. */
export function changedText(profile: AccountProfile): string {
  const date = /^(\d{4}-\d{2}-\d{2})T/.exec(profile.updated_at)?.[1];
  return date === undefined
    ? C.versionOnly(profile.version)
    : C.changedSince(profile.version, date);
}

function rowOf(account: ExchangeAccount, profile: AccountProfile, leads: boolean): ProfileRow {
  const p = profile.profile;
  const caps = p.risk_caps;
  const name = p.name;
  const versioned = `${name} (v${profile.version})`;
  const notes = profile.warnings.map(warningText).filter((t): t is string => t !== null);
  if (!p.trading_enabled) notes.push(C.tradingOff);
  return {
    key: profile.id,
    accountId: account.id,
    accountLabel: account.label,
    environment: profile.environment.toUpperCase(),
    profile,
    isDefault: p.is_default,
    leadsAccount: leads,
    name,
    profileText: p.is_default ? `${versioned} · ${C.roleDefault}` : `${C.alternates} ${versioned}`,
    trading: p.trading_enabled && p.enabled ? C.on : C.off,
    symbols: symbolsText(p),
    leverage: `${p.leverage}${C.units.leverage}`,
    sizing: sizingText(p),
    dailyLoss: joinCaps(
      withUnit(caps?.max_daily_loss_pct, C.units.pct),
      withUnit(caps?.max_daily_loss_usd, C.units.usdt),
    ),
    maxPosition: joinCaps(
      withUnit(caps?.max_position_notional_usd, C.units.usdt),
      withUnit(caps?.max_position_pct_equity, C.units.pct),
    ),
    changed: changedText(profile),
    notes,
  };
}

/**
 * The table's rows, in the accounts' served order: each account's default first, then its alternates
 * by name. An account the server answered `404` for (another environment, or gone) has no entry in
 * `profiles` and no row: nothing about it is guessed.
 */
export function buildRows(
  accounts: readonly ExchangeAccount[],
  profiles: ReadonlyMap<string, readonly AccountProfile[]>,
): ProfileRow[] {
  const rows: ProfileRow[] = [];
  for (const account of accounts) {
    const own = profiles.get(account.id);
    if (own === undefined) continue;
    const ordered = [...own].sort(
      (a, b) =>
        Number(b.profile.is_default) - Number(a.profile.is_default) ||
        a.profile.name.localeCompare(b.profile.name),
    );
    ordered.forEach((profile, i) => rows.push(rowOf(account, profile, i === 0)));
  }
  return rows;
}

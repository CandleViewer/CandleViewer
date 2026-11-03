/**
 * SCR-130 / SCR-131's words (E28-S01, #971), from the E28-D06 hand-off pack's copy deck (base
 * `a7d659a5be`), each row by its `id`. Each entry names its deck id and the deck's status: `merged`
 * and `RULED` strings are used verbatim; `PROPOSED` ones await the owner (#2701) and are re-synced at
 * E28-D07. `FZ-n` marks a frozen safety string, never reworded. A string with no deck id is marked
 * `CLIENT (PROPOSED)`: the deck has no row for it yet, and it is listed in the PR for D06's owner. A
 * fill (`{n}`) takes a served value only.
 */
export const PROFILES_COPY = {
  /** `e28.title.profiles` (RULED). */
  title: "Account profiles",
  /** `e28.helper.default_ceiling` (RULED): CD-1, the "default profile" column's description. */
  defaultCeiling: "Default profile — the most this account may do. Alternates can only narrow it.",
  /** `e28.label.alternates` (RULED): the lead word of a nested alternate row. */
  alternates: "alternates:",
  /** `e28.value.allowed_count` (RULED). */
  allowedCount: (n: number): string => `${n} allowed`,
  /** `e28.state.all_symbols` (RULED). */
  allSymbols: "Allows all symbols",
  /** `e28.state.all_symbols.warning` (RULED): the served `all_symbols` warning's words. */
  allSymbolsWarning: "(!) Allows all symbols - consider restricting",
  /** `e28.state.no_symbols` (RULED): the served `no_symbols` warning, and the symbol state. */
  noSymbols: "Allows no symbol yet",
  /** `e28.code.ap_trading_caps` (RULED): CD-3, a profile whose trading is off. */
  tradingOff:
    "Trading off — set the position, daily-loss, open-positions, concurrent-orders and leverage caps to turn it on",
  /** `e28.value.changed_since` (RULED), the served `version` and `updated_at` date. */
  changedSince: (version: number, date: string): string => `v${version} · changed ${date} UTC`,
  /** `e28.empty.profiles` (RULED). */
  empty: "No accounts yet. Add one on Accounts.",
  /** `e28.menu.duplicate` (PROPOSED). */
  duplicate: "Duplicate as a new alternate",
  /**
   * `e28.confirm.delete` (RULED; the deck row's `text` is cut at its first quote, so the whole sentence
   * is D02 §5.1's, which the row cites, `D02`:221).
   */
  confirmDelete: (account: string, profile: string): string =>
    `Delete ${account}'s profile '${profile}'? Positions sized from it keep their version.`,
  /**
   * `e28.code.conflict.delete` (PROPOSED, `deck+served`): the served `detail` follows. It names each
   * blocker; the default's (`e28.refusal.delete_default`, RULED) is the server's words, never ours.
   */
  cannotDelete: (detail: string): string => `Can't delete: ${detail}`,
  /** `e28.announce.deleted` (PROPOSED, LR-11). */
  deleted: (profile: string, account: string): string => `Deleted ${profile} of ${account}`,
  /**
   * `e28.code.version_conflict` (PROPOSED): `412 version_conflict`, the deck's alias of the AC code
   * `precondition_failed`. The row is scoped to SCR-131/133/062 and says "saved"; a delete-specific
   * row is open question 2.
   */
  versionConflict:
    "This changed since you opened it. Nothing was saved — reload to see the new version.",
  /** `e28.code.audit_unavailable` (PROPOSED): `503 audit_unavailable`. */
  auditUnavailable: "Nothing was saved — the change could not be recorded. Try again.",
  /** `e28.action.cancel` (RULED). */
  cancel: "Cancel",
  /** `e28.value.unknown` (RULED). */
  unknown: "unknown",
  /** `e28.unit.usdt`, `e28.unit.pct`, `e28.unit.leverage` (RULED). */
  units: { usdt: "USDT", pct: "%", leverage: "x" },
  /** Column heads: `e28.field.*` (PROPOSED) where the deck has one, else D02 §5.1's wireframe words. */
  columns: {
    /** CLIENT (PROPOSED): D02 §5.1's "account". */
    account: "Account",
    /** CLIENT (PROPOSED): D02 §5.1's "default profile", here every profile of the account. */
    profile: "Profile",
    /** `e28.field.trading` (PROPOSED). */
    trading: "Trading",
    /** `e28.section.symbols` (PROPOSED). */
    symbols: "Symbols",
    /** `e28.field.leverage` (PROPOSED). */
    leverage: "Leverage",
    /** `e28.field.sizing_rule` (PROPOSED). */
    sizing: "Rule",
    /** `e28.field.daily_loss` (PROPOSED). */
    dailyLoss: "Daily loss",
    /** `e28.field.max_position` (PROPOSED). */
    maxPosition: "Max position",
    /** CLIENT (PROPOSED): `14`'s "changed since" column. */
    changed: "Changed since",
    /** CLIENT (PROPOSED): the served warnings and CD-3, until CMP-049's reason row (DS-F) lands. */
    notes: "Notes",
  },
  /** `e28.option.*` (PROPOSED); `pct_equity` is `e28.unit.pct_equity` (PROPOSED, `D02`:241). */
  modes: {
    risk_based: "Risk-based",
    fixed_qty: "Fixed qty",
    fixed_notional: "Fixed notional",
    pct_equity: "% of equity",
  },
  /** CLIENT (PROPOSED): a cap that is `null` or absent in `ProfileRiskCaps` (`22`). */
  noCap: "no cap",
  /** CLIENT (PROPOSED): the served `version` alone, when `updated_at` has no readable date. */
  versionOnly: (version: number): string => `v${version}`,
  /** CLIENT (PROPOSED): D02 §5.1's trading words, "on" / "off". */
  on: "on",
  off: "off",
  /** CLIENT (PROPOSED): the default / alternate role words in the profile cell. */
  roleDefault: "default",
  /** CLIENT (PROPOSED): the row menu's actions (D02 §5.1 names Edit, Duplicate and Delete). */
  edit: "Edit",
  delete: "Delete",
  /** CLIENT (PROPOSED): CMP-027's sentence when the accounts or their profiles could not be read. */
  loadFailed: "The profiles could not be loaded.",
  /** CLIENT (PROPOSED): a refused delete the deck has no row for, with the served code verbatim. */
  notDeleted: (code: string): string => `Nothing was deleted (${code}).`,
} as const;

/**
 * The "Needs your action" strip's items (E42-S01, BQ-6; E42-D03 §4, §14 `strip.*`): only the items
 * whose source is served today, read from the shared store, so the strip adds no request of its own
 * where the overview already reads. Counts only, as the slices return them, each from the current
 * answer: a read that failed keeps its counts for its tiles, marked old, but an item can carry no
 * such mark, so a failed read shows none. The withdrawal (CG-7), tamper (CG-8), break-glass,
 * clock-drift and backup items wait for their sources. Links come from the route table
 * (`links.ts`), never from the data.
 */
import type { AdminStripItem } from "@candleviewer/ui";
import { OVERVIEW_COPY as COPY } from "./copy";
import { routePath, type AdminLink } from "./links";
import type { AdminReadState, ReadId } from "./readStore";
import type { Env } from "./tileModels";

/** What the strip reads: on every admin route, so their `/admin/*` calls record the entry (D27). */
export const STRIP_READS: readonly ReadId[] = ["overview", "capacity"];

type Fields = Readonly<Record<string, unknown>>;

const count = (fields: Fields | undefined, name: string): number | undefined => {
  const value = fields?.[name];
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
};

/**
 * The items, ordered by CMP-087; `[]` when both reads answered `ok` and nothing needs the owner;
 * and `undefined` (no strip) while a source is unread or failed and nothing else needs the owner:
 * an unread source or a kept count is never "Nothing needs your action" (D03 OV-2, D02 D4;
 * A-5330-06). No item is timed: a slice's `generated_at` is when it was read, not when its
 * condition was raised, and would reorder the items between re-reads (C-5330-08).
 */
export function stripItems(s: AdminReadState, env: Env): AdminStripItem[] | undefined {
  const overview = s.overview.phase === "ok" ? s.overview.data : undefined;
  const capacity = s.capacity.phase === "ok" ? s.capacity.data : undefined;
  const users = overview?.users as Fields | undefined;
  const accounts = overview?.accounts as Fields | undefined;
  const subaccounts = capacity?.subaccounts as Fields | undefined;
  const scoped = env === "unknown" ? {} : { env };
  const items: AdminStripItem[] = [];
  let unread = false;
  const add = (
    id: string,
    label: string,
    link: AdminLink,
    more: Partial<AdminStripItem> = {},
  ): void => {
    const href = routePath(link);
    if (href === undefined) return; // no table entry: no link, so no item
    items.push({ id, label, href, kind: "other", severity: "warning", ...more });
  };
  const counted = (fields: Fields | undefined, name: string): number => {
    const n = count(fields, name);
    if (n === undefined) unread = true;
    return n ?? 0;
  };

  const noMfa = counted(users, "without_mfa");
  if (noMfa > 0) add("no_mfa", COPY.strip.noMfa(noMfa), "users");
  const expiring = counted(accounts, "keys_expiring_30d");
  if (expiring > 0) add("key_expiry", COPY.strip.keyExpiry(expiring), "accounts", scoped);
  const invalid = counted(accounts, "keys_invalid");
  if (invalid > 0) add("keys_invalid", COPY.strip.keysInvalid(invalid), "accounts", scoped);
  const tierSource = subaccounts?.["tier_source"];
  if (tierSource === "unrecorded") {
    add("tier", COPY.strip.tier, "users");
  } else if (tierSource !== "recorded") {
    unread = true;
  }
  if (items.length > 0) return items;
  return unread ? undefined : [];
}

/** "Entering this area was recorded": once a strip read was answered `2xx` (D03 §4, D27). */
export const areaEntered = (s: AdminReadState): boolean =>
  s.overview.okAt !== undefined || s.capacity.okAt !== undefined;

/** The first read the server refused with `403`: the area is withdrawn (BQ-8). */
export function denial(s: AdminReadState): { readonly refId: string | undefined } | null {
  for (const id of Object.keys(s) as ReadId[]) {
    const entry = s[id];
    if (entry.phase === "denied") return { refId: entry.refId };
  }
  return null;
}

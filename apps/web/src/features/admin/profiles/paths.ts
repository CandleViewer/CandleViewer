/**
 * R-331's links (E28-S01 BQ-02 (a)): every profile operation sits under its account
 * (`/exchange-accounts/{accountId}/profiles/…`, `22`), and `12`'s R-331 path names the profile alone,
 * so the account rides in the query, `?account=`. A new alternate is `new`, a duplicate adds `&from=`.
 * No path of `12` changes.
 */
import type { AccountProfile } from "./api";

export const PROFILES_PATH = "/admin/profiles";
export const NEW_PROFILE = "new";

export function editorPath(profile: Pick<AccountProfile, "id" | "exchange_account_id">): string {
  const query = new URLSearchParams({ account: profile.exchange_account_id });
  return `${PROFILES_PATH}/${encodeURIComponent(profile.id)}?${query.toString()}`;
}

export function newProfilePath(accountId: string, fromProfileId?: string): string {
  const query = new URLSearchParams({ account: accountId });
  if (fromProfileId !== undefined) query.set("from", fromProfileId);
  return `${PROFILES_PATH}/${NEW_PROFILE}?${query.toString()}`;
}

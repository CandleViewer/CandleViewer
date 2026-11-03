// E28-S01 (#971) BQ-09 as ruled: SCR-130 / SCR-131 ship behind the backend-defined rollout flag
// `admin.account_profiles` (`admin/flags/catalogue.py`, `21` §10.7; default off; owner @basiltt,
// removal #5667, C-4.13), read from the WS system mirror through `useFlag` (`23` §15.9),
// so the gate adds no REST read (`GET /admin/feature-flags` is Owner-only). Off while unread, absent
// or not visible to the role: R-330 keeps its stub. It gates screens only; every safety check is the
// server's and is never behind it (C-4.14).
import { useFlag } from "../../../shell/flags/useFlag";

export const PROFILES_FLAG = "admin.account_profiles";

/** `true` only when the mirror carries the flag as boolean `true`; undefined (unread) is off. */
export function useProfilesFlag(): boolean {
  return useFlag(PROFILES_FLAG) === true;
}

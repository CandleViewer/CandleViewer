/**
 * `stopsConfirmed` for CMP-077's `connectionRegion` (E29-S07 #1028; BQ-7 ruled (6610918411)):
 * E17's stops clause stands only while every account the session names is synced and its last
 * reassurance read passed. Before `/me` names the accounts, or with none, it is unread and the
 * clause is dropped (fail closed).
 */
import { useSyncExternalStore } from "react";
import { useShellAccountSignals } from "../../shell/accountState";
import { useShellSelector } from "../../shell/useShellSelector.js";
import { getReassurance, stopsClauseHolds, subscribeReassurance } from "./reassurance";

export function useStopsConfirmed(): boolean {
  const accounts = useShellSelector((s) => s.me?.accounts);
  const signals = useShellAccountSignals((s) => s);
  const reassurance = useSyncExternalStore(subscribeReassurance, getReassurance, getReassurance);
  const scope = accounts?.map((a) => a.exchange_account_id);
  return stopsClauseHolds(scope, signals, reassurance);
}

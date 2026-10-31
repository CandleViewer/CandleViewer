/**
 * Pure status derivation for an alert row (E40-S01). Precedence: a disarmed alert (`enabled` false)
 * is disarmed whatever else it carries; then an active snooze; then "fired" once it has fired;
 * otherwise armed. The snooze is judged against an injected `nowMs`, never a hidden clock.
 */
import type { Alert } from "./types.js";

export type AlertStatus = "armed" | "fired" | "snoozed" | "disarmed";
export type AlertTab = "all" | "fired" | "snoozed";
export const ALERT_TABS: readonly AlertTab[] = ["all", "fired", "snoozed"];

/** True when `snoozed_until` parses and is strictly after `nowMs`. An unparseable value is not a snooze. */
export function isSnoozed(alert: Alert, nowMs: number): boolean {
  if (alert.snoozed_until === null || alert.snoozed_until === undefined) return false;
  const until = Date.parse(alert.snoozed_until);
  return Number.isFinite(until) && until > nowMs;
}

export function hasFired(alert: Alert): boolean {
  return (
    (alert.last_fired_at !== null && alert.last_fired_at !== undefined) ||
    (alert.fire_count ?? 0) > 0
  );
}

export function deriveAlertStatus(alert: Alert, nowMs: number): AlertStatus {
  if (alert.enabled === false) return "disarmed";
  if (isSnoozed(alert, nowMs)) return "snoozed";
  if (hasFired(alert)) return "fired";
  return "armed";
}

export function matchesTab(status: AlertStatus, tab: AlertTab): boolean {
  if (tab === "all") return true;
  return status === tab;
}

export function filterAlerts(
  alerts: readonly Alert[],
  tab: AlertTab,
  nowMs: number,
): readonly Alert[] {
  if (tab === "all") return alerts;
  return alerts.filter((alert) => matchesTab(deriveAlertStatus(alert, nowMs), tab));
}

/** Row counts per tab, for the tab labels. */
export function tabCounts(
  alerts: readonly Alert[],
  nowMs: number,
): Readonly<Record<AlertTab, number>> {
  let fired = 0;
  let snoozed = 0;
  for (const alert of alerts) {
    const status = deriveAlertStatus(alert, nowMs);
    if (status === "fired") fired += 1;
    else if (status === "snoozed") snoozed += 1;
  }
  return { all: alerts.length, fired, snoozed };
}

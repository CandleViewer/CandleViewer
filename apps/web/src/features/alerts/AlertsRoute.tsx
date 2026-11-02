/** R-190 `/alerts` (SCR-090): the alerts centre inside the shell's `main`, wired to the router. */
import type { JSX } from "react";
import { useNavigate } from "react-router";
import { ScreenRoot } from "../app-shell/ScreenRoot";
import { AlertsScreen } from "./AlertsScreen";
import type { Alert } from "./types";

/**
 * `Show on chart` opens the terminal at the alert's symbol and evaluate-on interval. Drawing the
 * level is E11's (DF-10); the terminal reads these params once its deep-link contract lands.
 */
export function chartHref(alert: Alert): string {
  const params = new URLSearchParams();
  if (alert.symbol != null) params.set("symbol", alert.symbol);
  const frame = (alert.condition_ir as { trigger?: { timeframe?: unknown } } | undefined)?.trigger
    ?.timeframe;
  if (typeof frame === "string") params.set("interval", frame);
  const query = params.toString();
  return query === "" ? "/terminal/last" : `/terminal/last?${query}`;
}

export function AlertsRoute(): JSX.Element {
  const navigate = useNavigate();
  return (
    <ScreenRoot>
      <AlertsScreen onShowOnChart={(alert) => void navigate(chartHref(alert))} />
    </ScreenRoot>
  );
}

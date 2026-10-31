/** Alert types for the management screen's data layer (E40-S01): protocol-derived only, no hand-written DTOs. */
import type { generated } from "@candleviewer/protocol";

export type Alert = generated.rest.components["schemas"]["Alert"];
/** One frame of the `alerts` WS topic: fired deliveries. */
export type AlertsFrame = generated.ws.Alerts;
export type AlertDelivery = AlertsFrame["deliveries"][number];
/** One REST delivery row (`GET /alerts/deliveries`), the history's source. */
export type DeliveryRow = generated.rest.components["schemas"]["AlertDelivery"];
/** The vocabulary's signal entries (`GET /rules/vocabulary`): display names and the estimated flag. */
export type VocabularySignal = NonNullable<
  generated.rest.components["schemas"]["RuleVocabulary"]["signals"]
>[number];

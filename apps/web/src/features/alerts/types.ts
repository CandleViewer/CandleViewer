/** Alert types for the management screen's data layer (E40-S01): protocol-derived only, no hand-written DTOs. */
import type { generated } from "@candleviewer/protocol";

export type Alert = generated.rest.components["schemas"]["Alert"];
/** One frame of the `alerts` WS topic: fired deliveries. */
export type AlertsFrame = generated.ws.Alerts;
export type AlertDelivery = AlertsFrame["deliveries"][number];

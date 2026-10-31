/** Shared fixtures for the alerts centre tests: synthetic alerts only, and a fake `AlertsApi`. */
import { vi } from "vitest";
import type { AlertsApi, Outcome } from "../../../src/features/alerts/alertsApi";
import type { Alert, DeliveryRow, VocabularySignal } from "../../../src/features/alerts/types";

export const NOW = Date.parse("2026-10-31T14:00:00.000Z");

export function alert(n: number, over: Partial<Alert> = {}): Alert {
  return {
    id: `00000000-0000-4000-8000-00000000000${n}`,
    name: `Alert ${n}`,
    symbol: "BTCUSDT",
    trigger_mode: "every_time",
    channels: ["in_app"],
    enabled: true,
    fire_count: 0,
    last_fired_at: null,
    snoozed_until: null,
    disarm_reason: null,
    cooldown_seconds: 60,
    created_at: "2026-10-30T10:00:00Z",
    updated_at: "2026-10-30T10:00:00Z",
    condition_ir: {
      ir_version: 1,
      trigger: { type: "on_price_update" },
      conditions: {
        node_id: "c1",
        op: "gte",
        left: { metric: "last_price" },
        right: { const: 64000 },
      },
    },
    ...over,
  } as Alert;
}

/** A vocabulary signal with the schema's required defaults filled in. */
export const signal = (id: string, over: Partial<VocabularySignal> = {}): VocabularySignal => ({
  id,
  display_name: id,
  type: "price",
  available: true,
  estimated: false,
  requires_recording: false,
  ...over,
});

export const ok = <T>(value: T): Outcome<T> => ({ kind: "ok", value });

export function fakeApi(alerts: readonly Alert[], over: Partial<AlertsApi> = {}): AlertsApi {
  return {
    list: vi.fn(() => Promise.resolve(ok(alerts))),
    setEnabled: vi.fn((id: string, enabled: boolean) =>
      Promise.resolve(ok({ ...(alerts.find((a) => a.id === id) as Alert), enabled })),
    ),
    setSnooze: vi.fn((id: string, until: string | null) =>
      Promise.resolve(ok({ ...(alerts.find((a) => a.id === id) as Alert), snoozed_until: until })),
    ),
    remove: vi.fn(() => Promise.resolve(ok(null))),
    deliveries: vi.fn(() => Promise.resolve(ok([] as readonly DeliveryRow[]))),
    vocabulary: vi.fn(() =>
      Promise.resolve(ok([signal("last_price", { display_name: "Last price" })])),
    ),
    ...over,
  };
}

export function delivery(
  id: number,
  alertId: string,
  firedAt: string,
  over: Partial<DeliveryRow> = {},
): DeliveryRow {
  return {
    id,
    alert_id: alertId,
    channel: "in_app",
    status: "sent",
    message: `Fired ${id}`,
    fired_at: firedAt,
    acked_at: null,
    error: null,
    ...over,
  } as DeliveryRow;
}

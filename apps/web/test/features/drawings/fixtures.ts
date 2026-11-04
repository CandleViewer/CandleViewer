import type { Drawing, DrawingInput } from "../../../src/features/drawings/store/types.js";

export const input = (symbol = "BTCUSDT", over: Partial<DrawingInput> = {}): DrawingInput => ({
  symbol,
  tool: "trendline",
  layout_id: null,
  geometry: {
    points: [
      { t: "2026-09-13T12:00:00Z", p: "61200.00" },
      { t: "2026-09-13T13:00:00.250Z", p: "61300.5" },
    ],
  },
  style: { colour: "#ff0000", width: 1 },
  label: null,
  locked: false,
  visible: true,
  z_index: 0,
  ...over,
});

let seq = 0;
/** A server row for `id` with `input`; `token` is the exact `updated_at` string. */
export const row = (id: string, body: DrawingInput, token?: string): Drawing => {
  seq += 1;
  return {
    ...body,
    style: body.style ?? {},
    id,
    owner_user_id: "00000000-0000-7000-8000-000000000001",
    created_at: "2026-09-13T12:00:00.000000Z",
    updated_at: token ?? `2026-09-13T12:00:${String(seq % 60).padStart(2, "0")}.123450Z`,
  };
};

/** Deterministic ids: id-1, id-2, ... */
export const counter = (prefix = "id"): (() => string) => {
  let n = 0;
  return () => {
    n += 1;
    return `${prefix}-${n}`;
  };
};

/**
 * Test support for the fills feature (E29-S04 #979): the goldens the shipped Python mappers write
 * (`packages/fixtures/golden/executions/`, BQ-18) and their rows, read once. The WS client fake
 * is the positions tests' (`../../support/fakes.ts`).
 */
import type { generated } from "@candleviewer/protocol";
import {
  mapFill,
  type FillRowModel,
} from "../../../../../src/features/positions/fills/model/fillRow";
import { repoFile } from "../../../../lib/ws/support/schemaHarness";

export const GOLDEN_DIR = "packages/fixtures/golden/executions";
export const golden = <T = unknown>(name: string): T =>
  JSON.parse(repoFile(`${GOLDEN_DIR}/${name}`)) as T;

type Rest = generated.rest.components["schemas"];
export type GetOrderCase = "limit" | "stop_exit" | "amended" | "at_limit" | "market";

export const snapshotBody = (): generated.ws.Executions =>
  golden<generated.ws.Executions>("ws_executions_snapshot.json");
export const deltaBody = (): generated.ws.Executions =>
  golden<{ case: string; body: generated.ws.Executions }[]>("ws_executions_deltas.json")[0]
    ?.body ?? { executions: [] };
export const restItems = (): Rest["Execution"][] =>
  golden<{ items: Rest["Execution"][] }>("rest_list_executions.json").items;
export function order(name: GetOrderCase): Rest["OrderWithEvents"] {
  const found = golden<{ case: string; body: Rest["OrderWithEvents"] }[]>(
    "rest_get_order.json",
  ).find((c) => c.case === name);
  if (found === undefined) throw new Error(`no getOrder golden ${name}`);
  return found.body;
}

/** The rows of items, dropping none (a golden item that fails to map is a test failure). */
export function rowsOf(
  items: readonly (generated.ws.Executions["executions"][number] | Rest["Execution"])[],
  source: "ws" | "rest",
): FillRowModel[] {
  return items.map((item) => {
    const row = mapFill(item, source);
    if (row === null) throw new Error(`golden item did not map: ${JSON.stringify(item)}`);
    return row;
  });
}

/** An order's fills from its `getOrder` golden (REST, oldest first). */
export const orderRows = (name: GetOrderCase): FillRowModel[] =>
  rowsOf(order(name).executions ?? [], "rest");

/** D03 §1.4: BTCUSDT's tick. */
export const TICK = "0.1";
export const ORDER_A3F2 = "0a000000-0000-4000-8000-00000000a3f2";
export const GROUP_7C1E = "0c000000-0000-4000-8000-000000007c1e";

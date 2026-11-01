/**
 * Test support for the Working-orders slice (E29-S02 #912): the goldens the shipped Python mappers
 * write (`packages/fixtures/golden/orders/`, through `test_orders_web_golden.py`), the fixture
 * accounts, and the positions slice's fake WS client and frame builders, which this slice shares.
 */
import type { generated } from "@candleviewer/protocol";
import type { ExchangeAccount } from "../../../../../src/features/positions/api";
import {
  accountInfo,
  type AccountInfo,
} from "../../../../../src/features/positions/model/rowMapping";
import type {
  RestOrder,
  WsOrder,
} from "../../../../../src/features/positions/orders/model/orderRow";
import { repoFile } from "../../../../lib/ws/support/schemaHarness";
import { golden as positionsGolden } from "../../support/fakes";

export {
  delta,
  fakeClient,
  fakeRaf,
  MAIN,
  reset,
  snap,
  SUB1,
  SUB2,
  type FakeClient,
  type FakeHandle,
} from "../../support/fakes";

export const ORDERS_DIR = "packages/fixtures/golden/orders";
export const golden = <T = unknown>(name: string): T =>
  JSON.parse(repoFile(`${ORDERS_DIR}/${name}`)) as T;

/** The two accounts only the five-account cancel-all names. */
export const SUB3 = "a1000000-0000-4000-8000-000000000004";
export const SUB4 = "a1000000-0000-4000-8000-000000000005";

/** The goldens' orders (`test_orders_web_golden.py`'s `oid`): D02 §6.2's five, then the rest. */
export const TP = "0e000000-0000-4000-8000-000000000001";
export const ENTRY = "0e000000-0000-4000-8000-000000000002";
export const ETH = "0e000000-0000-4000-8000-000000000003";
export const COND = "0e000000-0000-4000-8000-000000000004";
export const STOP = "0e000000-0000-4000-8000-000000000005";
export const HELD = "0e000000-0000-4000-8000-000000000006";
export const UNTRACKED = "0e000000-0000-4000-8000-000000000007";
export const NEW = "0e000000-0000-4000-8000-000000000008";
export const ADOPTED = "0e000000-0000-4000-8000-000000000009";
export const BRACKET = "7c1e0000-0000-4000-8000-000000000001";

export type OrdersBody = generated.ws.Orders;
export type DeltaCase =
  | "created"
  | "submitted"
  | "acked"
  | "amend_request"
  | "amend_accepted"
  | "amend_rejected"
  | "amend_unknown"
  | "cancel_request"
  | "cancel_lost_race"
  | "cancel_110001"
  | "reconcile_filled"
  | "untracked_adopted"
  | "held"
  | "late";

export const snapshotBody = (): OrdersBody => golden<OrdersBody>("ws_orders_snapshot.json");

/** One delta's body, by its case name in `ws_orders_deltas.json`. */
export function deltaBody(name: DeltaCase): OrdersBody {
  const found = golden<{ case: string; body: OrdersBody }[]>("ws_orders_deltas.json").find(
    (d) => d.case === name,
  );
  if (found === undefined) throw new Error(`no delta case ${name}`);
  return found.body;
}

export const wsItem = (body: OrdersBody, id: string): WsOrder => {
  const item = body.orders.find((o) => o.id === id);
  if (item === undefined) throw new Error(`no order ${id}`);
  return item;
};

export const restOpen = (): RestOrder[] =>
  golden<{ items: RestOrder[] }>("rest_list_orders_open.json").items;

/** The positions goldens' directory: Main, Sub-1 and Sub-2, LIVE. */
export function directory(): Map<string, AccountInfo> {
  const items = positionsGolden<{ items: ExchangeAccount[] }>(
    "rest_list_exchange_accounts.json",
  ).items;
  return new Map(
    items
      .map(accountInfo)
      .filter((a): a is AccountInfo => a !== null)
      .map((a) => [a.id, a]),
  );
}

export const exchangeAccounts = (): ExchangeAccount[] =>
  positionsGolden<{ items: ExchangeAccount[] }>("rest_list_exchange_accounts.json").items;

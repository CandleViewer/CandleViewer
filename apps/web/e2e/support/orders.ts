// E29-S02 (#912) the Working-orders REST stubs for the web specs: `GET /orders?open_only=true` from the
// shipped mappers' goldens (`golden/orders`), and the cancel writes as `22` answers them, each recorded
// with its `Idempotency-Key` and whether it carried an arm token. Call after `stubPositions` and before
// `goto`. No live backend (C-13.5); app code is not mocked.
import { readFileSync } from "node:fs";
import type { Page, Route } from "@playwright/test";
import { json } from "./api";

/** A golden of `golden/orders` (the shipped mappers' output; its manifest names each source). */
export function goldenOrders<T = unknown>(name: string): T {
  const url = new URL(`../../../../packages/fixtures/golden/orders/${name}`, import.meta.url);
  return JSON.parse(readFileSync(url, "utf8")) as T;
}

export interface OrderWrite {
  readonly method: string;
  readonly path: string;
  readonly key: string | null;
  readonly arm: boolean;
  readonly body: unknown;
}

export interface OrdersAnswers {
  /** `GET /orders?open_only=true`'s items: default the golden's seven. */
  readonly open?: readonly unknown[];
  /** `DELETE /orders/{id}`: default `202` with the order cancelling. */
  readonly cancel?: (id: string) => { readonly status: number; readonly body: unknown };
  /** `POST /orders/cancel-all`, by its request and its count from 1: default no result. */
  readonly cancelAll?: (
    body: { readonly exchange_account_ids?: readonly string[] },
    n: number,
  ) => { readonly status: number; readonly body: unknown };
}

export async function stubOrders(
  page: Page,
  answers: OrdersAnswers = {},
): Promise<{ writes(): readonly OrderWrite[] }> {
  const writes: OrderWrite[] = [];
  const open =
    answers.open ?? goldenOrders<{ items: unknown[] }>("rest_list_orders_open.json").items;
  let cancelAlls = 0;
  await page.route(
    (url) => url.pathname === "/api/v1/orders" || url.pathname.startsWith("/api/v1/orders/"),
    async (r: Route) => {
      const request = r.request();
      const url = new URL(request.url());
      const method = request.method();
      if (method === "GET" && url.pathname === "/api/v1/orders") {
        return r.fulfill(json({ items: open, meta: { next_cursor: null, has_more: false } }));
      }
      const headers = await request.allHeaders();
      const body = request.postData();
      writes.push({
        method,
        path: url.pathname,
        key: headers["idempotency-key"] ?? null,
        arm: "x-arm-token" in headers,
        body: body === null ? null : (JSON.parse(body) as unknown),
      });
      if (method === "POST" && url.pathname === "/api/v1/orders/cancel-all") {
        cancelAlls += 1;
        const out = answers.cancelAll?.(JSON.parse(body ?? "{}") as never, cancelAlls) ?? {
          status: 200,
          body: { results: [], requested: 0, succeeded: 0 },
        };
        return r.fulfill(json(out.body, out.status));
      }
      const id = url.pathname.slice("/api/v1/orders/".length);
      const out = answers.cancel?.(id) ?? {
        status: 202,
        body: { id, lifecycle_state: "cancel_pending" },
      };
      return r.fulfill(json(out.body, out.status));
    },
  );
  return { writes: () => writes };
}

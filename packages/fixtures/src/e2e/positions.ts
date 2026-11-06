import { readFileSync } from "node:fs";
import type { Page, Route } from "@playwright/test";
import type { generated } from "@candleviewer/protocol";
import { json } from "./stubs";

// E29-S01 (#911) Positions REST stubs, shared by the web and Electron E2E suites (as `stubs.ts` is,
// E10-Q02): `GET /me` for an owner, a manager or a viewer with the permissions and grants SCR-063
// reads, `GET /exchange-accounts` and `GET /positions` as the server scopes them, from the goldens
// the shipped mappers wrote (`golden/positions`, BQ-22), and the audited `403 account_scope_denied`
// for a filter naming an account outside the grants (`22` `listPositions`; the server's refusal and
// its audit row are E29-T07's tests, BQ-13). No live backend (C-13.5); app code is not mocked.

type Schemas = generated.rest.components["schemas"];

/** The goldens' three accounts (the manifest's remapping) and the stub user. */
export const POSITIONS_FIXTURE = {
  main: "a1000000-0000-4000-8000-000000000001",
  sub1: "a1000000-0000-4000-8000-000000000002",
  sub2: "a1000000-0000-4000-8000-000000000003",
  tradeGroup: "0c000000-0000-4000-8000-000000000001",
  user: "11111111-2222-4333-8444-555555555555",
} as const;

const ALL = [POSITIONS_FIXTURE.main, POSITIONS_FIXTURE.sub1, POSITIONS_FIXTURE.sub2];

/** A golden of `golden/positions` (the shipped mappers' output; its manifest names each source). */
export function goldenPositions<T = unknown>(name: string): T {
  const url = new URL(`../../golden/positions/${name}`, import.meta.url);
  return JSON.parse(readFileSync(url, "utf8")) as T;
}

/** `22` `x-rbac`'s permissions each role holds on SCR-063's reads and writes. */
const PERMISSIONS: Readonly<Record<PositionsSession["role"], readonly string[]>> = {
  owner: ["positions:read", "positions:write", "orders:read", "orders:write", "accounts:read"],
  manager: ["positions:read", "positions:write", "orders:read", "orders:write", "accounts:read"],
  viewer: ["positions:read", "orders:read", "accounts:read"],
};

export interface PositionsSession {
  readonly role: "owner" | "manager" | "viewer";
  /** The accounts the server serves the caller; default all three (the Owner's). */
  readonly scope?: readonly string[];
  /** Accounts of the scope granted read-only (a Manager's `mode: "read"`). */
  readonly readOnly?: readonly string[];
  /** REST's open positions: the goldens, or none. */
  readonly book?: "golden" | "empty";
}

export interface PositionsStubs {
  /** The `GET /positions` requests answered `403 account_scope_denied`. */
  refusals(): number;
  /** Every `GET /positions` query string, in order. */
  positionReads(): readonly string[];
}

/**
 * Answers SCR-063's reads for `session`. Call it after `stubSession` (its `/me` replaces that one) and
 * before `goto`.
 */
export async function stubPositions(
  page: Page,
  session: PositionsSession,
): Promise<PositionsStubs> {
  const scope = session.scope ?? ALL;
  const readOnly = new Set(session.readOnly ?? []);
  const accounts = goldenPositions<{ items: Schemas["ExchangeAccount"][] }>(
    "rest_list_exchange_accounts.json",
  ).items.filter((a) => scope.includes(a.id));
  const items =
    session.book === "empty"
      ? []
      : goldenPositions<{ items: Schemas["Position"][] }>("rest_list_positions.json").items.filter(
          (p) => scope.includes(p.exchange_account_id),
        );
  let refused = 0;
  const reads: string[] = [];
  await page.route("**/api/v1/me", (r: Route) =>
    r.fulfill(
      json({
        role: session.role,
        permissions: [...PERMISSIONS[session.role]],
        user: { id: POSITIONS_FIXTURE.user, username: `${session.role}.e2e` },
        accounts: accounts.map((a) => ({
          exchange_account_id: a.id,
          label: a.label,
          environment: a.environment,
          mode: readOnly.has(a.id) ? "read" : "trade",
        })),
        session: { environment: "live", elevated_until: null },
      }),
    ),
  );
  await page.route(
    (url) => url.pathname === "/api/v1/exchange-accounts",
    (r: Route) =>
      r.fulfill(
        json({
          items: accounts,
          meta: { next_cursor: null, has_more: false, count: accounts.length },
        }),
      ),
  );
  await page.route(
    (url) => url.pathname === "/api/v1/positions",
    (r: Route) => {
      const url = new URL(r.request().url());
      reads.push(url.search);
      const named = url.searchParams.getAll("exchange_account_ids");
      if (named.some((id) => !scope.includes(id))) {
        refused += 1;
        return r.fulfill(
          json(
            {
              type: "https://candleviewer.local/errors/account_scope_denied",
              title: "Account out of scope",
              status: 403,
              code: "account_scope_denied",
            },
            403,
          ),
        );
      }
      const wanted = named.length > 0 ? named : scope;
      return r.fulfill(
        json({
          items: items.filter((p) => wanted.includes(p.exchange_account_id)),
          aggregates: [],
        }),
      );
    },
  );
  return { refusals: () => refused, positionReads: () => reads };
}

/**
 * The Working-orders tab's sections (E29-S02 #912; E29-D02 §6.2, S-35): **Working** and
 * **Conditional — not triggered**, the second holding each order with a trigger price that has not
 * triggered (US-POS-002: a distinct section, the trigger in words). Within a section the rows group
 * by account and sort environment → account → time created, oldest first, so a new order joins the
 * end of its account's group and nothing above it moves (D01 D13 a). A section with no rows is not
 * drawn: board 06 draws no empty section row.
 */
import { bindDeck } from "../../copy";
import type { Environment } from "../../model/rowMapping";
import { bindProposed, ORDER_TEXT } from "../copy";
import type { OrderRowModel } from "./orderRow";

export type SectionId = "working" | "conditional";

export interface AccountGroup {
  readonly accountId: string;
  readonly label: string | null;
  readonly environment: Environment | null;
  readonly rows: readonly OrderRowModel[];
}

export interface OrdersSection {
  readonly id: SectionId;
  /** The section row: "Working · 3", "Conditional — not triggered · 2" (S-35). */
  readonly label: string;
  readonly count: number;
  readonly groups: readonly AccountGroup[];
}

const ENV_RANK: Readonly<Record<Environment, number>> = { live: 0, demo: 1, testnet: 2 };
const text = (a: string, b: string): number => (a < b ? -1 : a > b ? 1 : 0);
const envOf = (row: OrderRowModel): number =>
  row.environment === null ? 3 : ENV_RANK[row.environment];

/**
 * D01 D13 (a): environment → account (label, then id) → time created, oldest first. An order whose
 * creation time is not known yet (D01 OQ-9) goes last in its group; its id breaks every tie, so the
 * order is total and stable.
 */
export function compareOrders(a: OrderRowModel, b: OrderRowModel): number {
  const created = (r: OrderRowModel): number => r.createdAtMs ?? Number.MAX_SAFE_INTEGER;
  return (
    envOf(a) - envOf(b) ||
    text(a.accountLabel ?? "￿", b.accountLabel ?? "￿") ||
    text(a.accountId, b.accountId) ||
    created(a) - created(b) ||
    text(a.id, b.id)
  );
}

export function sortOrders(rows: readonly OrderRowModel[]): readonly OrderRowModel[] {
  return [...rows].sort(compareOrders);
}

/** Which section a row is in (D02 §6.2). */
export const sectionOf = (row: OrderRowModel): SectionId =>
  row.conditional ? "conditional" : "working";

/**
 * Both sections, Working first, each with its rows grouped by account in `compareOrders`' order;
 * `rows` may come in any order. Hidden rows (`draft`, `validated`) are left out.
 */
export function sectionsOf(rows: readonly OrderRowModel[]): readonly OrdersSection[] {
  const sorted = sortOrders(rows.filter((r) => !r.state.hidden));
  const out: OrdersSection[] = [];
  for (const id of ["working", "conditional"] as const) {
    const mine = sorted.filter((r) => sectionOf(r) === id);
    if (mine.length === 0) continue;
    const groups: AccountGroup[] = [];
    for (const row of mine) {
      const last = groups.at(-1);
      if (last !== undefined && last.accountId === row.accountId) {
        (last.rows as OrderRowModel[]).push(row);
      } else {
        groups.push({
          accountId: row.accountId,
          label: row.accountLabel,
          environment: row.environment,
          rows: [row],
        });
      }
    }
    const count = String(mine.length);
    const label =
      id === "working"
        ? bindDeck("blotter.ui.section.working", { "3": count })
        : bindDeck("blotter.ui.section.conditional", { "2": count });
    out.push({ id, label, count: mine.length, groups });
  }
  return out;
}

/** The environment's word in a group row: D02's LIVE and DEMO, and the PROPOSED TESTNET. */
const ENV_WORDS: Readonly<Record<Environment, () => string>> = {
  live: () => ORDER_TEXT.live.string,
  demo: () => ORDER_TEXT.demo.string,
  testnet: () => bindProposed("blotter.ui.env.testnet"),
};

/**
 * The environment's word, or `null` when there is none to give: no environment yet, or one outside
 * the union. The directory's `environment` reaches the group unnarrowed (`rowMapping.ts`'s
 * `accountInfo` passes it through), so a contract break must read as an unknown one and never throw
 * in a render. Only the record's own keys are words: `toString` is not one.
 */
function envWord(environment: Environment | null): string | null {
  return environment !== null && Object.hasOwn(ENV_WORDS, environment)
    ? ENV_WORDS[environment]()
    : null;
}

/**
 * The account group row, "Main · LIVE · 3 orders" (PROPOSED, BQ-9: board 06 draws it; §6 gives no
 * string). An account the directory does not name shows its id, as the positions grid does; one
 * whose environment is not known yet, or not one this client knows, drops that segment ("Main · 3
 * orders"), never leaving it empty.
 */
export function groupLabel(group: AccountGroup): string {
  const account = group.label ?? group.accountId;
  const count = String(group.rows.length);
  const one = group.rows.length === 1;
  const environment = envWord(group.environment);
  if (environment === null) {
    return one
      ? bindProposed("blotter.ui.orders_group.no_env.one", { Main: account })
      : bindProposed("blotter.ui.orders_group.no_env", { Main: account, "3": count });
  }
  const values = { Main: account, LIVE: environment };
  return one
    ? bindProposed("blotter.ui.orders_group.one", values)
    : bindProposed("blotter.ui.orders_group", { ...values, "3": count });
}

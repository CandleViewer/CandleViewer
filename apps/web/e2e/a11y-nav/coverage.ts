import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * The BQ-10 (a) coverage table source: every Q03-tagged case of qa/plans/e47-accessibility-test-plan.md
 * (the plan's 36; 110, 115, 118 and 306 are manual, BQ-05) mapped to one status. `cases.json` is the data; the
 * README's table is `renderCoverage(...)` of it, and a unit test holds the two equal.
 */
export type CaseStatus = "journey" | "existing" | "expected-fail" | "pending";

export interface Q03Case {
  readonly id: number;
  readonly scr: string;
  readonly status: CaseStatus;
  /** journey: the spec file here; existing: the spec elsewhere; expected-fail: the remediation ticket. */
  readonly where: string;
  readonly note: string;
}

const HERE = dirname(fileURLToPath(import.meta.url));

export function loadCases(): readonly Q03Case[] {
  return JSON.parse(readFileSync(join(HERE, "cases.json"), "utf8")) as Q03Case[];
}

export const TABLE_HEADER = "| Case | Surface | Status | Where | Note |\n|---|---|---|---|---|";

export function renderCoverage(cases: readonly Q03Case[]): string {
  const rows = cases.map(
    (c) => `| E47-TC-${c.id} | ${c.scr} | ${c.status} | ${c.where} | ${c.note} |`,
  );
  return [TABLE_HEADER, ...rows].join("\n");
}

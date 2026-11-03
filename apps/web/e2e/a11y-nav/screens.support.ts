import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { SCREENS, SIGNED_IN_SCREENS, type A11yScreen } from "../a11y/screens";
import { trapBudget } from "./trapBudget";

/** The mounted screens the keyboard sweeps walk: the collectors' own set (read-only import of screens.ts). */
export const MOUNTED: readonly A11yScreen[] = [...SCREENS, ...SIGNED_IN_SCREENS];

const TREES = join(
  dirname(fileURLToPath(import.meta.url)),
  "../../../../tools/a11y/tree-snapshots",
);
/** The legacy fixed bound (keyboard.collect.ts MAX_TABS), used only when a screen has no committed baseline. */
const FALLBACK_N = 80;

/** The screen's trap limit N (trapBudget.ts), from its committed G006 baseline. */
export function trapLimit(id: string): number {
  const file = join(TREES, `${id}.txt`);
  return existsSync(file) ? trapBudget(readFileSync(file, "utf8")) : FALLBACK_N;
}

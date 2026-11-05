// E15-S03 (#476) BQ-03: the seeded-workspace e2e entry. The workspace is the fixture in
// `@candleviewer/fixtures/e2e` (`22`'s shapes, a `chart` pane); the instruments are recorded
// (C-13.5: LUNAUSDT Closed). Push WORKSPACE_DOCK_ON from the WS harness, then `/terminal` mounts it.
import { readFileSync } from "node:fs";
import type { Page } from "@playwright/test";
import { SEEDED_WORKSPACE, seededLayout, type SeedPane } from "@candleviewer/fixtures/e2e";
import { json } from "./api";

export type { SeedPane };
/** The `system` push that turns the served `ui.workspace_dock` on, as the first-auth frame. */
export const WORKSPACE_DOCK_ON = {
  kind: "feature_flags",
  feature_flags: { "ui.workspace_dock": true },
};
const FIXTURE = "../../../../packages/fixtures/bybit/2026-10-05/rest/instruments_after.json";
const PAGE = new URL(FIXTURE, import.meta.url);

/** Serves the seeded workspace (at most 4 panes) and the instruments; returns its path. */
export async function seedWorkspace(page: Page, panes?: readonly SeedPane[]): Promise<string> {
  const listed = (
    JSON.parse(readFileSync(PAGE, "utf8")) as { result: { list: { symbol: string }[] } }
  ).result.list;
  const { id } = SEEDED_WORKSPACE;
  await page.route("**/api/v1/workspaces", (r) => r.fulfill(json({ items: [SEEDED_WORKSPACE] })));
  await page.route(`**/api/v1/workspaces/${id}`, (r) =>
    r.fulfill(json({ ...SEEDED_WORKSPACE, layouts: [seededLayout(panes)] })),
  );
  await page.route("**/api/v1/instruments/*", (r) => {
    const found = listed.find((i) => r.request().url().endsWith(`/${i.symbol}`));
    return r.fulfill(found === undefined ? json({ code: "not_found" }, 404) : json(found));
  });
  return `/w/${id}`;
}

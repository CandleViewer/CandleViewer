// @vitest-environment node
import { readdirSync, readFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";
import appConfig from "../vite.config";
import harnessConfig, { HARNESS_OUT_DIR } from "../e2e/a11y/chart-harness/vite.config";
import {
  CHART_SCREENS,
  CHART_SURFACES,
  CHART_TOGGLES,
  HARNESS_ORIGIN,
} from "../e2e/a11y/chart-harness/surfaces";
import { CHART_SCREENS as REGISTERED, SCREENS, SIGNED_IN_SCREENS } from "../e2e/a11y/screens";

/**
 * E11-Q05 (#517): the chart a11y harness is an e2e-only entry. These tests pin that the app's
 * production build cannot contain it (C-14.3 budgets; no test page shipped) and that its states
 * are the ones the a11y collectors visit.
 */
const WEB = resolve(import.meta.dirname, "..");
const HARNESS_DIR = join(WEB, "e2e/a11y/chart-harness");

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((e) =>
    e.isDirectory()
      ? sources(join(dir, e.name))
      : /\.(tsx?|css)$/.test(e.name)
        ? [join(dir, e.name)]
        : [],
  );
}

describe("the chart a11y harness is excluded from the app bundle (E11-Q05)", () => {
  it("leaves the app build on its one entry, apps/web/index.html", () => {
    expect(appConfig.root).toBeUndefined();
    expect(appConfig.build?.rollupOptions?.input).toBeUndefined();
    expect(readFileSync(join(WEB, "index.html"), "utf8")).not.toMatch(/e2e|harness/);
  });

  it("is never imported by the app's source", () => {
    const leaks = sources(join(WEB, "src")).filter((f) =>
      /from\s+["'][^"']*(e2e\/|chart-harness)/.test(readFileSync(f, "utf8")),
    );
    expect(leaks.map((f) => relative(WEB, f))).toEqual([]);
  });

  it("builds from its own root into its own outDir, outside the app's dist", () => {
    expect(harnessConfig.root).toBe(HARNESS_DIR);
    expect(harnessConfig.build?.outDir).toBe(HARNESS_OUT_DIR);
    expect(relative(join(WEB, "dist"), HARNESS_OUT_DIR).startsWith("..")).toBe(true);
    expect(HARNESS_OUT_DIR).toContain(join("node_modules", ".cache"));
  });
});

describe("the chart harness states the a11y collectors visit (E11-Q05)", () => {
  it("registers the harness states with the shared screen list", () => {
    expect(REGISTERED).toBe(CHART_SCREENS);
    expect(CHART_SCREENS).toEqual([
      { id: "SCR-030-mirror", path: `${HARNESS_ORIGIN}/?state=mirror` },
      { id: "SCR-030-mirror-off", path: `${HARNESS_ORIGIN}/?state=mirror-off` },
    ]);
  });

  it("never reuses a route screen id", () => {
    const routeIds = new Set([...SCREENS, ...SIGNED_IN_SCREENS].map((s) => s.id));
    expect(CHART_SCREENS.filter((s) => routeIds.has(s.id))).toEqual([]);
  });

  it("records the unbuilt surfaces and toggles as shipped:false, with no harness state", () => {
    const unbuilt = CHART_SURFACES.filter((s) => !s.shipped);
    expect(unbuilt.map((s) => s.screen)).toEqual(["SCR-031", "SCR-047", "SCR-044", "SCR-049"]);
    expect(unbuilt.flatMap((s) => s.states)).toEqual([]);
    expect(CHART_TOGGLES.every((t) => !t.shipped)).toBe(true);
  });

  it("lists the nine plan surfaces S1..S9 once each", () => {
    expect(CHART_SURFACES.map((s) => s.id)).toEqual(
      Array.from({ length: 9 }, (_, i) => `S${i + 1}`),
    );
  });
});

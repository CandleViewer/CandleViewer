import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { ROUTE_MANIFEST } from "../../src/routes/manifest";
import { ROUTE_TITLES, documentTitle } from "../../src/routes/titles";

/**
 * Parses the §2 "Full route tree" table out of `12-sitemap.md` and fails
 * this test if the manifest ever drifts from the sitemap (ticket
 * acceptance criterion "Complete route coverage").
 */
function sitemapRouteIds(): string[] {
  // vitest's `root` for @candleviewer/web is apps/web; walk up to the repo root.
  const path = resolve(process.cwd(), "../../docs/plan/12-sitemap.md");
  const text = readFileSync(path, "utf-8");
  const start = text.indexOf("## 2. Full route tree");
  const end = text.indexOf("## 3. Route tree diagram");
  const section = text.slice(start, end);
  const ids: string[] = [];
  for (const line of section.split("\n")) {
    const match = /^\|\s*(R-\d{3})\s*\|/.exec(line);
    if (match?.[1]) ids.push(match[1]);
  }
  return ids;
}

describe("route manifest coverage", () => {
  it("has exactly one manifest entry per sitemap route ID", () => {
    const sitemapIds = sitemapRouteIds();
    const manifestIds = ROUTE_MANIFEST.map((entry) => entry.id);
    expect(sitemapIds.length).toBeGreaterThan(0);
    expect(new Set(manifestIds)).toEqual(new Set(sitemapIds));
    expect(manifestIds.length).toBe(sitemapIds.length);
  });

  it("has no duplicate paths", () => {
    const paths = ROUTE_MANIFEST.map((entry) => entry.path);
    expect(new Set(paths).size).toBe(paths.length);
  });

  it("marks every /admin/** route as owner-only, deny-as-404, with no client step-up pre-emption", () => {
    for (const entry of ROUTE_MANIFEST) {
      if (entry.path.startsWith("/admin/") || entry.path === "/admin") {
        if (entry.id === "R-360") continue; // documented exception: reduced view for O/M outside admin-hat
        expect(entry.access.roles).toEqual(["owner"]);
        expect(entry.access.denyAs).toBe("404");
        expect(entry.access).toEqual({ roles: ["owner"], denyAs: "404" });
      }
    }
  });

  it("gives every route ID a unique, non-empty page title (D-01, WCAG 2.4.2)", () => {
    const titles = ROUTE_MANIFEST.map((entry) => ROUTE_TITLES[entry.id]);
    for (const [i, title] of titles.entries()) {
      expect(title?.trim(), ROUTE_MANIFEST[i]?.id).toBeTruthy();
    }
    expect(new Set(titles).size).toBe(titles.length);
    expect(Object.keys(ROUTE_TITLES).sort()).toEqual(ROUTE_MANIFEST.map((e) => e.id).sort());
    expect(documentTitle("Login")).toBe("Login - CandleViewer");
    expect(documentTitle(undefined)).toBe("CandleViewer");
  });
});

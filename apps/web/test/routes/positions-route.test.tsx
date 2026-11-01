/**
 * E29-S01 (#911, BQ-16) R-130 `/positions` mounts SCR-063: the manifest names no stub owner, the route
 * tree loads the panel through a dynamic import only (its own chunk, out of the first bundle), and
 * R-130's own element mounts the lazy panel with the deep link applied.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { render, screen, waitFor } from "@testing-library/react";
import { createMemoryRouter } from "react-router";
import { RouterProvider } from "react-router/dom";
import ts from "typescript";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { PreferencesProvider } from "../../src/features/a11y-preferences/PreferencesContext";
import { resetPanelState } from "../../src/features/positions/panelState";
import { ROUTE_MANIFEST } from "../../src/routes/manifest";
import { buildRoutes } from "../../src/routes/tree";

const TREE = resolve(import.meta.dirname, "../../src/routes/tree.tsx");
const PANEL = "../features/positions/PositionsPanel";

/** tree.tsx's module specifiers: the static ones and the dynamic `import()` ones. */
function specifiers(): { readonly staticSpecs: string[]; readonly dynamicSpecs: string[] } {
  const source = ts.createSourceFile(
    "tree.tsx",
    readFileSync(TREE, "utf8"),
    ts.ScriptTarget.Latest,
    true,
    ts.ScriptKind.TSX,
  );
  const staticSpecs: string[] = [];
  const dynamicSpecs: string[] = [];
  const visit = (node: ts.Node): void => {
    if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier))
      staticSpecs.push(node.moduleSpecifier.text);
    if (
      ts.isCallExpression(node) &&
      node.expression.kind === ts.SyntaxKind.ImportKeyword &&
      node.arguments[0] !== undefined &&
      ts.isStringLiteral(node.arguments[0])
    )
      dynamicSpecs.push(node.arguments[0].text);
    ts.forEachChild(node, visit);
  };
  visit(source);
  return { staticSpecs, dynamicSpecs };
}

/**
 * The lazy route's first import transforms the panel's whole module graph (CMP-114 and CMP-049 among it): paid here,
 * inside the default hook timeout, so the render test measures the mount, not the transform.
 */
beforeAll(async () => {
  await import("../../src/features/positions/PositionsPanel");
});

afterEach(() => {
  resetPanelState();
  vi.unstubAllGlobals();
});

describe("R-130 mounts SCR-063 (E29-S01, BQ-16)", () => {
  it("the manifest names no stub owner for R-130 (the screen ships here; the 'E12' owner was a placeholder)", () => {
    expect(ROUTE_MANIFEST.find((e) => e.id === "R-130")).toEqual({
      id: "R-130",
      path: "/positions",
      access: { roles: ["owner", "manager", "viewer"] },
      owner: null,
    });
  });

  it("the route tree loads the panel by a dynamic import only, so it is its own chunk", () => {
    const { staticSpecs, dynamicSpecs } = specifiers();
    expect(staticSpecs.filter((s) => s.includes("features/positions"))).toEqual([]);
    expect(dynamicSpecs).toContain(PANEL);
  });

  // The lazy panel's first render comes late under load: on the build host at a load of 26 to 35 it took over the
  // default 1 s wait and, with the shell around it, 14.4 s in all; the wait and the test take the screen tests'
  // measured bounds (`positions.integration.test.tsx`, `keymap-editor-axe.test.tsx`).
  it(
    "R-130's element mounts the lazy panel, the deep link applied",
    { timeout: 30_000 },
    async () => {
      // The tree's own element for R-130 (its `Suspense` and lazy panel) under a memory router, without the shell
      // layout, whose mount is the tree walk's (`tree.test.tsx`) and the role matrix's (E10-Q02)
      const shell = buildRoutes().find((route) => route.id === "shell");
      const r130 = shell?.children?.find((route) => route.id === "R-130");
      expect(r130?.element).toBeDefined();
      vi.stubGlobal(
        "fetch",
        vi.fn(async () => new Response("{}", { status: 404 })),
      );
      const router = createMemoryRouter([{ path: "/positions", element: r130?.element }], {
        initialEntries: ["/positions?groupBy=symbol"],
      });
      render(
        <PreferencesProvider>
          <RouterProvider router={router} />
        </PreferencesProvider>,
      );
      // `hidden: true` skips RTL's accessibility walk on every poll; the heading's visibility is asserted once
      const heading = await screen.findByRole(
        "heading",
        { level: 1, name: "Positions and orders", hidden: true },
        { timeout: 20_000 },
      );
      expect(heading).toBeVisible();
      expect(
        screen.getByRole("tab", { name: "Positions", selected: true, hidden: true }),
      ).toBeInTheDocument();
      // the link lands once the panel's readers have subscribed (their passive effects)
      await waitFor(() =>
        expect(screen.getByRole("combobox", { name: "Group by", hidden: true })).toHaveTextContent(
          "Symbol",
        ),
      );
    },
  );
});

// @vitest-environment node
import { resolve } from "node:path";
import { ESLint } from "eslint";
import { beforeAll, describe, expect, it } from "vitest";

/**
 * E37-S01 (BQ-1): the rule-graph editor's keyboard core (`a11y/`) and graph model (`model/`) stay
 * pure, proved through the ESLint API with the app's own config on virtual files. The rules under
 * test read no type information, so the probe lints without the TypeScript project service (the
 * app's config has no type-aware rule); a type-aware rule would fail this lint loudly.
 */
const WEB = resolve(import.meta.dirname, "../../..");
const SLICE = "src/features/rule-builder-graph";
const PURE = [`${SLICE}/model/__probe.ts`, `${SLICE}/a11y/__probe.ts`];
const FREE = `${SLICE}/canvas/__probe.tsx`;
/** The globals a pure core never reads, family by family, written out here, not read from the config. */
const GLOBAL_FAMILIES: readonly (readonly [string, readonly string[]])[] = [
  ["page", ["window", "document", "navigator", "location", "self", "globalThis"]],
  ["storage", ["localStorage", "sessionStorage", "indexedDB"]],
  ["network", ["fetch", "XMLHttpRequest", "WebSocket"]],
  [
    "rendering",
    ["requestAnimationFrame", "cancelAnimationFrame", "matchMedia", "getComputedStyle"],
  ],
  ["observers", ["ResizeObserver", "MutationObserver", "IntersectionObserver"]],
  ["elements", ["HTMLElement", "Element", "Event", "CustomEvent"]],
  ["clock", ["setTimeout", "setInterval", "queueMicrotask", "performance"]],
  ["log", ["console"]],
];

let eslint: ESLint;
const lint = async (file: string, code: string) =>
  (await eslint.lintText(code, { filePath: resolve(WEB, file) }))[0]?.messages ?? [];
const errors = async (file: string, code: string) =>
  (await lint(file, code)).filter((m) => m.severity === 2).map((m) => m.ruleId);

beforeAll(async () => {
  eslint = new ESLint({
    cwd: WEB,
    overrideConfig: {
      files: ["**/*.{ts,tsx}"],
      languageOptions: { parserOptions: { projectService: false, project: false } },
    },
  });
  // The first lint loads the config and its plugins: pay it here.
  await lint(FREE, "export {};\n");
}, 120_000);

describe("the rule-graph editor's a11y/ and model/ cores are pure", () => {
  it.each(PURE)("%s: a React, React DOM or graph-library import is an error", async (file) => {
    for (const code of [
      'import { useState } from "react";\nexport const s = useState;\n',
      'import ReactDOM from "react-dom";\nexport const d = ReactDOM;\n',
      'import { createRoot } from "react-dom/client";\nexport const r = createRoot;\n',
      'import { jsx } from "react/jsx-runtime";\nexport const j = jsx;\n',
      'import { ReactFlow } from "@xyflow/react";\nexport const f = ReactFlow;\n',
      'import { XYPanZoom } from "@xyflow/system";\nexport const z = XYPanZoom;\n',
    ]) {
      expect(await errors(file, code), code).toEqual(["no-restricted-imports"]);
    }
  });

  it.each(PURE)("%s: every impure global, family by family, is an error", async (file) => {
    for (const [family, names] of GLOBAL_FAMILIES) {
      for (const name of names) {
        const found = await errors(file, `export const g = ${name};\n`);
        expect(found, `${family}: ${name}`).toEqual(["no-restricted-globals"]);
      }
    }
  });

  it.each(PURE)("%s: the shared deep-import ban still holds", async (file) => {
    const code =
      'import { toIr } from "@candleviewer/rule-graph/src/adapter/toIr";\nexport const t = toIr;\n';
    expect(await errors(file, code)).toEqual(["no-restricted-imports"]);
  });

  it.each(PURE)("%s: a pure module lints clean", async (file) => {
    const code =
      'import type { GraphNode } from "@candleviewer/rule-graph";\nexport const id = (n: GraphNode): string => n.id;\n';
    expect(await errors(file, code)).toEqual([]);
  });

  it("leaves the rest of the slice free to use React and the DOM", async () => {
    const code =
      'import { useState } from "react";\nexport const s = useState;\nexport const w = window;\n';
    expect(await errors(FREE, code)).toEqual([]);
  });
});

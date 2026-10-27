/**
 * E49-K01-F4: composition guard for the `unwired-component` defect cluster.
 *
 * Statically walks the relative-import graph from `src/main.tsx` (static and
 * dynamic imports) and asserts that main.tsx boots via `startShell`, and that
 * every `src/features/<slice>/` has at least one module reachable from the
 * entry point. A new slice nobody mounts fails, naming the slice. Intentional
 * exceptions go in ALLOW_UNMOUNTED with a reason and ticket.
 *
 * Imports are read with the TypeScript parser (never regex), so commented-out
 * imports do not count. For the route tree, each imported symbol must also be
 * REFERENCED (JSX/call/identifier use) outside its import declaration.
 */
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";

const SRC = resolve(import.meta.dirname, "../src");
const ENTRY = join(SRC, "main.tsx");

/** slice -> reason + ticket. Stale entries (slice now reachable) fail. */
const ALLOW_UNMOUNTED: Readonly<Record<string, string>> = {};

interface ParsedImports {
  /** relative specifiers (static, re-export and dynamic `import()`) */
  readonly specs: string[];
  /** static import local bindings -> specifier */
  readonly bindings: Map<string, string>;
  /** identifier names used anywhere outside import declarations */
  readonly used: Set<string>;
}

export function parseImports(text: string, fileName = "x.tsx"): ParsedImports {
  const sf = ts.createSourceFile(fileName, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const specs: string[] = [];
  const bindings = new Map<string, string>();
  const used = new Set<string>();
  const add = (spec: string): boolean => {
    if (!/^\.{1,2}\//.test(spec)) return false;
    specs.push(spec);
    return true;
  };
  const visit = (node: ts.Node): void => {
    if (ts.isImportDeclaration(node)) {
      if (ts.isStringLiteral(node.moduleSpecifier) && add(node.moduleSpecifier.text)) {
        const c = node.importClause;
        if (c?.name) bindings.set(c.name.text, node.moduleSpecifier.text);
        const nb = c?.namedBindings;
        if (nb && ts.isNamedImports(nb)) {
          for (const el of nb.elements) bindings.set(el.name.text, node.moduleSpecifier.text);
        }
      }
      return;
    }
    if (
      ts.isExportDeclaration(node) &&
      node.moduleSpecifier &&
      ts.isStringLiteral(node.moduleSpecifier)
    ) {
      add(node.moduleSpecifier.text);
    }
    if (
      ts.isCallExpression(node) &&
      node.expression.kind === ts.SyntaxKind.ImportKeyword &&
      node.arguments[0] !== undefined &&
      ts.isStringLiteral(node.arguments[0])
    ) {
      add(node.arguments[0].text);
    }
    if (ts.isIdentifier(node)) used.add(node.text);
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return { specs, bindings, used };
}

function resolveModule(from: string, spec: string): string | null {
  const base = resolve(dirname(from), spec.replace(/\.js$/, ""));
  const candidates = [
    base,
    `${base}.ts`,
    `${base}.tsx`,
    join(base, "index.ts"),
    join(base, "index.tsx"),
  ];
  for (const c of candidates) {
    if (existsSync(c) && statSync(c).isFile()) return c;
  }
  return null;
}

function reachableFrom(entry: string): Set<string> {
  const seen = new Set<string>();
  const stack = [entry];
  while (stack.length > 0) {
    const file = stack.pop() as string;
    if (seen.has(file)) continue;
    seen.add(file);
    const text = readFileSync(file, "utf8");
    for (const spec of parseImports(text, file).specs) {
      const target = resolveModule(file, spec);
      if (target !== null) stack.push(target);
    }
  }
  return seen;
}

describe("composition guard (web)", () => {
  it("main.tsx boots the app through startShell and waits for it before rendering", () => {
    const src = readFileSync(ENTRY, "utf8");
    expect(src, "main.tsx must import startShell").toMatch(
      /import\s*\{[^}]*\bstartShell\b[^}]*\}\s*from\s*["']\.\/shell\/startShell["']/,
    );
    expect(src, "main.tsx must call startShell(...)").toMatch(/\bstartShell\s*\(/);
    expect(src, "App must render only after shell.ready").toMatch(/\.ready\b/);
    expect(src, "main.tsx must import App").toMatch(/import\(\s*["']\.\/App["']\s*\)/);
  });

  it("every feature slice has a module reachable from main.tsx", () => {
    const reachable = reachableFrom(ENTRY);
    const featuresDir = join(SRC, "features");
    const slices = readdirSync(featuresDir).filter((n) =>
      statSync(join(featuresDir, n)).isDirectory(),
    );
    expect(slices.length).toBeGreaterThan(0);

    const unmounted: string[] = [];
    const mounted: string[] = [];
    for (const slice of slices) {
      const prefix = join(featuresDir, slice) + (process.platform === "win32" ? "\\" : "/");
      const isMounted = [...reachable].some((f) => f.startsWith(prefix));
      (isMounted ? mounted : unmounted).push(slice);
    }

    const offenders = unmounted.filter((s) => !(s in ALLOW_UNMOUNTED));
    expect(
      offenders,
      `feature slices never imported from main.tsx/App/router: ${offenders.join(", ")}`,
    ).toEqual([]);
    const stale = mounted.filter((s) => s in ALLOW_UNMOUNTED);
    expect(stale, `allow-list entries now mounted, remove: ${stale.join(", ")}`).toEqual([]);
  });

  it("every routed feature screen file referenced by the route tree is reachable", () => {
    const tree = readFileSync(join(SRC, "routes/tree.tsx"), "utf8");
    const reachable = reachableFrom(ENTRY);
    const parsed = parseImports(tree, "tree.tsx");
    for (const spec of parsed.specs) {
      const target = resolveModule(join(SRC, "routes/tree.tsx"), spec);
      expect(target, `tree.tsx imports unresolvable ${spec}`).not.toBeNull();
      expect(reachable.has(target as string), `${spec} unreachable from main.tsx`).toBe(true);
    }
    const unused = [...parsed.bindings.keys()].filter((n) => !parsed.used.has(n));
    expect(unused, `tree.tsx imports symbols it never references: ${unused.join(", ")}`).toEqual(
      [],
    );
  });

  it("parseImports ignores commented-out imports and flags unreferenced symbols", () => {
    const src = [
      '// import { A } from "./a";',
      '/* import { B } from "./b"; */',
      'import { C, D } from "./c";',
      "export const x = <C />;",
      'void import("./e");',
    ].join("\n");
    const p = parseImports(src);
    expect(p.specs.sort()).toEqual(["./c", "./e"]);
    expect([...p.bindings.keys()].filter((n) => !p.used.has(n))).toEqual(["D"]);
  });
});

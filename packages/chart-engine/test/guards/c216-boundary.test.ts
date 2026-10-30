// Scenario: The framework-free boundary is enforced, not just documented (E11-T01, C-2.16).
// Each forbidden construct is linted / cruised from an in-memory or temporary fixture against the
// package's REAL ESLint config and the repo's REAL .dependency-cruiser.js rules, so no violating
// file is ever committed and the assertions follow any later edit of either config.
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { cruise, type IConfiguration, type ICruiseResult } from "dependency-cruiser";
import { ESLint, Linter } from "eslint";
import ts from "typescript";
import tseslint from "typescript-eslint";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

const PKG = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
const REPO = join(PKG, "..", "..");
const C216_RULES = ["no-restricted-imports", "no-restricted-globals", "no-restricted-syntax"];
// Generous per-test budget for the loops, the tsc programs and the project-service lint: they
// pass in ~2 s alone but share the runner with the whole unit project under load (C-9.3).
const SLOW = 20_000;
// Starting the TypeScript project service costs ~6 s alone; allow ten times that under load.
const PROJECT_SERVICE = 60_000;

// One ESLint instance and one resolved rule set per path, shared by every test in this file.
let eslint: ESLint | undefined;
const rulesCache = new Map<string, Promise<Linter.RulesRecord>>();

/** The effective C-2.16 rules for a file path, from the package's own eslint.config.mjs. */
function rulesFor(path: string): Promise<Linter.RulesRecord> {
  let rules = rulesCache.get(path);
  if (rules === undefined) {
    eslint ??= new ESLint({ cwd: PKG });
    rules = eslint
      .calculateConfigForFile(path)
      .then((config: { rules: Linter.RulesRecord }) =>
        Object.fromEntries(C216_RULES.map((r) => [r, config.rules[r] ?? "off"])),
      );
    rulesCache.set(path, rules);
  }
  return rules;
}

async function lint(path: string, code: string): Promise<string[]> {
  const linter = new Linter({ configType: "flat" });
  const messages = linter.verify(
    code,
    [
      {
        files: ["**/*.ts"],
        languageOptions: { parser: tseslint.parser },
        rules: await rulesFor(path),
      },
    ],
    path,
  );
  return messages.map((m) => `${m.ruleId ?? "parse"}: ${m.message}`);
}

describe("Scenario: The framework-free boundary is enforced, not just documented", () => {
  const files = ["src/api/chart.ts", "src/index.ts", "src/core/x.ts", "src/layers/x.ts"];

  it.each(files)(
    "%s: importing react fails, naming the import and C-2.16",
    async (path) => {
      const out = await lint(
        path,
        'import { useState } from "react";\nexport const s = useState;\n',
      );
      expect(out).toEqual([
        "no-restricted-imports: 'react' import is restricted from being used. C-2.16: " +
          "packages/chart-engine must not depend on React.",
      ]);
    },
    SLOW,
  );

  it.each([
    ['import { createRoot } from "react-dom/client";', "must not depend on React"],
    ['import { App } from "../../../../apps/web/src/App";', "must never import an app"],
    ['import { App } from "@candleviewer/web";', "must never import an app"],
    ['import { codec } from "./bybitCodec";', "no Bybit/exchange knowledge"],
    ['import { codec } from "../exchange/codec";', "no Bybit/exchange knowledge"],
  ])("%s fails naming C-2.16", async (source, reason) => {
    const out = await lint("src/api/chart.ts", `${source}\nexport const z = 1;\n`);
    expect(out).toHaveLength(1);
    expect(out[0]).toMatch(/^no-restricted-imports: .*C-2\.16/);
    expect(out[0]).toContain(reason);
  });

  it.each([
    ["fetch", 'export const f = () => fetch("/x");'],
    ["XMLHttpRequest", "export const f = () => new XMLHttpRequest();"],
    ["WebSocket", 'export const f = () => new WebSocket("ws://x");'],
  ])("using %s fails naming C-2.16", async (name, code) => {
    const out = await lint("src/core/x.ts", code);
    expect(out).toEqual([expect.stringMatching(new RegExp(`^no-restricted-globals: .*C-2\\.16`))]);
    expect(out[0]).toContain(`'${name}'`);
  });

  it("reaching the network through a global object fails naming C-2.16", async () => {
    const out = await lint("src/layers/x.ts", 'export const f = () => globalThis.fetch("/x");');
    expect(out).toEqual([
      "no-restricted-syntax: C-2.16: packages/chart-engine must not do network I/O " +
        "(fetch/XHR/WebSocket).",
    ]);
  });

  it("a symbol whose name matches /bybit/i fails naming C-2.16", async () => {
    const out = await lint("src/api/pane.ts", "export const toByBitSymbol = (s: string) => s;");
    expect(out).toEqual([
      "no-restricted-syntax: C-2.16: packages/chart-engine must have no Bybit/exchange " +
        "knowledge (symbol name).",
    ]);
  });

  it.each([
    ['export const u = "https://api.bybit.com";'],
    ["export const u = `wss://stream.ByBit.com/${1}`;"],
    ['export const m = () => import("./bybit-codec.js");'],
  ])("a string literal naming Bybit fails naming C-2.16: %s", async (code) => {
    const out = await lint("src/core/x.ts", code);
    expect(out).toEqual([
      "no-restricted-syntax: C-2.16: packages/chart-engine must have no Bybit/exchange " +
        "knowledge (string literal).",
    ]);
  });

  const domProbes: [string, string][] = [
    ["requestAnimationFrame", "export const f = () => requestAnimationFrame(() => undefined);"],
    ["navigator", "export const f = () => navigator.userAgent;"],
    ["localStorage", 'export const f = () => localStorage.getItem("k");'],
    ["sessionStorage", 'export const f = () => sessionStorage.getItem("k");'],
    ["HTMLElement", "export const f = (x: unknown) => x instanceof HTMLElement;"],
    ["matchMedia", 'export const f = () => matchMedia("(x)");'],
    ["ResizeObserver", "export const f = () => new ResizeObserver(() => undefined);"],
  ];

  it.each(["src/core/x.ts", "src/layers/x.ts"])(
    "%s: every browser global fails naming C-2.16, not only document/window",
    async (path) => {
      for (const [name, code] of domProbes) {
        const out = await lint(path, code);
        expect(out, name).toEqual([
          `no-restricted-globals: Unexpected use of '${name}'. C-2.16: no DOM globals in ` +
            "src/core or src/layers (DOM glue is the host adapter's).",
        ]);
      }
    },
    SLOW,
  );

  it("the worker keeps its OffscreenCanvas globals but not the network", async () => {
    expect(await lint("src/worker/x.ts", "export const w = () => self.postMessage(1);")).toEqual(
      [],
    );
    const out = await lint("src/worker/x.ts", 'export const f = () => fetch("/x");');
    expect(out).toEqual([expect.stringContaining("C-2.16")]);
  });

  it("the shipped facade itself lints clean", async () => {
    expect(
      await lint("src/api/x.ts", "export const ok = (c: HTMLElement) => c.ownerDocument;"),
    ).toEqual([]);
  });
});

describe("Scenario: The framework-free boundary is enforced (tsc, no DOM lib in core)", () => {
  const PROBE =
    "export const raf = () => requestAnimationFrame(() => undefined);\n" +
    "export const doc = (e: HTMLElement): Document => e.ownerDocument;\n";

  /** Type-checks PROBE as `rel` under the package's REAL tsconfig file; returns TS2304 names. */
  function compile(tsconfig: string, rel: string): string[] {
    const parsed = ts.getParsedCommandLineOfConfigFile(join(PKG, tsconfig), undefined, {
      ...ts.sys,
      onUnRecoverableConfigFileDiagnostic: (d) => {
        throw new Error(ts.flattenDiagnosticMessageText(d.messageText, "\n"));
      },
    });
    if (parsed === undefined) throw new Error(`${tsconfig} did not parse`);
    const file = join(PKG, rel);
    const host = ts.createCompilerHost(parsed.options);
    const getSourceFile = host.getSourceFile.bind(host);
    host.fileExists = (f) => f === file || ts.sys.fileExists(f);
    host.readFile = (f) => (f === file ? PROBE : ts.sys.readFile(f));
    host.getSourceFile = (f, lang) =>
      f === file ? ts.createSourceFile(f, PROBE, lang) : getSourceFile(f, lang);
    const program = ts.createProgram([file], { ...parsed.options, noEmit: true }, host);
    return ts
      .getPreEmitDiagnostics(program)
      .filter((d) => d.file?.fileName === file)
      .map((d) => ts.flattenDiagnosticMessageText(d.messageText, "\n"));
  }

  it.each(["src/core/probe.ts", "src/layers/probe.ts"])(
    "a DOM type or global in %s fails tsc under tsconfig.core.json",
    (rel) => {
      expect(compile("tsconfig.core.json", rel)).toEqual([
        "Cannot find name 'requestAnimationFrame'.",
        "Cannot find name 'HTMLElement'.",
        "Cannot find name 'Document'.",
      ]);
    },
    SLOW,
  );

  it(
    "only tsconfig.dom.json (src/api, src/host) carries the DOM lib",
    () => {
      expect(compile("tsconfig.dom.json", "src/host/probe.ts")).toEqual([]);
      const read = (name: string): unknown =>
        ts.readConfigFile(join(PKG, name), ts.sys.readFile).config;
      const core = read("tsconfig.core.json") as {
        compilerOptions: { lib?: string[] };
        exclude: string[];
      };
      expect(core.compilerOptions.lib).toBeUndefined(); // inherits the shared node preset: ES2022
      expect(core.exclude).toEqual(expect.arrayContaining(["src/api", "src/host", "src/index.ts"]));
      // The root is solution-style, so editors and the ESLint project service resolve each file
      // to the program that owns it instead of a merged DOM-typed one.
      expect(read("tsconfig.json")).toEqual({
        files: [],
        references: [{ path: "./tsconfig.core.json" }, { path: "./tsconfig.dom.json" }],
      });
    },
    SLOW,
  );

  it(
    "the render worker compiles without the DOM lib; only its main-thread host carries it",
    () => {
      // E11-T02: the worker entry, runtime and protocol stay in the no-DOM program.
      expect(compile("tsconfig.core.json", "src/worker/probe.ts")).toEqual([
        "Cannot find name 'requestAnimationFrame'.",
        "Cannot find name 'HTMLElement'.",
        "Cannot find name 'Document'.",
      ]);
      expect(compile("tsconfig.dom.json", "src/worker/host.ts")).toEqual([]);
      const core = ts.readConfigFile(join(PKG, "tsconfig.core.json"), ts.sys.readFile).config as {
        exclude: string[];
      };
      expect(core.exclude).toContain("src/worker/host.ts");
      expect(core.exclude).not.toContain("src/worker");
    },
    SLOW,
  );

  it(
    "ESLint lints the text it is given (stdin, editors), not the file on disk",
    async () => {
      eslint ??= new ESLint({ cwd: PKG });
      const [core] = await eslint.lintText("export const x = fetch;\n", {
        filePath: join(PKG, "src/core/flags.ts"),
      });
      expect(core?.messages.map((m) => `${m.ruleId ?? "parse"}: ${m.message}`)).toEqual([
        "no-restricted-globals: Unexpected use of 'fetch'. C-2.16: packages/chart-engine must " +
          "not call fetch (no I/O).",
      ]);
      const [api] = await eslint.lintText("export const ok = (c: HTMLElement) => c.id;\n", {
        filePath: join(PKG, "src/api/chart.ts"),
      });
      expect(api?.messages).toEqual([]);
    },
    PROJECT_SERVICE,
  );
});

describe("Scenario: The framework-free boundary is enforced (dependency-cruiser)", () => {
  let tmp = "";
  let result: ICruiseResult;

  const write = (rel: string, body: string): void => {
    mkdirSync(dirname(join(tmp, rel)), { recursive: true });
    writeFileSync(join(tmp, rel), body);
  };

  beforeAll(async () => {
    tmp = mkdtempSync(join(tmpdir(), "cv-c216-"));
    write("packages/chart-engine/src/core/uses-react.ts", 'import "react";\nexport {};\n');
    write("packages/chart-engine/src/api/uses-app.ts", 'import "../../../../apps/web/src/app";\n');
    write("apps/web/src/app.ts", "export const app = 1;\n");
    write("packages/chart-engine/src/api/uses-exchange.ts", 'import "./BybitCodec";\n');
    write("packages/chart-engine/src/api/BybitCodec.ts", "export const c = 1;\n");
    write(
      "packages/chart-engine/src/api/clean.ts",
      'import "./BybitCodec";\n'.replace("Bybit", "Plain"),
    );
    write("packages/chart-engine/src/api/PlainCodec.ts", "export const c = 1;\n");
    const require = createRequire(import.meta.url);
    const config = require(join(REPO, ".dependency-cruiser.js")) as IConfiguration;
    const out = await cruise(
      ["packages"],
      {
        baseDir: tmp,
        validate: true,
        ruleSet: { forbidden: config.forbidden ?? [] },
        tsPreCompilationDeps: true,
        doNotFollow: { path: "node_modules" },
      },
      { extensions: [".ts", ".js"] },
    );
    result = out.output as ICruiseResult;
  });

  afterAll(() => {
    rmSync(tmp, { recursive: true, force: true });
  });

  const violations = (from: string): string[] =>
    result.summary.violations
      .filter((v) => v.from === from)
      .map((v) => `${v.rule.name} -> ${v.to}`)
      .sort();

  it("a react import from packages/chart-engine fails chart-engine-no-react", () => {
    expect(violations("packages/chart-engine/src/core/uses-react.ts")).toContain(
      "chart-engine-no-react -> react",
    );
  });

  it("an apps/* import from packages/chart-engine fails packages-not-to-apps", () => {
    expect(violations("packages/chart-engine/src/api/uses-app.ts")).toEqual([
      "packages-not-to-apps -> apps/web/src/app.ts",
    ]);
  });

  it("an import whose path names Bybit fails chart-engine-no-exchange", () => {
    expect(violations("packages/chart-engine/src/api/uses-exchange.ts")).toEqual([
      "chart-engine-no-exchange -> packages/chart-engine/src/api/BybitCodec.ts",
    ]);
    expect(violations("packages/chart-engine/src/api/clean.ts")).toEqual([]);
  });

  it("each rule cites C-2.16 in its comment", () => {
    const require = createRequire(import.meta.url);
    const config = require(join(REPO, ".dependency-cruiser.js")) as IConfiguration;
    const cited = (config.forbidden ?? [])
      .filter((r) =>
        ["chart-engine-no-react", "chart-engine-no-exchange", "packages-not-to-apps"].includes(
          r.name ?? "",
        ),
      )
      .map((r) => /C-2\.16/.test(r.comment ?? ""));
    expect(cited).toEqual([true, true, true]);
  });
});

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
const C216_RULES = [
  "no-restricted-imports",
  "no-restricted-globals",
  "no-restricted-syntax",
  // E11-X02 (CE-E03): no dynamic code.
  "no-eval",
  "no-implied-eval",
  "no-new-func",
];
// E11-S02: the WebGL2 backend, E11-S03: the shared transform, E11-T05: the Canvas 2D backend and
// E11-S04: the gesture logic, E11-S08: picking (BQ-140) and E11-S11: the SDF atlas (BQ-261) join
// every DOM-free list below.
const GL = [
  "src/gl/probe.ts",
  "src/viewport/probe.ts",
  "src/canvas2d/probe.ts",
  "src/interaction/probe.ts",
  "src/hit/probe.ts",
  "src/text/probe.ts",
];
// Generous per-test budget for the loops, the tsc programs and the project-service lint: they
// pass in ~2 s alone but share the runner with the whole unit project under load (C-9.3).
const SLOW = 20_000;
// Starting the TypeScript project service costs ~6 s alone; allow ten times that under load.
const PROJECT_SERVICE = 60_000;

// One ESLint instance and one resolved rule set per path, shared by every test in this file.
let eslint: ESLint | undefined;
const rulesCache = new Map<string, Promise<Effective>>();

interface Effective {
  readonly rules: Linter.RulesRecord;
  readonly globals: Linter.Globals;
}

/**
 * The effective C-2.16 rules for a file path, and the globals it declares (`no-implied-eval` only
 * sees a timer the file declares), from the package's own eslint.config.mjs.
 */
function rulesFor(path: string): Promise<Effective> {
  const cached = rulesCache.get(path);
  if (cached !== undefined) return cached;
  eslint ??= new ESLint({ cwd: PKG });
  const effective = eslint
    .calculateConfigForFile(path)
    .then((config: Linter.Config): Effective => ({
      rules: Object.fromEntries(C216_RULES.map((r) => [r, config.rules?.[r] ?? "off"])),
      globals: (config.languageOptions?.["globals"] as Linter.Globals | undefined) ?? {},
    }));
  rulesCache.set(path, effective);
  return effective;
}

async function lint(path: string, code: string): Promise<string[]> {
  const linter = new Linter({ configType: "flat" });
  const { rules, globals } = await rulesFor(path);
  const messages = linter.verify(
    code,
    [
      {
        files: ["**/*.ts"],
        languageOptions: { parser: tseslint.parser, globals },
        rules,
      },
    ],
    path,
  );
  return messages.map((m) => `${m.ruleId ?? "parse"}: ${m.message}`);
}

describe("Scenario: The framework-free boundary is enforced, not just documented", () => {
  const files = ["src/api/chart.ts", "src/index.ts", "src/core/x.ts", "src/layers/x.ts", ...GL];

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
    // The dynamic import also fails the E11-X02 code-loader ban (CE-E03); the Bybit report is one.
    const out = (await lint("src/core/x.ts", code)).filter((m) => !m.includes("CE-E03"));
    expect(out).toEqual([
      "no-restricted-syntax: C-2.16: packages/chart-engine must have no Bybit/exchange " +
        "knowledge (string literal).",
    ]);
  });

  const domProbes: [string, string][] = [
    ["requestAnimationFrame", "export const f = () => requestAnimationFrame(() => undefined);"],
    ["navigator", "export const f = () => navigator.userAgent;"],
    ["HTMLElement", "export const f = (x: unknown) => x instanceof HTMLElement;"],
    ["matchMedia", 'export const f = () => matchMedia("(x)");'],
    ["ResizeObserver", "export const f = () => new ResizeObserver(() => undefined);"],
  ];

  it.each(["src/core/x.ts", "src/layers/x.ts", "src/scene/x.ts", "src/model/x.ts", ...GL])(
    "%s: every browser global fails naming C-2.16, not only document/window",
    async (path) => {
      for (const [name, code] of domProbes) {
        const out = await lint(path, code);
        expect(out, name).toEqual([
          `no-restricted-globals: Unexpected use of '${name}'. C-2.16: no DOM globals in ` +
            "src/core|layers|scene|model|gl|canvas2d (DOM glue is the host's).",
        ]);
      }
    },
    SLOW,
  );

  it("a shader source may not interpolate: a static string only (E11-S02 Security)", async () => {
    const path = "src/gl/shaders/line.ts";
    expect(await lint(path, "export const vs = `#version 300 es\nvoid main() {}`;")).toEqual([]);
    expect(await lint(path, "export const fs = (n: string) => `uniform float ${n};`;")).toEqual([
      "no-restricted-syntax: E11-S02: shader sources are static strings; no `${}` interpolation " +
        "(no dynamic GLSL).",
    ]);
    expect(await lint("src/gl/x.ts", "export const s = (n: string) => `${n}`;")).toEqual([]);
  });

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

describe("Scenario: The no-I/O invariant is enforced with its one narrow exception", () => {
  // E11-X02 (CE-E04): every engine directory, the DOM-side host and facade included.
  const everywhere = [
    "src/index.ts",
    "src/api/x.ts",
    "src/host/x.ts",
    "src/core/x.ts",
    "src/model/x.ts",
    "src/worker/x.ts",
    "src/text/x.ts",
    ...GL,
  ];
  // src/text is DOM-free as well (E11-S11, BQ-261): there `self` / `navigator` also meet the DOM ban.
  const notDom = (out: string[]): string[] =>
    out.filter((m) => !/^no-restricted-globals: Unexpected use of '\w+'\. C-2\.16: no DOM/.test(m));
  const storage = (name: string): string =>
    `no-restricted-globals: Unexpected use of '${name}'. C-2.16 / E11-X02 (CE-E04): ` +
    "packages/chart-engine keeps no origin storage (no I/O); IndexedDB is the src/text/ atlas " +
    "cache's alone (E11-S11).";

  it.each(everywhere)(
    "%s: fetch, EventSource, localStorage and sessionStorage fail",
    async (path) => {
      const network: [string, string][] = [
        ["fetch", 'export const f = () => fetch("/x");'],
        ["EventSource", 'export const f = () => new EventSource("/x");'],
      ];
      for (const [name, code] of network) {
        expect(await lint(path, code), name).toEqual([
          expect.stringMatching(
            new RegExp(`^no-restricted-globals: Unexpected use of '${name}'\\. C-2\\.16`),
          ),
        ]);
      }
      for (const name of ["localStorage", "sessionStorage"]) {
        expect(await lint(path, `export const f = () => ${name}.getItem("k");`)).toEqual([
          storage(name),
        ]);
        expect(await lint(path, `export const f = () => globalThis.${name}.getItem("k");`)).toEqual(
          [expect.stringMatching(/^no-restricted-syntax: .*keeps no origin storage/)],
        );
      }
    },
    SLOW,
  );

  it.each(["src/index.ts", "src/api/x.ts", "src/host/x.ts", "src/worker/x.ts", "src/text/x.ts"])(
    "%s: navigator.sendBeacon fails however it is reached",
    async (path) => {
      for (const code of [
        'export const f = () => navigator.sendBeacon("/x");',
        'export const f = () => self.navigator["sendBeacon"]("/x");',
      ]) {
        expect(notDom(await lint(path, code))).toEqual([
          "no-restricted-syntax: C-2.16 / E11-X02 (CE-E04): packages/chart-engine must not send " +
            "a beacon (network I/O).",
        ]);
      }
    },
    SLOW,
  );

  it.each(["src/index.ts", "src/api/x.ts", "src/host/x.ts", "src/worker/x.ts", "src/text/x.ts"])(
    "%s: a bracket key, an alias or a cast of the global object fails (review m3, l10)",
    async (path) => {
      for (const code of [
        'export const f = () => self["fetch"]("/x");',
        'export const f = () => new globalThis["WebSocket"]("ws://x");',
        'export const f = () => self["localStorage"];',
        "export const f = (k: string) => self[k];",
        "const g = self;\nexport const f = () => g;",
        "export const f = () => (globalThis as { fetch: unknown }).fetch;",
        "export const f = () => self.caches;",
        "export const f = () => navigator.storage;",
        "export const f = () => self.navigator.storage;",
      ]) {
        const out = notDom(await lint(path, code));
        expect(out, code).not.toEqual([]);
        expect(
          out.every((m) => m.startsWith("no-restricted-syntax: C-2.16")),
          code,
        ).toBe(true);
      }
      for (const name of [
        "caches",
        "cookieStore",
        "WebTransport",
        "RTCPeerConnection",
        "BroadcastChannel",
      ]) {
        expect(await lint(path, `export const f = () => ${name};`), name).toEqual([
          expect.stringMatching(new RegExp(`^no-restricted-globals: Unexpected use of '${name}'`)),
        ]);
      }
    },
    SLOW,
  );

  it.each(everywhere.filter((p) => !p.startsWith("src/text/")))(
    "%s: IndexedDB fails outside src/text/",
    async (path) => {
      expect(await lint(path, 'export const f = () => indexedDB.open("atlas");')).toEqual([
        storage("indexedDB"),
      ]);
      const idb = expect.stringMatching(
        /^no-restricted-syntax: .*IndexedDB is the src\/text\/ atlas/,
      );
      expect(await lint(path, 'export const f = () => globalThis.indexedDB.open("a");')).toEqual([
        idb,
      ]);
      // `self` is itself a DOM global in the DOM-free directories, so that ban may report it too.
      const viaSelf = await lint(path, 'export const f = () => self.indexedDB.open("atlas");');
      expect(viaSelf).toContainEqual(idb);
      expect(
        viaSelf.filter(
          (m) => !m.startsWith("no-restricted-globals: Unexpected use of 'self'. C-2.16: no DOM"),
        ),
      ).toEqual([idb]);
      // A structural scope (`scope.indexedDB`, `scope["indexedDB"]`) is no way round it either.
      for (const code of [
        'export const f = (s: { indexedDB: { open(n: string): void } }) => s.indexedDB.open("a");',
        'export const f = (s: Record<string, unknown>) => s["indexedDB"];',
      ]) {
        expect(await lint(path, code)).toEqual([idb]);
      }
    },
    SLOW,
  );

  it("IndexedDB is permitted in src/text/ only, for the atlas cache (E11-S11)", async () => {
    for (const path of ["src/text/atlas-cache.ts", "src/text/sdf/store.ts"]) {
      expect(await lint(path, 'export const f = () => indexedDB.open("atlas");')).toEqual([]);
      const viaSelf = 'export const f = () => self.indexedDB.open("atlas");';
      expect(notDom(await lint(path, viaSelf))).toEqual([]);
      const viaScope =
        "export const f = (s: { indexedDB?: { open(n: string): void } }) => s.indexedDB;";
      expect(await lint(path, viaScope)).toEqual([]);
    }
    expect(await lint("src/textual/x.ts", 'export const f = () => indexedDB.open("a");')).toEqual([
      storage("indexedDB"),
    ]);
  });
});

describe("Scenario: The engine runs no dynamic code (CE-E03)", () => {
  const dirs = [
    "src/index.ts",
    "src/api/x.ts",
    "src/host/x.ts",
    "src/core/x.ts",
    "src/worker/x.ts",
  ];
  const probes: [string, string][] = [
    ["no-eval", 'export const f = () => eval("1");'],
    ["no-eval", 'export const f = () => globalThis.eval("1");'],
    ["no-new-func", 'export const f = () => new Function("return 1");'],
    ["no-new-func", 'export const f = () => Function("return 1");'],
    ["no-implied-eval", 'export const f = () => setTimeout("tick()", 10);'],
    ["no-implied-eval", "export const f = (s: string) => setInterval(`${s}()`, 10);"],
  ];

  it.each([...dirs, "src/text/x.ts", ...GL])(
    "%s: eval, the Function constructor and string timers fail",
    async (path) => {
      for (const [rule, code] of probes) {
        const out = await lint(path, code);
        expect(out, code).toHaveLength(1);
        expect(out[0], code).toMatch(new RegExp(`^${rule}: `));
      }
    },
    SLOW,
  );

  it("a timer given a function passes", async () => {
    const code =
      "export const f = (g: () => void) => [setTimeout(g, 10), setInterval(() => g(), 5)];";
    for (const path of dirs) expect(await lint(path, code)).toEqual([]);
  });

  it.each([...dirs, "src/text/x.ts", ...GL])(
    "%s: a code loader fails: import(), importScripts, a Blob or object URL, a Worker (m4)",
    async (path) => {
      for (const code of [
        "export const f = (u: string) => import(u);",
        'export const f = () => importScripts("/x.js");',
        'export const f = () => self.importScripts("/x.js");',
        'export const f = () => new Blob(["1"]);',
        "export const f = (b: Blob) => URL.createObjectURL(b);",
        'export const f = () => new Worker("/w.js");',
        'export const f = () => new SharedWorker("/w.js");',
      ]) {
        const out = await lint(path, code);
        // The DOM-free directories also report `Worker` / `self` as DOM globals; the loader arm
        // is the one no-restricted-syntax report everywhere.
        expect(
          out.filter((m) => m.startsWith("no-restricted-syntax")),
          code,
        ).toEqual([expect.stringMatching(/^no-restricted-syntax: C-2\.16 .*CE-E03/)]);
      }
    },
    SLOW,
  );

  it("src/worker/host.ts alone may create the render worker; nothing else is lifted there", async () => {
    const make = 'export const f = () => new Worker(new URL("./w.js", import.meta.url));';
    expect(await lint("src/worker/host.ts", make)).toEqual([]);
    expect(await lint("src/worker/runtime.ts", make)).toHaveLength(1);
    expect(
      await lint("src/worker/host.ts", "export const f = (u: string) => import(u);"),
    ).toHaveLength(1);
    // The worker entry keeps its one typed alias of its scope, and only that.
    const alias = "export const s = globalThis as unknown as { x: 1 };";
    expect(await lint("src/worker/render-worker.ts", alias)).toEqual([]);
    expect(await lint("src/worker/runtime.ts", alias)).toHaveLength(1);
    expect(
      await lint("src/worker/render-worker.ts", 'export const f = () => self["fetch"];'),
    ).toHaveLength(1);
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

  it.each([...["core", "layers", "scene", "model"].map((d) => `src/${d}/probe.ts`), ...GL])(
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
    write("packages/chart-engine/src/host/mount.ts", "export const m = 1;\n");
    write("packages/chart-engine/src/scene/uses-host.ts", 'import "../host/mount";\n');
    write("packages/chart-engine/src/model/uses-host.ts", 'import "../host/mount";\n');
    write("packages/chart-engine/src/gl/registry.ts", "export const r = 1;\n");
    write("packages/chart-engine/src/scene/uses-gl.ts", 'import "../gl/registry";\n');
    write("packages/chart-engine/src/viewport/uses-gl.ts", 'import "../gl/registry";\n');
    write("packages/chart-engine/src/viewport/uses-host.ts", 'import "../host/mount";\n');
    write("packages/chart-engine/src/interaction/uses-host.ts", 'import "../host/mount";\n');
    write("packages/chart-engine/src/interaction/uses-gl.ts", 'import "../gl/registry";\n');
    write("packages/chart-engine/src/hit/uses-host.ts", 'import "../host/mount";\n');
    write("packages/chart-engine/src/hit/uses-gl.ts", 'import "../gl/registry";\n');
    write("packages/chart-engine/src/gl/uses-worker.ts", 'import "../worker/protocol";\n');
    write("packages/chart-engine/src/worker/protocol.ts", "export const p = 1;\n");
    write("packages/chart-engine/src/canvas2d/backend.ts", "export const b = 1;\n");
    write("packages/chart-engine/src/scene/uses-2d.ts", 'import "../canvas2d/backend";\n');
    write("packages/chart-engine/src/canvas2d/uses-worker.ts", 'import "../worker/protocol";\n');
    // E11-X02: src imports only its own files.
    write("packages/chart-engine/src/core/uses-store.ts", 'import "zustand";\nexport {};\n');
    write("packages/chart-engine/src/api/uses-axios.ts", 'import "axios";\nexport {};\n');
    write("packages/chart-engine/src/worker/uses-http.ts", 'import "node:http";\nexport {};\n');
    write(
      "packages/chart-engine/src/model/uses-protocol.ts",
      'import type { Bar } from "@candleviewer/protocol";\nexport type B = Bar;\n',
    );
    write(
      "packages/chart-engine/src/api/uses-bybit-type.ts",
      'import type { Kline } from "bybit-api";\nexport type K = Kline;\n',
    );
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
      "chart-engine-src-relative-only -> apps/web/src/app.ts",
      "packages-not-to-apps -> apps/web/src/app.ts",
    ]);
  });

  it("an import whose path names Bybit fails chart-engine-no-exchange", () => {
    expect(violations("packages/chart-engine/src/api/uses-exchange.ts")).toEqual([
      "chart-engine-no-exchange -> packages/chart-engine/src/api/BybitCodec.ts",
    ]);
    expect(violations("packages/chart-engine/src/api/clean.ts")).toEqual([]);
  });

  it.each(["scene", "model", "viewport", "interaction", "hit"])(
    "src/%s importing the DOM host adapter fails chart-engine-core-no-dom-host",
    (dir) => {
      expect(violations(`packages/chart-engine/src/${dir}/uses-host.ts`)).toEqual([
        "chart-engine-core-no-dom-host -> packages/chart-engine/src/host/mount.ts",
      ]);
    },
  );

  it.each(["scene", "viewport", "interaction", "hit"])(
    "src/%s importing src/gl fails chart-engine-core-no-gl",
    (dir) => {
      expect(violations(`packages/chart-engine/src/${dir}/uses-gl.ts`)).toEqual([
        "chart-engine-core-no-gl -> packages/chart-engine/src/gl/registry.ts",
      ]);
    },
  );

  it("src/scene importing src/canvas2d fails chart-engine-core-no-gl (E11-T05)", () => {
    expect(violations("packages/chart-engine/src/scene/uses-2d.ts")).toEqual([
      "chart-engine-core-no-gl -> packages/chart-engine/src/canvas2d/backend.ts",
    ]);
  });

  it("src/canvas2d importing the worker glue fails chart-engine-gl-no-host (E11-T05)", () => {
    expect(violations("packages/chart-engine/src/canvas2d/uses-worker.ts")).toEqual([
      "chart-engine-gl-no-host -> packages/chart-engine/src/worker/protocol.ts",
    ]);
  });

  it("src/gl importing the worker glue fails chart-engine-gl-no-host (E11-S02)", () => {
    expect(violations("packages/chart-engine/src/gl/uses-worker.ts")).toEqual([
      "chart-engine-gl-no-host -> packages/chart-engine/src/worker/protocol.ts",
    ]);
  });

  it.each([
    ["core/uses-store", "chart-engine-no-app-state -> zustand"],
    ["api/uses-axios", "chart-engine-no-io-client -> axios"],
    ["model/uses-protocol", "chart-engine-src-relative-only -> @candleviewer/protocol"],
    ["api/uses-bybit-type", "chart-engine-no-exchange -> bybit-api"],
  ])(
    "src/%s fails naming the import and its rule, and the relative-only allowlist (E11-X02)",
    (file, named) => {
      const out = violations(`packages/chart-engine/src/${file}.ts`);
      expect(out).toContain(named);
      expect(out).toContainEqual(expect.stringMatching(/^chart-engine-src-relative-only -> /));
    },
  );

  it("a Node network module fails chart-engine-no-io-client (E11-X02)", () => {
    expect(violations("packages/chart-engine/src/worker/uses-http.ts")).toEqual(
      expect.arrayContaining([
        expect.stringMatching(/^chart-engine-no-io-client -> (node:)?http$/),
        expect.stringMatching(/^chart-engine-src-relative-only -> (node:)?http$/),
      ]),
    );
  });

  it("the E11-X02 rules carry their reason: C-2.16 and the threat-model control", () => {
    const require = createRequire(import.meta.url);
    const config = require(join(REPO, ".dependency-cruiser.js")) as IConfiguration;
    const names = [
      "chart-engine-src-relative-only",
      "chart-engine-no-app-state",
      "chart-engine-no-io-client",
    ];
    const rules = (config.forbidden ?? []).filter((r) => names.includes(r.name ?? ""));
    expect(rules.map((r) => r.name)).toEqual(names);
    for (const r of rules) expect(r.comment).toMatch(/C-2\.16 \/ E11-X02 \(CE-E04/);
  });

  it(
    "the real packages/chart-engine/src passes every chart-engine rule (E11-X02, CI unit-engine)",
    async () => {
      // `pnpm arch` (depcruise) is local-only and the required `architecture` check runs
      // import-linter, so this cruise of the shipped source is what makes CI enforce the
      // boundary. Vacuity guard: the cruise must see the worker and the host modules.
      const require = createRequire(import.meta.url);
      const config = require(join(REPO, ".dependency-cruiser.js")) as IConfiguration;
      const rules = (config.forbidden ?? []).filter(
        (r) =>
          (r.name ?? "").startsWith("chart-engine-") ||
          ["packages-not-to-apps", "not-to-unresolvable"].includes(r.name ?? ""),
      );
      expect(rules.map((r) => r.name)).toContain("chart-engine-src-relative-only");
      const out = await cruise(
        ["packages/chart-engine/src"],
        { ...config.options, baseDir: REPO, validate: true, ruleSet: { forbidden: rules } },
        { extensions: [".ts", ".js"] },
      );
      const real = out.output as ICruiseResult;
      const sources = real.modules.map((m) => m.source);
      expect(sources).toContain("packages/chart-engine/src/worker/protocol.ts");
      expect(sources).toContain("packages/chart-engine/src/worker/host.ts");
      expect(real.summary.violations.map((v) => `${v.from}: ${v.rule.name} -> ${v.to}`)).toEqual(
        [],
      );
    },
    SLOW,
  );

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

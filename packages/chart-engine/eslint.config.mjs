// C-2.16 enforcement: packages/chart-engine must not import React, the DOM,
// `fetch`, or any Bybit/exchange-specific module; E11-X02 adds origin storage,
// `sendBeacon` and dynamic code (eval, Function, string timers). Violations fail lint with a
// message citing C-2.16 (ticket E02-T03 acceptance criterion #2).
import tseslint from "typescript-eslint";
import globals from "globals";
import baseConfig from "@candleviewer/config/eslint";

// C-2.16 / E11-X02 (CE-E04) I/O ban, shared by src/** and the overrides below: no network and no
// origin storage anywhere in the engine. IndexedDB alone is lifted, in src/text/ only (below).
const IO_GLOBALS = [
  { name: "fetch", message: "C-2.16: packages/chart-engine must not call fetch (no I/O)." },
  {
    name: "XMLHttpRequest",
    message: "C-2.16: packages/chart-engine must not use XMLHttpRequest (no I/O).",
  },
  {
    name: "WebSocket",
    message: "C-2.16: packages/chart-engine must not open a WebSocket (no I/O).",
  },
  {
    name: "EventSource",
    message: "C-2.16: packages/chart-engine must not open an EventSource (no I/O).",
  },
  ...["localStorage", "sessionStorage", "indexedDB", "caches", "cookieStore"].map((name) => ({
    name,
    message:
      "C-2.16 / E11-X02 (CE-E04): packages/chart-engine keeps no origin storage (no I/O); " +
      "IndexedDB is the src/text/ atlas cache's alone (E11-S11).",
  })),
  // E11-X02 (CE-E04, review l10): the other channels out of a worker or a page.
  ...["WebTransport", "RTCPeerConnection", "RTCDataChannel", "BroadcastChannel"].map((name) => ({
    name,
    message: `C-2.16 / E11-X02 (CE-E04): packages/chart-engine must not open a ${name} (no I/O).`,
  })),
];
const IO_NAMES = new Set(IO_GLOBALS.map((g) => g.name));
// E11-S11's SDF atlas cache (TM DS1, CE-I07) is the one IndexedDB user: src/text/ only.
const TEXT_IO_GLOBALS = IO_GLOBALS.filter((g) => g.name !== "indexedDB");

// C-2.16 DOM ban for src/core|layers|scene|model|gl|canvas2d: every browser global (`globals.browser`) that is
// neither an ES built-in nor a Node global, plus `navigator`, which Node also defines. The
// package tsconfig.core.json carries no DOM lib either (only tsconfig.dom.json, for src/api and
// src/host, does), so a DOM type there fails `tsc` as well (E11-T01).
const NODE_OR_ES = new Set([...Object.keys(globals.node), ...Object.keys(globals.es2021)]);
const DOM_GLOBALS = [
  ...Object.keys(globals.browser).filter((name) => !NODE_OR_ES.has(name)),
  "navigator",
  "Navigator",
]
  .filter((name) => !IO_NAMES.has(name))
  .map((name) => ({
    name,
    message:
      "C-2.16: no DOM globals in src/core|layers|scene|model|gl|canvas2d (DOM glue is the host's).",
  }));

// The storage globals reached through a global object (`self.indexedDB`, `self["indexedDB"]`), and
// `sendBeacon` however it is reached; `storage` is a regex alternation of the names banned there.
const GLOBAL_OBJ = "[object.name=/^(globalThis|self|window)$/]";
const named = (names) =>
  `:matches([property.name=/^(${names})$/], [property.value=/^(${names})$/])`;
const ioSyntax = (storage) => [
  {
    selector: `MemberExpression${GLOBAL_OBJ}${named(`${storage}|caches|cookieStore`)}`,
    message:
      "C-2.16 / E11-X02 (CE-E04): packages/chart-engine keeps no origin storage (no I/O); " +
      "IndexedDB is the src/text/ atlas cache's alone (E11-S11).",
  },
  {
    selector:
      "MemberExpression[property.name='sendBeacon'], MemberExpression[property.value='sendBeacon']",
    message:
      "C-2.16 / E11-X02 (CE-E04): packages/chart-engine must not send a beacon (network I/O).",
  },
  {
    selector: `MemberExpression[object.property.name='navigator']${named("storage")}, MemberExpression[object.name='navigator']${named("storage")}`,
    message:
      "C-2.16 / E11-X02 (CE-E04): packages/chart-engine keeps no origin storage " +
      "(navigator.storage).",
  },
];

// C-2.16 exchange-knowledge ban on symbol names and string literals (E11-T01), and the network
// globals reached through a global object, which `no-restricted-globals` does not see.
const C216_BASE = [
  {
    selector: "Identifier[name=/bybit/i]",
    message: "C-2.16: packages/chart-engine must have no Bybit/exchange knowledge (symbol name).",
  },
  {
    // Static import/export paths are no-restricted-imports' (one report each); a dynamic
    // `import("…bybit…")` is caught here.
    selector:
      "Literal[value=/bybit/i]:not(ImportDeclaration > Literal, ExportNamedDeclaration > Literal," +
      " ExportAllDeclaration > Literal), TemplateElement[value.raw=/bybit/i]",
    message:
      "C-2.16: packages/chart-engine must have no Bybit/exchange knowledge (string literal).",
  },
  {
    selector:
      `MemberExpression${GLOBAL_OBJ}` +
      named(
        "fetch|XMLHttpRequest|WebSocket|EventSource|WebTransport|RTCPeerConnection|" +
          "RTCDataChannel|BroadcastChannel",
      ),
    message: "C-2.16: packages/chart-engine must not do network I/O (fetch/XHR/WebSocket).",
  },
  {
    // E11-X02 (CE-E04, review m3): a computed key or an alias hides the name from the arms above.
    selector:
      `MemberExpression${GLOBAL_OBJ}[computed=true]:not([property.type='Literal']), ` +
      "VariableDeclarator[init.name=/^(globalThis|self|window)$/], " +
      "TSAsExpression[expression.name=/^(globalThis|self|window)$/]",
    message:
      "C-2.16 / E11-X02 (CE-E04): no computed access to, or alias of, the global object; it " +
      "hides an I/O global from the ban. src/worker/render-worker.ts holds the one typed alias.",
  },
];

// E11-X02 (CE-E03, review m4): no code loader. A dynamic import, importScripts, a Worker made
// outside src/worker/host.ts, or an object URL (with the CSP's `worker-src blob:`) would run
// code the bundle never shipped; no-eval and no-new-func do not see those.
const LOADER_SYNTAX = {
  importExpr: {
    selector: "ImportExpression",
    message: "C-2.16 / E11-X02 (CE-E03): no dynamic import() in packages/chart-engine/src.",
  },
  importScripts: {
    selector:
      "CallExpression[callee.name='importScripts'], CallExpression[callee.property.name=" +
      "'importScripts']",
    message: "C-2.16 / E11-X02 (CE-E03): packages/chart-engine never calls importScripts.",
  },
  objectUrl: {
    selector:
      "MemberExpression[property.name=/^(createObjectURL|revokeObjectURL)$/], " +
      "NewExpression[callee.name='Blob']",
    message:
      "C-2.16 / E11-X02 (CE-E03): no Blob or object URL in packages/chart-engine (a blob: " +
      "worker runs a string as code).",
  },
  worker: {
    selector: "NewExpression[callee.name=/^(Worker|SharedWorker)$/]",
    message:
      "C-2.16 / E11-X02 (CE-E03): the render worker is created in src/worker/host.ts only, " +
      "from its bundled same-origin URL.",
  },
};
const LOADERS = Object.values(LOADER_SYNTAX);
// E11-S11 / E11-X02 (CE-E04): IndexedDB reached through any other object (a structurally typed
// worker or page scope) is still IndexedDB; outside src/text/ that fails as well.
const IDB_VIA_SCOPE = {
  selector:
    `MemberExpression:not(${GLOBAL_OBJ}):matches([property.name='indexedDB'], ` +
    "[property.value='indexedDB'])",
  message:
    "C-2.16 / E11-X02 (CE-E04): packages/chart-engine keeps no origin storage (no I/O); " +
    "IndexedDB is the src/text/ atlas cache's alone (E11-S11), however the scope is typed.",
};
const C216_SYNTAX = [
  ...C216_BASE,
  ...ioSyntax("localStorage|sessionStorage|indexedDB"),
  IDB_VIA_SCOPE,
  ...LOADERS,
];
const TEXT_SYNTAX = [...C216_BASE, ...ioSyntax("localStorage|sessionStorage"), ...LOADERS];

// E11-X02 (CE-E03): no dynamic code. A string handed to eval, Function or a timer is code built
// at run time, which the CSP (no unsafe-eval, C-12.10) would refuse and the engine never needs.
const DYNAMIC_CODE = {
  "no-eval": "error",
  "no-implied-eval": "error",
  "no-new-func": "error",
};

// US-CHART-007 NFR (E11-S03, BQ-77): "projection is a single shared function used by every
// renderer". Arithmetic on `priceLow` / `priceHigh` (binary, compound assignment, ++/--) is a second
// projection anywhere but src/viewport/transform.ts; passing the values through is not.
const PRICE = "/^price(Low|High)$/";
const ON_PRICE = (...keys) =>
  `:matches(${keys.flatMap((k) => [`[${k}.name=${PRICE}]`, `[${k}.property.name=${PRICE}]`])})`;
const PROJECTION_MESSAGE =
  "US-CHART-007: arithmetic on priceLow/priceHigh outside src/viewport/transform.ts is a second " +
  "projection; map prices through the shared transform.";
const PROJECTION_SYNTAX = [
  {
    selector: `BinaryExpression[operator=/^([-+*%]|\\x2F|\\*\\*)$/]${ON_PRICE("left", "right")}`,
    message: PROJECTION_MESSAGE,
  },
  {
    selector: `AssignmentExpression[operator!="="]${ON_PRICE("left", "right")}`,
    message: PROJECTION_MESSAGE,
  },
  { selector: `UpdateExpression${ON_PRICE("argument")}`, message: PROJECTION_MESSAGE },
];

/** @type {import("eslint").Linter.Config[]} */
export default tseslint.config(
  ...baseConfig,
  {
    ignores: ["dist/**", "coverage/**", "bench/results.json", "bench/baseline.json"],
  },
  ...tseslint.configs.recommended,
  {
    files: ["**/*.ts"],
    languageOptions: {
      parserOptions: {
        // The project service lints the text it is given (stdin, editors), not the file on disk.
        // tsconfig.json is solution-style: each file resolves to tsconfig.core.json (no DOM lib)
        // or tsconfig.dom.json (src/index.ts, src/api, src/host, test/api).
        projectService: true,
        tsconfigRootDir: import.meta.dirname,
      },
    },
  },
  {
    files: [
      "bench/run-bench.mjs",
      "bench/scenes/run-scene-a.mjs",
      "bench/scenes/scene-a.mjs",
      "bench/scenes/run-scene-b.mjs",
      "bench/scenes/scene-b.mjs",
      "bench/scenes/run-scene-c.mjs",
      "bench/scenes/scene-c.mjs",
      "bench/scenes/atlas.mjs",
    ],
    languageOptions: {
      globals: { ...globals.node },
    },
  },
  {
    // CE-E03: `no-implied-eval` sees a string timer only through a timer the file declares, and
    // src/ declared none, so `setTimeout("code")` passed. Both runtimes (page, worker) have them.
    files: ["src/**/*.ts"],
    languageOptions: { globals: { setTimeout: "readonly", setInterval: "readonly" } },
  },
  {
    files: ["src/**/*.ts", "bench/**/*.ts"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          paths: [
            {
              name: "react",
              message: "C-2.16: packages/chart-engine must not depend on React.",
            },
            {
              name: "react-dom",
              message: "C-2.16: packages/chart-engine must not depend on React.",
            },
          ],
          patterns: [
            {
              group: ["react/*", "react-dom/*"],
              message: "C-2.16: packages/chart-engine must not depend on React.",
            },
            {
              group: ["**/apps/**", "@candleviewer/web", "@candleviewer/web/*"],
              message: "C-2.16 / C-3.5: packages/chart-engine must never import an app (apps/*).",
            },
            {
              group: ["**/exchange/**", "**/bybit/**"],
              message: "C-2.16: packages/chart-engine must have no Bybit/exchange knowledge.",
            },
            {
              regex: "bybit",
              caseSensitive: false,
              message: "C-2.16: packages/chart-engine must have no Bybit/exchange knowledge.",
            },
            {
              group: ["**/spike/**"],
              message:
                "E06-X02: the promoted benchmark harness must never import from a spike-only " +
                "(throwaway prototype) path. See tools/ci/check_spike_containment.py.",
            },
          ],
        },
      ],
      "no-restricted-globals": [
        "error",
        ...IO_GLOBALS,
        { name: "document", message: "C-2.16: no DOM globals in src/core or src/layers." },
        { name: "window", message: "C-2.16: no DOM globals in src/core or src/layers." },
      ],
      "no-restricted-syntax": ["error", ...C216_SYNTAX, ...PROJECTION_SYNTAX],
      ...DYNAMIC_CODE,
    },
  },
  {
    // E11-X02: the one narrow I/O exception. E11-S11's SDF atlas cache (26 §3.7, TM DS1) may use
    // IndexedDB here and nowhere else; network and the other storage stay banned.
    files: ["src/text/**/*.ts"],
    rules: {
      "no-restricted-globals": [
        "error",
        ...TEXT_IO_GLOBALS,
        { name: "document", message: "C-2.16: no DOM globals in src/core or src/layers." },
        { name: "window", message: "C-2.16: no DOM globals in src/core or src/layers." },
      ],
      "no-restricted-syntax": ["error", ...TEXT_SYNTAX, ...PROJECTION_SYNTAX],
    },
  },
  {
    // E11-S03: the one module allowed to project prices (US-CHART-007).
    files: ["src/viewport/transform.ts"],
    rules: { "no-restricted-syntax": ["error", ...C216_SYNTAX] },
  },
  {
    // The bench harness/runner/driver `.mjs` files are not covered by the
    // `**/*.ts` glob above but are exactly the "promoted harness" this
    // boundary protects (E06-X02 acceptance criterion "The harness does not
    // depend on the prototype").
    files: ["bench/**/*.mjs"],
    rules: {
      "no-restricted-imports": [
        "error",
        {
          patterns: [
            {
              group: ["**/spike/**"],
              message:
                "E06-X02: the promoted benchmark harness must never import from a spike-only " +
                "(throwaway prototype) path. See tools/ci/check_spike_containment.py.",
            },
          ],
        },
      ],
    },
  },
  {
    // E06-T01 cross-runtime matrix (spike-only harness): the runner/compare/manifest code
    // is Node; page/ and scenes/ run inside Chromium/Electron/WebView2 (browser + worker);
    // the Electron shell files are CommonJS by necessity (sandboxed preload).
    files: ["bench/machine.mjs", "bench/matrix/**/*.mjs", "bench/matrix/**/*.cjs"],
    languageOptions: {
      globals: { ...globals.node, ...globals.browser, ...globals.worker },
    },
  },
  {
    files: ["bench/matrix/**/*.cjs"],
    rules: { "@typescript-eslint/no-require-imports": "off" },
  },
  {
    // C-2.16: core, layers and the scene graph touch no DOM at all, not just `document` /
    // `window` (E11-T01, E11-S01, E11-T03: requestAnimationFrame is bound in the worker or host only).
    // E11-S02: the WebGL2 backend (src/gl) too; its GL type is the hand-written GL2Like.
    // E11-S03: and the shared transform (src/viewport). E11-T05: and the Canvas 2D backend
    // (src/canvas2d), whose context type is the hand-written Ctx2DLike (no Path2D, BQ-84).
    // E11-S04: and the gesture, velocity and momentum logic (src/interaction, BQ-98).
    // E11-S08: and picking (src/hit, BQ-140). E11-S11: and the SDF atlas (src/text, BQ-261), whose
    // font, raster and store needs reach the browser only through the TextPlatform seam.
    files: ["src/{core,layers,scene,model,gl,viewport,canvas2d,interaction,hit}/**/*.ts"],
    rules: {
      "no-restricted-globals": ["error", ...IO_GLOBALS, ...DOM_GLOBALS],
    },
  },
  {
    // The same DOM ban for src/text, which keeps its one IndexedDB exception (E11-X02, TM DS1):
    // this block comes after the src/text/** override, so it must carry TEXT_IO_GLOBALS itself.
    files: ["src/text/**/*.ts"],
    rules: {
      "no-restricted-globals": ["error", ...TEXT_IO_GLOBALS, ...DOM_GLOBALS],
    },
  },
  {
    // E11-S02 Security: shader sources are static, bundled strings. An interpolated template
    // literal could carry market-feed data into GLSL (code injection), so none is allowed here.
    files: ["src/gl/shaders/**/*.ts"],
    rules: {
      "no-restricted-syntax": [
        "error",
        ...C216_SYNTAX,
        ...PROJECTION_SYNTAX,
        {
          selector: "TemplateLiteral[expressions.length>0]",
          message:
            "E11-S02: shader sources are static strings; no `${}` interpolation (no dynamic GLSL).",
        },
      ],
    },
  },
  {
    // E14-X03 (#549; DR6, SR-E14-01): no inline comment lifts a rule in the drawing layer, C-2.16's
    // DOM ban among them. tools/ci/no-inline-suppression-paths.json lists the same path.
    files: ["src/layers/drawings/**/*.{ts,mts,cts}"],
    linterOptions: { noInlineConfig: true },
  },
  {
    files: ["src/worker/**/*.ts"],
    rules: {
      // The worker glue is the one place OffscreenCanvas/postMessage globals
      // are expected; core/layers stay DOM-free (C-2.16). The network ban still holds here.
      "no-restricted-globals": ["error", ...IO_GLOBALS],
    },
  },
  {
    // E11-X02 (CE-E03): the one site that creates the render worker (from its bundled URL).
    files: ["src/worker/host.ts"],
    rules: {
      "no-restricted-syntax": [
        "error",
        ...C216_SYNTAX.filter((s) => s !== LOADER_SYNTAX.worker),
        ...PROJECTION_SYNTAX,
      ],
    },
  },
  {
    // E11-X02 (CE-E04): the worker entry's one typed alias of its global scope.
    files: ["src/worker/render-worker.ts"],
    rules: {
      "no-restricted-syntax": [
        "error",
        ...C216_SYNTAX.filter((s) => s !== C216_BASE[3]),
        ...PROJECTION_SYNTAX,
      ],
    },
  },
  {
    // E11-X02 (review l11): no inline comment lifts a rule anywhere in the engine source, so the
    // I/O, loader and dynamic-code bans cannot be silenced next to the code they guard. (The
    // repo-wide suppression check, tools/ci/no-inline-suppression-paths.json, stays the drawing
    // paths: it must equal cv-drawings-text-to-html-sink's paths.)
    files: ["src/**/*.{ts,mts,cts}"],
    linterOptions: { noInlineConfig: true, reportUnusedDisableDirectives: "error" },
  },
);

# @candleviewer/ui

Design system: tokens, primitives, trading components. Storybook 8 with the
a11y addon; Style Dictionary token build. Depends only on
`@candleviewer/protocol` and `@candleviewer/chart-engine` — never on `apps/*`
(C-3.5).

- `tokens/` — DTCG source JSON (contract from E02-D01, content from E05-D01),
  verified by `tokens/tests/verify_tokens.py`.
- `src/tokens/`, `src/primitives/`, `src/components/` — TS/React surface.
- `scripts/build-tokens.mjs` — the token build entry point (E05-T01).
- `build/` — generated artefacts, **gitignored, never committed**. CI
  regenerates them on every run (`pnpm --filter @candleviewer/ui build:tokens`)
  and the `generated-code` required check fails the PR if `tokens/*.tokens.json`
  changed without a matching build (staleness is caught by re-running the
  build and diffing against a checked-in reference, not by committing the
  output — see "Build output policy" below).

Architectural record: [`docs/plan/27-adrs/ADR-0024-design-token-architecture-and-theming.md`](../../docs/plan/27-adrs/ADR-0024-design-token-architecture-and-theming.md)
records the tier model, theming/density decisions and the WebGL/Electron delivery
formats below, plus the alternatives rejected (CSS-in-JS runtime theming,
Tailwind-config-as-source, two parallel density scales, naive dark→light inversion).

## Token build (E05-T01)

One `pnpm --filter @candleviewer/ui build:tokens` run produces six artefacts
from `docs/plan/16-design-system-brief.md#11`:

| Artefact                             | Format                                           | Consumer                 |
| ------------------------------------ | ------------------------------------------------ | ------------------------ |
| `build/css/tokens.dark.css`          | `[data-theme="dark"]` custom properties          | React app                |
| `build/css/tokens.light.css`         | `[data-theme="light"]` custom properties         | React app                |
| `build/css/tokens.high-contrast.css` | `[data-theme="high-contrast"]` custom properties | React app                |
| `build/ts/tokens.ts`                 | typed nested `const tokens = {...} as const`     | React, Storybook         |
| `build/engine/theme-uniforms.json`   | flat `{ hex, rgba }` per chart-category token    | WebGL chart engine (E11) |
| `build/electron/tokens.main.json`    | flat key→value JSON, no CSS/TS syntax            | Electron main process    |

Custom Style Dictionary formats (`json/flat-rgba`, `json/flat`,
`typescript/nested-object`) live in `tools/style-dictionary/formats/` with
their own Vitest unit tests in `packages/ui/test/tokens-build/` (run as part
of `pnpm --filter @candleviewer/ui test`).

**Engine colour contract**: every `theme-uniforms.json` entry is `{ hex,
rgba }`, where `rgba` is **sRGB 0..1** floats (not linear — conversion to
linear happens in the shader, per the brief §11.1 so E11 never guesses).

**Determinism**: no timestamps in output headers; every object/array is
name-sorted before serialisation; `style-dictionary` is pinned in the
lockfile. Two consecutive builds are byte-identical (asserted by
`packages/ui/test/tokens-build/build-integration.test.ts`).

**Error codes** (thrown by `scripts/build-tokens.mjs`, caught by CI):

- `TOKENS-E001 missing-theme-parity` — a token defined in one theme but
  absent from another; the error names the token.
- `TOKENS-E002 unresolved alias reference` — a `{token.path}` that never
  resolves to a primitive (dangling or circular).
- `TOKENS-E003 unknown category for the engine filter` — a
  `color.chart.*`/`color.candle.*`/etc. token whose resolved value isn't a
  hex colour string.

**Build output policy**: `build/` is gitignored. The build must be
deterministic and fast enough (`<=10s` locally) to run on every `pnpm dev`
start, so nothing is checked in — CI's `generated-code` check re-runs the
build and fails if `packages/ui/tokens/**` changed without the corresponding
consumer types/tests being updated in the same PR (there is no stale
committed artefact to diff against, by design).

**Raw-value lint**: `packages/ui/src/**` may not hardcode a hex colour or a
raw `px` length — use a token from `build/ts/tokens.ts` instead
(`eslint.config.mjs`'s `candleviewer/no-raw-design-values` rule; the token
source files themselves are exempt).

## Theme runtime (E05-T02)

`src/theme/` owns the `data-theme`, `data-density`, `data-motion` and `data-text-scale` root attributes
(the token CSS and `theme.css` key off the first three). They are written on `document.documentElement` only
(never a React-owned wrapper), so a switch is a CSS custom-property swap with no remount. Contract and
event payload: [`16-design-system-brief.md` §4](../../docs/plan/16-design-system-brief.md).

- `createThemeStore()` — framework-free store: persistence (`localStorage["cv.theme.v1"]`), OS media
  listeners, the `candleviewer:themechange` event, an injectable analytics sink (`onAnalytics`).
- `ThemeProvider`, `useTheme`, `useDensity`, `useReducedMotion`, `useTextScale` — React bindings over
  `useSyncExternalStore`: only components that read a value re-render when it changes.
- `THEME_PREPAINT_SCRIPT` + `THEME_PREPAINT_SCRIPT_SHA256` — the synchronous no-flash snippet. The shell
  embeds it byte-for-byte as its only inline script and allows it by hash (a `'sha256-…'` source in
  `script-src`), never `'unsafe-inline'`.
- `HIGH_CONTRAST_SHORTCUT` (`Ctrl+Shift+H`) and `toggleHighContrastAnnounced` — the shortcut contract the
  E10 hotkey registry calls; each toggle is announced through one polite live region that the provider
  pre-renders (bootstraps without the provider, like the E10 registry, call `mountLiveRegion()` at startup).
- `theme.css` — density pointers, the `--cv-motion-scale` hook (the motion recipes are `TODO(#3174)`) and
  the `[data-motion="reduce"]` / `prefers-reduced-motion` blocks. Import it next to the token CSS.
- Storybook: run `build:tokens` first; the Theme / Density / Motion toolbars drive the runtime.
- Apps feed server-side preferences in through `store.apply(...)`; `applyAppearance` and the
  `a11y-preferences` feature should call it rather than write the attributes themselves.

## Scripts

- `pnpm --filter @candleviewer/ui build` — runs `build:tokens` (Style
  Dictionary-driven, see above) then the tsup build.
- `pnpm --filter @candleviewer/ui build:tokens` — token build only.
- `pnpm --filter @candleviewer/ui storybook` — dev server with the a11y addon.
- `pnpm --filter @candleviewer/ui test` / `test:cov` — Vitest, ≥80% gate.

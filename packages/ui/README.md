# @candleviewer/ui

Design system: tokens, primitives, trading components. Storybook 10 with the
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
that the token CSS and `src/theme/theme.css` key off. They are written on `document.documentElement` only
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
  E10 hotkey registry calls (it must ignore key auto-repeat: `ignoreRepeat`, the `repeat` option); each
  toggle is announced through one polite live region that the provider pre-renders (bootstraps without
  the provider, like the E10 registry, call `mountLiveRegion()` at startup).
- `theme.css` — density pointers (any element with `data-density` re-points its subtree), the text-scale
  rules (root font size and `--cv-text-scale`), the `--cv-motion-scale` hook (the motion recipes are
  `TODO(#3174, blocked by #162)`) and the `[data-motion="reduce"]` / `prefers-reduced-motion` blocks.
  Apps import the token CSS and then `theme.css` through the package exports:
  `import "@candleviewer/ui/tokens.dark.css"` (likewise `tokens.light.css` and `tokens.high-contrast.css`),
  then `import "@candleviewer/ui/theme.css"`. They are built files in `dist/`, so a build comes first:
  `pnpm --filter @candleviewer/ui build`, or `node scripts/build-tokens.mjs && node scripts/copy-css.mjs`
  in `packages/ui` (the copy fails when a token CSS file is missing; the `apps/web` resolve test runs both
  itself when `dist/` lacks them). A bundler alias for `@candleviewer/ui` must match the entry exactly
  (`/^@candleviewer\/ui$/`); a prefix alias turns these subpaths into `src/index.ts/theme.css`.
- Storybook: run `build:tokens` first; the Theme / Density / Motion toolbars drive the runtime.
- Apps feed server-side preferences in through `store.apply(...)`; `applyAppearance` and the
  `a11y-preferences` feature should call it rather than write the attributes themselves.
- Store details: `sharedThemeStore()` returns one store per root element, so every provider, story and
  bootstrap on a page agrees; without a DOM the store is inert (state and subscriptions only);
  `apply(patch, { persist: false, track: false })` is the hydration form, and an invalid value keeps the
  current preference of that field.
- Tests: a `ThemeProvider` without a `store` prop (or a `root` option) uses the shared store of
  `document.documentElement`, which outlives a single test. Call `resetSharedThemeStores()` in `afterEach`,
  or pass a fresh `root`, so tests do not leak preferences into each other.

## Storybook (E05-T03)

- Run: `build:tokens`, then `storybook` (dev server on 127.0.0.1:6006) or `storybook:build`. The
  preview imports the generated token bundles the app imports. Storybook 10 needs Node 20.19+ or
  22.12+.
- Test: `storybook:test` runs the `storybook` Vitest project (`@storybook/addon-vitest`) in headless
  Chromium (once: `pnpm --filter @candleviewer/ui exec playwright install chromium`): each story's
  play function, then axe. A serious or critical violation fails the story, naming the rule and the
  element; moderate and minor are reported only. Stories tagged `perf` are skipped unless
  `CV_STORYBOOK_PERF=1` (a quiet machine).
- Self-test: `CV_STORYBOOK_A11Y_FIXTURES=1 pnpm --filter @candleviewer/ui storybook:test` runs the
  gate on `.storybook/__fixtures__/` alone (never built or published otherwise): it must fail the
  2:1-contrast button naming `color-contrast` and `#a11y-gate-fixture`. CI's `storybook` job
  (`_job-a11y.yml`, the required `a11y` check) checks that, runs `storybook:test`, logs the story
  count and the axe violations by impact, and uploads the a11y report; codes `CI-A11Y-002..004`.
- Organisation: titles sit under a catalogue band (`Atoms/` .. `ChartEngine/`, see catalogue
  §0.3 rule 8) or `Foundations/`; the `candleviewer/story-title-bands` lint rule fails any other.
  The Theme, Density and Motion toolbars drive the E05-T02 runtime; decorators paint the canvas with
  `surface.app` (on a docs page, a wrapper around each inline story) and count story mounts
  (`<output aria-label="Mount count" hidden>`).
- Hosting: internal only, never an internet-reachable host (Pages, a public bucket, a preview
  service). Publishing the static build to the Tailscale-only internal host is not yet scheduled:
  it is the E05 threat model's accepted A4 residual (E05-X01, #215; its §5 and §6).

## Icons (E05-T06)

`src/icons/` is the icon registry of [`16-design-system-brief.md` §5](../../docs/plan/16-design-system-brief.md):

- `registry.ts`: each icon's canonical name (the `IconName` union), group, glyph source and
  one-sentence meaning, sorted by name. It is the code twin of the Penpot icon page; the two compare
  by diff.
- `source/<origin>/<name>.svg`: the vetted glyphs. `lucide/` holds glyphs vendored verbatim from
  `lucide-static` (ISC, with the MIT notice for its Feather-derived glyphs: `source/lucide/LICENSE`;
  version and owner in the vendored-code register,
  [`35-dependency-freeze-policy.md` §7](../../docs/plan/35-dependency-freeze-policy.md)), each
  renamed to its registry name. `custom/` receives the trading glyphs that E05-D02 draws.
- `generated/`: one component per icon (`CloseIcon`), plus `index.ts` and `components.ts`
  (`ICON_COMPONENTS`, every icon by name, for CMP-019 Icon and Storybook only: it bundles the whole
  set). `node scripts/build-icons.mjs` writes them (`--check` reports drift); never edit them, as
  `test/icons/generator.test.ts` compares them byte for byte with their sources. The generator reads
  a source as data, never markup: it accepts only a 24x24 outline root and plain geometry (path,
  circle, ellipse, line, polyline, polygon, rect), and fails on anything else, naming the file.
- `IconSvg.tsx`: the grid each icon draws in, which no prop can change: the 24-unit `viewBox`,
  `currentColor` (an icon takes its context's semantic colour), a 1.5px stroke at every size
  (`vector-effect: non-scaling-stroke`) and the optical `size`: `sm`, `md` or `lg` reads
  `--size-icon-sm|md|lg`, and no size reads the semantic `--size-icon`. Those tokens ship as 12, 16
  and 20px (`--size-icon` is md's 16px), where brief §5 says 16/20/24px: that is an open decision
  for the owner and E05-D01, and the icons follow the tokens either way. An icon is decorative
  (`aria-hidden`) unless named with a non-blank `aria-label` or `aria-labelledby`, which makes it
  `role="img"`. Both resolve after the forwarded props, so a wrapper's `undefined` cannot undo
  them: an unnamed icon is always hidden.

Use an icon by importing the component an element draws: `import { CloseIcon } from
"@candleviewer/ui"`. Each icon is its own module, so a bundle carries only the icons it imports
(`test/icons/tree-shaking.test.ts`). An icon beside visible text stays decorative; an icon-only
control carries its own `aria-label`. Lint binds this (`eslint.config.mjs`):

- `candleviewer/no-raw-svg`: a raw `<svg>` or an SVG data URL anywhere but the grid,
  `src/icons/IconSvg.tsx`, fails, naming the file; `react/no-danger` fails markup strings (SR-127),
  and `test/eslint-rules/no-raw-svg.test.ts` checks the MDX docs pages, which ESLint does not read.
- `no-restricted-imports`: only the generated modules import the grid's `IconSvg`, so no geometry
  reaches a page without passing the generator and the tests; its types and sizes stay open.
  `test/icons/registry.test.ts` also reads `import()` calls and the MDX pages.
- `candleviewer/icon-only-control-label`: a control whose only content is icons needs an
  `aria-label` (or `aria-labelledby`; for IconButton, its `label`). Icons in text-free wrappers
  (`<span>`) or in conditionals (`{open ? <ChevronUpIcon /> : <ChevronDownIcon />}`) count as
  icons; content the source does not show (a component, a computed value, spread props) is
  trusted.
- `candleviewer/icon-beside-text-hidden`: an icon beside visible text must stay `aria-hidden`. In
  a control, any other content counts as its text, a computed `{label}` included.

The Storybook a11y gate runs `Foundations/Icons`. Its `SizeScale` story measures every icon at each
optical size in the browser: the token's extent, a 1.5px stroke, and geometry inside the live area,
2 to 22 of the 24-unit box on both axes (the base set's own extent). Its fixture
`.storybook/__fixtures__/IconOnlyButton.stories.tsx` fails axe's `button-name` on purpose.

To add an icon:

1. Put its SVG at `src/icons/source/<origin>/<name>.svg`, with a kebab-case name. A Lucide glyph is
   copied verbatim from the vendored `lucide-static` version: download that version's tarball,
   check its sha512 against the register row (`35-dependency-freeze-policy.md` §7), then copy
   `package/icons/<glyph>.svg`. A custom glyph comes from its design ticket's Penpot export,
   prepared for the grid:
   - a `viewBox="0 0 24 24"` root with `fill="none"` and `stroke="currentColor"`;
   - outline geometry only (path, circle, ellipse, line, polyline, polygon, rect): no fill, group,
     transform, clip path, colour, style or text, so flatten them in the export. A dot is a
     zero-length, round-capped path, as in Lucide;
   - geometry inside the live area, 2 to 22 on both axes.

   The generator rejects anything else, naming the file.

2. Add its entry to `registry.ts`, in name order: `category`, `source` (`lucide/<glyph>` or
   `custom/<ticket>`) and a one-sentence `description`.
3. In `packages/ui`, run `node scripts/build-icons.mjs`, then `test`: it writes the new icon's
   snapshots, which are reviewed and committed with it. GitHub collapses the snapshot file
   (`linguist-generated`): expand it in review, as it shows each glyph renders as geometry only.
4. Update the Penpot icon page and the list in `16-design-system-brief.md` §5. A new `lucide-static`
   version also updates the vendored-code register.

## Scripts

- `pnpm --filter @candleviewer/ui build` — runs `build:tokens` (Style
  Dictionary-driven, see above) then the tsup build.
- `pnpm --filter @candleviewer/ui build:tokens` — token build only.
- `pnpm --filter @candleviewer/ui storybook` — dev server with the a11y addon.
- `pnpm --filter @candleviewer/ui storybook:build` / `storybook:test` — static build / its Vitest project.
- `pnpm --filter @candleviewer/ui test` / `test:cov` — the Vitest unit project, ≥80% gate.

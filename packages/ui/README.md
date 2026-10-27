# @candleviewer/ui

Design system: tokens, primitives, trading components. Storybook 10 with the
a11y addon; Style Dictionary token build. Depends only on
`@candleviewer/protocol` and `@candleviewer/chart-engine` — never on `apps/*`
(C-3.5).

- `tokens/` — DTCG source JSON (contract from E02-D01, content from E05-D01),
  verified by `tokens/tests/verify_tokens.py`.
- `src/tokens/`, `src/primitives/`, `src/components/` — TS/React surface.
- `scripts/build-tokens.mjs` — the token build entry point (E05-T01).
- `scripts/token-css.mjs` — how a token becomes CSS (a shadow as a `box-shadow` list, a typography
  token as one custom property per field) and the esbuild check of each written CSS file (#3422).
- `build/` — generated artefacts, **gitignored, never committed**. CI
  regenerates them on every run: the `js` lane's `build` job builds this
  package (which runs `pnpm --filter @candleviewer/ui build:tokens`) and then
  `contrast:gate`, and the unit lane's `test/tokens-build/*` tests run the real
  build and pin its artefacts (see "Build output policy" below).

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
- `TOKENS-E004 invalid CSS output` — a token that `scripts/token-css.mjs` cannot write (an
  unknown or missing shadow or typography field, a length or `inset` with no CSS form, an object of
  any other type) or will not let the browser misread (a name with a character other than a letter,
  a digit, `_`, `-` or `.`; a value with `;`, a brace, a comment delimiter, a control character, a
  trailing backslash, a `!` or brackets that do not pair up), or a theme's CSS that esbuild, the
  production minifier, warns about or minifies to an empty custom property, checked before
  `build/css/tokens.<theme>.css` is written; the error names the token or the custom property.

**Build output policy**: `build/` is gitignored. The build must be
deterministic and fast enough (`<=10s` locally) to run on every `pnpm dev`
start, so nothing is checked in and there is no stale committed artefact to
diff against, by design. The guards over a token change are the ones
`docs/plan/16-design-system-brief.md` §11 lists: the `js` lane's `build` job
(package build, then `contrast:gate`), the a11y lane's second `contrast:gate`
run before Storybook, and the unit lane's `test/tokens-build/*` tests, which
run the real build and pin a resolved value. The generated-code freshness gate
(`tools/ci/check_gen_freshness.py`) covers the protocol, CVWB and policy
generators, not these tokens.

**Raw-value lint**: `packages/ui/src/**` may not hardcode a hex colour or a
raw `px` length — use a token from `build/ts/tokens.ts` instead
(`eslint.config.mjs`'s `candleviewer/no-raw-design-values` rule; the token
source files themselves are exempt).

## Changing a token (contributing)

Every token change, in either direction, follows the runbook in
[`docs/plan/16-design-system-brief.md` §11](../../docs/plan/16-design-system-brief.md#11-handoff-spec-tokens-json--code-via-style-dictionary)
(E05-D06): §11.2 design → code (Penpot token sets → `tokens/*.tokens.json` → PR → gates →
`tokens/CHANGELOG.md` version bump), §11.3 code → design (a token an engineer discovers during
implementation, and how it is re-imported into Penpot), §11.4 the per-component handoff
checklist, §11.5 change control and arbitration, §11.6 secrets. The short form for an engineer:

1. Edit `tokens/primitives.tokens.json` (a value) or `tokens/semantic-dark.tokens.json` (a new
   alias, `category.subcategory.variant.state`, leaf `.default` when the path has children). A new
   name needs no light/high-contrast line unless those themes want a different value
   (`TOKENS-E001` names a missing one).
2. A new `color.*` token needs a pair in `tools/contrast/pairs.mjs` or an exemption with `reason`
   and `owner` in `tools/contrast/exemptions.json` (`A11Y-C002` otherwise); a new directional or
   status encoding needs its surfaces in `tools/contrast/encodings.json` (`A11Y-C008`).
3. Run `pnpm --filter @candleviewer/ui build:tokens`, then
   `pnpm --filter @candleviewer/ui contrast:gate`. On `A11Y-C007` run
   `pnpm --filter @candleviewer/ui contrast:data-ink` and commit `contrast/data-ink-matrix.{json,md}`.
   Then `python3 tokens/tests/verify_tokens.py` and `pnpm --filter @candleviewer/ui test`: a value
   pinned in `test/tokens-build/build-integration.test.ts` moves with the token, never the reverse.
4. Add a `## [x.y.z] - <date>` entry to `tokens/CHANGELOG.md` (pre-1.0, C-15.5: PATCH = retune or
   new name, MINOR = rename or removal, with `!` and a `BREAKING CHANGE:` footer; MAJOR only from
   1.0.0), commit `feat(design-system): …` and open the PR with the contrast report and the Penpot
   page link (§11.2 steps 7–9). CI adds `security-review` by itself (the token file names match
   C-10.2's `*token*`): leave it on; the second review is the `security-reviewer` (§11.2 step 11).
5. Never commit `build/`, never add to `tools/contrast/data-ink-baseline.json`, never lower a
   threshold, and never put a credential in a token file (§11.6).

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

`src/icons/` is the icon set of [`16-design-system-brief.md` §5](../../docs/plan/16-design-system-brief.md).
Code draws a glyph by name with CMP-019 `<Icon name size decorative label>`, never by raw SVG. The
registry holds 61 glyphs, each listed in §5: the base set's 48, vendored from Lucide (ISC), and the
13 trading glyphs CandleViewer draws from E05-D02 §7.12.

- `registry.ts`: each icon's canonical name (the `IconName` union), group, glyph source and
  one-sentence meaning, sorted by name: the code twin of the Penpot icon page, compared by diff.
  `minimumPx: 16` marks the six glyphs E05-D02 §7.12 calls "16 px minimum", whose detail closes
  up at 12 px, so they never draw at `sm`; the types hold that, not the runtime. `Icon` is
  generic in its name, and `IconProps<N>`'s `size` drops `sm` for a marked name: neither
  `<Icon name="twap" size="sm" />` nor a CMP-002 `IconButton` with `icon="twap"` and `size="sm"`
  type-checks. A name the call site leaves open, the whole `IconName` union as in a map over the
  registry, keeps all three sizes.
- `source/<origin>/<name>.svg`: the vetted glyphs, committed data (nothing is fetched at
  runtime). `lucide/` holds glyphs vendored byte for byte from `lucide-static`, each renamed to
  its registry name, beside their licence, `source/lucide/LICENSE` (ISC, plus the MIT notice of
  the Feather-derived glyphs); the version, its checksum and the owner are in the vendored-code
  register, [`35-dependency-freeze-policy.md` §7](../../docs/plan/35-dependency-freeze-policy.md).
- `source/custom/`: the 13 trading glyphs of E05-D02 §7.12, CandleViewer's own, so a custom
  source carries no `@license` line (the generator fails on one). Each draws its §7.12 motif as
  an outline on a root with the grid's stroke (1.5, round caps and joins), with no dash, fill or
  transform, its paths in absolute `M`, `L`, `H`, `V`, `C`, `A` and `Z` only (each arc circular
  and unrotated), so `test/icons/glyphs.test.ts` reads every point. Every point, Bezier control
  points and arc bulges included, stays in [1.75, 22.25]: the 1-unit clear margin plus half the
  stroke.
- `<name>.sm.svg` beside a source is its reduced form (E05-D02 §6 J24): a second drawing of the
  name, never a name of its own, that `Icon` draws at `size="sm"` in place of the 24-unit master.
  The generator gives it a module and an entry in `ICON_FORMS`, internal like the rest of
  `generated/`. One glyph has one, `estimated`, whose 12 px form §7.12 left #271 to choose once:
  a solid ring or the "≈" alone. It is the "≈" alone, drawn larger. At 12 px the master's dashed
  ring resolves to dots; a solid ring would drop the dash that marks the value as inferred and
  read as a plain circle; and a ring with the "≈" inside closes up. The reduced forms and the
  `minimumPx` guard are both keyed to the `sm` token, 12 px as shipped: if slice 1 A10
  (16 / 20 / 24 px) is approved, re-key them to the 12 px size.
- `generated/`: one component per icon, and `components.ts`, the map by name that `Icon` draws
  from. Both are internal: the package exports `Icon`, the registry and the sizes, never a glyph
  component. `scripts/build-icons.mjs` (`build:icons`) writes them from the sources, in name
  order and with no timestamp; `build` runs it with `--check`, which fails naming each stale,
  missing or extra module. Never edit one: `test/icons/generator.test.ts`, the drift check,
  compares each byte for byte with the generator's rendering. The generator reads a source as
  data, never markup: it accepts only a 24x24 outline root and plain geometry (path, circle,
  ellipse, line, polyline, polygon, rect), and fails on anything else, naming the file. A Lucide
  glyph's module repeats its source's `@license lucide-static v<version> - ISC` line as a legal
  comment (`/*! ... */`) above the component, which tsup keeps in `dist` and Vite in the app's
  bundle; a Lucide source without that line fails.
- `IconSvg.tsx`: the grid every module draws its geometry in, which no prop changes: the
  24-unit `viewBox`, `currentColor`, no fill, and a non-scaling 1.5px stroke at every size.
- Lint (`eslint.config.mjs`): `candleviewer/no-raw-svg` fails a raw `<svg>` in any file of the
  package outside `src/icons/`, the registry. On `src/**`, stories included,
  `candleviewer/icon-label-required`, `candleviewer/icon-only-control-label` and
  `candleviewer/icon-beside-text-hidden` (CMP-019's ids) enforce decorative vs meaningful. Tests
  are exempt from those three: they write unnamed cases on purpose to pin the types.
- Cost: `Icon` imports every glyph by name, so an app pays for the whole registry, never per
  screen. `test/icons/registry-cost.test.ts` bundles `src/icons/index.ts` with tsup as a production
  build would (minified ESM, React external) and holds it to E05-T06's bound, 15 KB gzipped.

To add an icon, put its SVG at `src/icons/source/<origin>/<name>.svg` (a Lucide glyph is copied
verbatim from the registered `lucide-static` tarball, once its sha512 matches the register row),
add its `registry.ts` entry in name order, then run `build:icons` and `test` in `packages/ui`.

## Scripts

- `pnpm --filter @candleviewer/ui build` — runs `build:tokens` (Style
  Dictionary-driven, see above), `build:icons --check`, then the tsup build.
- `pnpm --filter @candleviewer/ui build:tokens` — token build only.
- `pnpm --filter @candleviewer/ui build:icons` — writes `src/icons/generated/` (see "Icons").
- `pnpm --filter @candleviewer/ui storybook` — dev server with the a11y addon.
- `pnpm --filter @candleviewer/ui storybook:build` / `storybook:test` — static build / its Vitest project.
- `pnpm --filter @candleviewer/ui test` / `test:cov` — the Vitest unit project, ≥80% gate.

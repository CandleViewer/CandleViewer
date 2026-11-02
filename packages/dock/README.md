# @candleviewer/dock

The dock layout tree (E15-T02): pure TypeScript, no React, DOM, network or chart engine
(ESLint purity rules in `eslint.config.mjs`, `dock-framework-free` in `.dependency-cruiser.js`).

- **Model** (`model.ts`): `row` / `column` splits with fractional `sizes`, `tabset`s of leaves,
  and `leaf`s carrying `paneId`, `kind` and the compact-view minimums. Floating and minimised
  panes are kept beside the tree. Immutable plain data.
- **Operations** (`ops.ts`): `split`, `move`, `tabify`, `close`, `resize`, `equalise`,
  `activateTab`, `maximise` / `restore`, `float` / `redock`, `applyPreset`. Each returns a new tree
  through `normalise`; a move keeps the leaf object, so the app re-parents a panel and never
  recreates it.
- **Normal form** (`normalise.ts`): no single-child container, no one-tab tab group, sizes summing
  to 1, minimums kept where the dock can hold them, `22`'s caps (depth 6, 64 nodes, 16 panes).
- **Presets** (`presets.ts`): `presetToTree` / `matchPreset` for `lay_preset`.
- **Serialisation** (`serialise.ts`): `toLayoutInput` / `fromLayout` against `22`'s
  `LayoutInput` / `Layout`; `fromLayout` is the import boundary (bounded `validateGridSpec`, the
  caller's kind allow-list). Errors are `DockError` with `22`'s rule codes.
- **Drops** (`drop.ts`): `dropZones` (CMP-214 geometry), `resolveDrop` (pointer) and
  `resolveDirectionalMove` (CMP-216's keyboard chooser) over the same zones, applied by `relocate`.

## Guarantee: zero WebGL context creations per layout operation

No layout operation (split, move, tabify, close of another pane, resize, equalise, tab switch,
maximise / restore, float / redock, preset) creates a WebGL context. The tree keeps each pane's
leaf object across every operation, so the app keys a pane by `paneId` and never recreates it:

- each pane is mounted once into a **persistent host** element that outlives every layout change;
- a layout change **re-parents** that host into its new slot (`moveBefore` where the browser has
  it, else `insertBefore` with focus restored); the pane's canvas and its context stay alive;
- only adding a pane creates its context, and only closing it releases it.

The app's churn guard (E15-T02 GL-churn tests, landing in slice 2) will assert zero context creations and zero unmounts
across move, tabify and split-out, with a negative control. This covers context churn, not the
browser's live-context cap: more than four chart panes per worker stays unsafe until the
shared-context-per-worker engine change lands, which rides the held `26` §16 row, is confirmed on
runtimes by E11-Q07 and in Electron by owner leg OL-2.

## What a stored layout does not keep

`toLayoutInput` gives floating panes slot indices, but `fromLayout` reads every pane no leaf names
back as **minimised**: floating is client-only state, so a reload restores floating panes
minimised. A named grid keeps only its cells; panes beyond them come back minimised. E15-S02 must
not assume floating persists. A `grid_preset` that is neither `custom` nor a named preset is
refused (`unknown_preset`).

Ids come from an injected minter (`counterMinter`); one minter per dock keeps node and pane ids
apart. `pnpm --filter @candleviewer/dock test:cov` runs the suite, the 1000-operation property
test included, at the 85 % floor.

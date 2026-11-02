---
description: Frontend conventions for apps/web and packages/ui (TS strict, React 18, `useSyncExternalStore` stores per ADR-0001, Storybook mandatory for CMP-*, accessibility).
---
# Frontend (React / TypeScript)

Source: `AGENTS.md` §5.1, `docs/plan/05-accessibility-standard.md`, `15-component-catalogue.md`,
`16-design-system-brief.md`, `14-screens-catalogue.md`, CONSTITUTION C-3.5, C-14.1 to C-14.3.

## TypeScript
- `strict: true` everywhere; no `any` (use `unknown` + narrowing); no non-null `!` without a comment.
- No `@ts-ignore`; `@ts-expect-error` only with a reason. Named exports only.
- Protocol types come from `packages/protocol` (generated); never hand-write REST/WS DTOs (C-4.16).

## React 18
- Function components + hooks only. Render stays pure; side effects in effects with cleanup.
- Feature-sliced: `apps/web/src/features/<feature>/`. Shared components move to `packages/ui` once used
  by 2+ features. `apps/web` never imports another app (C-3.5); no deep imports into package internals.
- Business rules stay server-side (C-2.12); the UI renders server truth (risk, sizing, RBAC).

## State
- Plain external stores read through React's **`useSyncExternalStore`**: small stores, selectors, no stored
  derived state. Which state / data libraries `apps/web` may use is ADR-0001's (amendment 2026-11-02);
  read it before adding one.
- High-frequency values are coalesced by the transport layer before React sees them:
  transport -> coalescer (rAF or a timer batch) -> store publish. Never set state per WS message.
- Unsubscribe on unmount; every subscription has a teardown test.
- Chart data never flows through React state; it goes straight to the chart-engine API.

## Components (`CMP-*`)
- Every catalogued component (`CMP-*` in `15-component-catalogue.md`) ships with a **Storybook story**
  covering all variants/states (default, hover, focus, disabled, loading, error, empty, long text).
  Mandatory for Done.
- Radix primitives + Tailwind + tokens from `packages/ui/src/tokens` (generated; never hand-edit).
- No hard-coded colours/spacing; use tokens. Dark theme is default; both themes must pass contrast.

## Accessibility (WCAG 2.2 AA, C-14.1)
- Semantic HTML first; ARIA only when needed. Every interactive element keyboard reachable with visible focus.
- Trading actions have keyboard shortcuts and a confirm path; destructive actions are confirmable.
- Colour is never the only signal (buy/sell also shown by icon/label). Respect `prefers-reduced-motion`.
- Live values use polite `aria-live` regions at throttled rates; never announce every tick.
- `axe-core`: zero serious/critical (CI `a11y`). RTL tests query by role/label before test-id.

## Tests and budgets
- Vitest + React Testing Library; coverage >=80% (`unit-frontend`). Playwright for critical paths.
- Bundle budgets per entry via size-limit (C-14.3); lazy-load feature routes and heavy panels.

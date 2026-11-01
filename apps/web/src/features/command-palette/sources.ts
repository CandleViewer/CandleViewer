/**
 * SCR-012's row sources (E10-S05, #5236): a `PaletteSource` list, so a later source (E08-S09's Symbol group, E15's
 * panels, a settings index) registers without touching the host. Two ship: Navigate, over the route manifest, and
 * Action, over the keymap registry. Filtering is display only: the route guard and the server still decide every
 * route and action (C-2.12, C-12.4; `12` :188).
 */
import { KEYMAP, bindingAtoms, type KeymapCommand } from "../../keymap/keymap";
import { commandMeta } from "../../keymap/registry";
import { ROUTE_MANIFEST, type ManifestEntry } from "../../routes/manifest";
import { evaluateAccess, type MeClaims } from "../../routes/rbac";
import { ROUTE_TITLES } from "../../routes/titles";
import { GROUPS } from "./copy";
import { COMMAND_GATES, gateReason, type CommandGate } from "./gates";

export type PaletteGroup = (typeof GROUPS)[keyof typeof GROUPS];

/** E10-D02 f11's fixed group order; the host sorts its rows by it (CMP-059 groups by first appearance). */
export const GROUP_ORDER: readonly PaletteGroup[] = [
  GROUPS.navigate,
  GROUPS.panel,
  GROUPS.symbol,
  GROUPS.action,
  GROUPS.setting,
];

export type PaletteTarget =
  | { readonly kind: "route"; readonly path: string }
  | { readonly kind: "command"; readonly commandId: string };

/** One row: what CMP-059 draws, and what running it does. */
export interface PaletteRow {
  /** Unique across sources: `route:R-190`, `command:global.cheatsheet`. Recency stores it (ids only). */
  readonly id: string;
  readonly label: string;
  readonly group: PaletteGroup;
  readonly target: PaletteTarget;
  /** The active profile's binding in display form (`["Ctrl", "/"]`); absent when unbound. */
  readonly shortcut?: readonly string[];
  /** T2 (E09-D09 §3's sentence): drawn with the lock and this reason; never runs. */
  readonly disabledReason?: string;
  /** A destructive or `confirm` command: the warning glyph and "confirms"; its own confirmation runs it. */
  readonly destructive?: boolean;
}

/** What a source reads, at open and on a claims change while open. */
export interface SourceContext {
  readonly claims: MeClaims;
  /** The active keymap profile (`keymap/profile.ts` `getBindings()`). */
  readonly bindings: ReadonlyMap<string, string>;
  /** `isCommandValid`: a handler is registered and its predicate holds. */
  readonly isValid: (commandId: string) => boolean;
  /** The view-as context (`gates.ts`); `null` while none is active, and always today (no client source yet). */
  readonly viewAs: { readonly user: string } | null;
}

export interface PaletteSource {
  readonly id: string;
  readonly group: PaletteGroup;
  readonly rows: (ctx: SourceContext) => readonly PaletteRow[];
}

/** `14` §0.5 rule 5 step 1: an `/admin/*` destination needs `admin:read`, whatever the manifest's `access` says. */
export const ADMIN_READ = "admin:read";
export const isAdminPath = (path: string): boolean => path === "/admin" || path.startsWith("/admin/");

/**
 * Manifest entries that are not places to go: Sign out (an action that ends the session, R-004), the lock screen
 * (R-005) and the 403 landing (R-900). The public routes (login, 404, offline, maintenance) are dropped by `access`.
 */
const NOT_DESTINATIONS: ReadonlySet<string> = new Set(["R-004", "R-005", "R-900"]);

/**
 * Navigate: every manifest route with no `:param`, not public and not in `NOT_DESTINATIONS`, that the guard's own
 * `evaluateAccess` lets the claims open, labelled from `ROUTE_TITLES`. Every `/admin/*` route is absent without
 * `admin:read` (R-360 admits managers by role). A non-admin route the role cannot open is absent too, as the rail
 * leaves a gap: `RouteAccess` carries roles, not permission codes, so no E09-D09 verb exists for a T2 row.
 */
export function routeRows(
  ctx: SourceContext,
  manifest: readonly ManifestEntry[] = ROUTE_MANIFEST,
  titles: Readonly<Record<string, string>> = ROUTE_TITLES,
): PaletteRow[] {
  const admin = ctx.claims.permissions.includes(ADMIN_READ);
  const rows: PaletteRow[] = [];
  for (const entry of manifest) {
    const label = titles[entry.id];
    if (label === undefined || entry.path.includes(":") || NOT_DESTINATIONS.has(entry.id)) continue;
    if (entry.access.roles === "public") continue;
    if (isAdminPath(entry.path) && !admin) continue;
    if (evaluateAccess(entry.access, ctx.claims).kind !== "allow") continue;
    rows.push({
      id: `route:${entry.id}`,
      label,
      group: GROUPS.navigate,
      target: { kind: "route", path: entry.path },
    });
  }
  return rows;
}

/** A binding's display keys: `"Ctrl+/"` → `["Ctrl", "/"]`, `"Ctrl++"` → `["Ctrl", "+"]`. */
export const bindingKeys = (binding: string): readonly string[] =>
  binding.split(/\+(?=.)/u).filter((k) => k !== "");

/** A range binding (`Alt+1..9`) needs a pressed digit: the palette cannot run it. */
const isRange = (c: KeymapCommand): boolean => bindingAtoms(c.defaultBinding).length > 1;

/** The palette's own command: it never lists itself. */
export const PALETTE_COMMAND = "global.palette";

/**
 * Action: every keymap command that is registered and valid now, bound or not, labelled from `commandMeta`, with the
 * active profile's binding; not `global.palette` itself, and not a range command (the Navigate group covers the rail).
 */
export function actionRows(
  ctx: SourceContext,
  commands: readonly KeymapCommand[] = KEYMAP,
  gates: Readonly<Record<string, CommandGate>> = COMMAND_GATES,
): PaletteRow[] {
  const rows: PaletteRow[] = [];
  for (const c of commands) {
    if (c.id === PALETTE_COMMAND || isRange(c) || !ctx.isValid(c.id)) continue;
    const meta = commandMeta(c.id);
    const binding = ctx.bindings.get(c.id) ?? c.defaultBinding;
    const destructive = c.destructive || meta?.confirm === true;
    // T2 (E09-D09): the row stays, with its reason; a gated row never runs from here.
    const reason = gateReason(gates[c.id], ctx);
    rows.push({
      id: `command:${c.id}`,
      label: meta?.label ?? c.label,
      group: GROUPS.action,
      target: { kind: "command", commandId: c.id },
      ...(binding === "" ? {} : { shortcut: bindingKeys(binding) }),
      ...(destructive ? { destructive: true } : {}),
      ...(reason === undefined ? {} : { disabledReason: reason }),
    });
  }
  return rows;
}

export const ROUTE_SOURCE: PaletteSource = {
  id: "routes",
  group: GROUPS.navigate,
  rows: routeRows,
};
export const ACTION_SOURCE: PaletteSource = {
  id: "actions",
  group: GROUPS.action,
  rows: actionRows,
};

let sources: readonly PaletteSource[] = [ROUTE_SOURCE, ACTION_SOURCE];
const listeners = new Set<() => void>();

/** The mounted sources, in registration order (the host sorts rows by `GROUP_ORDER`). */
export const getPaletteSources = (): readonly PaletteSource[] => sources;
export function subscribePaletteSources(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** A later source (E08-S09's Symbol group) plugs in here; the returned function removes it. One source per id. */
export function registerPaletteSource(source: PaletteSource): () => void {
  if (sources.some((s) => s.id === source.id)) {
    throw new Error(`registerPaletteSource: "${source.id}" is already registered`);
  }
  sources = [...sources, source];
  listeners.forEach((l) => l());
  return () => {
    if (!sources.includes(source)) return;
    sources = sources.filter((s) => s !== source);
    listeners.forEach((l) => l());
  };
}

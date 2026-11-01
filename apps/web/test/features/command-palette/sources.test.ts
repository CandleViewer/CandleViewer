import { afterEach, describe, expect, it } from "vitest";
import { KEYMAP, type KeymapCommand } from "../../../src/keymap/keymap";
import { ROUTE_MANIFEST } from "../../../src/routes/manifest";
import type { MeClaims, Role } from "../../../src/routes/rbac";
import {
  ADMIN_READ,
  GROUP_ORDER,
  actionRows,
  bindingKeys,
  getPaletteSources,
  registerPaletteSource,
  routeRows,
  type SourceContext,
} from "../../../src/features/command-palette/sources";

// E10-S05 (#5236): the Navigate and Action sources over fixtures (no DOM, no network).

const claims = (role: Role, permissions: readonly string[] = []): MeClaims => ({
  authenticated: true,
  role,
  permissions,
});
const ctx = (c: MeClaims, valid: readonly string[] = []): SourceContext => ({
  claims: c,
  bindings: new Map(),
  isValid: (id) => valid.includes(id),
  viewAs: null,
});
const paths = (c: MeClaims): string[] =>
  routeRows(ctx(c)).map((r) => (r.target.kind === "route" ? r.target.path : ""));

describe("E10-S05 Navigate source: the route manifest", () => {
  it("lists no :param, public or non-destination route, for any role", () => {
    for (const role of ["owner", "manager", "viewer"] as const) {
      const listed = paths(claims(role, [ADMIN_READ]));
      expect(listed.filter((p) => p.includes(":"))).toEqual([]);
      for (const gone of [
        "/login",
        "/404",
        "/offline",
        "/maintenance",
        "/403",
        "/logout",
        "/locked",
      ])
        expect(listed).not.toContain(gone);
    }
  });

  it("an owner with admin:read finds Profile and security and Invite user (2.4.5, A11Y-F-0029)", () => {
    const rows = routeRows(ctx(claims("owner", [ADMIN_READ])));
    const labels = rows.map((r) => r.label);
    expect(labels).toContain("Profile and security"); // SCR-112, /settings/profile
    expect(labels).toContain("Invite user"); // SCR-123, /admin/users/new
    expect(rows.find((r) => r.label === "Invite user")?.target).toEqual({
      kind: "route",
      path: "/admin/users/new",
    });
    expect(rows.every((r) => r.group === "Navigate" && r.id.startsWith("route:R-"))).toBe(true);
  });

  it("drops every /admin/* route without admin:read, whatever access says (R-360 admits managers)", () => {
    for (const c of [claims("owner"), claims("manager"), claims("viewer")]) {
      expect(paths(c).filter((p) => p === "/admin" || p.startsWith("/admin/"))).toEqual([]);
    }
    expect(paths(claims("manager", [ADMIN_READ]))).toContain("/admin/audit");
    expect(paths(claims("manager", [ADMIN_READ]))).not.toContain("/admin/users");
  });

  it("follows evaluateAccess: a role-denied route is absent, not gated", () => {
    expect(paths(claims("viewer"))).not.toContain("/rules");
    expect(paths(claims("manager"))).toContain("/rules");
    expect(paths(claims("manager"))).not.toContain("/risk");
    expect(paths(claims("owner"))).toContain("/risk");
    expect(paths({ authenticated: false, role: null, permissions: [] })).toEqual([]);
  });

  it("skips a manifest entry with no title", () => {
    const entry = {
      id: "R-999",
      path: "/nowhere",
      access: { roles: ["owner"] },
      owner: null,
    } as const;
    expect(
      routeRows(ctx(claims("owner")), [...ROUTE_MANIFEST, entry]).map((r) => r.id),
    ).not.toContain("route:R-999");
  });
});

const fake = (id: string, extra: Partial<KeymapCommand> = {}): KeymapCommand => ({
  id,
  label: id,
  context: "Global",
  defaultBinding: "",
  destructive: false,
  validWhen: "always",
  visibleControl: false,
  ...extra,
});

describe("E10-S05 Action source: the keymap registry", () => {
  it("lists every registered, valid command bound or not, except the palette and range commands", () => {
    const ids = ["global.cheatsheet", "global.palette", "global.nav_rail", "global.region_cycle"];
    const rows = actionRows(ctx(claims("viewer"), ids));
    expect(rows.map((r) => r.id)).toEqual([
      "command:global.cheatsheet",
      "command:global.region_cycle",
    ]);
    expect(rows[0]).toMatchObject({
      label: "Hotkey cheatsheet",
      group: "Action",
      shortcut: ["Ctrl", "/"],
    });
  });

  it("omits an unregistered or invalid command", () => {
    expect(actionRows(ctx(claims("owner")))).toEqual([]);
  });

  it("shows the active profile's binding, and none for an unbound command", () => {
    const bindings = new Map([
      ["global.cheatsheet", "Ctrl+Shift+/"],
      ["global.region_cycle", ""],
    ]);
    const rows = actionRows({
      ...ctx(claims("owner"), ["global.cheatsheet", "global.region_cycle"]),
      bindings,
    });
    expect(rows[0]?.shortcut).toEqual(["Ctrl", "Shift", "/"]);
    expect(rows[1]).not.toHaveProperty("shortcut");
  });

  it("marks a destructive or confirm command, and no other", () => {
    const commands = [
      fake("a.plain"),
      fake("a.destructive", { destructive: true }),
      ...KEYMAP.filter((c) => c.confirm === true && !c.destructive).slice(0, 1),
    ];
    const valid = commands.map((c) => c.id);
    const rows = actionRows(ctx(claims("owner"), valid), commands);
    expect(rows.map((r) => r.destructive === true)).toEqual([false, true, true]);
  });

  it("splits a binding into its display keys", () => {
    expect(bindingKeys("Ctrl+/")).toEqual(["Ctrl", "/"]);
    expect(bindingKeys("Ctrl++")).toEqual(["Ctrl", "+"]);
    expect(bindingKeys("F11")).toEqual(["F11"]);
  });
});

describe("E10-S05 the source seam", () => {
  const off: (() => void)[] = [];
  afterEach(() => off.splice(0).forEach((f) => f()));

  it("mounts the route and action sources, and lets a later one plug in and out", () => {
    expect(getPaletteSources().map((s) => s.id)).toEqual(["routes", "actions"]);
    const symbol = { id: "symbols", group: "Symbol" as const, rows: () => [] };
    off.push(registerPaletteSource(symbol));
    expect(getPaletteSources().map((s) => s.id)).toEqual(["routes", "actions", "symbols"]);
    expect(() => registerPaletteSource(symbol)).toThrow(/already registered/);
    off.pop()?.();
    expect(getPaletteSources().map((s) => s.id)).toEqual(["routes", "actions"]);
  });

  it("keeps E10-D02 f11's fixed group order", () => {
    expect(GROUP_ORDER).toEqual(["Navigate", "Panel", "Symbol", "Action", "Setting"]);
  });
});

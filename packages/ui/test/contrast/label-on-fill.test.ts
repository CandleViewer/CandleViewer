import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

// The label-on-fill contrast matrix (#3896): the CI gate over tools/contrast/label-on-fill.json,
// whose `$comment` states the rules and the documented exemptions (hover and pressed fills are
// not held to the 3:1 boundary; the dimmed label of an inactive control is exempt under WCAG 2.2
// SC 1.4.3). packages/ui/tokens/tests/verify_tokens.py checks the same registry over the theme
// tokens; this test also checks the labels in every chart colour mode. Plain .mjs tooling loads
// untyped through a string specifier, as in data-ink.test.ts, and is typed here.

type Theme = Record<string, { $value: unknown } | undefined>;
type Pair = [string, string];
type Mode = { palette: string; convention: string };
interface Role {
  label: string;
  states: Record<string, string>;
  boundary: boolean;
  hue: boolean;
}
interface Registry {
  thresholds: Record<"label" | "glyph" | "boundary" | "stateLightness" | "stateHue", number>;
  surfaces: string[];
  stateSuffixes: string[];
  roles: Record<string, Role>;
  disabledWithReason: { text: Pair[]; glyph: Pair[] };
}

const math = (await import(
  /* @vite-ignore */ "../../../../tools/contrast/color-math.mjs" as string
)) as {
  contrastRatio(a: string, b: string): number;
  cieLab(hex: string): [number, number, number];
};
const build = (await import(/* @vite-ignore */ "../../scripts/build-tokens.mjs" as string)) as {
  loadResolvedThemes(): Promise<Record<string, Theme>>;
};
const modes = (await import(
  /* @vite-ignore */ "../../scripts/chart-color-modes.mjs" as string
)) as {
  MODES: Mode[];
  modeOverrides(theme: Theme, mode: Mode): Record<string, unknown>;
};
const registry = JSON.parse(
  readFileSync(new URL("../../../../tools/contrast/label-on-fill.json", import.meta.url), "utf-8"),
) as Registry;
const T = registry.thresholds;
const themes = await build.loadResolvedThemes();

// Truncated to three places, so a failing 2.9993:1 never prints as the 3:1 it misses.
const r3 = (n: number) => (Math.floor(n * 1000) / 1000).toFixed(3);

/** A token's resolved colour; an absent or non-opaque value fails loudly, never skips a pair. */
function hexOf(theme: Theme, name: string): string {
  const v = theme[name]?.$value;
  if (typeof v !== "string" || !/^#[0-9A-Fa-f]{6}$/.test(v)) {
    throw new Error(`label-on-fill: "${name}" does not resolve to an opaque hex colour`);
  }
  return v;
}
const lightness = (hex: string) => math.cieLab(hex)[0];
function hue(hex: string): number {
  const [, a, b] = math.cieLab(hex);
  return ((Math.atan2(b, a) * 180) / Math.PI + 360) % 360;
}
const hueGap = (x: number, y: number) => Math.abs(((x - y + 540) % 360) - 180);
const roles = () => Object.entries(registry.roles);

function labelFindings(
  name: string,
  theme: Theme,
  only: (r: Role) => boolean = () => true,
): string[] {
  return roles()
    .filter(([, r]) => only(r))
    .flatMap(([role, r]) =>
      Object.entries(r.states).flatMap(([state, fill]) => {
        const ratio = math.contrastRatio(hexOf(theme, r.label), hexOf(theme, fill));
        return ratio < T.label
          ? [`${name} ${role}.${state}: ${r.label} on ${fill} ${r3(ratio)}:1 < ${T.label}:1`]
          : [];
      }),
    );
}

function orderFindings(name: string, theme: Theme): string[] {
  return roles().flatMap(([role, r]) => {
    const fills = Object.values(r.states);
    return fills.flatMap((a, i) =>
      fills.slice(i + 1).flatMap((b) => {
        const d = Math.abs(lightness(hexOf(theme, a)) - lightness(hexOf(theme, b)));
        return d < T.stateLightness
          ? [`${name} ${role}: ${a} vs ${b} dL* ${r3(d)} < ${T.stateLightness}`]
          : [];
      }),
    );
  });
}

function hueFindings(name: string, theme: Theme): string[] {
  return roles()
    .filter(([, r]) => r.hue)
    .flatMap(([role, r]) => {
      const rest = hue(hexOf(theme, r.states["default"] ?? ""));
      return Object.values(r.states).flatMap((fill) => {
        const gap = hueGap(hue(hexOf(theme, fill)), rest);
        return gap > T.stateHue
          ? [`${name} ${role}: ${fill} hue ${r3(gap)} deg from the rest fill > ${T.stateHue}`]
          : [];
      });
    });
}

function boundaryFindings(name: string, theme: Theme): string[] {
  return roles()
    .filter(([, r]) => r.boundary)
    .flatMap(([role, r]) => {
      const rest = r.states["default"] ?? "";
      return registry.surfaces.flatMap((surface) => {
        const ratio = math.contrastRatio(hexOf(theme, rest), hexOf(theme, surface));
        return ratio < T.boundary
          ? [`${name} ${role}: ${rest} on ${surface} ${r3(ratio)}:1 < ${T.boundary}:1`]
          : [];
      });
    });
}

function disabledFindings(name: string, theme: Theme): string[] {
  const check = (pairs: Pair[], min: number, what: string) =>
    pairs.flatMap(([fg, bg]) => {
      const ratio = math.contrastRatio(hexOf(theme, fg), hexOf(theme, bg));
      return ratio < min ? [`${name} ${what}: ${fg} on ${bg} ${r3(ratio)}:1 < ${min}:1`] : [];
    });
  const glyphs = roles().map(([, r]): Pair => [r.label, r.states["default"] ?? ""]);
  return [
    ...check(registry.disabledWithReason.text, T.label, "reason text"),
    ...check([...glyphs, ...registry.disabledWithReason.glyph], T.glyph, "locked glyph"),
  ];
}

/** A `<role>.<hover|active|pressed>` token the matrix does not list fails, so a new state is gated. */
function undeclaredFindings(name: string, theme: Theme): string[] {
  return roles().flatMap(([role, r]) => {
    const prefix = (r.states["default"] ?? "").replace(/default$/, "");
    return registry.stateSuffixes
      .map((suffix) => prefix + suffix)
      .filter((token) => token in theme && !Object.values(r.states).includes(token))
      .map((token) => `${name} ${role}: ${token} is not in tools/contrast/label-on-fill.json`);
  });
}

/** The theme as a chart colour mode (E47-S06) renders it: the buy and sell fills re-pointed. */
function inMode(theme: Theme, mode: Mode): Theme {
  const out: Theme = { ...theme };
  for (const [k, v] of Object.entries(modes.modeOverrides(theme, mode))) out[k] = { $value: v };
  return out;
}

const everyTheme = (check: (name: string, theme: Theme) => string[]) =>
  Object.entries(themes).flatMap(([name, theme]) => check(name, theme));

describe("label-on-fill contrast matrix (#3896)", () => {
  it("covers the three themes the token build resolves", () => {
    expect(Object.keys(themes).sort()).toEqual(["dark", "high-contrast", "light"]);
  });

  it("every label clears 4.5:1 on each of its state fills", () => {
    expect(everyTheme(labelFindings)).toEqual([]);
  });

  it("every label clears 4.5:1 in every chart colour mode (re-pointed buy and sell fills)", () => {
    const found = everyTheme((name, theme) =>
      modes.MODES.flatMap((m) => {
        const moved = Object.keys(modes.modeOverrides(theme, m));
        const repointed = (r: Role) => Object.values(r.states).some((f) => moved.includes(f));
        return labelFindings(`${name} ${m.palette}+${m.convention}`, inMode(theme, m), repointed);
      }),
    );
    expect(found).toEqual([]);
  });

  it("a role's states are pairwise at least 5 CIE L* apart", () => {
    expect(everyTheme(orderFindings)).toEqual([]);
  });

  it("a chromatic role's states keep the rest fill's hue (LCh, within 10 degrees)", () => {
    expect(everyTheme(hueFindings)).toEqual([]);
  });

  it("each rest fill clears 3:1 against the app, raised and overlay surfaces", () => {
    expect(everyTheme(boundaryFindings)).toEqual([]);
  });

  it("disabled with reason: reason text clears 4.5:1, the locked glyph 3:1", () => {
    expect(everyTheme(disabledFindings)).toEqual([]);
  });

  it("lists every interaction-state token of each role", () => {
    expect(everyTheme(undeclaredFindings)).toEqual([]);
  });

  it("fails closed: each check reports a broken synthetic theme pair by pair", () => {
    const dark = themes["dark"] ?? {};
    const broken: Theme = {
      ...dark,
      "color.action.primary.hover": { $value: "#AFB8F8" }, // brand-hue tint under a white label
      "color.buy.hover": dark["color.buy.default"], // no visible hover step
      "color.sell.hover": { $value: "#3CB371" }, // sell hover turned green
      "color.status.danger.default": dark["color.surface.overlay"], // no boundary
      "color.buy.active": { $value: "#2EBD59" }, // a new state outside the matrix
    };
    expect(labelFindings("x", broken)).toEqual([
      "x primary.hover: color.text.on-action on color.action.primary.hover 1.903:1 < 4.5:1",
    ]);
    expect(orderFindings("x", broken)).toContainEqual(
      "x buy: color.buy.default vs color.buy.hover dL* 0.000 < 5",
    );
    expect(hueFindings("x", broken)).toEqual([
      expect.stringMatching(
        /^x sell: color\.sell\.hover hue \d+\.\d{3} deg from the rest fill > 10$/,
      ),
    ]);
    expect(boundaryFindings("x", broken)).toContainEqual(
      "x danger: color.status.danger.default on color.surface.overlay 1.000:1 < 3:1",
    );
    expect(undeclaredFindings("x", broken)).toEqual([
      "x buy: color.buy.active is not in tools/contrast/label-on-fill.json",
    ]);
    const missing: Theme = Object.fromEntries(
      Object.entries(dark).filter(([name]) => name !== "color.action.primary.active"),
    );
    expect(() => labelFindings("x", missing)).toThrow(/does not resolve/);
  });
});

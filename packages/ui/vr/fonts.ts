/**
 * The pinned fonts (E05-T04): the token families, `font.family.ui` (Inter) and `font.family.mono`
 * (JetBrains Mono), must be the faces Chromium draws, never a substitute. The vr job installs them from the
 * pinned image's archive (`_job-a11y.yml`, CI-A11Y-008); each shard then draws a sample of each family and
 * asks Chromium, through the DevTools protocol (`CSS.getPlatformFontsForNode`), which faces it used.
 */
import { readFileSync } from "node:fs";

/** A face Chromium drew a node's text with, as `CSS.getPlatformFontsForNode` reports it. */
export interface DrawnFace {
  readonly familyName: string;
  readonly postScriptName: string;
  readonly glyphCount: number;
}

/** The token names whose family the capture must draw. */
const FAMILY_TOKENS = ["font.family.ui", "font.family.mono"] as const;

/** Each family token's value in the token source (DTCG, flat dotted names). */
export function readTokenFamilies(tokensPath: string): Record<string, string> {
  const tokens = JSON.parse(readFileSync(tokensPath, "utf-8")) as Record<
    string,
    { $value?: unknown } | undefined
  >;
  return Object.fromEntries(
    FAMILY_TOKENS.map((name) => {
      const value = tokens[name]?.$value;
      if (typeof value !== "string") throw new Error(`${tokensPath} has no ${name}`);
      return [name, value];
    }),
  );
}

const attribute = (text: string): string =>
  text.replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;");

/** A page with one sample per family, `#family-0`, `#family-1`, ... in the order given. */
export function fontSample(families: Record<string, string>): string {
  return Object.values(families)
    .map((family, index) => {
      const css = `font: 16px ${JSON.stringify(family)}`;
      return `<p id="family-${String(index)}" style="${attribute(css)}">Aa Gg 0123 {}</p>`;
    })
    .join("");
}

const faces = (drawn: readonly DrawnFace[]): string =>
  drawn.map((face) => `${face.familyName} (${face.postScriptName})`).join(", ") || "nothing";

/** Why the faces drawn are not the token families: one sentence per family that drew another or several. */
export function fontProblems(
  families: Record<string, string>,
  drawn: Readonly<Record<string, readonly DrawnFace[]>>,
): string[] {
  return Object.entries(families).flatMap(([token, family]) => {
    const used = drawn[token] ?? [];
    const exact = used.length === 1 && used[0]?.familyName === family;
    return exact ? [] : [`${token} draws ${faces(used)}, not ${family}`];
  });
}

/** The summary's line: each family token with the face Chromium drew. */
export function describeFaces(drawn: Readonly<Record<string, readonly DrawnFace[]>>): string {
  return Object.entries(drawn)
    .map(([token, used]) => `${token} ${faces(used)}`)
    .join("; ");
}

// @vitest-environment node
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { ESLint } from "eslint";
import { beforeAll, describe, expect, it } from "vitest";

/**
 * E14-X03 (#549; DR6, SR-E14-01): the lint ban on the drawing render paths, proved through the ESLint
 * API with the app's own config. A virtual file has to be named in `allowDefaultProject`: the project
 * service refuses a path that is not on disk even under the tsconfig's `include`, and the rules under
 * test read no type information. The paths are those of tools/ci/no-inline-suppression-paths.json,
 * which the Semgrep rule and the suppression check read too.
 */
const WEB = resolve(import.meta.dirname, "../..");
const LISTED = JSON.parse(
  readFileSync(resolve(WEB, "../../tools/ci/no-inline-suppression-paths.json"), "utf8"),
) as { paths: string[] };
/** `apps/web/src/objecttree/**` -> `src/objecttree/__probe.tsx`, a file the ban must cover. */
const BANNED = LISTED.paths
  .filter((path) => path.startsWith("apps/web/src/"))
  .map((path) => path.replace(/^apps\/web\//, "").replace(/\/\*\*$/, "/__probe.tsx"));
const FREE = "src/features/indicators/__probe.tsx";

const DANGER =
  "export const A = ({ t }: { t: string }) => <div dangerouslySetInnerHTML={{ __html: t }} />;\n";
const WRITE = "export function f(el: HTMLElement, t: string): void { el.innerHTML = t; }\n";
const ANY = "export const a: any = 1;\n";
const NO_EFFECT = /has no effect because you have 'noInlineConfig'/;
const lineOff = (rule: string, code: string) => `// eslint-disable-next-line ${rule}\n${code}`;
const blockOff = (rule: string, code: string) => `/* eslint-disable ${rule} */\n${code}`;

type Message = { rule: string | null; severity: number; text: string };
let eslint: ESLint;
const lint = async (file: string, code: string): Promise<Message[]> => {
  const [result] = await eslint.lintText(code, { filePath: resolve(WEB, file) });
  if (!result) throw new Error(`no result for ${file}`);
  return result.messages.map((m) => ({ rule: m.ruleId, severity: m.severity, text: m.message }));
};
const errors = (found: Message[]) => found.filter((m) => m.severity === 2).map((m) => m.rule);
/** Warnings that say the comment is inert: `--max-warnings=0` turns each into a failed lint. */
const inert = (found: Message[]) => found.filter((m) => NO_EFFECT.test(m.text) && m.severity === 1);

beforeAll(() => {
  eslint = new ESLint({
    cwd: WEB,
    overrideConfig: {
      files: ["**/*.{ts,tsx}"],
      languageOptions: {
        parserOptions: {
          projectService: {
            allowDefaultProject: [...BANNED, FREE],
            defaultProject: "tsconfig.json",
            maximumDefaultProjectFileMatchCount_THIS_WILL_SLOW_DOWN_LINTING: 32,
          },
          tsconfigRootDir: WEB,
        },
      },
    },
  });
}, 120_000);

describe("the drawing render paths ban raw HTML and an inline switch-off", () => {
  it("lists the web app's drawing roots", () => {
    expect(BANNED.length).toBeGreaterThan(0);
  });

  it.each(BANNED)(
    "%s: dangerouslySetInnerHTML is an error",
    async (file) => {
      expect(errors(await lint(file, DANGER))).toEqual(["react/no-danger"]);
    },
    60_000,
  );

  it.each(BANNED)("%s: an eslint-disable comment silences nothing and warns", async (file) => {
    for (const off of [lineOff, blockOff]) {
      const found = await lint(file, off("react/no-danger", DANGER));
      expect(errors(found)).toEqual(["react/no-danger"]);
      expect(inert(found)).toHaveLength(1);
    }
  });

  it.each(BANNED)("%s: an innerHTML write is an error no comment silences", async (file) => {
    expect(errors(await lint(file, WRITE))).toEqual(["no-unsanitized/property"]);
    const found = await lint(file, blockOff("no-unsanitized/property", WRITE));
    expect(errors(found)).toEqual(["no-unsanitized/property"]);
    expect(inert(found)).toHaveLength(1);
  });

  it("is per path: elsewhere a disable comment still works and the ban is off", async () => {
    expect(await lint(FREE, lineOff("@typescript-eslint/no-explicit-any", ANY))).toEqual([]);
    expect(errors(await lint(FREE, DANGER))).toEqual([]);
    const inside = BANNED[0] ?? "";
    expect(errors(await lint(inside, ANY))).toEqual(["@typescript-eslint/no-explicit-any"]);
    const found = await lint(inside, lineOff("@typescript-eslint/no-explicit-any", ANY));
    expect(errors(found)).toEqual(["@typescript-eslint/no-explicit-any"]);
    expect(inert(found)).toHaveLength(1);
  }, 60_000);
});

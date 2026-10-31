// @vitest-environment node
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { ESLint } from "eslint";
import { beforeAll, describe, expect, it } from "vitest";

/**
 * E14-X03 (#549; DR6, SR-E14-01): the lint ban on the drawing render paths, proved through the ESLint
 * API with the app's config and the paths of tools/ci/no-inline-suppression-paths.json. A virtual
 * file must be named in `allowDefaultProject`: the project service refuses a path that is not on
 * disk even under the tsconfig's `include`, and the rules under test read no type information.
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
/** Every root as ECMAScript modules of either kind: TypeScript's `.mts` and `.cts`. */
const MODULES = BANNED.flatMap((file) =>
  ["mts", "cts"].map((ext) => file.replace(/\.tsx$/, `.${ext}`)),
);
/** The engine's drawing layer, linted with the engine's own config: its top and a nested folder. */
const ENGINE = resolve(WEB, "../../packages/chart-engine");
const LAYERS = ["src/layers/drawings/__probe.ts", "src/layers/drawings/deep/er/__probe.ts"];

const DANGER =
  "export const A = ({ t }: { t: string }) => <div dangerouslySetInnerHTML={{ __html: t }} />;\n";
const WRITE = "export function f(el: HTMLElement, t: string): void { el.innerHTML = t; }\n";
// A bare `window` read (not an alias of it: E11-X02 bans `const w = window` as its own error).
const WINDOW = "export const w = (): unknown => window;\n";
const INSERT =
  'export function g(el: HTMLElement, t: string): void { el.insertAdjacentHTML("beforeend", t); }\n';
const ANY = "export const a: any = 1;\n";
const NO_EFFECT = /has no effect because you have 'noInlineConfig'/;
const lineOff = (rule: string, code: string) => `// eslint-disable-next-line ${rule}\n${code}`;
const blockOff = (rule: string, code: string) => `/* eslint-disable ${rule} */\n${code}`;

let eslint: ESLint;
let engine: ESLint;
const lint = async (file: string, code: string) =>
  (await eslint.lintText(code, { filePath: resolve(WEB, file) }))[0]?.messages ?? [];
const lintEngine = async (code: string, file: string) =>
  (await engine.lintText(code, { filePath: resolve(ENGINE, file) }))[0]?.messages ?? [];
type Found = Awaited<ReturnType<typeof lint>>;
const errors = (found: Found) => found.filter((m) => m.severity === 2).map((m) => m.ruleId);
/** Warnings that say the comment is inert: `--max-warnings=0` turns each into a failed lint. */
const inert = (found: Found) => found.filter((m) => m.severity === 1 && NO_EFFECT.test(m.message));

beforeAll(async () => {
  eslint = new ESLint({
    cwd: WEB,
    overrideConfig: {
      files: ["**/*.{ts,tsx}"],
      languageOptions: {
        parserOptions: {
          projectService: {
            allowDefaultProject: [...BANNED, ...MODULES, FREE],
            defaultProject: "tsconfig.json",
            maximumDefaultProjectFileMatchCount_THIS_WILL_SLOW_DOWN_LINTING: 32,
          },
          tsconfigRootDir: WEB,
        },
      },
    },
  });
  engine = new ESLint({
    cwd: ENGINE,
    overrideConfig: {
      files: ["**/*.ts"],
      languageOptions: {
        parserOptions: {
          projectService: { allowDefaultProject: LAYERS, defaultProject: "tsconfig.json" },
          tsconfigRootDir: ENGINE,
        },
      },
    },
  });
  // The first lint of each instance builds its project (tens of seconds on a busy host): pay it here.
  await lint(FREE, "export {};\n");
  await lintEngine("export {};\n", LAYERS[0] ?? "");
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

  it.each(BANNED)("%s: an HTML-inserting call is an error no comment silences", async (file) => {
    expect(errors(await lint(file, INSERT))).toEqual(["no-unsanitized/method"]);
    const found = await lint(file, blockOff("no-unsanitized/method", INSERT));
    expect(errors(found)).toEqual(["no-unsanitized/method"]);
    expect(inert(found)).toHaveLength(1);
  });

  it.each(MODULES)("%s: the ban and its inert comments cover .mts and .cts", async (file) => {
    const found = await lint(file, blockOff("no-unsanitized/property", WRITE));
    expect(errors(found)).toEqual(["no-unsanitized/property"]);
    expect(inert(found)).toHaveLength(1);
  });

  it.each(LAYERS)(
    "the engine's drawing layer, %s: a config comment lifts no rule",
    async (file) => {
      expect(errors(await lintEngine(WINDOW, file))).toEqual(["no-restricted-globals"]);
      const found = await lintEngine(`/* eslint no-restricted-globals: off */\n${WINDOW}`, file);
      expect(errors(found)).toEqual(["no-restricted-globals"]);
      expect(inert(found)).toHaveLength(1);
    },
    60_000,
  );

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

// @vitest-environment node
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { ESLint, type Linter } from "eslint";
import { beforeAll, describe, expect, it } from "vitest";
import { KEYMAP } from "../../../src/keymap/keymap";
import { contextsOf } from "../../../src/keymap/registry";

/**
 * E37-X01 (#1073, SR-E37-11): the node-graph editor never asks the server to arm or simulate a
 * rule. Its one mode call is "Disarm to edit" (`disabled`), and `Arm…` opens SCR-085 (E37-D02 §2,
 * E37-D04 SC-8). The lint guard in `apps/web/eslint.config.mjs` is a tripwire for literal requests,
 * proved through the ESLint API with the app's own config on virtual files, as `purity-lint.test.ts`
 * proves the purity block; the keymap is read for a command that arms. The server's gates are the
 * control, and E37-S05's screen-level test reads the editor's requests. The rule under test reads
 * no type information, so the probes lint without the TypeScript project service.
 */
const WEB = resolve(import.meta.dirname, "../../..");
const SLICE = "src/features/rule-builder-graph";
const PROBES = [
  `${SLICE}/__probe.tsx`,
  `${SLICE}/model/__probe.ts`,
  `${SLICE}/a11y/__probe.ts`,
  `${SLICE}/data/__probe.ts`,
  `${SLICE}/screen/__probe.tsx`,
  `${SLICE}/canvas/__probe.tsx`,
];
const OUTSIDE = "src/features/rule-arming/__probe.ts";
const RULE = "no-restricted-syntax";
/** The `Rules` context's commands as reviewed for #1073: a new one is read here before it lands. */
const REVIEWED = `save_draft validate graph_mode move_up move_down duplicate delete select_all group
  auto_layout pan cycle_nodes inspect_node rename add_node nudge_left nudge_right nudge_up nudge_down
  nudge_left_large nudge_right_large nudge_up_large nudge_down_large`
  .split(/\s+/)
  .map((name) => `rules.${name}`);

let eslint: ESLint;
const lint = async (file: string, code: string) =>
  (await eslint.lintText(code, { filePath: resolve(WEB, file) }))[0]?.messages ?? [];
const errors = async (file: string, code: string) =>
  (await lint(file, code)).filter((m) => m.severity === 2);

beforeAll(async () => {
  eslint = new ESLint({
    cwd: WEB,
    overrideConfig: {
      files: ["**/*.{ts,tsx}"],
      languageOptions: { parserOptions: { projectService: false, project: false } },
    },
  });
  // The first lint loads the config and its plugins: pay it here.
  await lint(OUTSIDE, "export {};\n");
}, 120_000);

/** Requests to arm or simulate, each in a place a mode request carries its mode. */
const REQUESTS = [
  'export const body = { mode: "armed" };\n',
  'export const body = { mode: "simulate" };\n',
  'export const body = { "mode": "armed" };\n',
  'export const body = { mode: "armed" as const };\n',
  "export const body = { mode: `simulate` };\n",
  'export const body = (live: boolean) => ({ mode: live ? "armed" : "disabled" });\n',
  'declare function setRuleMode(id: string, mode: string): void;\nsetRuleMode("r1", "armed");\n',
  'declare const rules: { setMode(mode: string): void };\nrules.setMode("simulate");\n',
  'declare function mode(next: string): void;\nmode("armed");\n',
];
/** The slice's lawful neighbours: the disarm, a selection mode, and reading a rule's mode. */
const LAWFUL = [
  'export const body = { mode: "disabled" };\n',
  'export const selection = { mode: "replace" };\n',
  'export const isArmed = (rule: { mode: string }) => rule.mode === "armed";\n',
];

describe("the lint guard refuses an arm or simulate request in the rule-builder-graph slice", () => {
  it.each(PROBES)(
    "%s: every request to arm or simulate is an error citing SR-E37-11",
    async (file) => {
      for (const code of REQUESTS) {
        const found = await errors(file, code);
        expect(
          found.map((m) => m.ruleId),
          code,
        ).toEqual([RULE]);
        expect(found[0]?.message, code).toContain("SR-E37-11");
      }
    },
  );

  it("a mode prop on a component is refused too", async () => {
    const code =
      "const Mode = (props: { mode: string }) => <b>{props.mode}</b>;\n" +
      'export const arm = <Mode mode="armed" />;\n';
    expect((await errors(`${SLICE}/canvas/__probe.tsx`, code)).map((m) => m.ruleId)).toEqual([
      RULE,
    ]);
  });

  it.each(PROBES)("%s: the disarm, a selection mode and a mode read lint clean", async (file) => {
    for (const code of LAWFUL) expect(await errors(file, code), code).toEqual([]);
  });

  it("leaves code outside the slice, and a story's armed fixture, untouched", async () => {
    expect(await errors(OUTSIDE, REQUESTS[0] as string)).toEqual([]);
    const story = 'export const Armed = { args: { rule: { mode: "armed" } } };\n';
    expect(await errors(`${SLICE}/canvas/Node.stories.tsx`, story)).toEqual([]);
  });

  it("is the only object that sets no-restricted-syntax for a slice path", async () => {
    // ESLint keeps one object's options for a rule, the last to match a file: a second object that
    // sets it for any slice path drops the guard's selectors there, or the guard drops its own.
    const url = pathToFileURL(resolve(WEB, "eslint.config.mjs")).href;
    const config = ((await import(url)) as { default: Linter.Config[] }).default;
    const setters: Linter.Config[] = [];
    for (const object of config.filter((o) => o.rules?.[RULE] !== undefined)) {
      const alone = new ESLint({
        cwd: WEB,
        overrideConfigFile: true,
        overrideConfig: {
          files: object.files ?? ["**/*"],
          ignores: object.ignores ?? [],
          rules: { [RULE]: "error" },
        },
      });
      for (const file of [...PROBES, ...PROBES.map((p) => p.replace(/\.tsx?$/, ".mts"))]) {
        const reached = (await alone.calculateConfigForFile(resolve(WEB, file)))?.rules?.[RULE];
        if (reached !== undefined && !setters.includes(object)) setters.push(object);
      }
    }
    expect(setters.map((object) => object.files)).toEqual([
      ["src/features/rule-builder-graph/**/*.{ts,tsx,mts,cts}"],
    ]);
  });
});

describe("the keymap holds no command that arms a rule", () => {
  /** Every command whose binding is live while the Rules context is: its own and the Global ones. */
  const live = KEYMAP.filter((c) => contextsOf(c).some((x) => x === "Rules" || x === "Global"));
  const rules = KEYMAP.filter((c) => c.context === "Rules");

  it("the Rules context holds the 23 reviewed commands", () => {
    expect(rules.map((c) => c.id).sort()).toEqual([...REVIEWED].sort());
  });

  it("no command live in the Rules context arms, disarms or simulates a rule", () => {
    const arming = live.filter((c) => /\b(?:arm|disarm|simulat)/i.test(`${c.id} ${c.label}`));
    expect(arming.map((c) => c.id)).toEqual([]);
  });

  it("its one command that names a mode switches the editor, never the rule's mode", () => {
    const modes = rules.filter((c) => /mode/i.test(`${c.id} ${c.label}`));
    expect(modes.map((c) => [c.id, c.label])).toEqual([
      ["rules.graph_mode", "Switch to graph mode"],
    ]);
  });
});

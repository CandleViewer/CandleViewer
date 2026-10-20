import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  componentName,
  iconSources,
  IconSourceError,
  OUTPUT_DIR,
  parseIconSource,
  renderIconModules,
  run,
} from "../../scripts/build-icons.mjs";

const PACKAGE = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
/** A Lucide source's root, as the vendored files carry it (attributes on one line here). */
const ROOT =
  '<svg class="lucide lucide-x" xmlns="http://www.w3.org/2000/svg" width="24" height="24" ' +
  'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
  'stroke-linecap="round" stroke-linejoin="round">';
const LICENCE = "<!-- @license lucide-static v1.55.0 - ISC -->";
/** A source drawing `body` under `root`, after the upstream licence comment. */
const source = (body: string, root = ROOT): string => `${LICENCE}\n${root}\n${body}\n</svg>\n`;

describe("the icon generator (scripts/build-icons.mjs)", () => {
  it("left src/icons/generated/ as it renders it: no stale, missing or hand-edited module", () => {
    const modules = renderIconModules();
    const written = readdirSync(path.join(PACKAGE, OUTPUT_DIR)).map((f) => `${OUTPUT_DIR}/${f}`);
    expect(written.sort()).toEqual([...modules.keys()].sort());
    for (const [file, content] of modules) {
      expect(readFileSync(path.join(PACKAGE, file), "utf-8"), file).toBe(content);
    }
  });

  it("finds every source under its origin, sorted by name", () => {
    const sources = iconSources();
    expect(sources.map(({ name }) => name)).toEqual(sources.map(({ name }) => name).sort());
    for (const { name, origin, file } of sources) {
      expect(file).toBe(`src/icons/source/${origin}/${name}.svg`);
    }
  });

  it("keeps a source's geometry in order, and the Lucide glyph its class names", () => {
    const parsed = parseIconSource(
      source('  <path d="M18 6 6 18" />\n  <circle cx="12" cy="12" r="3" />'),
      "close.svg",
    );
    expect(parsed).toEqual({
      glyph: "x",
      children: [
        ["path", [["d", "M18 6 6 18"]]],
        [
          "circle",
          [
            ["cx", "12"],
            ["cy", "12"],
            ["r", "3"],
          ],
        ],
      ],
    });
  });

  it("accepts a custom glyph's root without a Lucide class", () => {
    const root = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none">';
    const parsed = parseIconSource(
      source('<line x1="4" y1="12" x2="20" y2="12" />', root),
      "a.svg",
    );
    expect(parsed.glyph).toBeNull();
    expect(parsed.children).toEqual([
      [
        "line",
        [
          ["x1", "4"],
          ["y1", "12"],
          ["x2", "20"],
          ["y2", "12"],
        ],
      ],
    ]);
  });

  // A source is data: the allowlist keeps the geometry of a 24x24 outline and fails on anything
  // that could run, fetch, restyle or move a glyph off the grid (the ticket's security note).
  it.each([
    ["an element that is not geometry", source("<script />")],
    ["an external reference", source('<use href="#glyph" />')],
    ["an embedded image", source('<image href="glyph.png" width="24" height="24" />')],
    ["embedded markup", source("<foreignObject />")],
    ["a group", source('<g><path d="M0 0h24" /></g>')],
    ["text", source("<text>A</text>")],
    ["an event-handler attribute", source('<path d="M0 0h24" onclick="run()" />')],
    ["an inline style", source('<path d="M0 0h24" style="stroke: red" />')],
    ["a hardcoded fill", source('<path d="M0 0h24" fill="#000000" />')],
    ["a transform", source('<path d="M0 0h24" transform="rotate(45)" />')],
    ["a class", source('<path d="M0 0h24" class="accent" />')],
    ["an attribute named like a prototype key", source('<path d="M0 0h24" constructor="x" />')],
    ["an element named like a prototype key", source('<constructor d="M0 0h24" />')],
    ["a repeated attribute", source('<path d="M0 0h24" d="M0 0v24" />')],
    ["an entity in a value", source('<path d="M0 0h24&amp;" />')],
    ["path data that is not path data", source('<path d="url(#a)" />')],
    ["a coordinate that is not a number", source('<circle cx="12px" cy="12" r="3" />')],
    ["geometry without its required attribute", source('<circle cx="12" cy="12" />')],
    ["a child with content", source('<path d="M0 0h24"></path>')],
    ["no geometry at all", source("")],
    [
      "a root that is not 24x24",
      source('<path d="M0 0h16" />', ROOT.replace("0 0 24 24", "0 0 16 16")),
    ],
    ["a root without a viewBox", source('<path d="M0 0h24" />', '<svg fill="none">')],
    [
      "a hardcoded root colour",
      source('<path d="M0 0h24" />', ROOT.replace("currentColor", "#fff")),
    ],
    ["a root event handler", source('<path d="M0 0h24" />', ROOT.replace(">", ' onload="run()">'))],
    ["a document type", `<!DOCTYPE svg>\n${source('<path d="M0 0h24" />')}`],
    ["markup after the root", `${source('<path d="M0 0h24" />')}<svg />`],
    ["a comment inside the root", source('<!-- note -->\n<path d="M0 0h24" />')],
  ])("rejects %s, naming the file", (_, text) => {
    expect(() => parseIconSource(text, "src/icons/source/lucide/bad.svg")).toThrow(IconSourceError);
    expect(() => parseIconSource(text, "src/icons/source/lucide/bad.svg")).toThrow(
      /^src\/icons\/source\/lucide\/bad\.svg: /,
    );
  });

  it("names a component after its icon", () => {
    expect(componentName("close")).toBe("CloseIcon");
    expect(componentName("chevrons-up-down")).toBe("ChevronsUpDownIcon");
    expect(componentName("zoom-in")).toBe("ZoomInIcon");
  });
});

describe("the generator's source tree (iconSources)", () => {
  const trees: string[] = [];
  /** A package root holding `files` (paths under src/icons/source/) in a fresh temp directory. */
  const tree = (...files: string[]) => {
    const root = mkdtempSync(path.join(tmpdir(), "cv-icon-sources-"));
    trees.push(root);
    for (const file of files) {
      mkdirSync(path.dirname(path.join(root, "src/icons/source", file)), { recursive: true });
      writeFileSync(path.join(root, "src/icons/source", file), source('<path d="M0 0h24" />'));
    }
    return root;
  };
  afterEach(() => {
    vi.restoreAllMocks();
    trees.splice(0).forEach((root) => rmSync(root, { recursive: true }));
  });

  it("reads each origin's sources, past its licence notice", () => {
    const root = tree("lucide/LICENSE", "lucide/close.svg", "custom/twap.svg");
    expect(iconSources(root)).toEqual([
      { name: "close", origin: "lucide", file: "src/icons/source/lucide/close.svg" },
      { name: "twap", origin: "custom", file: "src/icons/source/custom/twap.svg" },
    ]);
  });

  it("writes a tree's modules, finds them in sync, and repairs a hand-edit or a stray file", () => {
    const root = tree("lucide/close.svg", "custom/twap.svg");
    const logs = vi.spyOn(console, "log").mockImplementation(() => undefined);
    const errors = vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(run(["--check"], root)).toBe(1); // nothing generated yet
    expect(run([], root)).toBe(0);
    expect(run(["--check"], root)).toBe(0);
    writeFileSync(path.join(root, OUTPUT_DIR, "CloseIcon.tsx"), "// edited by hand\n");
    writeFileSync(path.join(root, OUTPUT_DIR, "Stray.tsx"), "");
    errors.mockClear();
    expect(run(["--check"], root)).toBe(1);
    expect(errors.mock.calls.slice(0, 2)).toEqual([
      [`stale or missing: ${OUTPUT_DIR}/CloseIcon.tsx`],
      [`not generated: ${OUTPUT_DIR}/Stray.tsx`],
    ]);
    expect(run([], root)).toBe(0);
    expect(logs.mock.calls.at(-1)).toEqual(["[icons] 4 modules: 1 written, 1 deleted"]);
    expect(run(["--check"], root)).toBe(0);
  });

  it("reports a rejected source in one line naming the file, not a stack trace", () => {
    const root = tree("custom/twap.svg");
    writeFileSync(path.join(root, "src/icons/source/custom/twap.svg"), source("<g />"));
    const errors = vi.spyOn(console, "error").mockImplementation(() => undefined);
    expect(run([], root)).toBe(1);
    expect(errors.mock.calls).toEqual([
      ["src/icons/source/custom/twap.svg: <g> is not a geometry element"],
    ]);
    expect(run(["--write"], root)).toBe(1);
    expect(errors.mock.calls.at(-1)).toEqual(["usage: node scripts/build-icons.mjs [--check]"]);
  });

  it.each([
    ["a directory that is not an origin", ["phosphor/close.svg"], /phosphor: not an origin/],
    ["a file that is not a kebab-case SVG", ["lucide/Close.svg"], /Close\.svg: not a kebab-case/],
    ["a stray file", ["lucide/README.md"], /README\.md: not a kebab-case/],
    ["two names with one component", ["lucide/a1b.svg", "custom/a-1b.svg"], /clashes with/],
  ])("fails on %s", (_, files, message) => {
    expect(() => iconSources(tree(...files))).toThrow(message);
  });
});

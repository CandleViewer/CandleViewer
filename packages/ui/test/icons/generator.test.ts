import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  componentName,
  iconSources,
  IconSourceError,
  OUTPUT_DIR,
  parseIconSource,
  renderIconModules,
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

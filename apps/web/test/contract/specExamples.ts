/**
 * Reads `docs/plan/22-api-openapi.yaml` for the recorder consumer contract tests (C-6.2; E16-S01,
 * E16-S03, E16-S04) with no YAML dependency: an example's `value` and a schema's `required` list.
 * The examples are plain maps, sequences and flow collections of scalars, so this reads exactly
 * those shapes and throws on anything else rather than guess.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const ROOT = resolve(import.meta.dirname, "../../../..");
const SPEC = readFileSync(resolve(ROOT, "docs/plan/22-api-openapi.yaml"), "utf8").split("\n");

interface Line {
  readonly indent: number;
  readonly text: string;
}
const KEY = /^([a-z_][\w-]*):(?: (.*))?$/;

/** A plain or double-quoted scalar of the examples; anything else throws rather than guess. */
function scalar(text: string): unknown {
  if (text === "null" || text === "true" || text === "false") return JSON.parse(text);
  if (/^-?\d+$/.test(text)) return Number(text);
  if (text.startsWith('"')) return JSON.parse(text) as string;
  if (/^[\w.-]+$/.test(text)) return text;
  throw new Error(`unread scalar: ${text}`);
}

/** A flow map or sequence (`{ a: 1, b: [x, y] }`), possibly joined from several lines. */
function flow(source: string): unknown {
  const tokens = (source.match(/"(?:[^"\\]|\\.)*"|[{}[\],:]|[^\s{}[\],:"][^{}[\],:]*/g) ?? []).map(
    (token) => token.trim(),
  );
  let at = 0;
  const take = (): string => tokens[at++] ?? "";
  const value = (): unknown => {
    const open = take();
    if (open !== "{" && open !== "[") return scalar(open);
    const out: Record<string, unknown> = {};
    const list: unknown[] = [];
    while (tokens[at] !== (open === "{" ? "}" : "]")) {
      if (at >= tokens.length) throw new Error(`unclosed flow: ${source}`);
      if (open === "{") {
        const key = take();
        if (take() !== ":") throw new Error(`no ':' after ${key}`);
        out[key] = value();
      } else list.push(value());
      if (tokens[at] === ",") at += 1;
    }
    at += 1;
    return open === "{" ? out : list;
  };
  const out = value();
  if (at !== tokens.length) throw new Error(`text after the flow: ${source}`);
  return out;
}

/** Each child of a block: its head line at the block's indent and the deeper lines after it. */
function children(lines: readonly Line[]): Line[][] {
  const indent = lines[0]?.indent;
  const out: Line[][] = [];
  for (const line of lines) {
    if (line.indent === indent) out.push([line]);
    else out.at(-1)?.push(line);
  }
  return out;
}

/** A block: flow, a sequence (`- …`) or a map (`key: …`), by its first line. */
function block(lines: readonly Line[]): unknown {
  const head = lines[0]?.text ?? "";
  if (/^[[{]/.test(head)) return flow(lines.map((line) => line.text).join(" "));
  if (head.startsWith("- ")) {
    return children(lines).map(([first, ...rest]) => {
      const item = first?.text.slice(2) ?? "";
      if (/^[[{]/.test(item)) return flow([item, ...rest.map((line) => line.text)].join(" "));
      if (!KEY.test(item)) return scalar(item);
      return block([{ indent: (first?.indent ?? 0) + 2, text: item }, ...rest]);
    });
  }
  const map: Record<string, unknown> = {};
  for (const [first, ...rest] of children(lines)) {
    const [, key, inline] = KEY.exec(first?.text ?? "") ?? [];
    if (key === undefined) throw new Error(`unread line: ${first?.text}`);
    const text = [inline ?? "", ...rest.map((line) => line.text)].join(" ").trim();
    map[key] =
      inline === undefined ? block(rest) : /^[[{]/.test(inline) ? flow(text) : scalar(inline);
  }
  return map;
}

/** The `value` of the first example called `name` after the line `anchor` in `22`. */
export function example(anchor: string, name: string): unknown {
  const from = SPEC.findIndex((line) => line.trim() === anchor);
  const at = SPEC.findIndex((line, i) => i > from && line.trim().startsWith(`${name}:`));
  if (from < 0 || at < 0) throw new Error(`example ${name} after ${anchor} not found`);
  const indent = SPEC[at]?.search(/\S/) ?? 0;
  const end = SPEC.findIndex(
    (line, i) => i > at && line.trim() !== "" && line.search(/\S/) <= indent,
  );
  const lines = SPEC.slice(at, end)
    .filter((line) => line.trim() !== "")
    .map((line) => ({ indent: line.search(/\S/), text: line.trim() }));
  return (block(lines) as Record<string, { value?: unknown }>)[name]?.value;
}

/** The `required` list of `components.schemas.<name>` in `22`, written flow or block. */
export function schemaRequired(name: string): string[] {
  const at = SPEC.findIndex((line) => line === `    ${name}:`);
  if (at < 0) throw new Error(`schema ${name} not found`);
  const end = SPEC.findIndex((line, i) => i > at && line.trim() !== "" && line.search(/\S/) <= 4);
  const body = SPEC.slice(at + 1, end);
  const head = body.findIndex((line) => line.startsWith("      required:"));
  if (head < 0) throw new Error(`schema ${name} has no required list`);
  const inline = body[head]?.slice("      required:".length).trim() ?? "";
  if (inline !== "") return flow(inline) as string[];
  const items: string[] = [];
  for (const line of body.slice(head + 1)) {
    const item = /^ {8}- ([\w-]+)$/.exec(line)?.[1];
    if (item === undefined) break;
    items.push(item);
  }
  return items;
}

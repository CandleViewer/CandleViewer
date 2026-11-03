/**
 * Reads `docs/plan/22-api-openapi.yaml` for the E42-S04 consumer contract tests (C-6.2). apps/web
 * has no YAML parser, so this reads the small subset the audit examples are written in: block maps
 * and lists, flow maps and lists over one or many lines, and quoted or plain scalars. Anything else
 * throws, so a reshaped example fails loudly instead of being half-read.
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

export const SPEC_PATH = resolve(
  import.meta.dirname,
  "../../../../../../docs/plan/22-api-openapi.yaml",
);

let cached: string | null = null;
export function specText(): string {
  cached ??= readFileSync(SPEC_PATH, "utf8");
  return cached;
}

const indentOf = (line: string): number => line.length - line.trimStart().length;
const blank = (line: string): boolean => line.trim() === "" || line.trim().startsWith("#");

/** The lines of the path item `path` (e.g. `/admin/audit`), up to the next path item. */
export function pathBlock(path: string): string[] {
  const lines = specText().split("\n");
  const at = lines.indexOf(`  ${path}:`);
  if (at < 0) throw new Error(`22 has no path ${path}`);
  const end = lines.findIndex((line, i) => i > at && /^ {0,2}\S/.test(line));
  return lines.slice(at, end < 0 ? undefined : end);
}

function scalar(raw: string): unknown {
  const text = raw.trim();
  if (text.startsWith('"')) return JSON.parse(text) as unknown;
  if (text.startsWith("'")) return text.slice(1, -1).replaceAll("''", "'");
  if (text === "null" || text === "~") return null;
  if (text === "true" || text === "false") return text === "true";
  if (/^-?\d+(\.\d+)?$/.test(text)) return Number(text);
  if (/[{}[\]]/.test(text)) throw new Error(`not a scalar: ${text}`);
  return text;
}

/** A flow collection (`{…}` or `[…]`), possibly over many lines. */
function flow(text: string): unknown {
  let i = 0;
  const skip = (): void => {
    while (i < text.length && /\s/.test(text.charAt(i))) i += 1;
  };
  const expect = (c: string): void => {
    skip();
    if (text.charAt(i) !== c) throw new Error(`expected "${c}" at ${i} in ${text.slice(0, 80)}`);
    i += 1;
  };
  const plain = (key: boolean): string => {
    const start = i;
    while (i < text.length) {
      const c = text.charAt(i);
      if (",{}[]\n".includes(c)) break;
      if (c === ":" && (key || /\s/.test(text.charAt(i + 1)))) break;
      i += 1;
    }
    return text.slice(start, i).trim();
  };
  const quoted = (): string => {
    const start = i;
    i += 1;
    while (i < text.length && text.charAt(i) !== '"') i += text.charAt(i) === "\\" ? 2 : 1;
    i += 1;
    return text.slice(start, i);
  };
  const value = (): unknown => {
    skip();
    const c = text.charAt(i);
    if (c === "{") {
      i += 1;
      const out: Record<string, unknown> = {};
      for (;;) {
        skip();
        if (text.charAt(i) === "}") {
          i += 1;
          return out;
        }
        const key = text.charAt(i) === '"' ? String(scalar(quoted())) : plain(true);
        expect(":");
        out[key] = value();
        skip();
        if (text.charAt(i) === ",") i += 1;
        else if (text.charAt(i) !== "}") throw new Error(`expected "," or "}" at ${i}`);
      }
    }
    if (c === "[") {
      i += 1;
      const out: unknown[] = [];
      for (;;) {
        skip();
        if (text.charAt(i) === "]") {
          i += 1;
          return out;
        }
        out.push(value());
        skip();
        if (text.charAt(i) === ",") i += 1;
        else if (text.charAt(i) !== "]") throw new Error(`expected "," or "]" at ${i}`);
      }
    }
    return scalar(c === '"' ? quoted() : plain(false));
  };
  const out = value();
  skip();
  if (i !== text.length)
    throw new Error(`trailing text after a flow value: ${text.slice(i, i + 40)}`);
  return out;
}

/** A node: a flow collection, a block list or a block map, by its first line. */
function node(lines: readonly string[]): unknown {
  const body = lines.filter((line) => !blank(line));
  const first = body[0];
  if (first === undefined) throw new Error("an empty node");
  const head = first.trimStart();
  if (head.startsWith("{") || head.startsWith("[")) return flow(body.join("\n"));
  return head.startsWith("- ") ? blockList(body) : blockMap(body);
}

function blockList(lines: readonly string[]): unknown[] {
  const base = indentOf(lines[0] ?? "");
  const items: string[][] = [];
  for (const line of lines) {
    const head = line.trimStart();
    if (indentOf(line) === base && head.startsWith("- ")) {
      items.push([`${" ".repeat(base + 2)}${head.slice(2)}`]);
    } else if (indentOf(line) > base && items.length > 0) {
      items[items.length - 1]?.push(line);
    } else {
      throw new Error(`not a list item: ${line}`);
    }
  }
  return items.map(node);
}

function blockMap(lines: readonly string[]): Record<string, unknown> {
  const base = indentOf(lines[0] ?? "");
  const out: Record<string, unknown> = {};
  let i = 0;
  while (i < lines.length) {
    const line = lines[i] ?? "";
    const match = /^ *("[^"]*"|[A-Za-z_][\w.-]*): *(.*)$/.exec(line);
    if (match === null || indentOf(line) !== base) throw new Error(`not a map entry: ${line}`);
    const [, rawKey = "", rest = ""] = match;
    const key = rawKey.startsWith('"') ? String(JSON.parse(rawKey)) : rawKey;
    let j = i + 1;
    while (j < lines.length && indentOf(lines[j] ?? "") > base) j += 1;
    const child = lines.slice(i + 1, j);
    if (rest === "") out[key] = node(child);
    else if (rest.startsWith("{") || rest.startsWith("["))
      out[key] = flow([rest, ...child].join("\n"));
    else if (child.length > 0) throw new Error(`a scalar with children: ${line}`);
    else out[key] = scalar(rest);
    i = j;
  }
  return out;
}

/** The `value` of the example `name` in the path item `path`. */
export function example(path: string, name: string): unknown {
  const block = pathBlock(path);
  const at = block.findIndex((line) => line.trim() === `${name}:`);
  if (at < 0) throw new Error(`22 ${path} has no example ${name}`);
  const indent = indentOf(block[at] ?? "");
  let end = at + 1;
  while (end < block.length && (blank(block[end] ?? "") || indentOf(block[end] ?? "") > indent)) {
    end += 1;
  }
  const parsed = node(block.slice(at + 1, end));
  if (typeof parsed !== "object" || parsed === null || !("value" in parsed)) {
    throw new Error(`22 ${path} ${name} has no value`);
  }
  return (parsed as { value: unknown }).value;
}

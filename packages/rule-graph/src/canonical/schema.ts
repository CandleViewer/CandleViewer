/**
 * The server's validate-and-dump step (canonical.py:156-157), from the published schema: bounds,
 * then each field with its default, numbers as decimal text, UUIDs lower-cased. Only what the
 * vectors pin is mirrored, the rest is a SCHEMA_VIOLATION; enums, ranges and patterns are E35's.
 */
import { RULE_IR_SCHEMA } from "@candleviewer/protocol/rule-ir";
import { RuleGraphError } from "../errors.js";
import { decimalOfNumber, decimalOfText } from "./decimal.js";

/** A canonical value. A Map holds any key of a free-form map, `__proto__` too. */
export type Canonical = string | boolean | null | Canonical[] | Map<string, Canonical>;
type Data = { readonly [key: string]: unknown };
type Props = { readonly [key: string]: Node };
type Node = Partial<Record<"$ref" | "type" | "format" | "pattern", string>> & {
  readonly anyOf?: readonly Node[];
  readonly oneOf?: readonly Node[];
  readonly enum?: readonly unknown[];
  readonly properties?: Props;
  readonly required?: readonly string[];
  readonly additionalProperties?: boolean | Node;
  readonly items?: Node;
  readonly default?: unknown;
};

const DEFS = RULE_IR_SCHEMA["$defs"] as Props;
const def = (name: string) => DEFS[name] as Node; // only names the schema defines are read
const opsOf = (name: string) => new Set(((def(name).properties as Props)["op"] as Node).enum);
const [BOOLEAN_OPS, TEMPORAL_OPS] = [opsOf("BooleanNode"), opsOf("TemporalNode")];
const OPERAND_TAGS = { metric: "MetricRef", const: "Literal_", operands: "ArithmeticNode" };
const DECIMAL_PATTERN = "^(?!^[-+.]*$)[+-]?0*\\d*\\.?\\d*$"; // pydantic's Decimal text
const UUID = /^[\da-f]{8}-[\da-f]{4}-[\da-f]{4}-[\da-f]{4}-[\da-f]{12}$/i;
const LONE_SURROGATE = /\p{Cs}/u; // under the u flag a valid pair is one code point
const [MAX_VALUES, MAX_DEPTH] = [20_000, 64]; // rules/compiler/common.py:17-18
// A free-form value (`{}`, `additionalProperties: true`) is any JSON value.
const free = (type: string): Node => ({ type, items: {}, additionalProperties: true });
const ANY = ["null", "boolean", "number", "string", "array", "object"].map(free);

function refuse(path: string, reason: string): never {
  throw new RuleGraphError("SCHEMA_VIOLATION", `${path}: ${reason}`);
}

/** Plain JSON data. `walk` handles null before it asks. */
const isData = (value: unknown): value is Data =>
  typeof value === "object" && [Object.prototype, null].includes(Object.getPrototypeOf(value));

/** A node's arms: `$ref` followed, `anyOf` flattened. */
function arms(node: Node): readonly Node[] {
  if (node.$ref !== undefined) return arms(def(node.$ref.slice("#/$defs/".length)));
  if (node.anyOf !== undefined) return node.anyOf.flatMap(arms);
  return node.type === undefined && node.oneOf === undefined ? ANY : [node];
}

/** The model the server's Discriminator picks (models.py:123-134 operands, :179-191 conditions). */
function tagOf(union: readonly Node[], value: Data): string | undefined {
  if (union.some((ref) => ref.$ref === "#/$defs/MetricRef")) {
    return Object.entries(OPERAND_TAGS).find(([key]) => Object.hasOwn(value, key))?.[1];
  }
  const op = value["op"];
  if (typeof op !== "string") return undefined;
  return BOOLEAN_OPS.has(op) ? "BooleanNode" : TEMPORAL_OPS.has(op) ? "TemporalNode" : "Comparison";
}

function text(value: string, all: readonly Node[], path: string): string {
  if (LONE_SURROGATE.test(value)) refuse(path, "text with a lone surrogate has no UTF-8 form");
  const strings = all.filter((arm) => arm.type === "string");
  // Plain text in the union wins and is kept as sent (pydantic's smart union: str is exact).
  if (strings.some((arm) => !arm.format && arm.pattern !== DECIMAL_PATTERN)) return value;
  // str(UUID) is lower case. Pydantic also reads the 32-digit, braced and urn:uuid: spellings,
  // which no vector pins: only the hyphenated one is mirrored.
  if (strings.some((arm) => arm.format === "uuid")) {
    return UUID.test(value) ? value.toLowerCase() : refuse(path, "a UUID must be hyphenated");
  }
  if (strings.length === 0) refuse(path, "text is not allowed here");
  return decimalOfText(value) ?? refuse(path, "only plain decimal text is mirrored");
}

/** A model: no unknown or missing field, and each absent field's default. */
function model(value: Data, node: Node, path: string): Map<string, Canonical> {
  const properties = node.properties as Props; // every model lists its fields
  const unknown = Object.keys(value).find((key) => !Object.hasOwn(properties, key));
  if (unknown !== undefined) refuse(`${path}.${unknown}`, "not a field of the rule IR");
  const missing = node.required?.find((key) => !Object.hasOwn(value, key));
  if (missing !== undefined) refuse(`${path}.${missing}`, "a required field is missing");
  const out = new Map<string, Canonical>();
  for (const [key, field] of Object.entries(properties)) {
    // `limits` and metric `params` default to their factory's {} (models.py:101, :288).
    const given = Object.hasOwn(value, key) ? value[key] : "default" in field ? field.default : {};
    out.set(key, walk(given, field, `${path}.${key}`));
  }
  return out;
}

function walk(value: unknown, node: Node, path: string): Canonical {
  const all = arms(node);
  const arm = (type: string) => all.find((a) => a.type === type);
  if (value === null) return arm("null") ? null : refuse(path, "null is not allowed here");
  // Read by JSON type alone. Pydantic's lax "7" or true for an integer, or 1 or "true" for a
  // boolean, are pinned by no vector and refused; an integer takes no fraction (int_from_float).
  if (typeof value === "boolean" && arm("boolean")) return value;
  if (typeof value === "number" && (arm("number") || (arm("integer") && Number.isInteger(value)))) {
    return decimalOfNumber(value) ?? refuse(path, "the number has no canonical decimal form");
  }
  if (typeof value === "string") return text(value, all, path);
  const items = Array.isArray(value) ? arm("array")?.items : undefined;
  if (items) return Array.from(value as unknown[], (item, i) => walk(item, items, `${path}[${i}]`));
  const union = all.find((a) => a.oneOf !== undefined)?.oneOf;
  const extra = arm("object")?.additionalProperties; // false for a model, else the values' schema
  if (!isData(value) || (union === undefined && extra === undefined)) {
    return refuse(path, "a value the rule IR does not allow here");
  }
  if (union !== undefined) {
    const tag = tagOf(union, value);
    return tag ? model(value, def(tag), path) : refuse(path, "no operand or condition kind fits");
  }
  if (extra === false) return model(value, arm("object") as Node, path);
  const out = new Map<string, Canonical>();
  for (const [key, item] of Object.entries(value)) {
    if (LONE_SURROGATE.test(key)) refuse(path, "a key with a lone surrogate has no UTF-8 form");
    out.set(key, walk(item, extra === true ? {} : (extra as Node), `${path}.${key}`));
  }
  return out;
}

/** The bounds, then `Rule.model_validate(ir).model_dump()`, normalised. */
export function dump(ir: unknown): Map<string, Canonical> {
  const stack: [unknown, number][] = [[ir, 0]]; // check_bounds (common.py:23-45): root at depth 0
  for (let count = 1; stack.length > 0; count++) {
    const [value, depth] = stack.pop() as [unknown, number]; // the loop runs while one is left
    if (count > MAX_VALUES || depth > MAX_DEPTH) {
      refuse("$", `the rule IR is over ${MAX_VALUES} values or ${MAX_DEPTH} levels deep`);
    }
    if (typeof value === "object" && value !== null) {
      for (const child of Object.values(value)) stack.push([child, depth + 1]);
    }
  }
  return walk(ir, RULE_IR_SCHEMA as Node, "$") as Map<string, Canonical>; // the root is a model
}

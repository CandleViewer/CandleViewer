// RFC 6901 JSON pointers over rule IR documents. An opaque region is addressed by its pointer, and
// `formToIr` writes form-derived nodes into a structural clone of the loaded IR at theirs, so
// anything the form never touched stays the same value (#1063 Technical notes). Object members
// are read as own properties only and written with `defineProperty`, so a `__proto__` member is
// data, never a prototype.

/** An RFC 6901 JSON pointer: `""` is the whole document, otherwise `/`-prefixed tokens. */
export type JsonPointer = string;

export type PointerErrorCode = "syntax" | "missing" | "not_a_container" | "bad_index";

/** A pointer that is malformed, or does not resolve where the caller needs it to. */
export class PointerError extends Error {
  override readonly name = "PointerError";
  constructor(
    readonly code: PointerErrorCode,
    readonly pointer: JsonPointer,
  ) {
    super(`JSON pointer ${JSON.stringify(pointer)}: ${code.replaceAll("_", " ")}`);
  }
}

const INDEX = /^(0|[1-9][0-9]*)$/;

/** The pointer of `tokens`, each escaped (`~` as `~0`, `/` as `~1`). */
export function encodePointer(tokens: readonly (string | number)[]): JsonPointer {
  let out = "";
  for (const token of tokens)
    out += `/${String(token).replaceAll("~", "~0").replaceAll("/", "~1")}`;
  return out;
}

/** The unescaped tokens of `pointer`; a pointer not starting with `/`, or a bad escape, throws. */
export function parsePointer(pointer: JsonPointer): string[] {
  if (pointer === "") return [];
  if (!pointer.startsWith("/")) throw new PointerError("syntax", pointer);
  return pointer
    .slice(1)
    .split("/")
    .map((raw) => {
      if (/~[^01]|~$/.test(raw)) throw new PointerError("syntax", pointer);
      return raw.replaceAll("~1", "/").replaceAll("~0", "~");
    });
}

type Container = Record<string, unknown> | unknown[];
const isContainer = (v: unknown): v is Container => typeof v === "object" && v !== null;

function child(parent: Container, token: string, pointer: JsonPointer): unknown {
  if (Array.isArray(parent)) {
    if (!INDEX.test(token)) throw new PointerError("bad_index", pointer);
    const index = Number(token);
    if (index >= parent.length) throw new PointerError("missing", pointer);
    return parent[index];
  }
  if (!Object.hasOwn(parent, token)) throw new PointerError("missing", pointer);
  return parent[token];
}

/** Whether `pointer` resolves in `doc`. A malformed pointer still throws. */
export function hasAt(doc: unknown, pointer: JsonPointer): boolean {
  try {
    getAt(doc, pointer);
    return true;
  } catch (err) {
    if (err instanceof PointerError && err.code !== "syntax") return false;
    throw err;
  }
}

/** The value at `pointer` in `doc`; throws a `PointerError` when it does not resolve. */
export function getAt(doc: unknown, pointer: JsonPointer): unknown {
  let cur = doc;
  for (const token of parsePointer(pointer)) {
    if (!isContainer(cur)) throw new PointerError("not_a_container", pointer);
    cur = child(cur, token, pointer);
  }
  return cur;
}

/**
 * Write `value` at `pointer` inside `doc`, in place: the caller passes the structural clone it owns
 * (`cloneJson`). The parent must exist; an existing member or item is replaced where it stands, so
 * member order is kept. The whole document (`""`) cannot be replaced in place.
 */
export function setAt(doc: unknown, pointer: JsonPointer, value: unknown): void {
  const tokens = parsePointer(pointer);
  const last = tokens.pop();
  if (last === undefined) throw new PointerError("syntax", pointer);
  let parent = doc;
  for (const token of tokens) {
    if (!isContainer(parent)) throw new PointerError("not_a_container", pointer);
    parent = child(parent, token, pointer);
  }
  if (!isContainer(parent)) throw new PointerError("not_a_container", pointer);
  if (Array.isArray(parent)) {
    if (!INDEX.test(last)) throw new PointerError("bad_index", pointer);
    const index = Number(last);
    if (index >= parent.length) throw new PointerError("missing", pointer);
    parent[index] = value;
    return;
  }
  Object.defineProperty(parent, last, {
    value,
    writable: true,
    enumerable: true,
    configurable: true,
  });
}

/**
 * A structural clone of a JSON document: the base `formToIr` writes into, so every value it does
 * not write is equal to the loaded one, and the loaded document is never mutated.
 */
export function cloneJson<T>(doc: T): T {
  return structuredClone(doc);
}

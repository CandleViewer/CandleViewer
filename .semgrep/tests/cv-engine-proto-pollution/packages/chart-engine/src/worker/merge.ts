// E11-X02 (F-15, CE-E02): no prototype write and no merge of an object the engine did not build.
type Bag = Record<string, unknown>;
declare const target: Bag;
declare const payload: Bag;

export function protoBad(): void {
  target.__proto__ = payload; // ruleid: cv-engine-proto-pollution
  target["__proto__"] = payload; // ruleid: cv-engine-proto-pollution
  Object.setPrototypeOf(target, payload); // ruleid: cv-engine-proto-pollution
  Reflect.setPrototypeOf(target, null); // ruleid: cv-engine-proto-pollution
  Object.assign(target, payload); // ruleid: cv-engine-proto-pollution
}

export function keyedCopyBad(): void {
  // prettier-ignore
  for (const k in payload) { // ruleid: cv-engine-proto-pollution
    target[k] = payload[k];
  }
  // prettier-ignore
  for (const k of Object.keys(payload)) { // ruleid: cv-engine-proto-pollution
    target[k] = payload[k];
  }
}

export function deepMerge(t: Bag, s: Bag): Bag {
  // prettier-ignore
  for (const k in s) { // ruleid: cv-engine-proto-pollution
    if (typeof s[k] === "object") deepMerge(t, s[k] as Bag);
  }
  return t;
}

declare const msg: { key: string; keys: string[] };
declare const Ctor: { prototype: Bag };

export function prototypeWriteBad(): void {
  Object.prototype.toString = () => ""; // ruleid: cv-engine-proto-pollution
  Ctor.prototype = payload; // ruleid: cv-engine-proto-pollution
  const p = target.constructor.prototype; // ruleid: cv-engine-proto-pollution
  Reflect.set(target, msg.key, 1); // ruleid: cv-engine-proto-pollution
  Object.defineProperty(target, msg.key, { value: 1 }); // ruleid: cv-engine-proto-pollution
  Object.defineProperties(target, payload as PropertyDescriptorMap); // ruleid: cv-engine-proto-pollution
  target[msg.key] = p; // ruleid: cv-engine-proto-pollution
  target[msg["key"]] = p; // ruleid: cv-engine-proto-pollution
}

export function expressionCopyBad(): void {
  Object.entries(payload).forEach(([k, v]) => (target[k] = v)); // ruleid: cv-engine-proto-pollution
  Object.keys(payload).forEach((k) => (target[k] = payload[k])); // ruleid: cv-engine-proto-pollution
  // prettier-ignore
  const merged = Object.keys(payload).reduce((acc: Bag, k) => { // ruleid: cv-engine-proto-pollution
    acc[k] = payload[k];
    return acc;
  }, {});
  void merged;
}

export function namedWritesOk(): void {
  Object.defineProperty(target, "kind", { value: 1 }); // ok: cv-engine-proto-pollution
  const i = 0;
  const out = new Float64Array(4);
  out[i] = 1; // ok: cv-engine-proto-pollution
  target["kind"] = 1; // ok: cv-engine-proto-pollution
}

export function readByNameOk(): Bag {
  const out = { kind: payload["kind"], id: payload["id"] }; // ok: cv-engine-proto-pollution
  Object.assign(target, { kind: "bar" }); // ok: cv-engine-proto-pollution
  return out;
}

export function countKeysOk(): number {
  let n = 0;
  // prettier-ignore
  for (const k in payload) { // ok: cv-engine-proto-pollution
    if (k.length > 0) n += 1;
  }
  return n;
}

// The runtime's per-store counts (E11-X02): a Map keyed by a received field writes no property.
declare const counts: Map<string, number>;
export function mapCountOk(): void {
  counts.set(msg.key, (counts.get(msg.key) ?? 0) + 1); // ok: cv-engine-proto-pollution
}

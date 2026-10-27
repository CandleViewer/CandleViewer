import { describe, expect, it } from "vitest";
import * as R from "../../../src/shell/crash/redact.js";

const { KEY_MARK, redactText, redactValue } = R;
// Secret-shaped values are built at run time, never written as literals (gitleaks, cv-secret-shaped-literal).
const jwt = ["a", "b", "c"].map((c) => c.repeat(12)).join(".");
const apiKey = "K".repeat(9) + "7".repeat(11); // 20 alphanumerics
const invite = "Q".repeat(20) + "-" + "z".repeat(22); // 43 URL-safe characters
const refresh = "R".repeat(32) + "_" + "s".repeat(31); // 64 URL-safe, not hex
const short = ["ab", "cd", "12"].join(""); // shapeless: only a name or a scheme marks it
const pemBody = ["Mi", "Ib", "Qz"].join("+") + "/x9"; // short runs: only the PEM rule catches them
const dashes = "-".repeat(5); // armour built at run time, like the secrets
const pem = [
  `${dashes}BEGIN PRIVATE KEY${dashes}`,
  pemBody,
  `${dashes}END PRIVATE KEY${dashes}`,
].join("\n");
const kek = "kh" + "9".repeat(4);
const SECRETS = [jwt, apiKey, invite, refresh, short, pemBody, kek, "zz" + "y".repeat(3)];
const leaks = (out: unknown): string[] => SECRETS.filter((s) => JSON.stringify(out).includes(s));

describe("redactText", () => {
  it.each([
    ["a JWT inside a message", `failed with ${jwt} at load`],
    ["a key-shaped word inside a stack frame", `Error: x\n    at f (app.js?k=${apiKey}:1:2)`],
    ["an invite token in a URL path", `GET /api/v1/invites/${invite} 404`],
    ["a refresh token", `refreshing ${refresh}`],
    ["an Authorization header", `Authorization: Bearer ${short}`],
    ["a Basic credential after its header", `Proxy-Authorization:  Basic  ${short}`],
    ["a bare Bearer credential", `retry with bearer ${short}`],
    ["a Bearer credential after any label", `token: Bearer  ${short}`],
    ["a cookie header to its line end", `Cookie: cv_s=${short}; zz=zzyyy\nnext line`],
    ["a JSON-quoted password", `{"password": "${short}"}`],
    ["PEM key material", `loaded ${pem} ok`],
    ["an unterminated PEM block", `loaded ${dashes}BEGIN KEY${dashes} ${pemBody}`],
    ["the KEK handle by name", `kek_handle=${kek}`],
  ])("redacts %s", (_name, input) => {
    expect(leaks(redactText(input))).toEqual([]);
  });

  it.each(R.KEY_NAMES)("redacts a value labelled %s, with - and _ alike", (name) => {
    for (const label of [name, name.replace(/-/g, "_"), name.replace(/_/g, "-").toUpperCase()]) {
      expect(redactText(`${label}=${short}`)).toBe(`${label}=${KEY_MARK}`);
    }
  });

  it("keeps the text around, a UUID, a commit hash and a timestamp readable", () => {
    const id = "3f2b8c1e-4a5d-4e6f-8a7b-9c0d1e2f3a4b";
    const keep = `crash ${id} at 2026-10-27T10:00:00.000Z build ${"0123456789abcdef".repeat(3).slice(0, 40)}`;
    expect(redactText(`${keep} token: ${short} {"password": "${short}"}`)).toBe(
      `${keep} token: ${KEY_MARK} {"password": "${KEY_MARK}"}`,
    );
  });

  it("is idempotent on its own markers", () => {
    const once = redactText(`Cookie: a=${short}\ntoken="${short}" ${jwt} password=${short}`);
    expect(redactText(once)).toBe(once);
  });

  it("cuts an oversize text before a run, so no partial token survives the cut", () => {
    const out = redactText("x ".repeat(2040) + jwt); // the cut falls inside the JWT
    expect(out.endsWith("...[truncated:oversize]")).toBe(true);
    expect(out).not.toContain("a".repeat(12));
  });
});

it.each([
  [jwt, "jwt-shape"],
  [apiKey, "key-shape"],
  [invite, "invite-token-shape"],
  [refresh, "refresh-token-shape"],
  ["123456", "totp-shape"],
  ["f".repeat(64), null], // a lowercase hex digest stays readable
  ["fe_dropped_frames_total_with_a_long_tail_xx", null], // a snake_case identifier stays readable
  ["17", null],
])("shapeOf(%s) is %s", (run, shape) => {
  expect(R.shapeOf(run)).toBe(shape);
});

describe("redactValue", () => {
  it("redacts by field name and by value shape in nested objects, arrays, keys and errors", () => {
    const out = redactValue({
      settings: { theme: "dark", nested: [{ access_token: short }, { note: `see ${apiKey}` }] },
      "Set-Cookie": "zzyyy",
      kek_handle: kek,
      [invite]: 1,
      error: new Error(`boom ${jwt}`),
      fn: () => short,
      // never the payload: dropped by field name, whatever the value's shape
      body: "zzyyy",
      framePayload: "zzyyy",
      request: { url: "zzyyy" },
    }) as Record<string, unknown>;
    expect(leaks(out)).toEqual([]);
    expect(out).toMatchObject({ "Set-Cookie": KEY_MARK, settings: { theme: "dark" } });
    expect(out["fn"]).toBe("[function]");
    expect(Object.keys(out).filter(R.isPayloadKey)).toEqual([]);
  });

  it("stops at the depth bound, so a cyclic structure ends too", () => {
    let nested: Record<string, unknown> = { leaf: true };
    for (let i = 0; i < 8; i += 1) nested = { a: nested };
    expect(JSON.stringify(redactValue(nested))).toMatch(/redacted:depth(?!.*leaf)/);
    const cyclic: Record<string, unknown> = {};
    cyclic["self"] = cyclic;
    expect(JSON.stringify(redactValue(cyclic))).toContain("[redacted:depth]");
  });
});

describe("camelCase credential names (M2)", () => {
  const CAMEL = [
    "accessToken", "refreshToken", "apiKey", "apiSecret", "kekHandle", "csrfToken", "armToken", "sessionToken",
  ]; // prettier-ignore

  it.each(CAMEL)("redacts %s as an object key", (name) => {
    expect(R.isRedactKey(name)).toBe(true);
    const out = redactValue({ [name]: short, nested: { [name]: { deep: short } } });
    expect(out).toEqual({ [name]: KEY_MARK, nested: { [name]: KEY_MARK } });
  });

  it.each(CAMEL)("redacts %s labelling a value in text, as name=value and name: value", (name) => {
    expect(redactText(`${name}=${short}`)).toBe(`${name}=${KEY_MARK}`);
    expect(redactText(`${name}: ${short}`)).toBe(`${name}: ${KEY_MARK}`);
    expect(redactText(`{"${name}": "${short}"}`)).toBe(`{"${name}": "${KEY_MARK}"}`);
  });

  it("redacts the CSRF double-submit cookie by its exact name, as a key and as a label", () => {
    const cookie = ["__Host", "cv_csrf"].join("-");
    expect(redactValue({ [cookie]: short })).toEqual({ [cookie]: KEY_MARK });
    expect(redactText(`sent ${cookie}=${short} next`)).toBe(`sent ${cookie}=${KEY_MARK} next`);
  });

  it("keeps camelCase names that are not credentials", () => {
    expect(["tokenCount", "sessionId", "signalName", "apiKeyLabel"].filter(R.isRedactKey)).toEqual(
      [],
    );
    expect(redactText(`sessionId=${short} tokenCount=3`)).toBe(`sessionId=${short} tokenCount=3`);
  });

  it("builds LABELLED from KEY_NAMES: longest first, each name with and without separators", () => {
    const alts = (name: string): string[] => {
      const words = name.toLowerCase().split(/[-_]+/).filter(Boolean);
      const start = /^[-_]/.test(name) ? "(?<![\\w-])[-_]+" : "\\b";
      const forms = words.length > 1 ? [words.join("[-_]"), words.join("")] : words;
      return forms.map((form) => start + form);
    };
    const names = [...R.KEY_NAMES].sort((a, b) => b.length - a.length || (a < b ? -1 : 1));
    const value = `("[^"\\n]*"?|'[^'\\n]*'?|[^\\s"',}\\]]+)`;
    const source = `((?:${names.flatMap(alts).join("|")})["']?\\s*[:=]\\s*)(?![ \\t]*["']?\\[redacted:)${value}`;
    expect(R.LABELLED.source).toBe(source);
    expect(R.LABELLED.flags).toBe("gi");
  });

  it("matches a multi-word name with separators or with none", () => {
    expect(redactText(`apikey=${short} API_KEY=${short}`)).toBe(
      `apikey=${KEY_MARK} API_KEY=${KEY_MARK}`,
    );
  });
});

describe("the backup download path (L3)", () => {
  it("becomes one marker, as the server's _DOWNLOAD_PATH_RE", () => {
    const id = "b".repeat(8);
    const tail = ["dl", "x9"].join("");
    // the server's rule: the path runs to the next `/` or space, a query string included
    expect(redactText(`GET /api/v1/admin/backups/${id}/download/${tail}?a=1 404`)).toBe(
      "GET /api/v1[redacted:download-path] 404",
    );
    expect(redactText(`GET /admin/backups//download/${tail}/more`)).toBe(
      "GET [redacted:download-path]/more",
    );
    expect(redactText("/admin/backups/x/download/")).toBe("/admin/backups/x/download/");
  });
});

describe("redactValue on hostile and non-JSON values", () => {
  const thrower = (): never => {
    throw new Error(short);
  };

  it("turns a Proxy whose has / ownKeys / getPrototypeOf traps throw into a marker, never a throw (M1)", () => {
    const trap = { has: thrower, ownKeys: thrower, getPrototypeOf: thrower };
    const proxy = new Proxy({}, trap);
    expect(redactValue(proxy)).toBe("[redacted:unrenderable]");
    expect(redactValue({ ok: 1, inner: proxy })).toEqual({
      ok: 1,
      inner: "[redacted:unrenderable]",
    });
  });

  it("keeps the other fields when one getter throws (M1)", () => {
    const value = Object.defineProperty({ ok: "yes" }, "bad", { get: thrower, enumerable: true });
    expect(redactValue(value)).toEqual({ ok: "yes", bad: "[redacted:unrenderable]" });
  });

  it("renders an Error whose name or message getter throws with a marker (M1)", () => {
    const badMessage = Object.defineProperty(new Error("x"), "message", { get: thrower });
    const badName = Object.defineProperty(new Error("y"), "name", { get: thrower });
    const oddName = Object.assign(new Error("z"), { name: { toString: thrower } });
    expect(redactValue(badMessage)).toBe("Error: [redacted:unrenderable]");
    expect(redactValue(badName)).toBe("[redacted:unrenderable]: y");
    expect(redactValue(oddName)).toBe("[redacted:unrenderable]: z");
    expect(JSON.stringify([badMessage, badName].map((e) => redactValue(e)))).not.toContain(short);
  });

  it("marks bytes, maps and sets, and redacts a String object as text (L4)", () => {
    const bytes = new TextEncoder().encode(short);
    expect(redactValue(bytes)).toBe("[redacted:bytes]");
    expect(redactValue(bytes.buffer)).toBe("[redacted:bytes]");
    expect(redactValue(new DataView(bytes.buffer))).toBe("[redacted:bytes]");
    expect(redactValue(new Map([["token", short]]))).toBe("[map]");
    expect(redactValue(new Set([short]))).toBe("[set]");
    expect(redactValue(new String(`token=${short} ${jwt}`))).toBe(
      `token=${KEY_MARK} [redacted:jwt-shape]`,
    );
  });

  it.each([
    "p",
    "data",
    "params",
    "args",
    "rawFrame",
    "wsFrame",
    "userInput",
    "inputText",
    "raw_frame",
  ])("drops the payload-carrying field %s (L6 backstop)", (key) => {
    expect(R.isPayloadKey(key)).toBe(true);
    expect(redactValue({ [key]: "zzyyy", kept: 1 })).toEqual({ kept: 1 });
  });
});

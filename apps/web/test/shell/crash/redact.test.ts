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

import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiFetch } from "../../../src/lib/http/csrfFetch";
import {
  CLIENT_REFUSAL_INSTANCE,
  OWN_OPERATIONS,
  PROTECTIVE_WRITES,
  REFUSAL_TITLES,
  REFUSED_READS,
  methodOf,
  onServerRefusal,
  viewAsRefusal,
  type ViewAsOperation,
} from "../../../src/lib/http/viewAsGuard";
import {
  resetShellState,
  setShellState,
  type HeldViewAs,
  type ViewAsState,
} from "../../../src/shell/bootstrap/store";

/**
 * E42-S03 (SCR-124): the request guard in front of the server's view-as guard (`22` "View-as
 * session"). It is a courtesy, never the control: the viewer's own operations and the eight
 * protective writes always pass (C-2.6, C-4.14), live or held; a live context refuses every other
 * write and the refused reads; a held one refuses everything else, reads included. Nothing it
 * refuses is sent or logged.
 */
const REPO = resolve(import.meta.dirname, "../../../../..");
const POLICY = "services/api/candleviewer/api/view_as_policy.py";
const GUARD = "apps/web/src/lib/http/viewAsGuard.ts";
const CONTRACT = "docs/plan/22-api-openapi.yaml";

const HELD: HeldViewAs = {
  kind: "held",
  targetId: "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0002",
  targetName: "alex",
  startedAtMs: Date.parse("2026-09-14T10:00:00Z"),
  expiresAtMs: Date.parse("2026-09-14T10:30:00Z"),
  state: "active",
  offsetMs: 0,
};
const LIVE: ViewAsState = HELD;
const ENDED: ViewAsState = { ...HELD, state: "expired" };
const WRITES = ["POST", "PUT", "PATCH", "DELETE"] as const;

/** A concrete path for a template: each `{param}` filled with a plausible id. */
const fill = (template: string): string => `/api/v1${template.replace(/\{[^}]+\}/g, "id-7")}`;
const op = ([method, template]: ViewAsOperation): [string, string] => [method, fill(template)];

async function bodyOf(res: Response | null): Promise<unknown> {
  expect(res).not.toBeNull();
  return (res as Response).json();
}

beforeEach(() => resetShellState());
afterEach(() => {
  resetShellState();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("the guard passes the C-2.6 protective writes and the viewer's own operations, live or held", () => {
  it.each(Object.entries(PROTECTIVE_WRITES))(
    "passes %s while live and while held",
    (_id, operation) => {
      const [method, path] = op(operation);
      expect(viewAsRefusal(path, method, LIVE)).toBeNull();
      expect(viewAsRefusal(path, method, ENDED)).toBeNull();
    },
  );

  it.each(OWN_OPERATIONS.map((operation) => [operation.join(" "), operation] as const))(
    "passes the viewer's own %s while live and while held",
    (_name, operation) => {
      const [method, path] = op(operation);
      expect(viewAsRefusal(path, method, LIVE)).toBeNull();
      expect(viewAsRefusal(path, method, ENDED)).toBeNull();
    },
  );

  it("names exactly the eight protective writes and the ten own operations", () => {
    expect(Object.keys(PROTECTIVE_WRITES).sort()).toEqual([
      "amendOrder",
      "amendTradeGroup",
      "cancelAllOrders",
      "cancelOrder",
      "closeAllPositions",
      "closePosition",
      "setKillSwitch",
      "setPositionTpSl",
    ]);
    expect(OWN_OPERATIONS).toHaveLength(10);
  });
});

describe("the guard refuses what the server would", () => {
  it.each(WRITES)("refuses any other %s while live: view_as_read_only", async (method) => {
    const res = viewAsRefusal("/api/v1/settings", method, LIVE);
    expect(await bodyOf(res)).toMatchObject({ status: 403, code: "view_as_read_only" });
  });

  it.each(["GET", "HEAD", "OPTIONS"])("passes a %s while live: reads answer as the target", (m) => {
    expect(viewAsRefusal("/api/v1/positions?account=a1", m, LIVE)).toBeNull();
  });

  it("refuses a refused read while live, its HEAD too, never its OPTIONS (exportWorkspace)", async () => {
    const [, path] = op(REFUSED_READS["exportWorkspace"] as ViewAsOperation);
    expect(await bodyOf(viewAsRefusal(path, "GET", LIVE))).toMatchObject({
      code: "view_as_read_only",
    });
    expect(await bodyOf(viewAsRefusal(path, "HEAD", LIVE))).toMatchObject({
      code: "view_as_read_only",
    });
    expect(viewAsRefusal(path, "OPTIONS", LIVE)).toBeNull();
  });

  it.each(["GET", "HEAD", ...WRITES])(
    "refuses any other %s while held, reads included: view_as_expired",
    async (method) => {
      const res = viewAsRefusal("/api/v1/me", method, ENDED);
      expect(await bodyOf(res)).toMatchObject({ status: 403, code: "view_as_expired" });
    },
  );

  it("matches a template's parameter as one path segment, as the router does", async () => {
    expect(viewAsRefusal("/api/v1/positions/close-all", "POST", LIVE)).toBeNull(); // closeAllPositions
    expect(viewAsRefusal("/api/v1/positions/p-1/close", "POST", LIVE)).toBeNull(); // closePosition
    expect(await bodyOf(viewAsRefusal("/api/v1/orders/a/b", "DELETE", LIVE))).toMatchObject({
      code: "view_as_read_only",
    });
    expect(await bodyOf(viewAsRefusal("/api/v1/positions/p-1/flip", "POST", LIVE))).toMatchObject({
      code: "view_as_read_only",
    });
  });

  it("reads a method in any case, from init or a Request", () => {
    expect(viewAsRefusal("/api/v1/orders/cancel-all", "post", LIVE)).toBeNull();
    expect(methodOf("/x", { method: "delete" })).toBe("DELETE");
    expect(methodOf(new Request("http://localhost/x", { method: "PATCH" }))).toBe("PATCH");
    expect(methodOf("/x")).toBe("GET");
  });

  it("answers the contract's problem, marked as the client's, with the 22 titles", async () => {
    const res = viewAsRefusal("/api/v1/settings", "PUT", LIVE) as Response;
    expect([res.status, res.headers.get("content-type")]).toEqual([
      403,
      "application/problem+json",
    ]);
    expect(await res.json()).toEqual({
      type: "https://candleviewer.local/errors/view_as_read_only",
      title: REFUSAL_TITLES.view_as_read_only,
      status: 403,
      code: "view_as_read_only",
      instance: CLIENT_REFUSAL_INSTANCE,
    });
    const contract = readFileSync(join(REPO, CONTRACT), "utf8");
    for (const [code, title] of Object.entries(REFUSAL_TITLES)) {
      const entry = new RegExp(`- code: ${code}\\n\\s+status: 403\\n\\s+title: (.+)\\n`).exec(
        contract,
      );
      expect(entry?.[1], `${CONTRACT} x-error-codes ${code}`).toBe(title);
    }
  });
});

describe("the guard judges only this origin's /api/v1/ requests, and only while a context is held", () => {
  it.each<[string, ViewAsState]>([
    ["unknown (before the boot read)", { kind: "unknown" }],
    ["none", { kind: "none" }],
  ])("passes everything while the context is %s", (_name, state) => {
    for (const method of ["GET", ...WRITES])
      expect(viewAsRefusal("/api/v1/settings", method, state)).toBeNull();
  });

  it("passes another origin's request and this origin's non-API paths", () => {
    expect(viewAsRefusal("https://example.test/api/v1/settings", "PUT", ENDED)).toBeNull();
    expect(viewAsRefusal("/assets/index.js", "GET", ENDED)).toBeNull();
    expect(viewAsRefusal("/api/v10/settings", "PUT", ENDED)).toBeNull();
  });

  it("reads the shell store's context by default", () => {
    expect(viewAsRefusal("/api/v1/settings", "PUT")).toBeNull();
    setShellState({ viewAs: HELD });
    expect(viewAsRefusal("/api/v1/settings", "PUT")).not.toBeNull();
  });
});

describe("apiFetch asks the guard first: a refusal is never sent and never logged", () => {
  function stubNetwork(answer: () => Response = () => new Response(null, { status: 204 })) {
    const sent: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        sent.push(
          `${methodOf(input, init)} ${new URL(String(input), "http://localhost").pathname}`,
        );
        return answer();
      }),
    );
    return sent;
  }

  it("answers a refused write locally, sending nothing and saying nothing", async () => {
    const sent = stubNetwork();
    const logs = (["log", "info", "warn", "error", "debug"] as const).map((level) =>
      vi.spyOn(console, level).mockImplementation(() => undefined),
    );
    setShellState({ viewAs: HELD });
    const res = await apiFetch("/api/v1/settings", { method: "PUT", body: "{}" });
    expect([res.status, sent]).toEqual([403, []]);
    expect(await res.json()).toMatchObject({ code: "view_as_read_only" });
    setShellState({ viewAs: ENDED });
    expect((await apiFetch("/api/v1/me")).status).toBe(403);
    expect(sent).toEqual([]);
    for (const log of logs) expect(log).not.toHaveBeenCalled();
  });

  it("sends a protective write and the viewer's own exit while held", async () => {
    const sent = stubNetwork();
    setShellState({ viewAs: ENDED });
    await apiFetch("/api/v1/orders/cancel-all", { method: "POST", body: "{}" });
    await apiFetch("/api/v1/auth/session/view-as", { method: "DELETE" });
    expect(sent).toEqual(["POST /api/v1/orders/cancel-all", "DELETE /api/v1/auth/session/view-as"]);
  });

  it("tells its listeners of a server's view-as refusal, and of nothing else", async () => {
    let answer = (): Response =>
      new Response(JSON.stringify({ status: 403, code: "view_as_read_only" }), { status: 403 });
    stubNetwork(() => answer());
    const heard = vi.fn();
    const off = onServerRefusal(heard);
    const res = await apiFetch("/api/v1/settings", { method: "PUT", body: "{}" });
    expect(await res.json()).toMatchObject({ code: "view_as_read_only" }); // the caller's copy is unread
    await vi.waitFor(() => expect(heard).toHaveBeenCalledTimes(1));
    answer = () =>
      new Response(JSON.stringify({ status: 403, code: "view_as_expired" }), { status: 403 });
    await apiFetch("/api/v1/me");
    await vi.waitFor(() => expect(heard).toHaveBeenCalledTimes(2));
    for (const other of [
      () => new Response(JSON.stringify({ status: 403, code: "forbidden" }), { status: 403 }),
      () => new Response("<html>403</html>", { status: 403 }),
      () => new Response(JSON.stringify({ code: "view_as_read_only" }), { status: 409 }),
    ]) {
      answer = other;
      await apiFetch("/api/v1/me");
    }
    await new Promise((settled) => setTimeout(settled, 0));
    expect(heard).toHaveBeenCalledTimes(2);
    off();
    answer = () =>
      new Response(JSON.stringify({ status: 403, code: "view_as_expired" }), { status: 403 });
    await apiFetch("/api/v1/me");
    await new Promise((settled) => setTimeout(settled, 0));
    expect(heard).toHaveBeenCalledTimes(2);
  });

  it("never tells them of its own refusals, which the context already explains", async () => {
    stubNetwork();
    const heard = vi.fn();
    const off = onServerRefusal(heard);
    setShellState({ viewAs: ENDED });
    await apiFetch("/api/v1/me");
    await new Promise((settled) => setTimeout(settled, 0));
    expect(heard).not.toHaveBeenCalled();
    off();
  });

  it("hands the caller a 403 it cannot copy (its body already read), never a rejection", async () => {
    const spent = new Response(JSON.stringify({ status: 403, code: "view_as_read_only" }), {
      status: 403,
    });
    await spent.text(); // a body read before apiFetch looks: `clone()` throws
    stubNetwork(() => spent);
    const off = onServerRefusal(vi.fn());
    await expect(apiFetch("/api/v1/settings", { method: "PUT", body: "{}" })).resolves.toBe(spent);
    off();
  });
});

/**
 * The parity pin (C-2.6, C-4.14): the guard's lists are the server's, read from
 * `view_as_policy.py` as text. It fails closed: a moved file, a literal it cannot parse in whole
 * or a list that differs fails here, naming both files, so a protective write is never refused by
 * drift and a new own operation is never held.
 */
describe(`parity with ${POLICY}`, () => {
  function policy(): string {
    try {
      return readFileSync(join(REPO, POLICY), "utf8");
    } catch (error) {
      throw new Error(
        `${GUARD}'s lists are pinned to ${POLICY}, which could not be read: ${String(error)}`,
      );
    }
  }

  /**
   * The `{ ... }` literal assigned to `name`, and the whole of its value: the statement reads
   * `NAME: Final… = frozenset({ ... })` or `NAME: Final… = MappingProxyType({ ... })`, braces
   * balanced, with only whitespace and the closing `)` after them (a comment may end the line).
   * Anything else, a union or a second literal included, throws.
   */
  function literal(text: string, name: string): string {
    const head = new RegExp(
      `^${name}: Final\\b[^=\\n]*= (?:frozenset|MappingProxyType)\\(\\s*\\{`,
      "m",
    ).exec(text);
    if (head === null) throw new Error(`${POLICY} has no ${name} literal for ${GUARD} to pin`);
    const open = head.index + head[0].length - 1;
    let depth = 0;
    for (let i = open; i < text.length; i += 1) {
      if (text[i] === "{") depth += 1;
      if (text[i] === "}") depth -= 1;
      if (depth > 0) continue;
      if (!/^\s*\)[ \t]*(?:#[^\n]*)?(?:\n|$)/.test(text.slice(i + 1)))
        throw new Error(`${POLICY}'s ${name} is more than one literal for ${GUARD} to pin`);
      return text.slice(open + 1, i);
    }
    throw new Error(`${POLICY}'s ${name} literal never closes`);
  }

  /** Every match of `entry` once comments are gone, failing unless they make up the whole of it. */
  function entries(body: string, entry: RegExp, name: string): RegExpExecArray[] {
    const code = body.replace(/#[^\n]*/g, "");
    const found = [...code.matchAll(entry)];
    const rest = code.replace(entry, "").replace(/[\s,]/g, "");
    if (found.length === 0 || rest !== "")
      throw new Error(`${POLICY}'s ${name} could not be parsed in whole for ${GUARD}: "${rest}"`);
    return found;
  }

  const PAIR = /\(\s*"([A-Z]+)"\s*,\s*"([^"]+)"\s*\)/g;
  const BY_ID = /"(\w+)"\s*:\s*\(\s*\(\s*"([A-Z]+)"\s*,\s*"([^"]+)"\s*\)\s*,\s*"[^"]*"\s*\)/g;
  const byId = (body: string, name: string): Record<string, string[]> =>
    Object.fromEntries(
      entries(body, BY_ID, name).map(([, id = "", m = "", path = ""]) => [id, [m, path]]),
    );

  it("pins OWN_OPERATIONS: the same pairs, none missing, none extra", () => {
    const server = entries(literal(policy(), "OWN_OPERATIONS"), PAIR, "OWN_OPERATIONS").map(
      ([, method = "", path = ""]) => `${method} ${path}`,
    );
    const client = OWN_OPERATIONS.map(([method, path]) => `${method} ${path}`);
    expect(new Set(client).size, `${GUARD} lists an own operation twice`).toBe(client.length);
    expect(client.sort(), `${GUARD} OWN_OPERATIONS vs ${POLICY}`).toEqual(server.sort());
  });

  it("pins PROTECTIVE_WRITES: the same operations, by operationId", () => {
    const server = byId(literal(policy(), "PROTECTIVE_WRITES"), "PROTECTIVE_WRITES");
    const client = Object.fromEntries(
      Object.entries(PROTECTIVE_WRITES).map(([id, pair]) => [id, [...pair]]),
    );
    expect(client, `${GUARD} PROTECTIVE_WRITES vs ${POLICY}`).toEqual(server);
  });

  it("pins REFUSED_READS: the same operations, by operationId", () => {
    const server = byId(literal(policy(), "REFUSED_READS"), "REFUSED_READS");
    const client = Object.fromEntries(
      Object.entries(REFUSED_READS).map(([id, pair]) => [id, [...pair]]),
    );
    expect(client, `${GUARD} REFUSED_READS vs ${POLICY}`).toEqual(server);
  });

  it("fails closed on a literal it cannot read in whole", () => {
    const changed = policy().replace('("POST", "/auth/lock"),', 'Operation("POST", "/auth/lock"),');
    expect(() => entries(literal(changed, "OWN_OPERATIONS"), PAIR, "OWN_OPERATIONS")).toThrow(
      /could not be parsed in whole/,
    );
    expect(() => literal("nothing here", "PROTECTIVE_WRITES")).toThrow(/has no PROTECTIVE_WRITES/);
  });

  it("fails closed on a list extended past its literal (a union), however the extension is spelt", () => {
    const text = policy();
    const start = text.indexOf("PROTECTIVE_WRITES: Final");
    const end = text.indexOf("\n)", start); // the line that closes the statement
    expect([start, end].every((at) => at > 0)).toBe(true);
    const union = `${text.slice(0, end)} | {"placeOrder": (("POST", "/orders"), "E29-T04")}`;
    expect(() => literal(`${union}${text.slice(end)}`, "PROTECTIVE_WRITES")).toThrow(
      /more than one literal/,
    );
    const before = text.replace(
      /(PROTECTIVE_WRITES: Final[^=\n]*= MappingProxyType\(\s*)\{/,
      '$1{"placeOrder": (("POST", "/orders"), "E29-T04")} | {',
    );
    expect(before).not.toBe(text);
    expect(() => literal(before, "PROTECTIVE_WRITES")).toThrow(/more than one literal/);
  });

  it("never counts an entry the server commented out", () => {
    const commented = policy().replace('("POST", "/auth/lock"),', '# ("POST", "/auth/lock"),');
    const server = entries(literal(commented, "OWN_OPERATIONS"), PAIR, "OWN_OPERATIONS");
    expect(server.map(([, method, path]) => `${method} ${path}`)).not.toContain("POST /auth/lock");
    expect(server).toHaveLength(OWN_OPERATIONS.length - 1);
  });
});

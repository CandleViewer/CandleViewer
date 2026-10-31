import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuditRecord } from "../src/keymap/audit";
import type { Role } from "../src/routes/rbac";

/**
 * #305 (E10-S02) PR B, the orchestrator's ruling A55 on #2701 (SEC-305B-02; DS-305B-01). A remap applies on the device
 * for every role, since WCAG 2.1.4 needs a Viewer to remap or turn off the single-character keys; its audit is POSTed
 * only for a session holding `settings:write` (the server still enforces); the stored profile and the audit outbox are
 * keyed by the signed-in user; and a record the server refuses for good is parked under a dead-letter key while the
 * outbox carries on. Each test loads its own copy of the modules, which keep their state at module level.
 */
const load = async () => ({
  ...(await import("../src/keymap/KeymapHost")),
  ...(await import("../src/keymap/HotkeyEditor")),
  ...(await import("../src/keymap/Cheatsheet")),
  ...(await import("../src/keymap/audit")),
  ...(await import("../src/keymap/profile")),
  ...(await import("../src/keymap/session")),
  ...(await import("../src/lib/auth/meCache")),
  ...(await import("../src/shell/bootstrap/store")),
});
let m: Awaited<ReturnType<typeof load>>;

beforeEach(async () => {
  window.localStorage.clear();
  vi.resetModules();
  m = await load();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

const AUDIT = "/api/v1/settings/hotkey-audit";
const PROFILE = "cv.keymap-profile.v1";
const OUTBOX = "cv.hotkey-audit-outbox.v1";
const DEAD = "cv.hotkey-audit-dead.v1";
const NOTE = "Saved on this device only.";

/** `/me` as the bootstrap applies it: the claims the guards read, then the shell's `me`. */
function signIn(id: string, role: Role): void {
  const permissions = role === "viewer" ? ["settings:read"] : ["settings:read", "settings:write"];
  act(() => {
    m.setMeClaims({ authenticated: true, role, permissions });
    m.setShellState({
      me: {
        accounts: [],
        permissions,
        role,
        user: { id, email: `${id}@example.test`, username: id, roles: [role], status: "active" },
      },
    });
  });
}

interface Post {
  readonly command_id: string;
  readonly after: string;
}
/**
 * Every audit POST's body, in order; `status` answers the nth (1-based), a thrown answer (0) is a network
 * error, and `body` is what a refusal carries (`{}` unless a test names a problem document).
 */
function stubServer(
  status: (n: number) => number = () => 204,
  body: (n: number) => string = () => "{}",
): Post[] {
  const posts: Post[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      if (String(url) !== AUDIT) return new Response("{}", { status: 404 });
      posts.push(JSON.parse(String(init?.body)) as Post);
      const code = status(posts.length);
      if (code === 0) throw new TypeError("Failed to fetch");
      return new Response(code === 204 ? null : body(posts.length), { status: code });
    }),
  );
  return posts;
}
/** A problem document as `22`'s refusals carry it: the `status` and the `code`. */
const problem = (status: number, code: string): string => JSON.stringify({ status, code });

const record = (commandId: string, after: string): AuditRecord => ({
  action: "hotkey.trading_binding_changed",
  commandId,
  before: "",
  after,
  acknowledgedUnsafe: false,
});
const stored = (key: string): unknown => JSON.parse(window.localStorage.getItem(key) ?? "null");

/** A row of the editor (its section, under the h1), never the cheatsheet's row of the same command. */
const inRow = (label: string) => {
  const h1 = screen.getByRole("heading", { level: 1, name: "Hotkeys" });
  const editor = within(h1.closest("section") as HTMLElement);
  return within(
    editor.getByText(label, { selector: 'th[scope="row"]' }).closest("tr") as HTMLElement,
  );
};
function bind(label: string, key: string, mods: readonly string[] = []): void {
  const row = inRow(label);
  for (const mod of mods)
    fireEvent.click(row.getByRole("checkbox", { name: `${mod} for ${label}` }));
  fireEvent.change(row.getByRole("textbox", { name: `Key for ${label}` }), {
    target: { value: key },
  });
  fireEvent.click(row.getByRole("button", { name: /^Save\b/ }));
}
const button = (name: string): HTMLElement => screen.getByText(name, { selector: "button" });
const CANCEL_ALL = "Cancel all working orders for symbol";

describe("A55: a remap applies on the device for every role; its audit is sent only with settings:write", () => {
  it("a Viewer's remap applies, nothing is POSTed, and the cheatsheet shows the new binding", async () => {
    const posts = stubServer();
    signIn("u-viewer", "viewer");
    const { Cheatsheet, HotkeyEditor, KeymapHost } = m;
    render(
      <>
        <KeymapHost />
        <HotkeyEditor />
        <Cheatsheet />
      </>,
    );
    bind(CANCEL_ALL, "Q", ["Ctrl", "Alt"]);
    expect(m.getBindings().get("dom.cancel_all")).toBe("Ctrl+Alt+Q");
    await act(() => m.flushAuditOutbox());
    expect([posts, m.auditOutbox()]).toEqual([[], []]);
    const dom = within(screen.getByRole("table", { name: "DOM" }));
    const row = dom.getByText(CANCEL_ALL, { selector: 'th[scope="row"]' }).closest("tr");
    expect(row).toHaveTextContent("Ctrl+Alt+Q");
    expect(stored(`${PROFILE}:u-viewer`)).toEqual({ "dom.cancel_all": "Ctrl+Alt+Q" });
  });

  it.each(["manager", "owner"] as const)(
    "a %s's remap applies and its audit is POSTed",
    async (role) => {
      const posts = stubServer();
      signIn(`u-${role}`, role);
      const { HotkeyEditor, KeymapHost } = m;
      render(
        <>
          <KeymapHost />
          <HotkeyEditor />
        </>,
      );
      bind(CANCEL_ALL, "Q", ["Ctrl", "Alt"]);
      expect(m.getBindings().get("dom.cancel_all")).toBe("Ctrl+Alt+Q");
      await vi.waitFor(() =>
        expect(posts).toEqual([
          {
            command_id: "dom.cancel_all",
            before: "Ctrl+Shift+X",
            after: "Ctrl+Alt+Q",
            acknowledged_unsafe: false,
          },
        ]),
      );
      await vi.waitFor(() => expect(m.auditOutbox()).toEqual([]));
    },
  );

  it("a Viewer's Import and Reset all apply and POST nothing, and Export stays enabled (T1)", async () => {
    const posts = stubServer();
    signIn("u-viewer", "viewer");
    const { HotkeyEditor, KeymapHost } = m;
    render(
      <>
        <KeymapHost />
        <HotkeyEditor />
      </>,
    );
    fireEvent.change(screen.getByLabelText("Import keymap JSON"), {
      target: { value: '{"ticket.submit":"Ctrl+Alt+Enter"}' },
    });
    fireEvent.click(button("Import"));
    expect(m.getBindings().get("ticket.submit")).toBe("Ctrl+Alt+Enter");
    fireEvent.click(button("Reset all"));
    expect(m.getBindings().get("ticket.submit")).toBe("Ctrl+Enter");
    await act(() => m.flushAuditOutbox());
    expect(posts).toEqual([]);
    expect(button("Export")).toBeEnabled();
    expect(button("Export")).not.toHaveAttribute("aria-disabled");
  });

  it("a session without settings:write reads one plain note, not a T2 reason: no control is disabled for it", () => {
    signIn("u-viewer", "viewer");
    render(<m.HotkeyEditor />);
    expect(screen.getByText(NOTE).tagName).toBe("P");
    expect(document.querySelector("[aria-disabled]")).toBeNull();
    expect(screen.queryByRole("img", { name: "Not available" })).toBeNull();
    expect(inRow(CANCEL_ALL).getByRole("button", { name: /^Unbind\b/ })).toBeEnabled();
  });

  it.each(["manager", "owner"] as const)("a %s reads no such note", (role) => {
    signIn(`u-${role}`, role);
    render(<m.HotkeyEditor />);
    expect(screen.queryByText(NOTE)).toBeNull();
  });
});

describe("A55: the profile and the audit outbox are keyed by user and device", () => {
  it("two users on one device keep separate profiles and separate outboxes", async () => {
    const posts = stubServer(() => 503); // the server is down: each record waits in its user's outbox
    m.setAuditSink(m.recordAudit);
    const remap = (id: string, binding: string): void =>
      act(() => m.setBindings(m.applyRebind(m.getBindings(), id, binding)));

    signIn("u-a", "owner");
    remap("dom.cancel_all", "Ctrl+Alt+Q");
    await m.flushAuditOutbox();
    expect(m.auditOutbox().map((r) => r.commandId)).toEqual(["dom.cancel_all"]);

    signIn("u-b", "manager");
    expect(m.getBindings().get("dom.cancel_all")).toBe("Ctrl+Shift+X"); // never A's remap
    expect(m.auditOutbox()).toEqual([]); // nor A's record
    const sentForA = posts.length;
    remap("ticket.submit", "Ctrl+Alt+Enter");
    await m.flushAuditOutbox();
    // under B's session only B's record goes out
    expect([...new Set(posts.slice(sentForA).map((p) => p.command_id))]).toEqual(["ticket.submit"]);
    expect(stored(`${PROFILE}:u-b`)).toEqual({ "ticket.submit": "Ctrl+Alt+Enter" });

    signIn("u-a", "owner");
    expect([m.getBindings().get("dom.cancel_all"), m.getBindings().get("ticket.submit")]).toEqual([
      "Ctrl+Alt+Q",
      "Ctrl+Enter",
    ]);
    expect(m.auditOutbox().map((r) => r.commandId)).toEqual(["dom.cancel_all"]);
    expect(stored(`${PROFILE}:u-a`)).toEqual({ "dom.cancel_all": "Ctrl+Alt+Q" });
    expect((stored(`${OUTBOX}:u-b`) as AuditRecord[]).map((r) => r.commandId)).toEqual([
      "ticket.submit",
    ]);
  });

  it("a legacy unkeyed profile is adopted once, by the first user who loads it, and removed", () => {
    window.localStorage.setItem(PROFILE, JSON.stringify({ "dom.zoom_in": "J" }));
    signIn("u-a", "owner");
    expect(m.getBindings().get("dom.zoom_in")).toBe("J");
    expect([window.localStorage.getItem(PROFILE), stored(`${PROFILE}:u-a`)]).toEqual([
      null,
      { "dom.zoom_in": "J" },
    ]);
    signIn("u-b", "owner");
    expect(m.getBindings().get("dom.zoom_in")).toBe("+");
  });

  it("a legacy unkeyed profile is adopted by an import's rules: no acknowledgement carries over (SEC-305BF-01)", () => {
    // Cancel-all on a bare `Del` stands only on E49-S07's acknowledgement, which the device's earlier user gave
    window.localStorage.setItem(PROFILE, JSON.stringify({ "dom.cancel_all": "Del" }));
    signIn("u-b", "owner"); // the second user, who acknowledged nothing
    expect(m.getBindings().get("dom.cancel_all")).toBe("Ctrl+Shift+X");
    // what was adopted is what is kept: under the adopting user's key, and the legacy key is gone
    expect([window.localStorage.getItem(PROFILE), stored(`${PROFILE}:u-b`)]).toEqual([null, {}]);
  });

  it("with no user named, a remap holds for the page only and nothing is queued", () => {
    act(() =>
      m.setMeClaims({ authenticated: true, role: "owner", permissions: ["settings:write"] }),
    );
    m.setAuditSink(m.recordAudit);
    act(() => m.setBindings(m.applyRebind(m.getBindings(), "dom.cancel_all", "Ctrl+Alt+Q")));
    expect(m.getBindings().get("dom.cancel_all")).toBe("Ctrl+Alt+Q");
    expect([window.localStorage.length, m.auditOutbox()]).toEqual([0, []]);
  });

  it("the profile follows a change of user only, and a listener stops once unsubscribed", () => {
    const seen = vi.fn();
    const off = m.subscribeKeymapUser(seen);
    signIn("u-a", "owner");
    act(() => m.setShellState({ environment: "demo" })); // another change of the shell's state
    signIn("u-a", "owner"); // the same user again
    signIn("u-b", "viewer");
    expect(seen).toHaveBeenCalledTimes(2);
    off();
    signIn("u-c", "owner");
    expect(seen).toHaveBeenCalledTimes(2);
  });

  it("a stored outbox is read back for its own user only", () => {
    window.localStorage.setItem(
      `${OUTBOX}:u-a`,
      JSON.stringify([record("dom.cancel_all", "Ctrl+Alt+Q")]),
    );
    signIn("u-b", "owner");
    expect(m.auditOutbox()).toEqual([]);
    signIn("u-a", "owner");
    expect(m.auditOutbox()).toEqual([record("dom.cancel_all", "Ctrl+Alt+Q")]);
  });
});

/**
 * The server's first answer is a refusal a later attempt can pass: the record stays first in line,
 * nothing is parked or said, and the next flush sends both records, oldest first, as after a 5xx.
 */
async function expectKeptFirstInLine(status: number, body: string): Promise<void> {
  const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
  const posts = stubServer(
    (n) => (n === 1 ? status : 204),
    () => body,
  );
  signIn("u-a", "owner");
  act(() => {
    m.recordAudit(record("dom.cancel_all", "Ctrl+Alt+Q"));
    m.recordAudit(record("ticket.submit", "Ctrl+Alt+Enter"));
  });
  await m.flushAuditOutbox(); // the refusal
  expect(m.auditOutbox().map((r) => r.commandId)).toEqual(["dom.cancel_all", "ticket.submit"]);
  await m.flushAuditOutbox(); // a later attempt passes: both go, oldest first
  expect(m.auditOutbox()).toEqual([]);
  expect(posts.map((p) => p.command_id)).toEqual([
    "dom.cancel_all",
    "dom.cancel_all",
    "ticket.submit",
  ]);
  expect([window.localStorage.getItem(`${DEAD}:u-a`), warn.mock.calls.length]).toEqual([null, 0]);
}

describe("SEC-305B-02: a record the server refuses for good is parked, and the outbox carries on", () => {
  it.each([
    { status: 422, code: "validation_failed" },
    { status: 403, code: "forbidden" },
  ])(
    "a $status $code parks the record under the dead-letter key, said once",
    async ({ status, code }) => {
      const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
      const posts = stubServer(
        (n) => (n === 1 ? status : 204),
        () => problem(status, code),
      );
      signIn("u-a", "owner");
      act(() => {
        m.recordAudit(record("dom.cancel_all", "Ctrl+Alt+Q"));
        m.recordAudit(record("ticket.submit", "Ctrl+Alt+Enter"));
      });
      await vi.waitFor(() => expect(m.auditOutbox()).toEqual([]));
      expect(posts.map((p) => p.command_id)).toEqual(["dom.cancel_all", "ticket.submit"]);
      expect(stored(`${DEAD}:u-a`)).toEqual([
        { status, record: record("dom.cancel_all", "Ctrl+Alt+Q") },
      ]);
      expect(warn).toHaveBeenCalledTimes(1);
      expect(String(warn.mock.calls[0]?.[0])).toContain(String(status));
      await m.flushAuditOutbox(); // nothing is left to send, and nothing is said again
      expect([posts.length, warn.mock.calls.length]).toEqual([2, 1]);
    },
  );

  it("a network error or a 5xx keeps the record first in line, and nothing is parked", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    const posts = stubServer((n) => [0, 503][n - 1] ?? 204);
    signIn("u-a", "owner");
    act(() => {
      m.recordAudit(record("dom.cancel_all", "Ctrl+Alt+Q"));
      m.recordAudit(record("ticket.submit", "Ctrl+Alt+Enter"));
    });
    await m.flushAuditOutbox(); // a network error
    expect(m.auditOutbox().map((r) => r.commandId)).toEqual(["dom.cancel_all", "ticket.submit"]);
    await m.flushAuditOutbox(); // a 503
    expect(m.auditOutbox()).toHaveLength(2);
    await m.flushAuditOutbox(); // the server is back: both go, oldest first
    expect(m.auditOutbox()).toEqual([]);
    expect(posts.map((p) => p.command_id)).toEqual([
      "dom.cancel_all",
      "dom.cancel_all",
      "dom.cancel_all",
      "ticket.submit",
    ]);
    expect([window.localStorage.getItem(`${DEAD}:u-a`), warn.mock.calls.length]).toEqual([null, 0]);
  });

  it.each([401, 408, 429])(
    "a %i keeps the record first in line, and nothing is parked (CR-305BF-02)",
    (status) => expectKeptFirstInLine(status, "{}"),
  );

  // 22's Forbidden is also the CSRF guard's, a read-only session's and a view-as context's refusal,
  // which a later attempt can pass: only `forbidden` (the role lacks `settings:write`) is final
  it.each([
    { what: "csrf_token_invalid", body: problem(403, "csrf_token_invalid") },
    { what: "session_read_only", body: problem(403, "session_read_only") },
    { what: "view_as_read_only", body: problem(403, "view_as_read_only") },
    { what: "no code", body: "{}" },
    { what: "an unreadable body", body: "<html>403 Forbidden</html>" },
  ])(
    "a 403 ($what) keeps the record first in line, and nothing is parked (CR-305BF-01)",
    ({ body }) => expectKeptFirstInLine(403, body),
  );

  it("a legacy unkeyed outbox is never read or sent, whoever signs in (CR-305BF-02)", async () => {
    window.localStorage.setItem(OUTBOX, JSON.stringify([record("dom.cancel_all", "Ctrl+Alt+Q")]));
    const read = vi.spyOn(Storage.prototype, "getItem");
    const posts = stubServer();
    signIn("u-a", "owner");
    act(() => m.recordAudit(record("ticket.submit", "Ctrl+Alt+Enter")));
    await vi.waitFor(() => expect(m.auditOutbox()).toEqual([]));
    signIn("u-b", "manager");
    await m.flushAuditOutbox();
    expect(posts.map((p) => p.command_id)).toEqual(["ticket.submit"]); // never the legacy record
    expect(read.mock.calls.map(([key]) => key)).not.toContain(OUTBOX);
  });
});

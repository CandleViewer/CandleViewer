import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { fireEvent, render, screen, within } from "@testing-library/react";
import type { JSX } from "react";
import { describe, expect, it, vi } from "vitest";
import { AppShell } from "../../../src/features/app-shell/AppShell";
import { PANIC_LEGS, ShellPanicSlot } from "../../../src/features/app-shell/slots";
import { KEYMAP } from "../../../src/keymap/keymap";
import { reservedBy, validateBinding } from "../../../src/keymap/validate";

// axe-core is a transitive dependency of @axe-core/playwright (already a devDependency).
const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };

/** Elements reachable by Tab, in document order (jsdom has no real Tab traversal). */
function tabStops(root: HTMLElement): HTMLElement[] {
  const sel =
    "a[href], button:not([disabled]), input:not([disabled]), select, textarea, [tabindex]";
  return [...root.querySelectorAll<HTMLElement>(sel)].filter((el) => el.tabIndex >= 0);
}

function shell(panic?: JSX.Element) {
  return render(
    <AppShell mainId="m" connection={<button type="button">Connection</button>} panic={panic}>
      <h1>Screen</h1>
    </AppShell>,
  );
}

describe("E10-S01 S7: the reserved CMP-211 slot is empty until E39-S05 mounts", () => {
  it("renders nothing: no node, no focusable element, nothing in the accessibility tree", () => {
    const { container } = render(<ShellPanicSlot />);
    expect(container.childNodes).toHaveLength(0);
    expect(tabStops(container)).toHaveLength(0);
    expect(screen.queryAllByRole("button")).toHaveLength(0);
    expect(screen.queryAllByRole("group")).toHaveLength(0);
  });

  it("mounted in the header, it leaves the DOM and the Tab order unchanged", () => {
    const without = shell();
    const before = without.container.innerHTML;
    const stopsBefore = tabStops(without.container).map((el) => el.outerHTML);
    without.unmount();
    const withSlot = shell(<ShellPanicSlot />);
    expect(withSlot.container.innerHTML).toBe(before);
    expect(tabStops(withSlot.container).map((el) => el.outerHTML)).toEqual(stopsBefore);
    expect(
      within(screen.getByRole("banner")).queryByRole("button", {
        name: /flatten|cancel all|freeze/i,
      }),
    ).toBeNull();
  });

  it("a consumer passed into the slot renders last in the header (banner) landmark", () => {
    shell(<div role="group" aria-label="Safety" />);
    const header = screen.getByRole("banner");
    const group = within(header).getByRole("group", { name: "Safety" });
    expect(header.lastElementChild).toBe(group);
  });

  it("keeps the C-2.6 carve-out: view-as never gates FLATTEN ALL… or CANCEL ALL…", () => {
    const keys = (a: keyof typeof PANIC_LEGS) => PANIC_LEGS[a].reasons.map((r) => r.key);
    const tail = [
      "rbac.permission",
      "rbac.owner_only",
      "health.offline",
      "health.protocol_incompatible",
    ];
    expect(keys("flatten")).toEqual(tail);
    expect(keys("cancel")).toEqual(tail);
    expect(keys("kill")).toEqual(["rbac.view_as", ...tail]);
    expect(PANIC_LEGS.kill.reasons[0]).toEqual({
      leg: "view_as",
      key: "rbac.view_as",
      onlyOn: "global-freeze-and-release",
    });
  });

  it("each leg's permission is its endpoint's x-rbac permission in the REST contract", () => {
    const spec = readFileSync(
      resolve(import.meta.dirname, "../../../../../docs/plan/22-api-openapi.yaml"),
      "utf8",
    );
    /** The first `x-rbac` permission under `post:` of a top-level path. */
    const postPermission = (path: string): string | undefined => {
      const at = spec.indexOf(`\n  ${path}:\n`);
      expect(at, path).toBeGreaterThan(-1);
      const next = spec.slice(at + 1).search(/\n {2}\/|\n\S/);
      const block = spec.slice(at, next === -1 ? undefined : at + 1 + next);
      const post = block.indexOf("\n    post:\n");
      expect(post, `${path} post`).toBeGreaterThan(-1);
      return /x-rbac: \{ permissions: \[([a-z_]+:[a-z_]+)\]/.exec(block.slice(post))?.[1];
    };
    expect(PANIC_LEGS.flatten.permission).toBe(postPermission("/positions/close-all"));
    expect(PANIC_LEGS.cancel.permission).toBe(postPermission("/orders/cancel-all"));
    expect(PANIC_LEGS.kill.permission).toBe(postPermission("/trading/kill-switch"));
  });

  it("has no serious or critical axe violations with the slot mounted", async () => {
    const { container } = shell(<ShellPanicSlot />);
    const { violations } = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    }); // jsdom has no layout
    expect(violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
  });
});

describe("E10-S01 S7: Ctrl+Shift+K is reserved for the freeze confirmation, with no handler", () => {
  it("no keymap command binds it, and rebinding any command to it is refused", () => {
    expect(KEYMAP.filter((c) => c.defaultBinding === "Ctrl+Shift+K")).toEqual([]);
    expect(reservedBy("Ctrl+Shift+K")).toMatch(/Safety cluster/);
    const current = new Map(KEYMAP.map((c) => [c.id, c.defaultBinding]));
    expect(validateBinding("global.palette", "Ctrl+Shift+K", current)).toMatchObject({
      kind: "reserved",
    });
  });

  it("pressing it does nothing: no command runs, no notice, the default is not prevented", async () => {
    vi.resetModules();
    const { KeymapHost, registerCommand } = await import("../../../src/keymap/KeymapHost");
    const run = vi.fn();
    const off = registerCommand("global.palette", run);
    render(<KeymapHost />);
    const notPrevented = fireEvent.keyDown(window, { key: "k", ctrlKey: true, shiftKey: true });
    expect(notPrevented).toBe(true);
    expect(run).not.toHaveBeenCalled();
    expect(screen.getByTestId("toast-host").childNodes).toHaveLength(0);
    off();
  });
});

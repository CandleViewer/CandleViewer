// @vitest-environment jsdom
import { expect, fireEvent, fn, userEvent, within } from "storybook/test";
import { describe, it } from "vitest";
import {
  Button,
  IconButton,
  RBAC_REASONS,
  RbacGate,
  Toggle,
  formatRbacReason,
  type RbacGateProps,
  type RbacReasonKey,
} from "../src/components/index.js";
import { mount } from "./theme/mount.js";

const button = (host: HTMLElement): HTMLButtonElement =>
  within(host).getByRole("button", { name: "Place order" }) as HTMLButtonElement;

describe("RBAC_REASONS (E09-D09 §3.1)", () => {
  it("holds exactly the seven keys of the vocabulary", () => {
    expect(Object.keys(RBAC_REASONS).sort()).toEqual([
      "rbac.account",
      "rbac.account_read_only",
      "rbac.env",
      "rbac.owner_only",
      "rbac.permission",
      "rbac.read_only",
      "rbac.view_as",
    ]);
  });

  it("keeps every sentence to one line of at most 60 characters, ending in a full stop", () => {
    for (const text of Object.values(RBAC_REASONS)) {
      expect(text.length).toBeLessThanOrEqual(60);
      expect(text).toMatch(/^[^.]+\.$/);
    }
  });

  it("fills the verb and the view-as target; fixed strings take no fills", () => {
    expect(formatRbacReason("rbac.permission", { verb: "use the kill switch" })).toBe(
      "Your role can't use the kill switch.",
    );
    expect(formatRbacReason("rbac.owner_only", { verb: "release the kill switch" })).toBe(
      "Only the owner can release the kill switch.",
    );
    expect(formatRbacReason("rbac.view_as", { user: "alex" })).toBe(
      "Read-only while viewing as alex.",
    );
    expect(formatRbacReason("rbac.env")).toBe("Live trading isn't enabled for you.");
  });
});

describe("RbacGate (CMP-079)", () => {
  it("allowed renders the child untouched: no wrapper, no description, activation fires", async () => {
    const onClick = fn();
    const host = await mount(
      <RbacGate allowed reason="rbac.account">
        <Button onClick={onClick}>Place order</Button>
      </RbacGate>,
    );
    const control = button(host);
    expect(host.firstElementChild).toBe(control);
    expect(control.hasAttribute("aria-disabled")).toBe(false);
    expect(control.hasAttribute("aria-describedby")).toBe(false);
    await userEvent.click(control);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("denied: aria-disabled, never disabled, described by the reason, focusable, inert", async () => {
    const onClick = fn();
    const host = await mount(
      <RbacGate allowed={false} reason="rbac.permission" fills={{ verb: "place orders" }}>
        <Button onClick={onClick}>Place order</Button>
      </RbacGate>,
    );
    const control = button(host);
    expect(control.getAttribute("aria-disabled")).toBe("true");
    expect(control.hasAttribute("disabled")).toBe(false);
    const describedBy = control.getAttribute("aria-describedby") ?? "";
    expect(document.getElementById(describedBy)?.textContent).toBe("Your role can't place orders.");
    expect(control).toHaveAccessibleDescription("Your role can't place orders.");
    await userEvent.tab();
    expect(control).toHaveFocus();
    await userEvent.keyboard("{Enter}");
    await userEvent.keyboard(" ");
    fireEvent.click(control);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("keeps the wrapped control's role and full name on other atoms", async () => {
    const host = await mount(
      <>
        <RbacGate allowed={false} reason="rbac.env">
          <IconButton icon="chevron-down" label="Order settings" />
        </RbacGate>
        <RbacGate allowed={false} reason="rbac.view_as" fills={{ user: "alex" }}>
          <Toggle label="Sound alerts" />
        </RbacGate>
      </>,
    );
    const canvas = within(host);
    expect(canvas.getByRole("button", { name: "Order settings" })).toHaveAccessibleDescription(
      "Live trading isn't enabled for you.",
    );
    const toggle = canvas.getByRole("switch", { name: "Sound alerts" });
    expect(toggle).toHaveAccessibleDescription("Read-only while viewing as alex.");
    await userEvent.click(toggle);
    expect(toggle.getAttribute("aria-checked")).toBe("false");
  });

  it("type: allowed={false} without a reason, or a key without its fills, does not compile", () => {
    // @ts-expect-error a T2 control must say why: `reason` is required when `allowed` is false.
    const missing: RbacGateProps = { allowed: false, children: <Button>Save</Button> };
    // @ts-expect-error `rbac.permission` has a `{verb}` fill, so `fills` is required.
    const unfilled: RbacGateProps = {
      allowed: false,
      reason: "rbac.permission",
      children: <Button>Save</Button>,
    };
    const invented: RbacGateProps = {
      allowed: false,
      // @ts-expect-error only D09 §3.1 keys exist; a screen never writes its own string.
      reason: "No access.",
      children: <Button>Save</Button>,
    };
    expect([missing, unfilled, invented]).toHaveLength(3);
  });
});

/**
 * RBAC matrix (per role × action), from E09-D09 §3.1 and its rulings: a Manager holds `orders:write`
 * and `killswitch:write`, a Viewer neither; releasing the kill switch and `recording:write` are
 * owner-only. Fixture only: the server decides; the gate renders what it is told (C-12.4).
 */
type Role = "owner" | "manager" | "viewer";
interface ActionRow {
  readonly label: string;
  readonly verb: string;
  readonly expected: Readonly<Record<Role, RbacReasonKey | null>>;
}
const ACTIONS: readonly ActionRow[] = [
  {
    label: "Place order",
    verb: "place orders",
    expected: { owner: null, manager: null, viewer: "rbac.permission" },
  },
  {
    label: "Engage kill switch",
    verb: "use the kill switch",
    expected: { owner: null, manager: null, viewer: "rbac.permission" },
  },
  {
    label: "Release kill switch",
    verb: "release the kill switch",
    expected: { owner: null, manager: "rbac.owner_only", viewer: "rbac.owner_only" },
  },
  {
    label: "Start recording",
    verb: "change recording",
    expected: { owner: null, manager: "rbac.owner_only", viewer: "rbac.owner_only" },
  },
];
const ROLES: readonly Role[] = ["owner", "manager", "viewer"];
const CASES = ROLES.flatMap((role) => ACTIONS.map((row) => [role, row.label, row] as const));

describe("RbacGate RBAC matrix", () => {
  it.each(CASES)("%s × %s", async (role, label, { verb, expected }) => {
    const key = expected[role];
    const gate: RbacGateProps =
      key === "rbac.permission" || key === "rbac.owner_only"
        ? { allowed: false, reason: key, fills: { verb }, children: <Button>{label}</Button> }
        : { allowed: true, children: <Button>{label}</Button> };
    const host = await mount(<RbacGate {...gate} />);
    const control = within(host).getByRole("button", { name: label });
    if (key === null) {
      expect(control.hasAttribute("aria-disabled")).toBe(false);
    } else {
      expect(control.getAttribute("aria-disabled")).toBe("true");
      expect(control).toHaveAccessibleDescription(formatRbacReason(key, { verb }));
    }
  });
});

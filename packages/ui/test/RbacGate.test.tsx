// @vitest-environment jsdom
import { createRequire } from "node:module";
import { act, useState, type JSX } from "react";
import { createPortal } from "react-dom";
import { expect, fireEvent, fn, userEvent, within } from "storybook/test";
import { describe, it, vi } from "vitest";
import {
  Button,
  Callout,
  FormField,
  IconButton,
  RBAC_REASONS,
  RbacGate,
  TextInput,
  Toggle,
  formatRbacReason,
  type RbacGateProps,
  type RbacReasonKey,
} from "../src/components/index.js";
import { mount } from "./theme/mount.js";
import { clearPolite, politeText } from "./theme/polite.js";

type Axe = {
  run: (context: object, options?: object) => Promise<{ violations: { impact?: string | null }[] }>;
};
const axe = createRequire(createRequire(import.meta.url).resolve("@storybook/addon-a11y"))(
  "axe-core",
) as Axe;

async function seriousAxe(host: HTMLElement): Promise<unknown[]> {
  const { violations } = await axe.run(
    { include: [host] },
    { rules: { "color-contrast": { enabled: false } } },
  );
  return violations.filter((v) => v.impact === "serious" || v.impact === "critical");
}

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

  it("denied: Enter, click and a dispatched click each announce the reason once, never call the handler", async () => {
    const onClick = fn();
    const host = await mount(
      <RbacGate allowed={false} reason="rbac.permission" fills={{ verb: "place orders" }}>
        <Button onClick={onClick}>Place order</Button>
      </RbacGate>,
    );
    const control = button(host);
    const reason = "Your role can't place orders.";
    expect(await politeText()).toBe("");
    await userEvent.tab();
    expect(await politeText()).toBe("");
    await userEvent.keyboard("{Enter}");
    expect(await politeText()).toBe(reason);
    clearPolite();
    await userEvent.click(control);
    expect(await politeText()).toBe(reason);
    clearPolite();
    fireEvent.click(control);
    expect(await politeText()).toBe(reason);
    expect(document.querySelectorAll("[role=status]")).toHaveLength(1);
    expect(onClick).not.toHaveBeenCalled();
  });

  it("allowed: an activation announces nothing", async () => {
    const host = await mount(
      <RbacGate allowed reason="rbac.account">
        <Button>Place order</Button>
      </RbacGate>,
    );
    await userEvent.click(button(host));
    expect(await politeText()).toBe("");
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

const OWNER_ONLY = "Only the owner can change account settings.";

describe("RbacGate forms (E05-D02 G15, E09-D09 §2.2)", () => {
  it("tooltip: the icon keeps its name, badges the lock, echoes the reason on hover and focus; Esc hides it", async () => {
    vi.useFakeTimers();
    try {
      const host = await mount(
        <RbacGate
          form="tooltip"
          allowed={false}
          reason="rbac.owner_only"
          fills={{ verb: "change account settings" }}
        >
          <IconButton icon="settings" label="Account settings" />
        </RbacGate>,
      );
      const control = within(host).getByRole("button", { name: "Account settings" });
      const echo = (): HTMLElement | null => document.querySelector<HTMLElement>(".cv-tooltip");
      expect(control).toHaveAttribute("aria-disabled", "true");
      expect(control).not.toHaveAttribute("disabled");
      expect(control).not.toHaveAttribute("title");
      expect(control).toHaveAccessibleDescription(OWNER_ONLY);
      expect(control.querySelector(".cv-icon-button__badge")).not.toBeNull();
      expect(within(control).getByRole("img", { name: "Not available" })).toBeInTheDocument();
      await act(async () => {
        fireEvent.pointerOver(control);
        vi.advanceTimersByTime(300);
      });
      expect(echo()?.hidden).toBe(false);
      expect(echo()).toHaveTextContent(OWNER_ONLY);
      await act(async () => {
        fireEvent.pointerOut(control);
        vi.advanceTimersByTime(1000);
      });
      await act(async () => control.focus());
      expect(echo()?.hidden).toBe(false);
      await act(async () => {
        fireEvent.keyDown(control, { key: "Escape" });
      });
      expect(echo()?.hidden).toBe(true);
      expect(control).toHaveFocus();
    } finally {
      vi.useRealTimers();
    }
  });

  it("tooltip: a control with visible text warns in development", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    try {
      await mount(
        <RbacGate form="tooltip" allowed={false} reason="rbac.env">
          <Button>Place order</Button>
        </RbacGate>,
      );
      expect(warn).toHaveBeenCalledWith(expect.stringContaining("icon-only"));
    } finally {
      warn.mockRestore();
    }
  });

  it("tooltip: the misuse warning fires once per mount, not on every re-render", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    let bump: () => void = () => undefined;
    function Host(): JSX.Element {
      const [n, setN] = useState(0);
      bump = () => setN((v) => v + 1);
      return (
        <RbacGate form="tooltip" allowed={false} reason="rbac.env">
          <Button>{`Place order ${n}`}</Button>
        </RbacGate>
      );
    }
    try {
      await mount(<Host />);
      await act(async () => bump());
      await act(async () => bump());
      expect(warn).toHaveBeenCalledTimes(1);
    } finally {
      warn.mockRestore();
    }
  });

  it("tooltip: an icon-only control does not warn", async () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => undefined);
    try {
      await mount(
        <RbacGate form="tooltip" allowed={false} reason="rbac.env">
          <IconButton icon="settings" label="Account settings" />
        </RbacGate>,
      );
      expect(warn).not.toHaveBeenCalled();
    } finally {
      warn.mockRestore();
    }
  });

  it("tooltip: a press re-announces the reason once and calls nothing", async () => {
    const onClick = fn();
    const host = await mount(
      <RbacGate
        form="tooltip"
        allowed={false}
        reason="rbac.owner_only"
        fills={{ verb: "change account settings" }}
      >
        <IconButton icon="settings" label="Account settings" onClick={onClick} />
      </RbacGate>,
    );
    clearPolite();
    await userEvent.click(within(host).getByRole("button", { name: "Account settings" }));
    expect(await politeText()).toBe(OWNER_ONLY);
    expect(document.querySelectorAll("[role='status']")).toHaveLength(1);
    expect(onClick).not.toHaveBeenCalled();
  });

  const notice = (allowed: boolean): JSX.Element => {
    const gate = { form: "notice", noticeId: "panel-notice" } as const;
    const deny = allowed
      ? ({ allowed: true } as const)
      : ({
          allowed: false,
          reason: "rbac.owner_only",
          fills: { verb: "change account settings" },
        } as const);
    return (
      <>
        <Callout id="panel-notice" title={OWNER_ONLY} live="off" />
        <RbacGate {...gate} {...deny}>
          <Button>Save</Button>
        </RbacGate>
        <RbacGate {...gate} {...deny}>
          <FormField label="Display name">
            <TextInput />
          </FormField>
        </RbacGate>
      </>
    );
  };

  it("notice: every gated control points at the one notice; no own node, no echo, the sentence once", async () => {
    const host = await mount(notice(false));
    const save = within(host).getByRole("button", { name: "Save" });
    const field = within(host).getByRole("textbox", { name: "Display name" });
    for (const control of [save, field]) {
      expect(control).toHaveAttribute("aria-disabled", "true");
      expect(control).not.toHaveAttribute("disabled");
      expect(control).toHaveAttribute("aria-describedby", "panel-notice");
      expect(control).toHaveAccessibleDescription(OWNER_ONLY);
    }
    expect(field).toHaveAttribute("readonly");
    expect(within(host).getByRole("img", { name: "Not available" })).toBeInTheDocument();
    const copies = [...host.querySelectorAll("*")].filter(
      (n) => n.childElementCount === 0 && n.textContent === OWNER_ONLY,
    );
    expect(copies).toHaveLength(1);
    expect(document.querySelectorAll("#panel-notice")).toHaveLength(1);
    await act(async () => save.focus());
    expect(document.querySelector(".cv-tooltip")).toBeNull();
  });

  it("notice: a press still re-announces the reason once and calls nothing", async () => {
    const onClick = fn();
    const host = await mount(
      <>
        <Callout id="n" title={OWNER_ONLY} live="off" />
        <RbacGate
          form="notice"
          noticeId="n"
          allowed={false}
          reason="rbac.owner_only"
          fills={{ verb: "change account settings" }}
        >
          <Button onClick={onClick}>Save</Button>
        </RbacGate>
      </>,
    );
    const panel = document.getElementById("n");
    const silent = (): void => {
      expect(panel).not.toHaveAttribute("role");
      expect(panel).not.toHaveAttribute("aria-live");
      expect(panel).toHaveTextContent(OWNER_ONLY);
    };
    silent();
    clearPolite();
    await userEvent.click(within(host).getByRole("button", { name: "Save" }));
    expect(await politeText()).toBe(OWNER_ONLY);
    expect(document.querySelectorAll("[role='status']")).toHaveLength(1);
    expect(onClick).not.toHaveBeenCalled();
    silent();
  });

  it("notice: a descendant with the same sentence follows the notice, portalled or not (by design)", async () => {
    const host = await mount(
      <RbacGate
        form="notice"
        noticeId="n"
        allowed={false}
        reason="rbac.owner_only"
        fills={{ verb: "change account settings" }}
      >
        <>
          <Button disabledReason={OWNER_ONLY}>Save</Button>
          {createPortal(<Button disabledReason={OWNER_ONLY}>Send</Button>, document.body)}
        </>
      </RbacGate>,
    );
    expect(within(host).getByRole("button", { name: "Save" })).toHaveAttribute(
      "aria-describedby",
      "n",
    );
    expect(within(document.body).getByRole("button", { name: "Send" })).toHaveAttribute(
      "aria-describedby",
      "n",
    );
  });

  it("notice: a portalled descendant with another reason keeps its own node", async () => {
    const other = "Live trading isn't enabled for you.";
    function Host({ disabledReason }: { readonly disabledReason?: string }): JSX.Element {
      return (
        <>
          <Button {...(disabledReason === undefined ? {} : { disabledReason })}>Save</Button>
          {createPortal(<Button disabledReason={other}>Send</Button>, document.body)}
        </>
      );
    }
    const host = await mount(
      <RbacGate
        form="notice"
        noticeId="n"
        allowed={false}
        reason="rbac.owner_only"
        fills={{ verb: "change account settings" }}
      >
        <Host />
      </RbacGate>,
    );
    expect(within(host).getByRole("button", { name: "Save" })).toHaveAttribute(
      "aria-describedby",
      "n",
    );
    const send = within(document.body).getByRole("button", { name: "Send" });
    expect(send.getAttribute("aria-describedby")).not.toBe("n");
    expect(send).toHaveAccessibleDescription(other);
  });

  it("notice: a gate that flips keeps the control mounted and focused", async () => {
    let flip: (allowed: boolean) => void = () => undefined;
    function Panel(): JSX.Element {
      const [allowed, setAllowed] = useState(false);
      flip = setAllowed;
      return notice(allowed);
    }
    const host = await mount(<Panel />);
    const save = within(host).getByRole("button", { name: "Save" });
    await act(async () => save.focus());
    await act(async () => flip(true));
    expect(within(host).getByRole("button", { name: "Save" })).toBe(save);
    expect(save).toHaveFocus();
    expect(save).not.toHaveAttribute("aria-describedby");
    await act(async () => flip(false));
    expect(save).toHaveFocus();
    expect(save).toHaveAttribute("aria-describedby", "panel-notice");
  });

  it("type: notice requires noticeId; noticeId belongs to the notice form only", () => {
    const missing = (
      // @ts-expect-error `form="notice"` points at a notice node, so `noticeId` is required.
      <RbacGate form="notice" allowed={false} reason="rbac.env">
        <Button>Save</Button>
      </RbacGate>
    );
    const stray = (
      // @ts-expect-error `noticeId` only exists on the notice form.
      <RbacGate form="tooltip" noticeId="n" allowed={false} reason="rbac.env">
        <IconButton icon="settings" label="Settings" />
      </RbacGate>
    );
    expect([missing, stray]).toHaveLength(2);
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

describe("RbacGate axe (E05-D02 G15)", () => {
  it("inline: no serious or critical violations", async () => {
    const host = await mount(
      <RbacGate allowed={false} reason="rbac.env">
        <Button>Place order</Button>
      </RbacGate>,
    );
    expect(await seriousAxe(host)).toEqual([]);
  });

  it("tooltip: no serious or critical violations", async () => {
    const host = await mount(
      <RbacGate
        form="tooltip"
        allowed={false}
        reason="rbac.owner_only"
        fills={{ verb: "change account settings" }}
      >
        <IconButton icon="settings" label="Account settings" />
      </RbacGate>,
    );
    expect(await seriousAxe(host)).toEqual([]);
  });

  it("notice: no serious or critical violations", async () => {
    const deny = {
      form: "notice",
      noticeId: "panel-notice",
      allowed: false,
      reason: "rbac.owner_only",
      fills: { verb: "change account settings" },
    } as const;
    const host = await mount(
      <>
        <Callout id="panel-notice" title={OWNER_ONLY} live="off" />
        <RbacGate {...deny}>
          <Button>Save</Button>
        </RbacGate>
        <RbacGate {...deny}>
          <FormField label="Display name">
            <TextInput />
          </FormField>
        </RbacGate>
      </>,
    );
    expect(await seriousAxe(host)).toEqual([]);
  });
});

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

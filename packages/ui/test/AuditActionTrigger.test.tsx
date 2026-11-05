// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { act, useState, type JSX } from "react";
import { afterEach, describe, it, vi } from "vitest";
import { expect, fireEvent, userEvent, within } from "storybook/test";
import {
  AUDIT_MARKER_COPY,
  AuditActionTrigger,
  Button,
  GatedAnnounceProvider,
  RbacGate,
  auditMarkerText,
  formatRbacReason,
} from "../src/components/index.js";
import * as stories from "../src/components/AuditActionTrigger.stories.js";
import { seriousViolations } from "./axe.js";
import { mount } from "./theme/mount.js";

const EXPORT_MARKER =
  "Recorded · needs your confirmation — Audit log exported (admin.audit_export)";
const VERIFY_MARKER = "Recorded in the audit log · admin.audit_verify";
const OWNER_ONLY = formatRbacReason("rbac.owner_only", { verb: "export the audit log" });
const VIEW_AS = formatRbacReason("rbac.view_as", { user: "jdoe" });

afterEach(() => {
  vi.restoreAllMocks();
});

const root = (host: HTMLElement): HTMLElement => {
  const el = host.querySelector<HTMLElement>('[data-cmp="CMP-093"]');
  if (el === null) throw new Error("no CMP-093 rendered");
  return el;
};
const ids = (el: HTMLElement): string[] =>
  (el.getAttribute("aria-describedby") ?? "").split(" ").filter((id) => id !== "");
const textOf = (id: string): string => document.getElementById(id)?.textContent ?? "";

describe("auditMarkerText (D02 §4.3's marker, E42-D04 §8)", () => {
  it.each([
    [
      "a step-up action: the confirmation lead and the registered label",
      { codes: ["admin.audit_export"], confirm: true },
      EXPORT_MARKER,
    ],
    [
      "a code with no registered label reads as itself",
      { codes: ["admin.audit_verify"] },
      VERIFY_MARKER,
    ],
    [
      "the host's label for the action",
      { label: "Disable user", codes: ["users.disable"] },
      "Recorded in the audit log · Disable user (users.disable)",
    ],
    [
      "several codes, each with its label or alone, joined by a plus",
      { codes: ["flags.change", "maintenance.enabled", "rbac.denied"] },
      "Recorded in the audit log · Flag changed (flags.change) + Maintenance on (maintenance.enabled) + rbac.denied",
    ],
    [
      "one label over several codes",
      { label: "Maintenance on", codes: ["flags.change", "maintenance.enabled"] },
      "Recorded in the audit log · Maintenance on (flags.change + maintenance.enabled)",
    ],
    [
      "an action with no registered code: the lead alone",
      { codes: [] },
      AUDIT_MARKER_COPY.recorded,
    ],
  ])("%s", (_name, marker, text) => {
    expect(auditMarkerText(marker)).toBe(text);
  });

  it("never takes a label from the object's prototype for a code", () => {
    expect(auditMarkerText({ codes: ["constructor"] })).toBe(
      "Recorded in the audit log · constructor",
    );
  });
});

describe("AuditActionTrigger (CMP-093)", () => {
  it("renders the control, then the marker line, and joins the marker to the control's description", async () => {
    const host = await mount(
      <AuditActionTrigger marker={{ codes: ["admin.audit_export"], confirm: true }}>
        <Button aria-describedby="host-help">Signed export…</Button>
      </AuditActionTrigger>,
    );
    const button = within(host).getByRole("button", { name: "Signed export…" });
    const marker = within(host).getByText(EXPORT_MARKER);
    expect(root(host).firstElementChild).toBe(button);
    expect(root(host).lastElementChild).toBe(marker);
    // The host's own description stays first; the marker joins after it.
    expect(ids(button)).toEqual(["host-help", marker.id]);
    expect(button).not.toHaveAttribute("aria-disabled");
  });

  it("is plain text with no role, live region or tab stop of its own", async () => {
    const host = await mount(
      <AuditActionTrigger marker={{ codes: ["admin.audit_verify"] }}>
        <Button>Run tamper check</Button>
      </AuditActionTrigger>,
    );
    expect(root(host).querySelectorAll("[aria-live], [role]")).toHaveLength(0);
    expect(host.querySelectorAll("a[href], button, [tabindex]")).toHaveLength(1);
    expect(root(host).querySelectorAll('[data-cmp="CMP-093"]')).toHaveLength(0);
  });

  it("gated: the reason line shows under the control and alone describes it; the marker stays visible", async () => {
    const host = await mount(
      <AuditActionTrigger
        marker={{ codes: ["admin.audit_export"], confirm: true }}
        disabledReason={OWNER_ONLY}
      >
        <Button>Signed export…</Button>
      </AuditActionTrigger>,
    );
    const button = within(host).getByRole("button", { name: /Signed export…$/ });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).not.toBeDisabled();
    // 2a: the lock leads the full label, named "Not available" (E09-D09 §2.2, §10).
    expect(button).toHaveAccessibleName("Not available Signed export…");
    expect(ids(button)).toHaveLength(1);
    expect(textOf(ids(button)[0] ?? "")).toBe(OWNER_ONLY);
    const reason = within(host).getByText(OWNER_ONLY);
    expect(reason).toBeVisible();
    expect(reason.classList.contains("cv-visually-hidden")).toBe(false);
    expect(within(host).getByText(EXPORT_MARKER)).toBeVisible();
    // DOM order: the control, its reason, then the marker.
    expect([...root(host).children].map((el) => el.textContent)).toEqual([
      "Signed export…",
      OWNER_ONLY,
      EXPORT_MARKER,
    ]);
  });

  it("takes the gate from CMP-079 RbacGate wrapping it", async () => {
    const host = await mount(
      <RbacGate allowed={false} reason="rbac.owner_only" fills={{ verb: "export the audit log" }}>
        <AuditActionTrigger marker={{ codes: ["admin.audit_export"], confirm: true }}>
          <Button>Signed export…</Button>
        </AuditActionTrigger>
      </RbacGate>,
    );
    const button = within(host).getByRole("button", { name: /Signed export…$/ });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(textOf(ids(button)[0] ?? "")).toBe(OWNER_ONLY);
    expect(within(host).getByText(OWNER_ONLY)).toBeVisible();
  });

  // BQ-9, G-T2.5: under RbacGate's notice form the panel's one notice is the reason node; no second copy.
  it("under CMP-079 RbacGate's notice form, points the control at the one notice and draws no line", async () => {
    const host = await mount(
      <>
        <p id="panel-notice">{VIEW_AS}</p>
        <RbacGate
          form="notice"
          noticeId="panel-notice"
          allowed={false}
          reason="rbac.view_as"
          fills={{ user: "jdoe" }}
        >
          <AuditActionTrigger marker={{ codes: ["admin.audit_verify"] }}>
            <Button>Run tamper check</Button>
          </AuditActionTrigger>
        </RbacGate>
      </>,
    );
    const button = within(host).getByRole("button", { name: /Run tamper check$/ });
    expect(button).toHaveAttribute("aria-disabled", "true");
    expect(button).toHaveAccessibleName("Not available Run tamper check");
    expect(ids(button)).toEqual(["panel-notice"]);
    const copies = [...host.querySelectorAll("*")].filter(
      (n) => n.childElementCount === 0 && n.textContent === VIEW_AS,
    );
    expect(copies).toEqual([document.getElementById("panel-notice")]);
    expect(root(host).querySelector(".cv-audit-action__reason")).toBeNull();
    expect(within(host).getByText(VERIFY_MARKER)).toBeVisible();
  });

  it("under a notice-form gate, an explicit disabledReasonId still wins over the notice", async () => {
    const host = await mount(
      <>
        <p id="panel-notice">{VIEW_AS}</p>
        <p id="footer-line">{VIEW_AS}</p>
        <RbacGate
          form="notice"
          noticeId="panel-notice"
          allowed={false}
          reason="rbac.view_as"
          fills={{ user: "jdoe" }}
        >
          <AuditActionTrigger
            marker={{ codes: ["admin.audit_verify"] }}
            disabledReasonId="footer-line"
          >
            <Button>Run tamper check</Button>
          </AuditActionTrigger>
        </RbacGate>
      </>,
    );
    const button = within(host).getByRole("button", { name: /Run tamper check$/ });
    expect(ids(button)).toEqual(["footer-line"]);
    expect(root(host).querySelector(".cv-audit-action__reason")).toBeNull();
  });

  it("takes the gate from the control itself", async () => {
    const host = await mount(
      <AuditActionTrigger marker={{ codes: ["admin.audit_verify"] }}>
        <Button disabledReason="Paused by a rate limit.">Run tamper check</Button>
      </AuditActionTrigger>,
    );
    const button = within(host).getByRole("button", { name: /Run tamper check$/ });
    expect(ids(button)).toHaveLength(1);
    expect(textOf(ids(button)[0] ?? "")).toBe("Paused by a rate limit.");
    expect(within(host).getByText(VERIFY_MARKER)).toBeVisible();
  });

  it("points a gated control at the host's one notice and draws no reason line of its own", async () => {
    const host = await mount(
      <>
        <p id="limited-notice">Paused by a rate limit.</p>
        <AuditActionTrigger
          marker={{ codes: ["admin.audit_verify"] }}
          disabledReason="Paused by a rate limit."
          disabledReasonId="limited-notice"
        >
          <Button>Run tamper check</Button>
        </AuditActionTrigger>
      </>,
    );
    const button = within(host).getByRole("button", { name: /Run tamper check$/ });
    expect(ids(button)).toEqual(["limited-notice"]);
    expect(within(host).getAllByText("Paused by a rate limit.")).toHaveLength(1);
  });

  it("rejoins the marker to the description once the control is enabled again", async () => {
    function Host(): JSX.Element {
      const [limited, setLimited] = useState(true);
      return (
        <>
          <button type="button" onClick={() => setLimited(false)}>
            Lift
          </button>
          <AuditActionTrigger
            marker={{ codes: ["admin.audit_verify"] }}
            {...(limited ? { disabledReason: "Paused by a rate limit." } : {})}
          >
            <Button>Run tamper check</Button>
          </AuditActionTrigger>
        </>
      );
    }
    const host = await mount(<Host />);
    await act(async () => {
      fireEvent.click(within(host).getByRole("button", { name: "Lift" }));
    });
    const button = within(host).getByRole("button", { name: "Run tamper check" });
    expect(button).not.toHaveAttribute("aria-disabled");
    expect(ids(button).map(textOf)).toEqual([VERIFY_MARKER]);
    expect(within(host).queryByText("Paused by a rate limit.")).toBeNull();
  });

  it("a press on a gated control acts on nothing and says the reason once", async () => {
    const onClick = vi.fn();
    const announce = vi.fn();
    const host = await mount(
      <GatedAnnounceProvider announce={announce}>
        <AuditActionTrigger
          marker={{ codes: ["admin.audit_verify"] }}
          disabledReason="Paused by a rate limit."
        >
          <Button onClick={onClick}>Run tamper check</Button>
        </AuditActionTrigger>
      </GatedAnnounceProvider>,
    );
    await userEvent.click(within(host).getByRole("button", { name: /Run tamper check$/ }));
    expect(onClick).not.toHaveBeenCalled();
    expect(announce).toHaveBeenCalledTimes(1);
    expect(announce).toHaveBeenCalledWith("Paused by a rate limit.");
  });

  it("makes no request of its own: the endpoint writes the record (14 §0.5 item 8)", async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    const onClick = vi.fn();
    const host = await mount(
      <AuditActionTrigger marker={{ codes: ["admin.audit_verify"] }}>
        <Button onClick={onClick}>Run tamper check</Button>
      </AuditActionTrigger>,
    );
    await userEvent.click(within(host).getByRole("button", { name: "Run tamper check" }));
    expect(onClick).toHaveBeenCalledTimes(1);
    expect(fetchSpy).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("aligns its lines to the end on request (a page header's actions)", async () => {
    const host = await mount(
      <AuditActionTrigger marker={{ codes: ["admin.audit_export"], confirm: true }} align="end">
        <Button>Signed export…</Button>
      </AuditActionTrigger>,
    );
    expect(root(host).dataset["align"]).toBe("end");
  });

  it("has no serious or critical axe violation, enabled or gated", async () => {
    const host = await mount(
      <>
        <AuditActionTrigger marker={{ codes: ["admin.audit_verify"] }}>
          <Button>Run tamper check</Button>
        </AuditActionTrigger>
        <AuditActionTrigger
          marker={{ codes: ["admin.audit_export"], confirm: true }}
          disabledReason={OWNER_ONLY}
        >
          <Button>Signed export…</Button>
        </AuditActionTrigger>
      </>,
    );
    expect(await seriousViolations(host)).toEqual([]);
  });
});

describe("AuditActionTrigger stories", () => {
  it.each(Object.entries(composeStories(stories)))(
    "%s renders its marker",
    async (_name, Story) => {
      const host = await mount(<Story />);
      expect(host.querySelectorAll('[data-cmp="CMP-093"]').length).toBeGreaterThan(0);
      expect(host.textContent).toContain("Recorded");
    },
  );

  // The storybook project runs each play in Chromium; here in jsdom too, so a wrong name fails without a browser.
  it("runs each story's play function", { timeout: 20_000 }, async () => {
    for (const [name, Story] of Object.entries(composeStories(stories))) {
      const canvasElement = document.body.appendChild(document.createElement("div"));
      await expect(Story.run({ canvasElement }), name).resolves.toBeUndefined();
    }
  });
});

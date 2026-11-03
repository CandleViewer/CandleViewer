// E29-S07 (#1028) Resolve… (E29-D03 §4.4; BQ-10 of 6575172489): the Owner's dialog, T2 for every
// other role and while viewing as, the step-up through `features/stepUp`. No network.
import { createRequire } from "node:module";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ShellAnnouncer, clearAnnouncements } from "../../../src/features/app-shell/announcer";
import { ResolveControl, resolvedText } from "../../../src/features/reconciliation/ResolveDialog";
import type { ResolveOutcome } from "../../../src/features/reconciliation/resolve";
import { resolveRequest } from "../../../src/features/reconciliation/resolve";
import type { HeldRequest } from "../../../src/features/stepUp/challenge";

const keyOf = (held: HeldRequest): string | undefined =>
  new Map(held.headers).get("Idempotency-Key");
const reasonOf = (held: HeldRequest): unknown =>
  (JSON.parse(held.body ?? "{}") as { reason?: unknown }).reason;

const axe = createRequire(createRequire(import.meta.url).resolve("@axe-core/playwright"))(
  "axe-core",
) as { run: (el: Element, o?: object) => Promise<{ violations: { impact?: string | null }[] }> };
const seriousAxe = async (el: Element): Promise<unknown[]> =>
  (await axe.run(el, { rules: { "color-contrast": { enabled: false } } })).violations.filter(
    (v) => v.impact === "serious" || v.impact === "critical",
  );

const A = "a1000000-0000-4000-8000-00000000000a";
const LABEL = "Sub-2 · LIVE";

function mount(
  role: "owner" | "manager" | "viewer",
  send?: (held: HeldRequest) => Promise<ResolveOutcome>,
  viewingAs?: string,
) {
  return render(
    <>
      <ResolveControl
        accountId={A}
        accountLabel={LABEL}
        role={role}
        viewingAs={viewingAs ?? null}
        {...(send === undefined ? {} : { send })}
      />
      <ShellAnnouncer />
    </>,
  );
}
const control = () => screen.getByRole("button", { name: /Resolve…/ });

afterEach(() => act(() => clearAnnouncements()));

describe("Resolve… per role", () => {
  it.each(["manager", "viewer"] as const)(
    "a %s's control is T2 rbac.owner_only: focusable, aria-disabled, its reason linked",
    (role) => {
      const send = vi.fn();
      mount(role, send);
      const button = control();
      expect(button).toHaveAttribute("aria-disabled", "true");
      expect(button).not.toBeDisabled();
      expect(button).toHaveAccessibleDescription("Only the owner can resolve the lock.");
      fireEvent.click(button);
      expect(screen.queryByRole("dialog")).toBeNull();
      expect(send).not.toHaveBeenCalled();
    },
  );

  it("while viewing as anyone, rbac.view_as comes first, the Owner's included", () => {
    mount("owner", vi.fn(), "Dana");
    expect(control()).toHaveAccessibleDescription("Read-only while viewing as Dana.");
  });
});

describe("the Owner's dialog", () => {
  it("a short reason sends nothing and says why", () => {
    const send = vi.fn();
    mount("owner", send);
    fireEvent.click(control());
    const dialog = screen.getByRole("dialog", { name: "Resolve the lock" });
    fireEvent.change(within(dialog).getByRole("textbox", { name: /Reason/ }), {
      target: { value: " ab " },
    });
    fireEvent.click(within(dialog).getByRole("button", { name: "Resolve" }));
    expect(send).not.toHaveBeenCalled();
    expect(dialog).toHaveTextContent("Enter a reason of 3 to 280 characters.");
    expect(within(dialog).getByRole("textbox", { name: /Reason/ })).toHaveFocus(); // a11y m5
  });

  it("a resolve closes the dialog and is said once, politely", async () => {
    const send = vi.fn<(held: HeldRequest) => Promise<ResolveOutcome>>(async () => ({
      kind: "resolved" as const,
      resolved: { exchange_account_id: A, resolved: "stale_lockout" as const, resolved_at: "x" },
    }));
    mount("owner", send);
    fireEvent.click(control());
    fireEvent.change(screen.getByRole("textbox", { name: /Reason/ }), {
      target: { value: "Checked every order on Bybit." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Resolve" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    const held = send.mock.calls[0]?.[0] as HeldRequest;
    expect(held.url).toBe(`/api/v1/admin/reconciliation/${A}/resolve`);
    expect(reasonOf(held)).toBe("Checked every order on Bybit.");
    // the shell announcer's polite region (rendered last; the theme's own live region is first)
    const polite = [...document.querySelectorAll('[aria-live="polite"]')].at(-1);
    expect(polite).toHaveTextContent(resolvedText(LABEL));
  });

  it("nothing to resolve stays in the dialog as an alert, the reason kept", async () => {
    mount("owner", async () => ({ kind: "nothing_to_resolve" }));
    fireEvent.click(control());
    const input = screen.getByRole("textbox", { name: /Reason/ });
    fireEvent.change(input, { target: { value: "Checked." } });
    fireEvent.click(screen.getByRole("button", { name: "Resolve" }));
    expect(
      await within(screen.getByRole("dialog")).findByText(
        "Nothing to resolve: this account is not locked.",
      ),
    ).toHaveAttribute("role", "alert");
    expect(input).toHaveValue("Checked.");
  });

  it("a step-up challenge closes the dialog and opens the step-up gate (never the arm)", async () => {
    const held = resolveRequest(A, "Checked.");
    mount("owner", async () => ({
      kind: "step_up",
      held,
      challenge: {
        challengeId: "c-1",
        expiresAt: new Date(Date.now() + 120_000).toISOString(),
        actionClass: "accounts",
        actionSummary: "Resolve the reconciliation lock on Sub-2",
        target: null,
        clockOffsetMs: 0,
      },
    }));
    fireEvent.click(control());
    fireEvent.change(screen.getByRole("textbox", { name: /Reason/ }), {
      target: { value: "Checked." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Resolve" }));
    expect(
      await screen.findByRole("alertdialog", { name: /Confirm with two-factor/ }),
    ).toBeVisible();
    expect(screen.queryByRole("dialog", { name: "Resolve the lock" })).toBeNull();
  });

  it("a retry after no answer re-sends the same request and key; a new reason is a new decision (m2)", async () => {
    const sent: HeldRequest[] = [];
    const send = vi.fn(async (held: HeldRequest) => {
      sent.push(held);
      return { kind: "unavailable" as const };
    });
    mount("owner", send);
    fireEvent.click(control());
    const input = screen.getByRole("textbox", { name: /Reason/ });
    const submit = () => fireEvent.click(screen.getByRole("button", { name: "Resolve" }));
    fireEvent.change(input, { target: { value: "Checked." } });
    submit();
    await screen.findByText("Cannot reach the server. Try again.");
    submit();
    await waitFor(() => expect(sent).toHaveLength(2));
    expect(sent[1]).toBe(sent[0]);
    fireEvent.change(input, { target: { value: "Checked again." } });
    submit();
    await waitFor(() => expect(sent).toHaveLength(3));
    expect(keyOf(sent[2] as HeldRequest)).not.toBe(keyOf(sent[0] as HeldRequest));
  });

  it("axe: no serious or critical violation in the open dialog", { timeout: 30_000 }, async () => {
    const view = mount("owner", vi.fn());
    fireEvent.click(control());
    expect(await seriousAxe(view.baseElement)).toEqual([]);
  });
});

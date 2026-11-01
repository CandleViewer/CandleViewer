// @vitest-environment jsdom
import { createRequire } from "node:module";
import { describe, it } from "vitest";
import { expect, fn, within } from "storybook/test";
import { EmptyState, RbacGate } from "../src/components/index.js";
import { mount } from "./theme/mount.js";

type Axe = {
  run: (context: object, options?: object) => Promise<{ violations: { impact?: string | null }[] }>;
};
const axe = createRequire(createRequire(import.meta.url).resolve("@storybook/addon-a11y"))(
  "axe-core",
) as Axe;

const cta = (): JSX.Element => (
  <EmptyState
    variant="recording-not-started"
    title="Not recorded"
    actions={[{ label: "Record this symbol…", onClick: fn() }]}
  />
);

describe("RbacGate sentence form (E09-D09 §8, G-T2.1c)", () => {
  it("allowed renders the host's empty state with its CTA unchanged", async () => {
    const host = await mount(
      <RbacGate form="sentence" title="Not recorded" allowed>
        {cta()}
      </RbacGate>,
    );
    const button = within(host).getByRole("button", { name: "Record this symbol…" });
    expect(button).not.toHaveAttribute("aria-disabled");
  });

  const denied = async (
    gate:
      | { reason: "rbac.owner_only"; fills: { verb: string } }
      | { reason: "rbac.view_as"; fills: { user: string } },
    text: string,
  ): Promise<void> => {
    const host = await mount(
      <RbacGate form="sentence" title="Not recorded" allowed={false} {...gate}>
        {cta()}
      </RbacGate>,
    );
    expect(within(host).getByText(text)).toBeTruthy();
    expect(within(host).getByRole("heading", { name: "Not recorded", level: 3 })).toBeTruthy();
    expect(within(host).queryByRole("button")).toBeNull();
    expect(host.querySelector("[aria-disabled]")).toBeNull();
    expect(host.querySelector("svg[aria-label='Not available']")).toBeNull();
    expect(host.querySelector("[data-cmp='CMP-026']")).toBeTruthy();
  };

  it("denied by rbac.owner_only: the sentence alone, no button, no lock", async () => {
    await denied(
      { reason: "rbac.owner_only", fills: { verb: "start recording" } },
      "Only the owner can start recording.",
    );
  });

  it("denied by rbac.view_as: the sentence alone, no button, no lock", async () => {
    await denied(
      { reason: "rbac.view_as", fills: { user: "alex" } },
      "Read-only while viewing as alex.",
    );
  });

  it("passes the heading level through", async () => {
    const host = await mount(
      <RbacGate
        form="sentence"
        title="Not recorded"
        headingLevel={4}
        allowed={false}
        reason="rbac.owner_only"
        fills={{ verb: "start recording" }}
      >
        {cta()}
      </RbacGate>,
    );
    expect(within(host).getByRole("heading", { level: 4 })).toBeTruthy();
  });

  it("axe: the denied sentence has no serious or critical violation", async () => {
    const host = await mount(
      <RbacGate
        form="sentence"
        title="Not recorded"
        allowed={false}
        reason="rbac.owner_only"
        fills={{ verb: "start recording" }}
      >
        {cta()}
      </RbacGate>,
    );
    const { violations } = await axe.run(
      { include: [host] },
      { rules: { "color-contrast": { enabled: false } } },
    );
    expect(violations.filter((v) => v.impact === "serious" || v.impact === "critical")).toEqual([]);
  });
});

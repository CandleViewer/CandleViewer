// @vitest-environment jsdom
import { createRequire } from "node:module";
import { act } from "react";
import { expect, fireEvent, within } from "storybook/test";
import { describe, it, vi } from "vitest";
import { ForbiddenState, NotFoundState } from "../src/components/index.js";
import { mount } from "./theme/mount.js";

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

const TRY = [
  { label: "Terminal", href: "/terminal" },
  { label: "Journal", href: "/journal" },
];

describe("ForbiddenState (CMP-089)", () => {
  it("renders the never-had h1 at level 1 with tabindex -1, the sentence and the home link", async () => {
    const host = await mount(<ForbiddenState capability="see the journal" homeHref="/terminal" />);
    const h1 = within(host).getByRole("heading", { level: 1 });
    expect(h1).toHaveTextContent("You don't have access to this");
    expect(h1).toHaveAttribute("tabindex", "-1");
    expect(host.textContent).not.toContain("Access denied");
    within(host).getByText("Your role can't see the journal. Ask the owner if you need it.");
    expect(within(host).getByRole("link", { name: "Back to your workspace" })).toHaveAttribute(
      "href",
      "/terminal",
    );
    within(host).getByRole("button", { name: "Copy details" });
  });

  it("shows the Ref only when refId is given", async () => {
    const without = await mount(<ForbiddenState homeHref="/" />);
    expect(within(without).queryByText(/^Ref /)).toBeNull();
    const withRef = await mount(<ForbiddenState homeHref="/" refId="urn:cv:req:abc" />);
    within(withRef).getByText("Ref urn:cv:req:abc");
  });

  it("echoes the account id in the account scope, and never copies it", async () => {
    const onCopyDetails = vi.fn();
    const host = await mount(
      <ForbiddenState
        scope="account"
        accountId="acc_1"
        refId="r-2"
        homeHref="/"
        onCopyDetails={onCopyDetails}
      />,
    );
    within(host).getByText("This account isn't assigned to you. Ask the owner if you need it.");
    expect(within(host).getByText("acc_1")).toHaveClass("cv-appstate__echo");
    await act(async () => {
      fireEvent.click(within(host).getByRole("button", { name: "Copy details" }));
    });
    expect(onCopyDetails).toHaveBeenCalledWith("This account isn't assigned to you.\nRef r-2");
  });

  it("renders the withdrawn copy", async () => {
    const host = await mount(
      <ForbiddenState variant="withdrawn" capability="see the journal" homeHref="/" />,
    );
    expect(within(host).getByRole("heading", { level: 1 })).toHaveTextContent(
      "Your access changed",
    );
    within(host).getByText(
      "Your role can't see the journal any more — this changed just now. Anything you already sent was decided by the server: check Orders. Ask the owner if this is unexpected.",
    );
  });

  it("copies the sentence and the Ref, then says Copied once and reverts after 2 s", async () => {
    vi.useFakeTimers();
    try {
      const onCopyDetails = vi.fn();
      const host = await mount(
        <ForbiddenState
          capability="see rules"
          refId="r-1"
          homeHref="/"
          onCopyDetails={onCopyDetails}
        />,
      );
      const status = within(host).getByRole("status");
      expect(status).toHaveTextContent("");
      await act(async () => {
        fireEvent.click(within(host).getByRole("button", { name: "Copy details" }));
      });
      expect(onCopyDetails).toHaveBeenCalledWith("Your role can't see rules.\nRef r-1");
      expect(status).toHaveTextContent("Copied");
      await act(async () => vi.advanceTimersByTime(2000));
      expect(status).toHaveTextContent("");
    } finally {
      vi.useRealTimers();
    }
  });

  it("has no serious or critical axe violations", async () => {
    const host = await mount(
      <ForbiddenState scope="account" accountId="acc_1" refId="r-1" homeHref="/" />,
    );
    expect(await seriousAxe(host)).toEqual([]);
  });
});

describe("NotFoundState (CMP-090)", () => {
  it("renders the h1, echoes the path as text and never as a link", async () => {
    const host = await mount(<NotFoundState path="/nowhere" tryRoutes={TRY} />);
    const h1 = within(host).getByRole("heading", { level: 1 });
    expect(h1).toHaveTextContent("Page not found");
    expect(h1).toHaveAttribute("tabindex", "-1");
    expect(host.querySelector(".cv-appstate__body")).toHaveTextContent(
      "There's nothing at /nowhere.",
    );
    expect(within(host).getByText("/nowhere").closest("a")).toBeNull();
    expect(within(host).queryByRole("link", { name: "/nowhere" })).toBeNull();
  });

  it("renders the try routes as a list of links after Try:, with aria-hidden separators", async () => {
    const host = await mount(<NotFoundState path="/x" tryRoutes={TRY} />);
    const list = within(host).getByRole("list", { name: "Try:" });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(
      within(list)
        .getAllByRole("link")
        .map((a) => a.getAttribute("href")),
    ).toEqual(["/terminal", "/journal"]);
    const seps = list.querySelectorAll(".cv-appstate__sep");
    expect(seps).toHaveLength(1);
    expect(seps[0]).toHaveAttribute("aria-hidden", "true");
    expect(seps[0]).toHaveTextContent("·");
  });

  it("omits the Try line with no permitted routes, and renders the deleted copy", async () => {
    const host = await mount(<NotFoundState variant="deleted" path="/w/1" tryRoutes={[]} />);
    within(host).getByText("This workspace was deleted.");
    expect(within(host).queryByRole("list")).toBeNull();
  });

  it("passes every link through the host's renderLink", async () => {
    const host = await mount(
      <NotFoundState
        path="/x"
        tryRoutes={TRY}
        renderLink={({ href, className, children }) => (
          <a href={href} className={className} data-router="">
            {children}
          </a>
        )}
      />,
    );
    expect(host.querySelectorAll("a[data-router]")).toHaveLength(2);
  });

  it("has no serious or critical axe violations", async () => {
    const host = await mount(<NotFoundState path="/admin/users" tryRoutes={TRY} />);
    expect(await seriousAxe(host)).toEqual([]);
  });
});

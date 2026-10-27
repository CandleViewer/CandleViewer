// @vitest-environment jsdom
import { createRequire } from "node:module";
import { act } from "react";
import { expect, fireEvent, userEvent, within } from "storybook/test";
import { describe, it } from "vitest";
import { SKIP_LINK_COPY, SkipLink } from "../src/components/index.js";
import { mount } from "./theme/mount.js";

type Axe = {
  run: (context: object, options?: object) => Promise<{ violations: { impact?: string | null }[] }>;
};
const axe = createRequire(createRequire(import.meta.url).resolve("@storybook/addon-a11y"))(
  "axe-core",
) as Axe;

const page = (several = false) => (
  <>
    <SkipLink
      targets={
        several
          ? [
              { id: "m", label: SKIP_LINK_COPY.main },
              { id: "t", label: SKIP_LINK_COPY.orderTicket },
            ]
          : [{ id: "m", label: SKIP_LINK_COPY.main }]
      }
    />
    <header>
      <button type="button">Menu</button>
    </header>
    <main id="m">
      <h1>Page</h1>
      <section id="t" aria-label="Order ticket">
        <button type="button">Buy</button>
      </section>
    </main>
  </>
);

const link = (host: HTMLElement, name: string = SKIP_LINK_COPY.main): HTMLAnchorElement =>
  within(host).getByRole("link", { name }) as HTMLAnchorElement;

describe("SkipLink (CMP-085)", () => {
  it("exports the default English copy, main content first", () => {
    expect(SKIP_LINK_COPY.main).toBe("Skip to main content");
    expect(SKIP_LINK_COPY.orderTicket).toBe("Skip to order ticket");
    expect(SKIP_LINK_COPY.chart).toBe("Skip to chart");
  });

  it("renders one hidden link per target, in order, with the hash href and the cv class", async () => {
    const host = await mount(page(true));
    const links = within(host).getAllByRole("link");
    expect(links.map((a) => a.textContent)).toEqual([
      SKIP_LINK_COPY.main,
      SKIP_LINK_COPY.orderTicket,
    ]);
    expect(links.map((a) => a.getAttribute("href"))).toEqual(["#m", "#t"]);
    for (const a of links) {
      expect(a).toHaveClass("cv-skip-link");
      expect(a.dataset["cmp"]).toBe("CMP-085");
    }
  });

  it("is the first Tab stop: the first Tab focuses the link", async () => {
    const host = await mount(page());
    await userEvent.tab();
    expect(link(host)).toHaveFocus();
  });

  it("Enter moves focus to the target, which takes tabindex -1 and the ring marker", async () => {
    const host = await mount(page());
    const main = within(host).getByRole("main");
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    expect(main).toHaveFocus();
    expect(main).toHaveAttribute("tabindex", "-1");
    expect(main).toHaveAttribute("data-cv-skip-target");
  });

  it("the next Tab continues from the target, which then loses tabindex and the marker", async () => {
    const host = await mount(page());
    const main = within(host).getByRole("main");
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    await userEvent.tab();
    expect(within(host).getByRole("button", { name: "Buy" })).toHaveFocus();
    expect(main).not.toHaveAttribute("tabindex");
    expect(main).not.toHaveAttribute("data-cv-skip-target");
  });

  it("keeps a target's own tabindex on blur", async () => {
    const host = await mount(page());
    const main = within(host).getByRole("main");
    main.setAttribute("tabindex", "-1");
    act(() => link(host).focus());
    fireEvent.click(link(host));
    expect(main).toHaveFocus();
    act(() => main.blur());
    expect(main).toHaveAttribute("tabindex", "-1");
  });

  it("prevents the default click, so the hash never reaches the router", async () => {
    const host = await mount(page(true));
    const event = new MouseEvent("click", { bubbles: true, cancelable: true });
    act(() => {
      link(host, SKIP_LINK_COPY.orderTicket).dispatchEvent(event);
    });
    expect(event.defaultPrevented).toBe(true);
    expect(window.location.hash).toBe("");
    expect(within(host).getByRole("region", { name: "Order ticket" })).toHaveFocus();
  });

  it("leaves a modified click to the browser", async () => {
    const host = await mount(page(true));
    for (const init of [{ ctrlKey: true }, { metaKey: true }, { shiftKey: true }]) {
      const event = new MouseEvent("click", { bubbles: true, cancelable: true, ...init });
      act(() => {
        link(host, SKIP_LINK_COPY.orderTicket).dispatchEvent(event);
      });
      expect(event.defaultPrevented).toBe(false);
      expect(within(host).getByRole("region", { name: "Order ticket" })).not.toHaveFocus();
    }
  });

  it("does nothing but prevent the default when the target is not mounted", async () => {
    const host = await mount(<SkipLink targets={[{ id: "absent", label: "Skip" }]} />);
    const event = new MouseEvent("click", { bubbles: true, cancelable: true });
    act(() => {
      link(host, "Skip").dispatchEvent(event);
    });
    expect(event.defaultPrevented).toBe(true);
    expect(link(host, "Skip")).not.toHaveFocus();
  });

  it("has no serious or critical axe violations, unfocused and focused", async () => {
    const host = await mount(page(true));
    const run = async () =>
      (await axe.run(host, { rules: { "color-contrast": { enabled: false } } })).violations.filter(
        (v) => v.impact === "serious" || v.impact === "critical",
      );
    expect(await run()).toEqual([]);
    await userEvent.tab();
    expect(await run()).toEqual([]);
  });
});

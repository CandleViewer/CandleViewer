// @vitest-environment jsdom
import type { JSX } from "react";
import { expect, fireEvent, fn, userEvent, within } from "storybook/test";
import { describe, it } from "vitest";
import { Link, type LinkProps, type LinkRouteProps } from "../src/components/index.js";
import { EXTERNAL_LINK_TEXT } from "../src/components/Link.js";
import { mount } from "./theme/mount.js";

const DOCS = "https://example.com/api-docs";

/** A minimal router link: what the app's router component does with `to`. */
const navigate = fn();
function RouterLink({ to, onClick, children, ...rest }: LinkRouteProps): JSX.Element {
  return (
    <a
      {...rest}
      href={to}
      data-router=""
      onClick={(event) => {
        onClick?.(event);
        event.preventDefault();
        navigate(to);
      }}
    >
      {children}
    </a>
  );
}

describe("Link (CMP-021)", () => {
  it("an href link is a native, focusable <a> named by its text, with the CMP-039 ring", async () => {
    const host = await mount(<Link href="#settings">Shortcut settings</Link>);
    const link = within(host).getByRole("link", { name: "Shortcut settings" });
    expect(link.tagName).toBe("A");
    expect(link).toHaveAttribute("href", "#settings");
    expect(link.dataset["cmp"]).toBe("CMP-021");
    expect(link).toHaveClass("cv-link", "cv-focus-ring");
    expect(link).not.toHaveAttribute("target");
    expect(link).not.toHaveAttribute("rel");
    expect(link.querySelector("svg")).toBeNull();
    await userEvent.tab();
    expect(link).toHaveFocus();
  });

  it("external: rel noopener noreferrer, a new context, the hidden suffix and a decorative glyph (E25)", async () => {
    const host = await mount(
      <Link href={DOCS} external>
        Bybit API documentation
      </Link>,
    );
    const link = within(host).getByRole("link", {
      name: "Bybit API documentation (opens externally)",
    });
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("data-external");
    const hidden = link.querySelector(".cv-visually-hidden");
    expect(hidden?.textContent).toBe(EXTERNAL_LINK_TEXT);
    const mark = link.querySelector(".cv-link__external");
    expect(mark).toHaveAttribute("aria-hidden", "true");
    // The word joiner sits in the plain inline mark, before the inline-block glyph, never in the name.
    expect(mark?.firstChild?.textContent).toBe("\u2060");
    expect(mark?.querySelector(".cv-link__glyph svg")).not.toBeNull();
  });

  it("to: renders through the router slot, which owns navigation; no href of its own", async () => {
    navigate.mockClear();
    const onClick = fn();
    const host = await mount(
      <Link to="/settings/shortcuts" as={RouterLink} onClick={onClick}>
        Shortcut settings
      </Link>,
    );
    const link = within(host).getByRole("link", { name: "Shortcut settings" });
    expect(link).toHaveAttribute("data-router");
    expect(link).toHaveAttribute("href", "/settings/shortcuts");
    expect(link).toHaveClass("cv-link", "cv-focus-ring");
    expect(link.dataset["cmp"]).toBe("CMP-021");
    await userEvent.tab();
    await userEvent.keyboard("{Enter}");
    expect(navigate).toHaveBeenCalledWith("/settings/shortcuts");
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("keeps to with as, and external with href, at the type level", () => {
    // @ts-expect-error `to` needs the router slot
    const noSlot: LinkProps = { to: "/x", children: "x" };
    // @ts-expect-error a route is never external
    const externalRoute: LinkProps = { to: "/x", as: RouterLink, external: true, children: "x" };
    // @ts-expect-error href and to are exclusive
    const both: LinkProps = { href: "/x", to: "/x", as: RouterLink, children: "x" };
    expect([noSlot, externalRoute, both]).toHaveLength(3);
  });

  it.each([
    [
      "href",
      <Link key="h" href="#settings" disabled onClick={fn()}>
        Shortcut settings
      </Link>,
    ],
    [
      "to",
      <Link key="t" to="/settings" as={RouterLink} disabled>
        Shortcut settings
      </Link>,
    ],
  ])(
    "disabled (%s): role link, aria-disabled, no href, not focusable, no router",
    async (_kind, ui) => {
      navigate.mockClear();
      const host = await mount(ui);
      const link = within(host).getByRole("link", { name: "Shortcut settings" });
      expect(link).toHaveAttribute("aria-disabled", "true");
      expect(link).not.toHaveAttribute("href");
      expect(link).not.toHaveAttribute("tabindex");
      expect(link).not.toHaveAttribute("data-router");
      await userEvent.tab();
      expect(document.body).toHaveFocus();
      await userEvent.click(link);
      expect(navigate).not.toHaveBeenCalled();
    },
  );

  it("disabled never fires onClick", async () => {
    const onClick = fn();
    const host = await mount(
      <Link href="#settings" disabled onClick={onClick}>
        Shortcut settings
      </Link>,
    );
    await userEvent.click(within(host).getByRole("link"));
    expect(onClick).not.toHaveBeenCalled();
  });

  it("disabled stays unfocusable and inert even when tabIndex and handlers are passed", async () => {
    const onKeyDown = fn();
    const onMouseDown = fn();
    const onFocus = fn();
    const host = await mount(
      <Link
        href="#settings"
        disabled
        tabIndex={0}
        onKeyDown={onKeyDown}
        onMouseDown={onMouseDown}
        onFocus={onFocus}
        id="shortcuts"
      >
        Shortcut settings
      </Link>,
    );
    const link = within(host).getByRole("link", { name: "Shortcut settings" });
    expect(link).not.toHaveAttribute("tabindex");
    expect(link).toHaveAttribute("id", "shortcuts");
    await userEvent.tab();
    expect(document.body).toHaveFocus();
    await userEvent.click(link);
    fireEvent.keyDown(link, { key: "Enter" });
    expect(onKeyDown).not.toHaveBeenCalled();
    expect(onMouseDown).not.toHaveBeenCalled();
    expect(onFocus).not.toHaveBeenCalled();
  });

  it("disabled external keeps the glyph and suffix but drops rel and target", async () => {
    const host = await mount(
      <Link href={DOCS} external disabled>
        Bybit API documentation
      </Link>,
    );
    const link = within(host).getByRole("link", { name: /opens externally/ });
    expect(link).not.toHaveAttribute("rel");
    expect(link).not.toHaveAttribute("target");
    expect(link.querySelector(".cv-link__external")).not.toBeNull();
  });

  it("passes through anchor attributes but never its own className or style", async () => {
    const host = await mount(
      <Link href="#a" id="help" aria-describedby="hint" title="Help">
        Help
      </Link>,
    );
    const link = within(host).getByRole("link", { name: "Help" });
    expect(link).toHaveAttribute("id", "help");
    expect(link).toHaveAttribute("aria-describedby", "hint");
    expect(link).not.toHaveAttribute("style");
  });
});

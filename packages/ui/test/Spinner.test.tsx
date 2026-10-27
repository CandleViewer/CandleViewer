// @vitest-environment jsdom
import { expect, within } from "storybook/test";
import { describe, it } from "vitest";
import { Button, Spinner } from "../src/components/index.js";
import { mount } from "./theme/mount.js";

describe("Spinner (CMP-014)", () => {
  it("without a label it is nested: aria-hidden, no status role, md by default", async () => {
    const host = await mount(<Spinner />);
    const spinner = host.querySelector(".cv-spinner");
    expect(spinner).toHaveAttribute("aria-hidden", "true");
    expect(spinner).toHaveAttribute("data-size", "md");
    expect(spinner).not.toHaveAttribute("data-standalone");
    expect(within(host).queryByRole("status")).toBeNull();
    expect(host.textContent).toBe("");
  });

  it("with a label it is standalone: a polite status region that speaks the label", async () => {
    const host = await mount(<Spinner label="Loading positions" />);
    const status = within(host).getByRole("status");
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(status).toHaveAttribute("aria-atomic", "true");
    expect(status).toHaveAttribute("data-standalone");
    expect(status).not.toHaveAttribute("aria-hidden");
    expect(status).not.toHaveAttribute("aria-label");
    // Live regions announce content, so the label is a visually hidden text node, not an aria-label.
    expect(status).toHaveTextContent("Loading positions");
    expect(status.querySelector(".cv-visually-hidden")).toHaveTextContent("Loading positions");
    expect(status.querySelector("svg.cv-spinner__arc")).toHaveAttribute("aria-hidden", "true");
  });

  it("an empty label does not make a silent status region", async () => {
    const host = await mount(<Spinner label="" />);
    expect(within(host).queryByRole("status")).toBeNull();
  });

  it("Button loading nests it: the unlabelled spinner sits inside an aria-busy host", async () => {
    const host = await mount(<Button loading>Save</Button>);
    const button = within(host).getByRole("button", { name: "Save" });
    const spinner = button.querySelector(".cv-spinner");
    expect(spinner).toHaveAttribute("aria-hidden", "true");
    expect(spinner).toHaveAttribute("data-size", "sm");
    expect(spinner?.closest('[aria-busy="true"], [role="status"]')).toBe(button);
  });
});

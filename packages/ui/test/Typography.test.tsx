// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { expect, within } from "storybook/test";
import { describe, it } from "vitest";
import { Heading, MonoText, Text } from "../src/components/index.js";
import * as stories from "../src/components/Typography.stories.js";
import { mount } from "./theme/mount.js";

describe("Text", () => {
  it("is a generic span with the body role by default", async () => {
    const host = await mount(<Text>Hello</Text>);
    const el = within(host).getByText("Hello");
    expect(el.tagName).toBe("SPAN");
    expect(el).toHaveClass("cv-text");
    expect(el).toHaveAttribute("data-variant", "body");
    expect(el).toHaveAttribute("data-tone", "primary");
  });

  it("renders a paragraph with a variant, tone and the caller's class", async () => {
    const host = await mount(
      <Text as="p" variant="caption" tone="secondary" className="extra">
        Note
      </Text>,
    );
    const el = within(host).getByText("Note");
    expect(el.tagName).toBe("P");
    expect(el).toHaveClass("cv-text", "extra");
    expect(el).toHaveAttribute("data-variant", "caption");
    expect(el).toHaveAttribute("data-tone", "secondary");
  });
});

describe("Heading", () => {
  it.each([1, 2, 3, 4, 5, 6] as const)("level %d renders h%d with that level", async (level) => {
    const host = await mount(<Heading level={level}>Title</Heading>);
    const heading = within(host).getByRole("heading", { level, name: "Title" });
    expect(heading.tagName).toBe(`H${level}`);
    expect(heading).toHaveAttribute("data-variant", "heading-md");
  });

  it("keeps the level independent of the visual style", async () => {
    const host = await mount(
      <>
        <Heading level={1} variant="heading-sm">
          Small one
        </Heading>
        <Heading level={6} variant="display">
          Big six
        </Heading>
      </>,
    );
    const canvas = within(host);
    expect(canvas.getByRole("heading", { level: 1 })).toHaveAttribute("data-variant", "heading-sm");
    expect(canvas.getByRole("heading", { level: 6 })).toHaveAttribute("data-variant", "display");
  });
});

describe("MonoText", () => {
  it("is a span at num.base by default and code when asked", async () => {
    const host = await mount(
      <>
        <MonoText>ord-1</MonoText>
        <MonoText as="code" size="xs">
          x = 1
        </MonoText>
      </>,
    );
    const canvas = within(host);
    expect(canvas.getByText("ord-1")).toHaveAttribute("data-size", "base");
    expect(canvas.getByText("ord-1").tagName).toBe("SPAN");
    expect(canvas.getByText("x = 1").tagName).toBe("CODE");
    expect(canvas.getByText("x = 1")).toHaveClass("cv-mono");
  });
});

describe("Typography stories", () => {
  it.each(Object.entries(composeStories(stories)))("%s renders", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(host.querySelector("[data-cmp='CMP-020']")).not.toBeNull();
  });
});

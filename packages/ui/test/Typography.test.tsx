// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { expect, within } from "storybook/test";
import { describe, it } from "vitest";
import { Heading, MonoText, NumericText, Text } from "../src/components/index.js";
import * as stories from "../src/components/Typography.stories.js";
import { mount } from "./theme/mount.js";

const num = (host: HTMLElement): HTMLElement =>
  host.querySelector<HTMLElement>(".cv-num") as HTMLElement;

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

describe("NumericText", () => {
  it("always carries the tabular class, whatever class the consumer adds", async () => {
    const host = await mount(<NumericText value={1} className="cell" size="lg" />);
    expect(num(host)).toHaveClass("cv-num", "cell");
    expect(num(host)).toHaveAttribute("data-size", "lg");
    expect(num(host)).toHaveAttribute("data-format", "price");
    expect(num(host)).toHaveTextContent("1.00");
  });

  it("signs pnl and marks the sign for colour", async () => {
    const host = await mount(
      <>
        <NumericText value={420} format="pnl" signDisplay="always" colorBySign />
        <NumericText value={-420} format="pnl" signDisplay="always" colorBySign />
        <NumericText value={0} format="pnl" signDisplay="always" colorBySign />
      </>,
    );
    const [up, down, zero] = host.querySelectorAll(".cv-num");
    expect(up).toHaveTextContent("+420.00");
    expect(up).toHaveAttribute("data-sign", "positive");
    expect(up).toHaveAttribute("data-color-by-sign", "");
    expect(down).toHaveTextContent("-420.00");
    expect(down).toHaveAttribute("data-sign", "negative");
    expect(zero).toHaveTextContent(/^0\.00$/);
    expect(zero).toHaveAttribute("data-sign", "zero");
  });

  it("forces the sign for an untyped caller that asks for colour without it", async () => {
    const props = { value: 5, colorBySign: true, signDisplay: "never" } as unknown as Parameters<
      typeof NumericText
    >[0];
    const host = await mount(<NumericText {...props} />);
    expect(num(host)).toHaveTextContent("+5.00");
  });

  it("never colours by sign unless asked", async () => {
    const host = await mount(<NumericText value={-3} />);
    expect(num(host)).not.toHaveAttribute("data-color-by-sign");
    expect(num(host)).toHaveTextContent("-3.00");
  });

  it("reads an abbreviated value by its expanded reading, never an aria-label", async () => {
    const host = await mount(
      <table>
        <tbody>
          <tr>
            <td>
              <NumericText value={1_200_000} format="notional" />
            </td>
          </tr>
        </tbody>
      </table>,
    );
    expect(within(host).getByRole("cell", { name: "1,200,000" })).toBeInTheDocument();
    expect(num(host)).not.toHaveAttribute("aria-label");
    expect(within(host).getByText("1.2M")).toHaveAttribute("aria-hidden", "true");
    expect(within(host).getByText("1,200,000")).toHaveClass("cv-visually-hidden");
  });

  it("shows a dash read as 'no value', with no sign, for a non-finite value", async () => {
    const host = await mount(<NumericText value={Number.NaN} format="pnl" signDisplay="always" />);
    expect(within(host).getByText("—")).toHaveAttribute("aria-hidden", "true");
    expect(within(host).getByText("no value")).toHaveClass("cv-visually-hidden");
    expect(num(host)).not.toHaveAttribute("data-sign");
  });

  it("types pnl and colorBySign as needing an explicit sign", () => {
    // @ts-expect-error pnl requires signDisplay="always"
    void (<NumericText value={1} format="pnl" />);
    // @ts-expect-error colorBySign requires signDisplay="always"
    void (<NumericText value={1} colorBySign signDisplay="auto" />);
    void (<NumericText value={1} format="qty" signDisplay="never" />);
  });
});

describe("Typography stories", () => {
  it.each(Object.entries(composeStories(stories)))("%s renders", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(host.querySelector("[data-cmp='CMP-020']")).not.toBeNull();
  });
});

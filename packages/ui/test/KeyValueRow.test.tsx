// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import type { ReactNode } from "react";
import { expect, within } from "storybook/test";
import { describe, it } from "vitest";
import { KeyValueRow, NumericText } from "../src/components/index.js";
import * as stories from "../src/components/KeyValueRow.stories.js";
import { mount } from "./theme/mount.js";

const inList = (row: ReactNode): Promise<HTMLElement> => mount(<dl>{row}</dl>);

describe("KeyValueRow (CMP-036)", () => {
  it("renders a term and a definition, inline by default", async () => {
    const host = await inList(
      <KeyValueRow label="Liquidation" value={<NumericText value={61234.5} />} />,
    );
    const c = within(host);
    expect(c.getByRole("term")).toHaveTextContent("Liquidation");
    expect(c.getByRole("definition")).toHaveTextContent("61,234.50");
    const row = host.querySelector(".cv-kv");
    expect(row?.tagName).toBe("DIV");
    expect(row?.getAttribute("data-cmp")).toBe("CMP-036");
    expect(row?.getAttribute("data-layout")).toBe("inline");
    expect(row).not.toHaveAttribute("data-emphasis");
  });

  it("stacks the value under its label and marks emphasis", async () => {
    const host = await inList(
      <KeyValueRow label="Order id" value="ord-7f3a" layout="stacked" emphasis />,
    );
    const row = host.querySelector(".cv-kv");
    expect(row?.getAttribute("data-layout")).toBe("stacked");
    expect(row).toHaveAttribute("data-emphasis", "");
    expect(within(host).getByRole("definition")).toHaveTextContent("ord-7f3a");
  });

  it.each([undefined, null, ""])(
    "shows a missing value (%j) as a dash read as a word",
    async (value) => {
      const host = await inList(<KeyValueRow label="Funding" value={value} />);
      const dd = within(host).getByRole("definition");
      expect(dd).toHaveAttribute("data-missing", "");
      expect(dd.querySelector('[aria-hidden="true"]')).toHaveTextContent(/^—$/);
      expect(dd.querySelector(".cv-visually-hidden")).toHaveTextContent(/^no value$/);
    },
  );

  it("keeps a zero as a value and reads the host's state word when missing", async () => {
    const zero = await inList(<KeyValueRow label="Open" value={0} />);
    expect(within(zero).getByRole("definition")).not.toHaveAttribute("data-missing");
    const host = await inList(
      <KeyValueRow label="Mark" value={null} missingLabel="disconnected" />,
    );
    expect(host.querySelector(".cv-visually-hidden")).toHaveTextContent("disconnected");
  });

  it("wraps mixed inline content in one span and treats booleans as missing", async () => {
    const host = await inList(
      <KeyValueRow
        label="Venue"
        value={
          <>
            Bybit <b>linear</b> perp
          </>
        }
      />,
    );
    const dd = within(host).getByRole("definition");
    expect(dd.children).toHaveLength(1);
    expect(dd.firstElementChild).toHaveClass("cv-kv__content");
    expect(dd).toHaveTextContent("Bybit linear perp");
    const flag = await inList(<KeyValueRow label="Flag" value={false} />);
    expect(flag.querySelector(".cv-kv__value")).toHaveAttribute("data-missing", "");
  });

  it("puts the freshness slot inside the definition, after the value", async () => {
    const host = await inList(
      <KeyValueRow label="Mark" value="61,000" freshness={<span>stale</span>} />,
    );
    const dd = within(host).getByRole("definition");
    expect(dd.lastElementChild).toHaveClass("cv-kv__freshness");
    expect(dd).toHaveTextContent("61,000stale");
  });
});

describe("KeyValueRow stories", () => {
  it.each(Object.entries(composeStories(stories)))("%s renders", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(host.querySelector("dl .cv-kv")).not.toBeNull();
  });
});

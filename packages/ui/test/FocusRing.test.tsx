// @vitest-environment jsdom
import type { JSX } from "react";
import { expect, within } from "storybook/test";
import { describe, it } from "vitest";
import {
  Button,
  IconButton,
  RadioGroup,
  useFocusRing,
  type FocusRingOptions,
} from "../src/components/index.js";
import { mount } from "./theme/mount.js";

function Probe(props: FocusRingOptions): JSX.Element {
  const { className } = useFocusRing(props);
  return (
    <a href="#x" className={className}>
      Sample
    </a>
  );
}

describe("useFocusRing (CMP-039)", () => {
  it("returns the ring class, plus the inset modifier only when inset is set", async () => {
    const host = await mount(
      <>
        <Probe inset />
        <Probe inset={false} />
        <Probe />
      </>,
    );
    const [inset, plain, byDefault] = within(host).getAllByRole("link");
    expect(byDefault).toHaveClass("cv-focus-ring", { exact: true });
    expect(inset).toHaveClass("cv-focus-ring cv-focus-ring--inset", { exact: true });
    expect(plain).toHaveClass("cv-focus-ring", { exact: true });
  });

  it("the merged atoms use it: Button and IconButton carry the ring class", async () => {
    const host = await mount(
      <>
        <Button>Save</Button>
        <IconButton icon="close" label="Close" />
      </>,
    );
    expect(within(host).getByRole("button", { name: "Save" })).toHaveClass("cv-focus-ring");
    expect(within(host).getByRole("button", { name: "Close" })).toHaveClass("cv-focus-ring");
  });

  it("RadioGroup delegates the ring from the focusable row to its drawn ring", async () => {
    const host = await mount(
      <RadioGroup
        aria-label="Side"
        options={[
          { value: "a", label: "Alpha" },
          { value: "b", label: "Bravo" },
        ]}
      />,
    );
    const radio = within(host).getByRole("radio", { name: "Alpha" });
    expect(radio).toHaveClass("cv-focus-ring-host");
    expect(radio).not.toHaveClass("cv-focus-ring");
    expect(radio.querySelector(".cv-radio__ring")).toHaveClass("cv-focus-ring-target");
  });
});

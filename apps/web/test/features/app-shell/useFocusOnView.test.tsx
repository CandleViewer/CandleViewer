import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import type { JSX } from "react";
import { useFocusOnView } from "../../../src/features/app-shell/useFocusOnView";

function View({ view }: { readonly view: string }): JSX.Element {
  const ref = useFocusOnView(view);
  return <h1 ref={ref}>{view}</h1>;
}

describe("useFocusOnView (A11Y-P-02)", () => {
  it("leaves the first view alone and focuses the heading when the view changes", () => {
    const { rerender } = render(<View view="one" />);
    expect(screen.getByRole("heading")).not.toHaveFocus();
    rerender(<View view="one" />);
    expect(screen.getByRole("heading")).not.toHaveFocus();
    rerender(<View view="two" />);
    expect(screen.getByRole("heading", { name: "two" })).toHaveFocus();
    expect(screen.getByRole("heading")).toHaveAttribute("tabindex", "-1");
  });
});

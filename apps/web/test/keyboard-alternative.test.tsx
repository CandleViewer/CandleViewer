import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { assertKeyboardAlternative } from "./support/assertKeyboardAlternative";

/**
 * E47-S05 (#1319) "Every drag has a discrete equivalent": the parity helper itself, on a tiny order-line stand-in
 * that moves by pointer or by arrow keys (05 §3.1 rule 6: select, arrows nudge by a tick, Enter commits).
 */
const TICK = 5;

function Line({ keyed }: { readonly keyed: boolean }): JSX.Element {
  const [price, setPrice] = useState(100);
  return (
    <>
      <div
        role="slider"
        aria-label="Stop loss"
        aria-valuenow={price}
        tabIndex={0}
        data-testid="line"
        onMouseUp={(e) => setPrice(100 + e.clientY)}
        onKeyDown={(e) => {
          if (keyed && e.key === "ArrowUp") setPrice((p) => p + TICK);
        }}
      />
      <output data-testid="price">{price}</output>
      <button type="button" onClick={() => setPrice(100)}>
        reset
      </button>
    </>
  );
}

const run = (keys: readonly string[], keyed: boolean, tabIndex?: number) => {
  render(<Line keyed={keyed} />);
  const target = screen.getByTestId("line");
  if (tabIndex !== undefined) target.tabIndex = tabIndex;
  return assertKeyboardAlternative({
    target,
    drag: () => void fireEvent.mouseUp(target, { clientY: TICK }),
    keys,
    read: () => Number(screen.getByTestId("price").textContent),
    reset: () => void fireEvent.click(screen.getByRole("button", { name: "reset" })),
  });
};

describe("assertKeyboardAlternative", () => {
  it("passes when the keys reach the value the drag reaches", async () => {
    await run(["ArrowUp"], true);
  });
  it("fails when the keys do nothing", async () => {
    await expect(run(["ArrowUp"], false)).rejects.toThrow(/keys \["ArrowUp"\] reached 100/u);
  });
  it("fails when the keys land elsewhere", async () => {
    await expect(run(["ArrowUp", "ArrowUp"], true)).rejects.toThrow(
      /reached 110, the drag reached 105/u,
    );
  });
  it("fails when the target cannot take focus", async () => {
    await expect(run(["ArrowUp"], true, -1)).rejects.toThrow(/cannot take keyboard focus/u);
  });
});

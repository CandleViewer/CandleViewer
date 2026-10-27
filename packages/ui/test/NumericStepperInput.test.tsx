// @vitest-environment jsdom
import { act, useState, type JSX } from "react";
import { expect, fireEvent, fn, userEvent, waitFor, within } from "storybook/test";
import { describe, it } from "vitest";
import { NumericStepperInput, type NumericStepperInputProps } from "../src/components/index.js";
import { formatNumeric } from "../src/components/internal/numeric.js";
import { mount } from "./theme/mount.js";

const REASON = "Owner only";
type Props = Partial<NumericStepperInputProps> & { start?: number; log?: string[] };

/** A controlled host: `log` records the order of the callbacks. */
function Stepper({ start = 1, log, ...rest }: Props): JSX.Element {
  const [value, setValue] = useState(start);
  return (
    <NumericStepperInput
      label="Qty"
      step={0.1}
      precision={1}
      {...rest}
      value={value}
      onChange={(next) => {
        log?.push(`change ${next}`);
        setValue(next);
      }}
      onStep={(direction) => log?.push(`step ${direction}`)}
    />
  );
}

/** The description with its empty live nodes: compared as words, so a blank node never matters. */
const described = (el: HTMLElement, words: string): void => {
  const pattern = words
    .split(/\s+/)
    .filter(Boolean)
    .map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  expect(el).toHaveAccessibleDescription(new RegExp(`^\\s*${pattern.join("\\s+")}\\s*$`));
};
const field = (host: HTMLElement): HTMLInputElement =>
  within(host).getByRole("spinbutton", { name: "Qty" }) as HTMLInputElement;
const btn = (host: HTMLElement, name: string): HTMLButtonElement =>
  within(host).getByRole("button", { name }) as HTMLButtonElement;
const key = async (el: HTMLElement, init: KeyboardEventInit): Promise<boolean> => {
  let ok = true;
  await act(async () => {
    ok = await fireEvent.keyDown(el, init);
  });
  return ok;
};

describe("NumericStepperInput (CMP-008) semantics", () => {
  it("is a spinbutton with value, bounds and a valuetext that carries the unit", async () => {
    const host = await mount(
      <Stepper start={5} min={0} max={10} step={1} precision={0} suffix="%" />,
    );
    const el = field(host);
    expect(el).toHaveAttribute("type", "text");
    expect(el).toHaveAttribute("inputmode", "decimal");
    expect(el).toHaveAttribute("aria-valuenow", "5");
    expect(el).toHaveAttribute("aria-valuemin", "0");
    expect(el).toHaveAttribute("aria-valuemax", "10");
    expect(el).toHaveAttribute("aria-valuetext", "5 %");
    expect(el).toHaveValue("5");
    expect(host.querySelector(".cv-field__trail")).toHaveAttribute("aria-hidden", "true");
    described(el, "");
    expect(host.querySelector("[data-cmp]")).toHaveAttribute("data-cmp", "CMP-008");
  });

  it("omits the bounds and the unit when not given, and can be named by aria-labelledby", async () => {
    const host = await mount(
      <>
        <span id="l">Size</span>
        <Stepper aria-labelledby="l" density="compact" id="q" name="q" placeholder="0.0" />
      </>,
    );
    const el = within(host).getByRole("spinbutton", { name: "Size" });
    expect(el).not.toHaveAttribute("aria-valuemin");
    expect(el).not.toHaveAttribute("aria-valuemax");
    expect(el).toHaveAttribute("aria-valuetext", "1.0");
    expect(btn(host, "Increase Qty")).toBeInTheDocument();
    expect(host.querySelector("[data-density]")).toHaveAttribute("data-density", "compact");
  });

  it("the step buttons are named, outside the Tab order and plain disabled at a bound", async () => {
    const host = await mount(<Stepper start={0} min={0} max={0.1} />);
    for (const name of ["Decrease Qty", "Increase Qty"]) {
      expect(btn(host, name)).toHaveAttribute("tabindex", "-1");
      expect(btn(host, name)).toHaveAttribute("type", "button");
    }
    expect(btn(host, "Decrease Qty")).toBeDisabled();
    expect(btn(host, "Decrease Qty")).not.toHaveAttribute("aria-disabled");
    expect(btn(host, "Increase Qty")).toBeEnabled();
    await userEvent.tab();
    expect(field(host)).toHaveFocus();
    await userEvent.tab();
    expect(field(host)).not.toHaveFocus();
    expect(btn(host, "Increase Qty")).not.toHaveFocus();
  });
});

describe("NumericStepperInput keys", () => {
  it("steps by step, Shift by 10 x step, Page by 10 x step or largeStep; stops at the bounds", async () => {
    const host = await mount(<Stepper start={1} min={0} max={2} />);
    const el = field(host);
    expect(await key(el, { key: "ArrowUp" })).toBe(false);
    expect(el).toHaveValue("1.1");
    await key(el, { key: "ArrowDown", shiftKey: true });
    expect(el).toHaveValue("0.1");
    await key(el, { key: "ArrowDown" });
    await key(el, { key: "ArrowDown" });
    expect(el).toHaveValue("0.0");
    await key(el, { key: "PageUp" });
    expect(el).toHaveValue("1.0");
    await key(el, { key: "PageUp", shiftKey: true });
    expect(el).toHaveValue("2.0");
    await key(el, { key: "ArrowUp", shiftKey: true });
    expect(el).toHaveValue("2.0");
    await key(el, { key: "PageDown" });
    expect(el).toHaveValue("1.0");
  });

  it("Page uses largeStep when given, and the exact 10 x step otherwise", async () => {
    const host = await mount(
      <>
        <Stepper start={0.3} step={0.3} largeStep={2} aria-labelledby="none" label="Big" />
        <Stepper start={0.3} step={0.3} label="Def" />
      </>,
    );
    const [big, def] = within(host).getAllByRole("spinbutton");
    await key(big as HTMLElement, { key: "PageUp" });
    await key(def as HTMLElement, { key: "PageUp" });
    expect(big).toHaveValue("2.3");
    expect(def).toHaveValue("3.3");
  });

  it("Home and End jump to the bounds when set, otherwise do nothing and are not prevented", async () => {
    const host = await mount(
      <>
        <Stepper start={1} min={0.5} max={3} />
        <Stepper start={1} label="Free" />
      </>,
    );
    const el = field(host);
    expect(await key(el, { key: "End" })).toBe(false);
    expect(el).toHaveValue("3.0");
    await key(el, { key: "Home" });
    expect(el).toHaveValue("0.5");
    const free = within(host).getByRole("spinbutton", { name: "Free" });
    expect(await key(free, { key: "Home" })).toBe(true);
    expect(await key(free, { key: "End" })).toBe(true);
    expect(free).toHaveValue("1.0");
  });

  it("ignores modifier chords and IME composition, and other keys pass through", async () => {
    const log: string[] = [];
    const host = await mount(<Stepper log={log} />);
    const el = field(host);
    for (const mod of ["ctrlKey", "metaKey", "altKey"]) {
      expect(await key(el, { key: "ArrowUp", [mod]: true })).toBe(true);
    }
    expect(await key(el, { key: "ArrowUp", isComposing: true })).toBe(true);
    expect(await key(el, { key: "a" })).toBe(true);
    expect(log).toEqual([]);
  });

  it("onChange fires first, then onStep, only for a step that moved the value", async () => {
    const log: string[] = [];
    const host = await mount(<Stepper log={log} start={1.9} max={2} />);
    const el = field(host);
    await key(el, { key: "ArrowUp" });
    await key(el, { key: "ArrowUp" });
    await key(el, { key: "PageDown" });
    await key(el, { key: "Home" });
    expect(log).toEqual(["change 2", "step up", "change 1", "step down"]);
  });

  it("the buttons step once per press, keep the focus on the field, and disable at a bound", async () => {
    const log: string[] = [];
    const host = await mount(<Stepper log={log} start={1.9} max={2} />);
    await userEvent.click(btn(host, "Increase Qty"));
    expect(field(host)).toHaveFocus();
    expect(field(host)).toHaveValue("2.0");
    expect(btn(host, "Increase Qty")).toBeDisabled();
    await userEvent.click(btn(host, "Decrease Qty"));
    expect(field(host)).toHaveValue("1.9");
    expect(log).toEqual(["change 2", "step up", "change 1.9", "step down"]);
  });

  it("steps from clean typed text, and from the committed value when the entry was refused", async () => {
    const host = await mount(<Stepper start={1} min={0} max={9} />);
    const el = field(host);
    await userEvent.clear(el);
    await userEvent.type(el, "5");
    await key(el, { key: "ArrowUp" });
    expect(el).toHaveValue("5.1");
    await userEvent.clear(el);
    await userEvent.type(el, "-5");
    await userEvent.tab();
    expect(el).toHaveAttribute("aria-invalid", "true");
    el.focus();
    await key(el, { key: "ArrowUp" });
    expect(el).toHaveValue("5.2");
    expect(el).not.toHaveAttribute("aria-invalid");
  });

  it("a seeded loop of step sequences stays exact against scaled-integer arithmetic", async () => {
    let seed = 20261027;
    const rand = (n: number): number => {
      seed = (seed + 0x6d2b79f5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return Math.floor((((t ^ (t >>> 14)) >>> 0) / 4294967296) * n);
    };
    for (let round = 0; round < 8; round++) {
      const precision = rand(7);
      const unit = 10 ** precision;
      const stepUnits = 1 + rand(40);
      const min = -500 - rand(500);
      const max = 500 + rand(500);
      let model = min + rand(max - min);
      const host = await mount(
        <Stepper
          start={model / unit}
          precision={precision}
          step={stepUnits / unit}
          label={`R${round}`}
          min={min / unit}
          max={max / unit}
        />,
      );
      const el = within(host).getByRole("spinbutton");
      for (let i = 0; i < 30; i++) {
        const k = rand(4);
        const dir = rand(2) === 0 ? 1 : -1;
        const mult = k === 0 ? 1 : 10;
        const init =
          k < 2
            ? { key: dir > 0 ? "ArrowUp" : "ArrowDown", shiftKey: k === 1 }
            : { key: dir > 0 ? "PageUp" : "PageDown" };
        await key(el, init);
        model = Math.min(max, Math.max(min, model + dir * stepUnits * mult));
        const expected = formatNumeric(model / unit, precision);
        expect(el).toHaveValue(expected);
        expect(Number(el.getAttribute("aria-valuenow"))).toBe(Number(expected));
      }
    }
  });
});

describe("NumericStepperInput typed text", () => {
  const type = async (el: HTMLElement, text: string): Promise<void> => {
    await userEvent.clear(el);
    await userEvent.type(el, text);
  };

  it("an out-of-range entry is invalid, never clamped: error shown, value unchanged (AC)", async () => {
    const log: string[] = [];
    const host = await mount(<Stepper log={log} start={0.5} min={0} />);
    const el = field(host);
    await type(el, "-5");
    expect(el).not.toHaveAttribute("aria-invalid");
    expect(log).toEqual([]);
    await userEvent.tab();
    expect(el).toHaveAttribute("aria-invalid", "true");
    expect(el).toHaveValue("-5");
    expect(el).toHaveAttribute("aria-valuenow", "0.5");
    described(el, "Minimum 0.0");
    expect(host.querySelector(".cv-field")).toHaveAttribute("data-invalid");
    expect(log).toEqual([]);
    await userEvent.type(el, "{Backspace}");
    expect(el).toHaveAttribute("aria-invalid", "true");
    await type(el, "2");
    expect(el).not.toHaveAttribute("aria-invalid");
  });

  it("above the maximum names the bound; text that is no number is refused", async () => {
    const host = await mount(<Stepper start={1} min={0} max={9.5} />);
    const el = field(host);
    await type(el, "12{Enter}");
    described(el, "Maximum 9.5");
    await type(el, "1e3{Enter}");
    described(el, "Enter a number.");
    await type(el, "1.2.3");
    await userEvent.tab();
    described(el, "Enter a number.");
    expect(el).toHaveAttribute("aria-valuenow", "1");
  });

  it("commits in-range text on blur or Enter, rounded to precision, with the caption", async () => {
    const log: string[] = [];
    const host = await mount(<Stepper log={log} start={1} min={0} max={9} />);
    const el = field(host);
    await type(el, "2.26");
    expect(log).toEqual([]);
    await userEvent.tab();
    expect(log).toEqual(["change 2.3"]);
    expect(el).toHaveValue("2.3");
    described(el, "(rounded to nearest tick)");
    expect(host.querySelector(".cv-field__caption")).toHaveAttribute("aria-live", "polite");
    await type(el, "3{Enter}");
    expect(log).toEqual(["change 2.3", "change 3"]);
    expect(el).toHaveValue("3.0");
    described(el, "");
  });

  it("the caption stays when rounding lands on the current value, and goes with the next edit", async () => {
    const log: string[] = [];
    const host = await mount(<Stepper log={log} start={1} />);
    const el = field(host);
    await type(el, "1.04{Enter}");
    expect(log).toEqual([]);
    described(el, "(rounded to nearest tick)");
    await userEvent.type(el, "{Backspace}");
    described(el, "");
  });

  it("empty text is invalid on blur (Enter a number.), never a silent revert; Enter commits only an edit", async () => {
    const log: string[] = [];
    const host = await mount(<Stepper start={1} log={log} />);
    const el = field(host);
    await userEvent.click(el);
    await key(el, { key: "Enter" });
    expect(el).not.toHaveAttribute("aria-invalid");
    await userEvent.clear(el);
    await userEvent.tab();
    expect(el).toHaveValue("");
    expect(el).toHaveAttribute("aria-invalid", "true");
    described(el, "Enter a number.");
    expect(log).toEqual([]);
  });

  it("an error stays, with the same words, while the text is still invalid, and is not spoken again on blur", async () => {
    const host = await mount(<Stepper start={0.5} min={0} />);
    const el = field(host);
    const message = host.querySelector("[aria-live]") as HTMLElement;
    const spoken: string[] = [];
    const watch = new MutationObserver(() => spoken.push(message.textContent ?? ""));
    watch.observe(message, { childList: true, characterData: true, subtree: true });
    await userEvent.clear(el);
    await userEvent.type(el, "-5");
    await userEvent.tab();
    described(el, "Minimum 0.0");
    const heard = spoken.length;
    await userEvent.click(el);
    await userEvent.type(el, "6");
    expect(el).toHaveValue("-56");
    expect(el).toHaveAttribute("aria-invalid", "true");
    described(el, "Minimum 0.0");
    await userEvent.tab();
    expect(el).toHaveAttribute("aria-invalid", "true");
    described(el, "Minimum 0.0");
    expect(spoken.length).toBe(heard);
    await userEvent.click(el);
    await type(el, "6");
    expect(el).not.toHaveAttribute("aria-invalid");
    described(el, "");
    watch.disconnect();
  });

  it("while an error shows, typing does not re-word it; a commit does, and valid text clears it", async () => {
    const host = await mount(<Stepper start={1} min={0} max={9} />);
    const el = field(host);
    const message = host.querySelector("[aria-live]") as HTMLElement;
    await type(el, "-1");
    await userEvent.tab();
    described(el, "Minimum 0.0");
    const spoken: string[] = [];
    const watch = new MutationObserver(() => spoken.push(message.textContent ?? ""));
    watch.observe(message, { childList: true, characterData: true, subtree: true });
    await userEvent.click(el);
    await userEvent.type(el, "{Backspace}{Backspace}{Backspace}");
    expect(el).toHaveValue("");
    described(el, "Minimum 0.0");
    await userEvent.type(el, "-3");
    described(el, "Minimum 0.0");
    expect(spoken).toEqual([]);
    await userEvent.tab();
    described(el, "Minimum 0.0");
    await userEvent.click(el);
    await userEvent.clear(el);
    await userEvent.tab();
    described(el, "Enter a number.");
    expect(spoken).toEqual(["Enter a number."]);
    watch.disconnect();
  });

  it("an empty draft has no aria-valuetext, and a tiny bound is shown in plain decimals", async () => {
    const host = await mount(<Stepper start={1} min={0.0000001} />);
    const el = field(host);
    await userEvent.clear(el);
    expect(el).not.toHaveAttribute("aria-valuetext");
    await userEvent.type(el, "0");
    await userEvent.tab();
    described(el, "Minimum 0.0000001");
  });

  it("a NaN value renders empty without a render loop, and a later finite value shows", async () => {
    const Moves = (): JSX.Element => {
      const [v, setV] = useState(Number.NaN);
      return (
        <>
          <NumericStepperInput label="Qty" step={1} precision={0} value={v} onChange={setV} />
          <button type="button" onClick={() => setV((x) => (Number.isNaN(x) ? 3 : Number.NaN))}>
            swing
          </button>
        </>
      );
    };
    const host = await mount(<Moves />);
    const el = field(host);
    expect(el).toHaveValue("");
    await userEvent.click(within(host).getByRole("button", { name: "swing" }));
    expect(el).toHaveValue("3");
    await userEvent.click(within(host).getByRole("button", { name: "swing" }));
    expect(el).toHaveValue("");
  });

  it("a field whose value is NaN takes a typed number and commits it", async () => {
    const onChange = fn();
    const host = await mount(
      <NumericStepperInput
        label="Qty"
        step={1}
        precision={0}
        value={Number.NaN}
        onChange={onChange}
      />,
    );
    const el = field(host);
    expect(el).not.toHaveAttribute("aria-valuenow");
    await userEvent.type(el, "5");
    expect(el).toHaveValue("5");
    await userEvent.tab();
    expect(onChange).toHaveBeenLastCalledWith(5);
  });

  it("an empty draft carries no stale aria-valuenow", async () => {
    const host = await mount(<Stepper start={4} />);
    const el = field(host);
    expect(el).toHaveAttribute("aria-valuenow", "4");
    await userEvent.clear(el);
    expect(el).not.toHaveAttribute("aria-valuenow");
  });

  it("an off-grid bound is shown as given, an on-grid one at the precision", async () => {
    const host = await mount(<Stepper start={1} min={0.05} />);
    const el = field(host);
    await type(el, "0");
    await userEvent.tab();
    described(el, "Minimum 0.05");
  });

  it("while a draft is pending Home and End are caret keys, not steps", async () => {
    const log: string[] = [];
    const host = await mount(<Stepper start={1} min={0.5} max={3} log={log} />);
    const el = field(host);
    await type(el, "12");
    expect(await key(el, { key: "Home" })).toBe(true);
    expect(await key(el, { key: "End", shiftKey: true })).toBe(true);
    expect(el).toHaveValue("12");
    expect(log).toEqual([]);
  });

  it("a caption earned by an old value does not come back when the host returns to it", async () => {
    const Moves = (): JSX.Element => {
      const [v, setV] = useState(1);
      return (
        <>
          <NumericStepperInput label="Qty" step={0.1} precision={1} value={v} onChange={setV} />
          <button type="button" onClick={() => setV((x) => (x === 1.1 ? 7 : 1.1))}>
            swing
          </button>
        </>
      );
    };
    const host = await mount(<Moves />);
    const el = field(host);
    await type(el, "1.14{Enter}");
    described(el, "(rounded to nearest tick)");
    await userEvent.click(within(host).getByRole("button", { name: "swing" }));
    expect(el).toHaveValue("7.0");
    described(el, "");
    await userEvent.click(within(host).getByRole("button", { name: "swing" }));
    expect(el).toHaveValue("1.1");
    described(el, "");
  });

  it("aria-valuetext follows the shown text while an edit is pending, with the unit", async () => {
    const host = await mount(<Stepper start={5} step={1} precision={0} suffix="%" />);
    const el = field(host);
    await type(el, "7");
    expect(el).toHaveAttribute("aria-valuetext", "7 %");
    expect(el).toHaveAttribute("aria-valuenow", "5");
    const plain = await mount(<Stepper start={5} label="P" />);
    const other = within(plain).getByRole("spinbutton", { name: "P" });
    await type(other, "7");
    expect(other).toHaveAttribute("aria-valuetext", "7");
  });

  it("a draft is discarded, not committed, when the field becomes gated mid-edit", async () => {
    const log: string[] = [];
    const Gates = (): JSX.Element => {
      const [gated, setGated] = useState(false);
      return (
        <>
          <Stepper log={log} start={1} {...(gated ? { disabledReason: REASON } : {})} />
          <button type="button" onClick={() => setGated(true)}>
            gate
          </button>
        </>
      );
    };
    const host = await mount(<Gates />);
    const el = field(host);
    await type(el, "2");
    await act(async () => {
      within(host).getByRole("button", { name: "gate" }).click();
    });
    await act(async () => {
      el.focus();
      el.blur();
    });
    expect(log).toEqual([]);
    expect(el).toHaveValue("1.0");
  });

  it("an edit is dropped when the host moves the value", async () => {
    const Moves = (): JSX.Element => {
      const [v, setV] = useState(1);
      return (
        <>
          <NumericStepperInput label="Qty" step={0.1} precision={1} value={v} onChange={setV} />
          <button type="button" onClick={() => setV(7)}>
            reset
          </button>
        </>
      );
    };
    const host = await mount(<Moves />);
    await type(field(host), "4");
    await userEvent.click(within(host).getByRole("button", { name: "reset" }));
    expect(field(host)).toHaveValue("7.0");
  });

  it("a draft typed against A does not come back when the host goes A, B, A", async () => {
    const Moves = (): JSX.Element => {
      const [v, setV] = useState(1);
      return (
        <>
          <NumericStepperInput label="Qty" step={0.1} precision={1} value={v} onChange={setV} />
          <button type="button" onClick={() => setV((x) => (x === 1 ? 7 : 1))}>
            swing
          </button>
        </>
      );
    };
    const host = await mount(<Moves />);
    const el = field(host);
    await type(el, "4");
    await fireEvent.click(within(host).getByRole("button", { name: "swing" }));
    expect(el).toHaveValue("7.0");
    await fireEvent.click(within(host).getByRole("button", { name: "swing" }));
    expect(el).toHaveValue("1.0");
  });

  it("the host's own invalid and message render; a typed error replaces its message", async () => {
    const host = await mount(
      <>
        <span id="help">Help</span>
        <Stepper start={1} min={0} invalid errorMessage="Too small." aria-describedby="help" />
      </>,
    );
    const el = field(host);
    expect(el).toHaveAttribute("aria-invalid", "true");
    described(el, "Too small. Help");
    await type(el, "-1{Enter}");
    described(el, "Minimum 0.0 Help");
  });
});

describe("NumericStepperInput states", () => {
  it("T2: lock, aria-disabled, readonly, the reason alone described; keys change nothing, announced once", async () => {
    const log: string[] = [];
    const host = await mount(
      <>
        <Stepper log={log} disabledReason={REASON} max={9} />
        <button type="button">next</button>
      </>,
    );
    const el = field(host);
    expect(el).toHaveAttribute("aria-disabled", "true");
    expect(el).toHaveAttribute("readonly");
    expect(el).not.toHaveAttribute("aria-readonly");
    expect(el).toHaveAccessibleDescription(REASON);
    expect(within(host).getByRole("img", { name: "Not available" })).toBeInTheDocument();
    const status = within(host).getByRole("status");
    await userEvent.tab();
    expect(el).toHaveFocus();
    expect(status).toHaveTextContent("");
    expect(await key(el, { key: "ArrowUp", ctrlKey: true })).toBe(true);
    expect(await key(el, { key: "Home", ctrlKey: true })).toBe(true);
    expect(status).toHaveTextContent("");
    for (const init of [
      { key: "ArrowUp" },
      { key: "ArrowDown", shiftKey: true },
      { key: "PageUp" },
      { key: "PageDown" },
    ]) {
      expect(await key(el, init)).toBe(false);
      expect(status).toHaveTextContent(REASON);
    }
    expect(el).toHaveValue("1.0");
    expect(log).toEqual([]);
    await userEvent.tab();
    expect(status).toHaveTextContent("");
  });

  it("T2: Home and End are refused and announced when their bound is set, free when it is not", async () => {
    const host = await mount(
      <>
        <Stepper start={1} min={0.5} disabledReason={REASON} label="MinOnly" />
        <Stepper start={1} max={3} disabledReason={REASON} label="MaxOnly" />
        <Stepper start={1} disabledReason={REASON} label="None" />
      </>,
    );
    const open = within(host).getAllByRole("status");
    const pick = (n: string): HTMLElement => within(host).getByRole("spinbutton", { name: n });
    expect(await key(pick("MinOnly"), { key: "End" })).toBe(true);
    expect(open[0]).toHaveTextContent("");
    expect(await key(pick("MinOnly"), { key: "Home" })).toBe(false);
    expect(open[0]).toHaveTextContent(REASON);
    expect(await key(pick("MaxOnly"), { key: "Home" })).toBe(true);
    expect(await key(pick("MaxOnly"), { key: "End" })).toBe(false);
    expect(open[1]).toHaveTextContent(REASON);
    expect(await key(pick("None"), { key: "Home" })).toBe(true);
    expect(await key(pick("None"), { key: "End" })).toBe(true);
    expect(open[2]).toHaveTextContent("");
    expect(pick("MinOnly")).toHaveValue("1.0");
  });

  it("T2: Enter and printable keys are refused and never submit the form", async () => {
    const onSubmit = fn((e: { preventDefault: () => void }) => e.preventDefault());
    const host = await mount(
      <form onSubmit={onSubmit}>
        <Stepper disabledReason={REASON} />
        <button type="submit">go</button>
      </form>,
    );
    await userEvent.click(field(host));
    await userEvent.keyboard("5{Enter}");
    expect(onSubmit).not.toHaveBeenCalled();
    expect(field(host)).toHaveValue("1.0");
    expect(within(host).getByRole("status")).toHaveTextContent(REASON);
  });

  it("T2: the step buttons are aria-disabled, point at the reason, focus the field and re-show it", async () => {
    const log: string[] = [];
    const host = await mount(<Stepper log={log} disabledReason={REASON} min={1} />);
    const status = within(host).getByRole("status");
    for (const name of ["Decrease Qty", "Increase Qty"]) {
      expect(btn(host, name)).toHaveAttribute("aria-disabled", "true");
      expect(btn(host, name)).toBeEnabled();
      expect(btn(host, name)).toHaveAccessibleDescription(REASON);
    }
    await userEvent.click(btn(host, "Increase Qty"));
    expect(field(host)).toHaveFocus();
    await waitFor(() => expect(status).toHaveTextContent(REASON));
    await userEvent.tab();
    expect(status).toHaveTextContent("");
    await userEvent.click(btn(host, "Decrease Qty"));
    await waitFor(() => expect(status).toHaveTextContent(REASON));
    expect(field(host)).toHaveValue("1.0");
    expect(log).toEqual([]);
  });

  it("read-only: focusable, aria-readonly, keys and buttons change nothing", async () => {
    const log: string[] = [];
    const host = await mount(<Stepper log={log} readOnly />);
    const el = field(host);
    expect(el).toHaveAttribute("aria-readonly", "true");
    expect(el).toHaveAttribute("readonly");
    await userEvent.tab();
    expect(el).toHaveFocus();
    expect(await key(el, { key: "ArrowUp" })).toBe(true);
    expect(btn(host, "Increase Qty")).toBeDisabled();
    expect(btn(host, "Decrease Qty")).toBeDisabled();
    expect(log).toEqual([]);
    expect(within(host).queryByRole("status")).toBeNull();
  });

  it("plain disabled: native disabled field and buttons, out of the Tab order", async () => {
    const host = await mount(<Stepper disabled />);
    expect(field(host)).toBeDisabled();
    expect(btn(host, "Increase Qty")).toBeDisabled();
    await userEvent.tab();
    expect(field(host)).not.toHaveFocus();
  });

  it("a press on the well's padding or the unit focuses the field", async () => {
    const host = await mount(<Stepper suffix="%" />);
    await userEvent.click(host.querySelector(".cv-field__trail") as HTMLElement);
    expect(field(host)).toHaveFocus();
  });
});

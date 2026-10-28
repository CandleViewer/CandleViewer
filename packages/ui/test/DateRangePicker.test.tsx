// @vitest-environment jsdom
import { act, useState, type JSX } from "react";
import { expect, fireEvent, fn, within } from "storybook/test";
import { afterEach, describe, it, vi } from "vitest";
import {
  DateRangePicker,
  FormField,
  type DateRangePickerProps,
  type DateRangeValue,
} from "../src/components/index.js";
import { rangeSentence, startSentence } from "../src/components/DateRangePicker.js";
import { mount } from "./theme/mount.js";

afterEach(() => vi.restoreAllMocks());

const NOW = (): number => Date.UTC(2026, 9, 28, 12);
const REASON = "Your role can't control replay.";
const EMPTY: DateRangeValue = { start: null, end: null };

function Host(props: Partial<DateRangePickerProps>): JSX.Element {
  const [value, setValue] = useState<DateRangeValue>(props.value ?? EMPTY);
  return (
    <DateRangePicker
      aria-label="Replay range"
      now={NOW}
      {...props}
      value={value}
      onChange={(next) => {
        setValue(next);
        props.onChange?.(next);
      }}
    />
  );
}

const box = (host: HTMLElement, name: string): HTMLInputElement =>
  within(host).getByRole("textbox", { name }) as HTMLInputElement;
const button = (host: HTMLElement): HTMLButtonElement =>
  within(host).getByRole("button", { name: "Choose dates" }) as HTMLButtonElement;
const dialog = (): HTMLElement | null =>
  document.querySelector<HTMLElement>(".cv-datepicker__dialog:not([hidden])");
const openDialog = (): HTMLElement => {
  const node = dialog();
  if (node === null) throw new Error("the calendar is closed");
  return node;
};
const day = (name: string): HTMLButtonElement =>
  within(openDialog()).getByRole("button", { name }) as HTMLButtonElement;
const cell = (name: string): HTMLElement => day(name).parentElement as HTMLElement;
const focusedName = (): string | null => document.activeElement?.getAttribute("aria-label") ?? null;
const key = async (k: string, init: object = {}): Promise<void> => {
  await act(async () => {
    fireEvent.keyDown(document.activeElement ?? document.body, { key: k, ...init });
  });
};
const click = async (el: Element): Promise<void> => {
  await act(async () => {
    fireEvent.click(el);
  });
};
const type = async (input: HTMLInputElement, text: string): Promise<void> => {
  await act(async () => input.focus());
  await act(async () => {
    fireEvent.change(input, { target: { value: text } });
  });
  await act(async () => input.blur());
};
/** The group's own status (not the dialog's). */
const groupStatus = (host: HTMLElement): HTMLElement => {
  const node = host.querySelector<HTMLElement>(".cv-daterange > [role='status']");
  if (node === null) throw new Error("no group status");
  return node;
};

describe("DateRangePicker (CMP-047 range): the fields", () => {
  it("renders a named group: Start and End fields and one calendar button, on the End field", async () => {
    const host = await mount(<Host value={{ start: "2026-10-01", end: "2026-10-07" }} />);
    const group = within(host).getByRole("group", { name: "Replay range" });
    expect(group).toHaveAttribute("data-cmp", "CMP-047");
    expect(group).toHaveAttribute("data-mode", "range");
    expect(box(host, "Start")).toHaveValue("2026-10-01");
    expect(box(host, "End")).toHaveValue("2026-10-07");
    expect(within(host).getAllByRole("button")).toHaveLength(1);
    expect(box(host, "End").closest(".cv-field")).toContainElement(button(host));
    expect(button(host)).toHaveAttribute("aria-haspopup", "dialog");
    expect(box(host, "Start")).toHaveAccessibleDescription(/YYYY-MM-DD UTC$/);
  });

  it("commits each typed field on its own, keeping the other", async () => {
    const onChange = fn();
    const host = await mount(
      <Host value={{ start: "2026-10-01", end: null }} onChange={onChange} />,
    );
    await type(box(host, "End"), "2026-10-09");
    expect(onChange).toHaveBeenLastCalledWith({ start: "2026-10-01", end: "2026-10-09" });
    await type(box(host, "Start"), "");
    expect(onChange).toHaveBeenLastCalledWith({ start: null, end: "2026-10-09" });
  });

  it("words an unparsable field and marks only that well invalid", async () => {
    const onChange = fn();
    const host = await mount(<Host onChange={onChange} />);
    await type(box(host, "End"), "2026-13-01");
    expect(onChange).not.toHaveBeenCalled();
    expect(box(host, "End")).toHaveAttribute("aria-invalid", "true");
    expect(box(host, "Start")).not.toHaveAttribute("aria-invalid");
    expect(within(host).getByText("Enter a date as YYYY-MM-DD.")).toBeInTheDocument();
  });

  it("refuses a typed day outside min-max with the caption; a reversed range is the host's to judge", async () => {
    const onChange = fn();
    const host = await mount(<Host min="2026-09-01" max="2026-10-28" onChange={onChange} />);
    await type(box(host, "Start"), "2026-08-31");
    expect(onChange).not.toHaveBeenCalled();
    expect(within(host).getByText("Choose a date from 2026-09-01 to 2026-10-28.")).toBeVisible();
    await type(box(host, "Start"), "2026-10-10");
    await type(box(host, "End"), "2026-10-02");
    expect(onChange).toHaveBeenLastCalledWith({ start: "2026-10-10", end: "2026-10-02" });
  });

  it("lets a FormField name the group and draw the lines", async () => {
    const host = await mount(
      <FormField label="Replay window" error="Nothing is recorded for that window.">
        <DateRangePicker value={EMPTY} onChange={fn()} now={NOW} />
      </FormField>,
    );
    expect(within(host).getByRole("group", { name: "Replay window" })).toBeInTheDocument();
    expect(box(host, "Start")).toHaveAttribute("aria-invalid", "true");
    expect(box(host, "End")).toHaveAccessibleDescription(/^Nothing is recorded for that window\./);
    expect(within(host).getAllByText("Nothing is recorded for that window.")).toHaveLength(1);
  });
});

describe("DateRangePicker (CMP-047 range): the calendar", () => {
  it("opens on the start; the first pick sets the start, the second the end, and closes", async () => {
    const onChange = fn();
    const host = await mount(
      <Host value={{ start: "2026-10-05", end: "2026-10-06" }} onChange={onChange} />,
    );
    await click(button(host));
    expect(focusedName()).toBe("5 October 2026");
    await click(day("1 October 2026"));
    expect(onChange).not.toHaveBeenCalled();
    expect(dialog()).not.toBeNull();
    expect(cell("1 October 2026")).toHaveAttribute("aria-selected", "true");
    expect(cell("6 October 2026")).not.toHaveAttribute("aria-selected");
    await click(day("7 October 2026"));
    expect(onChange).toHaveBeenCalledWith({ start: "2026-10-01", end: "2026-10-07" });
    expect(dialog()).toBeNull();
    expect(button(host)).toHaveFocus();
    expect(box(host, "Start")).toHaveValue("2026-10-01");
    expect(box(host, "End")).toHaveValue("2026-10-07");
  });

  it("replaces the start with a second pick before it", async () => {
    const onChange = fn();
    const host = await mount(<Host onChange={onChange} />);
    await click(button(host));
    await click(day("10 October 2026"));
    await click(day("3 October 2026"));
    expect(dialog()).not.toBeNull();
    expect(cell("3 October 2026")).toHaveAttribute("aria-selected", "true");
    expect(cell("10 October 2026")).not.toHaveAttribute("aria-selected");
    await click(day("3 October 2026"));
    expect(onChange).toHaveBeenCalledWith({ start: "2026-10-03", end: "2026-10-03" });
  });

  it("selects every day of the range, the ends marked and the band between", async () => {
    const host = await mount(<Host value={{ start: "2026-10-01", end: "2026-10-04" }} />);
    await click(button(host));
    for (const d of [1, 2, 3, 4])
      expect(cell(`${d} October 2026`)).toHaveAttribute("aria-selected");
    expect(cell("5 October 2026")).not.toHaveAttribute("aria-selected");
    expect(day("1 October 2026")).toHaveAttribute("data-selected");
    expect(day("4 October 2026")).toHaveAttribute("data-selected");
    expect(cell("2 October 2026")).toHaveAttribute("data-in-range");
    expect(cell("3 October 2026")).toHaveAttribute("data-in-range");
    expect(cell("1 October 2026")).not.toHaveAttribute("data-in-range");
  });

  it("previews the band to the day under the pointer, else the focused day, while the end is pending", async () => {
    const host = await mount(<Host />);
    await click(button(host));
    await click(day("5 October 2026"));
    await key("ArrowRight");
    await key("ArrowRight");
    expect(cell("6 October 2026")).toHaveAttribute("data-in-range");
    expect(cell("7 October 2026")).toHaveAttribute("data-in-range");
    expect(cell("7 October 2026")).not.toHaveAttribute("aria-selected");
    await act(async () => {
      // React derives mouseenter from mouseover.
      fireEvent.mouseOver(day("9 October 2026"));
    });
    expect(cell("8 October 2026")).toHaveAttribute("data-in-range");
    await act(async () => {
      fireEvent.mouseOut(within(openDialog()).getByRole("grid"), {
        relatedTarget: document.body,
      });
    });
    expect(cell("8 October 2026")).not.toHaveAttribute("data-in-range");
  });

  it("speaks the start then the range: two polite sentences, at most", async () => {
    const host = await mount(<Host />);
    const status = groupStatus(host);
    await click(button(host));
    const inDialog = within(openDialog()).getAllByRole("status");
    const startStatus = inDialog[inDialog.length - 1] as HTMLElement;
    expect(startStatus).toHaveTextContent("");
    await click(day("1 October 2026"));
    expect(startStatus).toHaveTextContent("Start 2026-10-01. Choose the end date.");
    await key("ArrowRight");
    expect(startStatus).toHaveTextContent("Start 2026-10-01. Choose the end date.");
    await click(day("7 October 2026"));
    expect(status).toHaveTextContent("2026-10-01 to 2026-10-07, 7 days.");
    expect(status).toHaveAttribute("role", "status");
  });

  it("forms the two sentences, a one-day range in the singular", () => {
    expect(startSentence("2026-10-01")).toBe("Start 2026-10-01. Choose the end date.");
    expect(rangeSentence("2026-10-01", "2026-10-07")).toBe("2026-10-01 to 2026-10-07, 7 days.");
    expect(rangeSentence("2026-10-03", "2026-10-03")).toBe("2026-10-03 to 2026-10-03, 1 day.");
  });

  it("closes on Esc without a change, dropping a pending start", async () => {
    const onChange = fn();
    const host = await mount(
      <Host value={{ start: "2026-10-05", end: "2026-10-06" }} onChange={onChange} />,
    );
    await click(button(host));
    await click(day("1 October 2026"));
    await key("Escape");
    expect(dialog()).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
    expect(button(host)).toHaveFocus();
    expect(groupStatus(host)).toHaveTextContent("");
    await click(button(host));
    expect(focusedName()).toBe("5 October 2026");
    expect(cell("6 October 2026")).toHaveAttribute("aria-selected");
  });

  it("opens with Alt+ArrowDown in the Start field", async () => {
    const host = await mount(<Host />);
    await act(async () => box(host, "Start").focus());
    await key("ArrowDown", { altKey: true });
    expect(focusedName()).toBe("28 October 2026, today");
  });

  it("refuses an out-of-range day as a pick, the caption spoken", async () => {
    const onChange = fn();
    const host = await mount(<Host min="2026-10-02" onChange={onChange} />);
    await click(button(host));
    await click(day("1 October 2026"));
    expect(cell("1 October 2026")).not.toHaveAttribute("aria-selected");
    expect(within(openDialog()).getAllByRole("status")[0]).toHaveTextContent(
      "Choose a date on or after 2026-10-02.",
    );
  });
});

describe("DateRangePicker (CMP-047 range): time and gates", () => {
  it("withTime: Start time and End time wells, typed HH:MM, the button after the End time", async () => {
    const onChange = fn();
    const host = await mount(
      <Host
        withTime
        value={{ start: "2026-10-01", end: "2026-10-02", startTime: null, endTime: null }}
        onChange={onChange}
      />,
    );
    const startTime = box(host, "Start time");
    expect(startTime).toHaveAttribute("placeholder", "HH:MM");
    await type(startTime, "9:05");
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ startTime: "09:05" }));
    await type(box(host, "End time"), "24:00");
    expect(box(host, "End time")).toHaveAttribute("aria-invalid", "true");
    expect(within(host).getByText("Enter a time as HH:MM, 24-hour UTC.")).toBeInTheDocument();
    expect(box(host, "End time").closest(".cv-field")).toContainElement(button(host));
    expect(within(host).getByText("YYYY-MM-DD HH:MM")).toBeInTheDocument();
  });

  it("keeps the times when the calendar sets the days", async () => {
    const onChange = fn();
    const host = await mount(
      <Host
        withTime
        value={{ start: null, end: null, startTime: "14:05", endTime: "15:00" }}
        onChange={onChange}
      />,
    );
    await click(button(host));
    await click(day("1 October 2026"));
    await click(day("2 October 2026"));
    expect(onChange).toHaveBeenCalledWith({
      start: "2026-10-01",
      end: "2026-10-02",
      startTime: "14:05",
      endTime: "15:00",
    });
  });

  it("T2: every field read-only behind the lock, one reason, the button aria-disabled, nothing opens", async () => {
    const host = await mount(<Host withTime disabledReason={REASON} />);
    for (const name of ["Start", "Start time", "End", "End time"]) {
      const input = box(host, name);
      expect(input).toHaveAttribute("readonly");
      expect(input).toHaveAttribute("aria-disabled", "true");
      expect(input).toHaveAccessibleDescription(REASON);
    }
    expect(within(host).getAllByRole("img", { name: "Not available" })).toHaveLength(4);
    expect(within(host).getAllByText(REASON).length).toBeGreaterThanOrEqual(1);
    expect(button(host)).toHaveAttribute("aria-disabled", "true");
    await click(button(host));
    expect(dialog()).toBeNull();
  });

  it("plain disabled: every field and the button natively disabled, the labels dimmed", async () => {
    const host = await mount(<Host disabled />);
    expect(box(host, "Start")).toBeDisabled();
    expect(box(host, "End")).toBeDisabled();
    expect(button(host)).toBeDisabled();
    expect(within(host).getByRole("group")).toHaveAttribute("data-disabled");
  });

  it("read-only: the values stay, the button is disabled", async () => {
    const host = await mount(<Host readOnly value={{ start: "2026-10-01", end: "2026-10-02" }} />);
    expect(box(host, "Start")).toHaveAttribute("readonly");
    expect(box(host, "Start")).not.toHaveAttribute("aria-disabled");
    expect(button(host)).toBeDisabled();
  });
});

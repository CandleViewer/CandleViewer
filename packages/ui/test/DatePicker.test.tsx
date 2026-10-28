// @vitest-environment jsdom
import { act, useState, type JSX } from "react";
import { expect, fireEvent, fn, userEvent, within } from "storybook/test";
import { afterEach, describe, it, vi } from "vitest";
import { DatePicker, FormField, type DatePickerProps } from "../src/components/index.js";
import { nextFocus } from "../src/components/internal/CalendarGrid.js";
import { mount } from "./theme/mount.js";

afterEach(() => vi.restoreAllMocks());

/** The injected clock: 2026-10-28, mid-day UTC. */
const NOW = (): number => Date.UTC(2026, 9, 28, 12);
const REASON = "Your role can't control replay.";
const CAPTION = "Recorded history: 2026-09-01 – 2026-10-28";

function Host(props: Partial<DatePickerProps>): JSX.Element {
  const [value, setValue] = useState<string | null>(props.value ?? null);
  return (
    <DatePicker
      aria-label="Go to date"
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

const field = (host: HTMLElement): HTMLInputElement =>
  within(host).getByRole("textbox", { name: "Go to date" }) as HTMLInputElement;
const button = (host: HTMLElement): HTMLButtonElement =>
  within(host).getByRole("button", { name: "Choose date" }) as HTMLButtonElement;
const dialog = (): HTMLElement | null =>
  document.querySelector<HTMLElement>(".cv-datepicker__dialog:not([hidden])");
const openDialog = (): HTMLElement => {
  const node = dialog();
  if (node === null) throw new Error("the calendar is closed");
  return node;
};
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

describe("DatePicker (CMP-047): the field", () => {
  it("renders the well: a named textbox with the hint, the UTC suffix and the calendar button", async () => {
    const host = await mount(<Host value="2026-10-23" />);
    const input = field(host);
    expect(input).toHaveValue("2026-10-23");
    expect(input).toHaveAttribute("placeholder", "YYYY-MM-DD");
    // The empty error node leads the chain (in the DOM at mount, conventions 23).
    expect(input).toHaveAccessibleDescription(/^\s*YYYY-MM-DD UTC$/);
    expect(button(host)).toHaveAttribute("aria-haspopup", "dialog");
    expect(button(host)).toHaveAttribute("aria-expanded", "false");
    expect(host.querySelectorAll('[data-cmp="CMP-047"]')).toHaveLength(1);
    expect(dialog()).toBeNull();
  });

  it("parses typed text on blur and commits the ISO day", async () => {
    const onChange = fn();
    const host = await mount(<Host onChange={onChange} />);
    await type(field(host), "2024-02-29");
    expect(onChange).toHaveBeenCalledWith("2024-02-29");
    expect(field(host)).not.toHaveAttribute("aria-invalid");
  });

  it("commits on Enter too, and an emptied field commits null", async () => {
    const onChange = fn();
    const host = await mount(<Host value="2026-10-23" onChange={onChange} />);
    const input = field(host);
    await act(async () => input.focus());
    await act(async () => {
      fireEvent.change(input, { target: { value: "2026-10-01" } });
    });
    await key("Enter");
    expect(onChange).toHaveBeenLastCalledWith("2026-10-01");
    await type(input, "");
    expect(onChange).toHaveBeenLastCalledWith(null);
  });

  it("keeps Enter that commits or refuses typed text from submitting a host form", async () => {
    const onSubmit = fn((event: { preventDefault: () => void }) => event.preventDefault());
    const host = await mount(
      <form onSubmit={onSubmit}>
        <Host value="2026-10-23" />
      </form>,
    );
    const input = field(host);
    await act(async () => input.focus());
    const enter = async (): Promise<boolean> => {
      let kept = true;
      await act(async () => {
        kept = await fireEvent.keyDown(input, { key: "Enter" });
      });
      return kept;
    };
    await act(async () => {
      fireEvent.change(input, { target: { value: "2026-10-01" } });
    });
    expect(await enter()).toBe(false);
    await act(async () => {
      fireEvent.change(input, { target: { value: "not a date" } });
    });
    expect(await enter()).toBe(false);
    await act(async () => {
      fireEvent.change(input, { target: { value: "2026-10-01" } });
    });
    await enter();
    // No typed text under way: Enter is left to the host form.
    expect(await enter()).toBe(true);
  });

  it("words unparsable text, keeps it, and clears silently once it is valid", async () => {
    const onChange = fn();
    const host = await mount(<Host onChange={onChange} />);
    const input = field(host);
    await type(input, "2023-02-29");
    expect(onChange).not.toHaveBeenCalled();
    expect(input).toHaveValue("2023-02-29");
    expect(input).toHaveAttribute("aria-invalid", "true");
    expect(input).toHaveAccessibleDescription("Enter a date as YYYY-MM-DD. YYYY-MM-DD UTC");
    // Still wrong while typing: the words stay; valid: they go without a commit.
    await act(async () => input.focus());
    await act(async () => {
      fireEvent.change(input, { target: { value: "2023-02-2" } });
    });
    expect(input).toHaveAttribute("aria-invalid", "true");
    await act(async () => {
      fireEvent.change(input, { target: { value: "2023-02-28" } });
    });
    expect(input).not.toHaveAttribute("aria-invalid");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("refuses typed days outside min-max with the caption, never clamping them", async () => {
    const onChange = fn();
    const host = await mount(
      <Host onChange={onChange} min="2026-09-01" max="2026-10-28" rangeCaption={CAPTION} />,
    );
    await type(field(host), "2026-08-31");
    expect(onChange).not.toHaveBeenCalled();
    expect(field(host)).toHaveValue("2026-08-31");
    expect(host.querySelector(".cv-field__message")).toHaveTextContent(CAPTION);
  });

  it("composes a caption from the bounds when the host gives none", async () => {
    const host = await mount(<Host min="2026-09-01" />);
    await type(field(host), "2026-01-01");
    expect(host.querySelector(".cv-field__message")).toHaveTextContent(
      "Choose a date on or after 2026-09-01.",
    );
  });

  it("drops a draft when the host moves the value", async () => {
    function Moved(): JSX.Element {
      const [value, setValue] = useState<string | null>("2026-10-01");
      return (
        <>
          <DatePicker aria-label="Go to date" value={value} onChange={setValue} now={NOW} />
          <button type="button" onClick={() => setValue("2026-10-05")}>
            Move
          </button>
        </>
      );
    }
    const host = await mount(<Moved />);
    await act(async () => {
      fireEvent.change(field(host), { target: { value: "2026-1" } });
    });
    await click(within(host).getByRole("button", { name: "Move" }));
    expect(field(host)).toHaveValue("2026-10-05");
  });

  it("shows the host's error under the field, polite and once", async () => {
    const host = await mount(
      <Host value="2026-10-23" invalid errorMessage="Nothing is recorded for that window." />,
    );
    const message = host.querySelector(".cv-field__message");
    expect(message).toHaveAttribute("aria-live", "polite");
    expect(message).toHaveTextContent("Nothing is recorded for that window.");
    expect(field(host)).toHaveAttribute("aria-invalid", "true");
  });

  it("lets a FormField name it and draw the lines", async () => {
    const host = await mount(
      <FormField label="Start" help="UTC day" error="Pick a day.">
        <DatePicker value={null} onChange={fn()} now={NOW} />
      </FormField>,
    );
    const input = within(host).getByRole("textbox", { name: "Start" });
    expect(input).toHaveAccessibleDescription("Pick a day. UTC day YYYY-MM-DD UTC");
    // The field draws the one message line; the picker draws none of its own.
    expect(host.querySelectorAll(".cv-field__message")).toHaveLength(1);
  });

  it("has no hint line for an empty formatHint", async () => {
    const host = await mount(<Host formatHint="" />);
    expect(host.querySelector(".cv-datepicker__hint")).toBeNull();
    expect(field(host)).toHaveAccessibleDescription(/^\s*UTC$/);
  });
});

describe("DatePicker (CMP-047): the calendar dialog", () => {
  it("opens modal, named by the month, with focus on the selected day", async () => {
    const host = await mount(<Host value="2026-10-23" />);
    await click(button(host));
    const calendar = openDialog();
    expect(calendar).toHaveAttribute("role", "dialog");
    expect(calendar).toHaveAttribute("aria-modal", "true");
    expect(calendar).toHaveAccessibleName("October 2026");
    expect(within(calendar).getByRole("grid")).toHaveAccessibleName("October 2026");
    expect(focusedName()).toBe("23 October 2026");
    const selectedCell = (document.activeElement as HTMLElement).closest("td");
    expect(selectedCell).toHaveAttribute("aria-selected", "true");
    expect(button(host)).toHaveAttribute("aria-expanded", "true");
  });

  it("lays out Monday-first weekday headers, with full names", async () => {
    const host = await mount(<Host value="2026-10-23" />);
    await click(button(host));
    const headers = within(openDialog()).getAllByRole("columnheader");
    expect(headers.map((h) => h.textContent)).toEqual(["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]);
    expect(headers[0]?.querySelector("abbr")).toHaveAttribute("title", "Monday");
  });

  it("opens on today without a value, marked as the current date", async () => {
    const host = await mount(<Host />);
    await click(button(host));
    expect(focusedName()).toBe("28 October 2026, today");
    expect(document.activeElement).toHaveAttribute("aria-current", "date");
  });

  it("opens on the first allowed day when today is out of range", async () => {
    const host = await mount(<Host min="2026-11-03" />);
    await click(button(host));
    expect(focusedName()).toBe("3 November 2026");
  });

  it("opens on the last allowed day when today is past max", async () => {
    const host = await mount(<Host max="2026-06-30" />);
    await click(button(host));
    expect(focusedName()).toBe("30 June 2026");
  });

  it("has one roving tab stop in the grid", async () => {
    const host = await mount(<Host value="2026-10-23" />);
    await click(button(host));
    const stops = openDialog().querySelectorAll('.cv-datepicker__day[tabindex="0"]');
    expect(stops).toHaveLength(1);
    expect(stops[0]).toHaveAttribute("aria-label", "23 October 2026");
  });

  it("opens with Alt+ArrowDown in the field", async () => {
    const host = await mount(<Host value="2026-10-23" />);
    await act(async () => field(host).focus());
    await key("ArrowDown", { altKey: true });
    expect(dialog()).not.toBeNull();
    expect(focusedName()).toBe("23 October 2026");
  });

  it("picks a day with Enter: commits it, closes, and returns focus to the button", async () => {
    const onChange = fn();
    const host = await mount(<Host value="2026-10-23" onChange={onChange} />);
    await click(button(host));
    await key("ArrowRight");
    expect(focusedName()).toBe("24 October 2026");
    await act(async () => {
      await userEvent.keyboard("{Enter}");
    });
    expect(onChange).toHaveBeenCalledWith("2026-10-24");
    expect(dialog()).toBeNull();
    expect(button(host)).toHaveFocus();
    expect(field(host)).toHaveValue("2026-10-24");
  });

  it("closes on Esc without a change, focus back on the button", async () => {
    const onChange = fn();
    const host = await mount(<Host value="2026-10-23" onChange={onChange} />);
    await click(button(host));
    await key("ArrowDown");
    await key("Escape");
    expect(dialog()).toBeNull();
    expect(onChange).not.toHaveBeenCalled();
    expect(button(host)).toHaveFocus();
  });

  it("returns focus to the button after an Alt+ArrowDown opening too", async () => {
    const host = await mount(<Host value="2026-10-23" />);
    await act(async () => field(host).focus());
    await key("ArrowDown", { altKey: true });
    await key("Escape");
    expect(button(host)).toHaveFocus();
  });

  it("moves months with the buttons; focus stays on the button", async () => {
    const host = await mount(<Host value="2026-01-31" />);
    await click(button(host));
    const next = within(openDialog()).getByRole("button", { name: "Next month" });
    await act(async () => next.focus());
    await click(next);
    expect(openDialog()).toHaveAccessibleName("February 2026");
    expect(next).toHaveFocus();
    const stop = openDialog().querySelector('.cv-datepicker__day[tabindex="0"]');
    expect(stop).toHaveAttribute("aria-label", "28 February 2026");
    await click(within(openDialog()).getByRole("button", { name: "Previous month" }));
    await click(within(openDialog()).getByRole("button", { name: "Previous month" }));
    expect(openDialog()).toHaveAccessibleName("December 2025");
  });

  it("walks the grid across a year edge by keyboard, the heading following", async () => {
    const host = await mount(<Host value="2026-12-31" />);
    await click(button(host));
    await key("ArrowRight");
    expect(focusedName()).toBe("1 January 2027");
    expect(openDialog()).toHaveAccessibleName("January 2027");
    await key("ArrowUp");
    expect(focusedName()).toBe("25 December 2026");
    await key("PageUp", { shiftKey: true });
    expect(focusedName()).toBe("25 December 2025");
  });

  it("leaves chords and other keys alone", async () => {
    const host = await mount(<Host value="2026-10-23" />);
    await click(button(host));
    await key("ArrowRight", { ctrlKey: true });
    await key("a");
    expect(focusedName()).toBe("23 October 2026");
  });

  it("marks out-of-range days aria-disabled and speaks the caption on a press", async () => {
    const onChange = fn();
    const host = await mount(
      <Host
        value="2026-09-01"
        min="2026-09-01"
        max="2026-10-28"
        rangeCaption={CAPTION}
        onChange={onChange}
      />,
    );
    await click(button(host));
    const calendar = openDialog();
    expect(within(calendar).getByText(CAPTION)).toHaveClass("cv-datepicker__caption");
    const status = within(calendar).getByRole("status");
    expect(status).toHaveTextContent("");
    await key("ArrowLeft");
    expect(focusedName()).toBe("31 August 2026");
    expect(document.activeElement).toHaveAttribute("aria-disabled", "true");
    await click(document.activeElement as Element);
    expect(onChange).not.toHaveBeenCalled();
    expect(dialog()).not.toBeNull();
    expect(status).toHaveTextContent(CAPTION);
    // In range, no aria-disabled.
    await key("ArrowRight");
    expect(document.activeElement).not.toHaveAttribute("aria-disabled");
  });

  it("keeps the roving stop where it was on a refused press (the single form)", async () => {
    const host = await mount(<Host value="2026-10-01" min="2026-09-01" max="2026-10-20" />);
    await click(button(host));
    const calendar = openDialog();
    await click(within(calendar).getByRole("button", { name: "25 October 2026" }));
    expect(within(calendar).getByRole("button", { name: "1 October 2026" })).toHaveAttribute(
      "tabindex",
      "0",
    );
    expect(within(calendar).getByRole("button", { name: "25 October 2026" })).toHaveAttribute(
      "tabindex",
      "-1",
    );
  });

  it("speaks the caption again on each later press, in this month or another", async () => {
    const host = await mount(
      <Host value="2026-09-01" min="2026-09-01" max="2026-10-28" rangeCaption={CAPTION} />,
    );
    await click(button(host));
    const status = within(openDialog()).getByRole("status");
    await key("ArrowLeft");
    const day = document.activeElement as Element;
    await click(day);
    const first = status.firstElementChild;
    expect(first).toHaveTextContent(CAPTION);
    await click(day);
    const second = status.firstElementChild;
    expect(second).toHaveTextContent(CAPTION);
    expect(second).not.toBe(first);
    await key("PageUp");
    expect(focusedName()).toBe("31 July 2026");
    await click(document.activeElement as Element);
    expect(status.firstElementChild).toHaveTextContent(CAPTION);
    expect(status.firstElementChild).not.toBe(second);
  });

  it("tabs from Next month to the new month's roving day", async () => {
    const host = await mount(<Host value="2026-01-31" />);
    await click(button(host));
    const next = within(openDialog()).getByRole("button", { name: "Next month" });
    await act(async () => next.focus());
    await click(next);
    await act(async () => userEvent.tab());
    expect(focusedName()).toBe("28 February 2026");
  });

  it("keeps focus in the dialog on a press of its heading", async () => {
    const host = await mount(<Host value="2026-10-23" />);
    await click(button(host));
    const heading = within(openDialog()).getByRole("heading", { name: "October 2026" });
    let unprevented = false;
    await act(async () => {
      unprevented = await fireEvent.mouseDown(heading);
    });
    expect(unprevented).toBe(true);
    expect(field(host)).not.toHaveFocus();
    expect(focusedName()).toBe("23 October 2026");
  });

  it("starts a fresh calendar on each opening", async () => {
    const host = await mount(<Host value="2026-10-23" />);
    await click(button(host));
    await key("PageDown");
    expect(focusedName()).toBe("23 November 2026");
    await key("Escape");
    await click(button(host));
    expect(focusedName()).toBe("23 October 2026");
  });
});

describe("DatePicker (CMP-047): gates", () => {
  it("T2: read-only field, aria-disabled button with the reason, and the dialog never opens", async () => {
    const host = await mount(<Host value="2026-10-23" disabledReason={REASON} />);
    const input = field(host);
    expect(input).toHaveAttribute("readonly");
    expect(input).toHaveAttribute("aria-disabled", "true");
    expect(input).toHaveAccessibleDescription(REASON);
    expect(within(host).getByRole("img", { name: "Not available" })).toBeInTheDocument();
    const calendar = button(host);
    expect(calendar).toHaveAttribute("aria-disabled", "true");
    expect(calendar).not.toBeDisabled();
    expect(calendar).toHaveAccessibleDescription(REASON);
    await click(calendar);
    expect(dialog()).toBeNull();
    await act(async () => input.focus());
    await key("ArrowDown", { altKey: true });
    expect(dialog()).toBeNull();
    // The refusal is spoken once per focus visit.
    expect(within(host).getByRole("status")).toHaveTextContent(REASON);
  });

  it("closes when it becomes gated while open, and stays closed once free again", async () => {
    function Gate(): JSX.Element {
      const [gated, setGated] = useState(false);
      return (
        <>
          <Host value="2026-10-23" {...(gated ? { disabledReason: REASON } : {})} />
          <button type="button" onClick={() => setGated((g) => !g)}>
            Gate
          </button>
        </>
      );
    }
    const host = await mount(<Gate />);
    await click(button(host));
    expect(dialog()).not.toBeNull();
    const gate = within(host).getByRole("button", { name: "Gate" });
    await click(gate);
    expect(dialog()).toBeNull();
    await click(gate);
    expect(dialog()).toBeNull();
  });

  it("T2: the reason is in the DOM at mount", async () => {
    const host = await mount(<Host disabledReason={REASON} />);
    expect(host).toHaveTextContent(REASON);
  });

  it("plain disabled: the field and the button are natively disabled", async () => {
    const host = await mount(<Host value="2026-10-23" disabled />);
    expect(field(host)).toBeDisabled();
    expect(button(host)).toBeDisabled();
  });

  it("read-only: the value stays selectable, the button is disabled and nothing opens", async () => {
    const host = await mount(<Host value="2026-10-23" readOnly />);
    expect(field(host)).toHaveAttribute("readonly");
    expect(field(host)).not.toBeDisabled();
    expect(button(host)).toBeDisabled();
    await act(async () => field(host).focus());
    await key("ArrowDown", { altKey: true });
    expect(dialog()).toBeNull();
  });

  it("a press on the well's suffix focuses the field; a press on the button does not", async () => {
    const host = await mount(<Host value="2026-10-23" />);
    const suffix = within(host).getByText("UTC");
    await act(async () => {
      fireEvent.mouseDown(suffix);
    });
    expect(field(host)).toHaveFocus();
    await act(async () => button(host).focus());
    await act(async () => {
      fireEvent.mouseDown(button(host));
    });
    expect(button(host)).toHaveFocus();
  });
});

describe("DatePicker (CMP-047): withTime", () => {
  function TimeHost(props: Partial<DatePickerProps>): JSX.Element {
    const [time, setTime] = useState<string | null>(props.time ?? null);
    return (
      <Host
        withTime
        {...props}
        time={time}
        onTimeChange={(next) => {
          setTime(next);
          props.onTimeChange?.(next);
        }}
      />
    );
  }
  const time = (host: HTMLElement): HTMLInputElement =>
    within(host).getByRole("textbox", { name: "Time" }) as HTMLInputElement;

  it("adds an HH:MM UTC well after the date; the button moves to its end (date, time, button)", async () => {
    const host = await mount(<TimeHost value="2026-10-23" time="14:05" />);
    const input = time(host);
    expect(input).toHaveValue("14:05");
    expect(input).toHaveAttribute("placeholder", "HH:MM");
    expect(input).toHaveAccessibleDescription(/YYYY-MM-DD HH:MM UTC$/);
    expect(input.closest(".cv-field")).toContainElement(button(host));
    expect(field(host).closest(".cv-field")).not.toContainElement(button(host));
    const follows = (a: Element, b: Element): boolean =>
      (a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
    expect(follows(field(host), input)).toBe(true);
    expect(follows(input, button(host))).toBe(true);
  });

  it("parses the time on blur into 24-hour HH:MM; the calendar never touches it", async () => {
    const onTimeChange = fn();
    const onChange = fn();
    const host = await mount(
      <TimeHost value="2026-10-23" onTimeChange={onTimeChange} onChange={onChange} />,
    );
    await type(time(host), "7:30");
    expect(onTimeChange).toHaveBeenLastCalledWith("07:30");
    expect(time(host)).toHaveValue("07:30");
    await type(time(host), "");
    expect(onTimeChange).toHaveBeenLastCalledWith(null);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("words an unparsable time, keeps it, and marks only the time well invalid", async () => {
    const onTimeChange = fn();
    const host = await mount(<TimeHost value="2026-10-23" onTimeChange={onTimeChange} />);
    await type(time(host), "14:5");
    expect(onTimeChange).not.toHaveBeenCalled();
    expect(time(host)).toHaveValue("14:5");
    expect(time(host)).toHaveAttribute("aria-invalid", "true");
    expect(field(host)).not.toHaveAttribute("aria-invalid");
    expect(within(host).getByText("Enter a time as HH:MM, 24-hour UTC.")).toBeInTheDocument();
    await type(time(host), "14:50");
    expect(onTimeChange).toHaveBeenLastCalledWith("14:50");
    expect(time(host)).not.toHaveAttribute("aria-invalid");
  });

  it("opens the calendar with Alt+ArrowDown in the time field too", async () => {
    const host = await mount(<TimeHost value="2026-10-23" />);
    await act(async () => time(host).focus());
    await key("ArrowDown", { altKey: true });
    expect(focusedName()).toBe("23 October 2026");
  });

  it("T2: the time well is read-only behind its own lock too", async () => {
    const host = await mount(<TimeHost value="2026-10-23" disabledReason={REASON} />);
    expect(time(host)).toHaveAttribute("readonly");
    expect(time(host)).toHaveAccessibleDescription(REASON);
    expect(within(host).getAllByRole("img", { name: "Not available" })).toHaveLength(2);
  });
});

describe("CalendarGrid keyboard matrix (APG Date Picker Dialog)", () => {
  it.each([
    // [from, key, shift, to]
    ["2026-10-23", "ArrowLeft", false, "2026-10-22"],
    ["2026-10-23", "ArrowRight", false, "2026-10-24"],
    ["2026-10-23", "ArrowUp", false, "2026-10-16"],
    ["2026-10-23", "ArrowDown", false, "2026-10-30"],
    ["2026-10-01", "ArrowLeft", false, "2026-09-30"],
    ["2026-10-31", "ArrowRight", false, "2026-11-01"],
    ["2026-10-28", "ArrowDown", false, "2026-11-04"],
    ["2026-01-01", "ArrowLeft", false, "2025-12-31"],
    ["2026-12-31", "ArrowRight", false, "2027-01-01"],
    ["2027-01-03", "ArrowUp", false, "2026-12-27"],
    ["2026-12-28", "ArrowDown", false, "2027-01-04"],
    ["2024-02-28", "ArrowRight", false, "2024-02-29"],
    ["2024-03-01", "ArrowLeft", false, "2024-02-29"],
    ["2023-03-01", "ArrowLeft", false, "2023-02-28"],
    ["2026-10-23", "Home", false, "2026-10-19"],
    ["2026-10-23", "End", false, "2026-10-25"],
    ["2026-10-19", "Home", false, "2026-10-19"],
    ["2026-11-01", "End", false, "2026-11-01"],
    ["2026-10-01", "Home", false, "2026-09-28"],
    ["2026-12-30", "End", false, "2027-01-03"],
    ["2026-10-23", "PageUp", false, "2026-09-23"],
    ["2026-10-23", "PageDown", false, "2026-11-23"],
    ["2026-01-15", "PageUp", false, "2025-12-15"],
    ["2026-12-15", "PageDown", false, "2027-01-15"],
    ["2026-10-31", "PageDown", false, "2026-11-30"],
    ["2026-03-31", "PageUp", false, "2026-02-28"],
    ["2024-01-31", "PageDown", false, "2024-02-29"],
    ["2024-03-31", "PageUp", false, "2024-02-29"],
    ["2026-10-23", "PageUp", true, "2025-10-23"],
    ["2026-10-23", "PageDown", true, "2027-10-23"],
    ["2024-02-29", "PageDown", true, "2025-02-28"],
    ["2024-02-29", "PageUp", true, "2023-02-28"],
    ["2028-02-29", "PageUp", true, "2027-02-28"],
    ["0001-01-01", "ArrowLeft", false, "0001-01-01"],
    ["9999-12-31", "PageDown", true, "9999-12-31"],
  ])("%s %s (shift %s) -> %s", (from, k, shift, to) => {
    expect(nextFocus(from, k, shift)).toBe(to);
  });

  it("returns null for keys the grid does not handle", () => {
    expect(nextFocus("2026-10-23", "Enter", false)).toBeNull();
    expect(nextFocus("2026-10-23", "Tab", false)).toBeNull();
  });
});

// @vitest-environment jsdom
import { composeStories } from "@storybook/react-vite";
import { act, useState, type JSX } from "react";
import { afterEach, beforeEach, describe, it, vi } from "vitest";
import { expect, fireEvent, userEvent, within } from "storybook/test";
import {
  AUDIT_FILTER_COPY,
  AuditFilterBar,
  formatRbacReason,
  type AuditFilterBarProps,
  type AuditFilters,
} from "../src/components/index.js";
import * as stories from "../src/components/AuditFilterBar.stories.js";
import { seriousViolations } from "./axe.js";
import { mount } from "./theme/mount.js";

/** E42-D04's worked example: the Owner basiltt and the managers alex and bea. */
const BASILTT = "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0001";
const ALEX = "9f1c2b4e-0a1d-4f2b-9e3a-11c0ffee0002";
const ACTORS = [
  { id: BASILTT, label: "basiltt" },
  { id: ALEX, label: "alex" },
];
const ACTIONS = [
  { code: "flags.change", label: "Flag changed" },
  { code: "orders.submit", label: "Order submitted" },
  { code: "rbac.denied" },
];
const LIMITED = "Paused by a rate limit.";
const ownReason = (verb: string): string => formatRbacReason("rbac.owner_only", { verb });

type Props = Partial<AuditFilterBarProps>;

/** A controlled host, as SCR-135 is: every applied set is recorded and fed back. */
function Host({
  initial = {},
  spy,
  ...props
}: Props & { initial?: AuditFilters; spy: (f: AuditFilters) => void }): JSX.Element {
  const [filters, setFilters] = useState<AuditFilters>(initial);
  return (
    <AuditFilterBar
      actorOptions={ACTORS}
      actionOptions={ACTIONS}
      {...props}
      filters={filters}
      onChange={(next) => {
        setFilters(next);
        spy(next);
      }}
    />
  );
}

const form = (host: HTMLElement): HTMLElement =>
  within(host).getByRole("search", { name: "Filter the audit log" });
const field = (host: HTMLElement, name: string | RegExp): HTMLElement =>
  within(form(host)).getByLabelText(name, { selector: "input, [role=combobox]" });
const box = (host: HTMLElement, name: string | RegExp): HTMLInputElement =>
  within(form(host)).getByRole("combobox", { name }) as HTMLInputElement;
const typeIn = (el: HTMLElement, text: string): Promise<void> =>
  act(async () => void fireEvent.change(el, { target: { value: text } }));
const key = async (el: HTMLElement, name: string, init: KeyboardEventInit = {}): Promise<void> => {
  await act(async () =>
    el.dispatchEvent(
      new KeyboardEvent("keydown", { key: name, bubbles: true, cancelable: true, ...init }),
    ),
  );
};
/** Focus leaving the field as a browser does it (`focusout`, which React's onBlur reads). */
const blur = async (el: HTMLElement): Promise<void> => {
  await act(async () => el.focus());
  await act(async () => el.blur());
};
const describedTexts = (el: HTMLElement): string[] =>
  (el.getAttribute("aria-describedby") ?? "")
    .split(" ")
    .filter((id) => id !== "")
    .map((id) => document.getElementById(id)?.textContent ?? "");

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => {
  vi.restoreAllMocks();
});

describe("AuditFilterBar (CMP-174)", () => {
  it("is a search form named 'Filter the audit log' with a visible label on every control", async () => {
    const host = await mount(<Host spy={vi.fn()} />);
    expect(form(host).tagName).toBe("FORM");
    expect(form(host)).toHaveAttribute("data-cmp", "CMP-174");
    for (const name of [
      "From",
      "To",
      "Actor",
      "Action",
      "Subject type",
      "Subject id",
      "Outcome",
      "Severity",
      "IP",
      "Search",
      "Environment",
    ]) {
      const control = field(host, name);
      const labelledBy = control.getAttribute("aria-labelledby");
      const label =
        labelledBy === null
          ? form(host).querySelector(`label[for="${control.id}"]`)
          : document.getElementById(labelledBy);
      expect(label?.tagName, name).toBe("LABEL");
      expect(label).toBeVisible();
    }
    expect(within(form(host)).getByRole("button", { name: "Clear filters" })).toBeVisible();
    // No page number or total: paging is CMP-053's, a count the host's.
    expect(form(host).querySelector("[aria-current]")).toBeNull();
  });

  it("From and To say UTC", async () => {
    const host = await mount(<Host spy={vi.fn()} />);
    for (const name of ["From", "To"]) {
      expect(field(host, name)).toHaveAccessibleDescription(/UTC/);
    }
  });

  it("shows a deep-linked set as text in its controls, its actions as removable chips", async () => {
    const initial: AuditFilters = {
      from: "2026-10-22T14:00:00Z",
      to: "2026-10-22T15:30:00.000Z",
      actor_user_id: ALEX,
      action: ["flags.change", "rbac.denied"],
      subject_type: "feature_flag",
      subject_id: "trading.one_click",
      outcome: "denied",
      severity: "warning",
      ip: "100.84.12.9",
      q: "credential",
      environment: "live",
    };
    const host = await mount(<Host spy={vi.fn()} initial={initial} />);
    expect((field(host, "From") as HTMLInputElement).value).toBe("2026-10-22");
    expect((within(form(host)).getByLabelText("From time") as HTMLInputElement).value).toBe(
      "14:00",
    );
    expect((field(host, "To") as HTMLInputElement).value).toBe("2026-10-22");
    expect((within(form(host)).getByLabelText("To time") as HTMLInputElement).value).toBe("15:30");
    expect(box(host, "Actor").value).toBe("alex");
    expect(
      within(form(host)).getByRole("button", { name: "Remove Flag changed (flags.change)" }),
    ).toBeVisible();
    expect(within(form(host)).getByRole("button", { name: "Remove rbac.denied" })).toBeVisible();
    expect((field(host, "Subject type") as HTMLInputElement).value).toBe("feature_flag");
    expect((field(host, "Subject id") as HTMLInputElement).value).toBe("trading.one_click");
    expect(box(host, "Outcome")).toHaveTextContent("Denied");
    expect(box(host, "Severity")).toHaveTextContent("Warning");
    expect((field(host, "IP") as HTMLInputElement).value).toBe("100.84.12.9");
    expect((field(host, "Search") as HTMLInputElement).value).toBe("credential");
    expect(box(host, "Environment")).toHaveTextContent("LIVE (this page only)");
  });

  it("applies a select on change", async () => {
    const spy = vi.fn();
    const host = await mount(<Host spy={spy} initial={{ q: "flag" }} />);
    await userEvent.click(box(host, "Severity"));
    await userEvent.click(within(document.body).getByRole("option", { name: "Error" }));
    expect(spy).toHaveBeenLastCalledWith({ q: "flag", severity: "error" });
    await userEvent.click(box(host, "Severity"));
    await userEvent.click(within(document.body).getByRole("option", { name: "Any" }));
    expect(spy).toHaveBeenLastCalledWith({ q: "flag" });
  });

  it("applies text on Enter or on leaving the field, never per keystroke; an emptied field drops its filter", async () => {
    const spy = vi.fn();
    const host = await mount(<Host spy={spy} initial={{ q: "flag" }} />);
    const ip = field(host, "IP");
    await typeIn(ip, "100.84.12.9");
    expect(spy).not.toHaveBeenCalled();
    await key(ip, "Enter");
    expect(spy).toHaveBeenLastCalledWith({ q: "flag", ip: "100.84.12.9" });
    const search = field(host, "Search");
    await typeIn(search, "  ");
    await blur(search);
    expect(spy).toHaveBeenLastCalledWith({ ip: "100.84.12.9" });
    // Leaving a field that did not change applies nothing.
    await blur(ip);
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it("Enter while an IME composes applies nothing; the Enter that ends it does", async () => {
    const spy = vi.fn();
    const host = await mount(<Host spy={spy} />);
    const ip = field(host, "IP");
    await typeIn(ip, "100.84.12.9");
    await key(ip, "Enter", { isComposing: true });
    expect(spy).not.toHaveBeenCalled();
    await key(ip, "Enter");
    expect(spy.mock.calls).toEqual([[{ ip: "100.84.12.9" }]]);
  });

  it("Enter, then leaving the field, applies once even while the host's set still lags", async () => {
    const onChange = vi.fn();
    // The host has not fed the set back yet (a URL write in flight): `filters` stays the old one.
    const host = await mount(
      <AuditFilterBar
        filters={{}}
        onChange={onChange}
        actorOptions={ACTORS}
        actionOptions={ACTIONS}
      />,
    );
    const ip = field(host, "IP");
    await typeIn(ip, "100.84.12.9");
    await act(async () => ip.focus());
    await key(ip, "Enter");
    await act(async () => ip.blur());
    expect(onChange.mock.calls).toEqual([[{ ip: "100.84.12.9" }]]);
    // A new value is a new set.
    await typeIn(ip, "100.84.12.10");
    await key(ip, "Enter");
    expect(onChange).toHaveBeenLastCalledWith({ ip: "100.84.12.10" });
    expect(onChange).toHaveBeenCalledTimes(2);
  });

  it("an actor chosen by Enter, then leaving the field, applies once even while the host's set still lags", async () => {
    const onChange = vi.fn();
    const host = await mount(
      <AuditFilterBar
        filters={{}}
        onChange={onChange}
        actorOptions={ACTORS}
        actionOptions={ACTIONS}
      />,
    );
    const actor = box(host, "Actor");
    await typeIn(actor, "alex");
    await act(async () => actor.focus());
    await key(actor, "Enter");
    await act(async () => actor.blur());
    expect(onChange.mock.calls).toEqual([[{ actor_user_id: ALEX }]]);
  });

  it("Enter in a field never submits the form", async () => {
    const submit = vi.fn((event: SubmitEvent) => event.preventDefault());
    const host = await mount(<Host spy={vi.fn()} />);
    form(host).addEventListener("submit", submit);
    await userEvent.type(field(host, "Subject id"), "order-1{Enter}");
    expect(submit).not.toHaveBeenCalled();
  });

  it("applies From and To as RFC 3339 UTC instants once each field commits", async () => {
    const spy = vi.fn();
    const host = await mount(<Host spy={spy} />);
    const from = field(host, "From");
    await typeIn(from, "2026-10-22");
    await blur(from);
    expect(spy).toHaveBeenLastCalledWith({ from: "2026-10-22T00:00:00Z" });
    const time = within(form(host)).getByLabelText("From time");
    await typeIn(time, "14:05");
    await blur(time);
    expect(spy).toHaveBeenLastCalledWith({ from: "2026-10-22T14:05:00Z" });
    await typeIn(from, "");
    await blur(from);
    expect(spy).toHaveBeenLastCalledWith({});
  });

  it("adds an action from the list or by its exact code, at most once each, and removes it from its chip", async () => {
    const spy = vi.fn();
    const host = await mount(<Host spy={spy} />);
    const action = box(host, "Action");
    await typeIn(action, "flag");
    await key(action, "ArrowDown");
    await key(action, "Enter");
    expect(spy).toHaveBeenLastCalledWith({ action: ["flags.change"] });
    expect(box(host, "Action").value).toBe("");
    await typeIn(action, "admin.audit_read");
    await key(action, "Enter");
    expect(spy).toHaveBeenLastCalledWith({ action: ["flags.change", "admin.audit_read"] });
    await typeIn(action, "Flag changed");
    await key(action, "Enter");
    // Already in the set: nothing new is applied.
    expect(spy).toHaveBeenCalledTimes(2);
    await typeIn(action, "not a code");
    await key(action, "Enter");
    expect(spy).toHaveBeenCalledTimes(2);
    await userEvent.click(
      within(form(host)).getByRole("button", { name: "Remove Flag changed (flags.change)" }),
    );
    expect(spy).toHaveBeenLastCalledWith({ action: ["admin.audit_read"] });
  });

  it("adds no action past the contract's 50", async () => {
    const spy = vi.fn();
    const fifty = Array.from({ length: 50 }, (_, i) => `test.code_${i}`);
    const host = await mount(<Host spy={spy} initial={{ action: fifty }} />);
    const action = box(host, "Action");
    await typeIn(action, "orders.submit");
    await key(action, "Enter");
    expect(spy).not.toHaveBeenCalled();
  });

  it("applies an actor chosen from the list as actor_user_id; emptying it and leaving drops it", async () => {
    const spy = vi.fn();
    const host = await mount(<Host spy={spy} />);
    const actor = box(host, "Actor");
    await typeIn(actor, "ale");
    await key(actor, "ArrowDown");
    await key(actor, "Enter");
    expect(spy).toHaveBeenLastCalledWith({ actor_user_id: ALEX });
    await typeIn(actor, "");
    await blur(actor);
    expect(spy).toHaveBeenLastCalledWith({});
  });

  it("puts the scope in the Environment options: 'LIVE (this page only)' (audit.env_page)", async () => {
    const spy = vi.fn();
    const host = await mount(<Host spy={spy} />);
    await userEvent.click(box(host, "Environment"));
    const names = within(document.body)
      .getAllByRole("option")
      .map((o) => o.textContent);
    expect(names).toEqual([
      "Any",
      "LIVE (this page only)",
      "DEMO (this page only)",
      "TESTNET (this page only)",
    ]);
    await userEvent.click(
      within(document.body).getByRole("option", { name: "DEMO (this page only)" }),
    );
    expect(spy).toHaveBeenLastCalledWith({ environment: "demo" });
  });

  it("Clear filters empties the set", async () => {
    const spy = vi.fn();
    const host = await mount(
      <Host spy={spy} initial={{ severity: "error", action: ["rbac.denied"], q: "denied" }} />,
    );
    await userEvent.click(within(form(host)).getByRole("button", { name: "Clear filters" }));
    expect(spy).toHaveBeenLastCalledWith({});
  });

  it("own view: Actor reads 'you'; Actor, IP, Search and Environment stay, T2 rbac.owner_only, read-only", async () => {
    const spy = vi.fn();
    const host = await mount(
      <Host
        spy={spy}
        view="own"
        initial={{ actor_user_id: ALEX, ip: "100.84.12.9", q: "x", environment: "live" }}
      />,
    );
    const cases: [HTMLElement, string][] = [
      [box(host, /Actor$/), "see other users' entries"],
      [field(host, /IP$/), "filter by IP address"],
      [field(host, /Search$/), "search the audit log"],
      [box(host, /Environment$/), "filter by environment"],
    ];
    for (const [control, verb] of cases) {
      expect(control).toHaveAttribute("aria-disabled", "true");
      expect(describedTexts(control)).toEqual([ownReason(verb)]);
      expect(within(form(host)).getByText(ownReason(verb))).toBeVisible();
    }
    expect(box(host, /Actor$/).value).toBe(AUDIT_FILTER_COPY.you);
    expect((field(host, /IP$/) as HTMLInputElement).value).toBe("");
    expect((field(host, /Search$/) as HTMLInputElement).readOnly).toBe(true);
    await typeIn(field(host, /IP$/), "1.2.3.4");
    await key(field(host, /IP$/), "Enter");
    // Nothing the view gates is ever sent: the server replaces the actor and refuses q and ip (22).
    await userEvent.click(box(host, "Severity"));
    await userEvent.click(within(document.body).getByRole("option", { name: "Error" }));
    expect(spy.mock.calls).toEqual([[{ severity: "error" }]]);
  });

  it("own view: the gated Environment picker is read-only too, as the gated text fields are (§12.1)", async () => {
    const host = await mount(<Host spy={vi.fn()} view="own" />);
    expect(box(host, /Environment$/)).toHaveAttribute("aria-readonly", "true");
    expect((field(host, /IP$/) as HTMLInputElement).readOnly).toBe(true);
    // Not gated in the raw view: no read-only state.
    const raw = await mount(<Host spy={vi.fn()} />);
    expect(box(raw, "Environment")).not.toHaveAttribute("aria-readonly");
  });

  it("rate-limited: every control T2 behind the host's one notice; nothing applies", async () => {
    const spy = vi.fn();
    const host = await mount(
      <>
        <p id="limited">{LIMITED}</p>
        <Host
          spy={spy}
          blockedReason={LIMITED}
          blockedReasonId="limited"
          initial={{ action: ["rbac.denied"], q: "x" }}
        />
      </>,
    );
    const controls = [
      ...within(form(host)).getAllByRole("combobox"),
      ...within(form(host)).getAllByRole("textbox"),
      ...within(form(host)).getAllByRole("button"),
    ];
    expect(controls.length).toBeGreaterThan(10);
    for (const control of controls) {
      expect(control, control.outerHTML.slice(0, 80)).toHaveAttribute("aria-disabled", "true");
      expect(control.getAttribute("aria-describedby")).toBe("limited");
    }
    expect(within(host).getAllByText(LIMITED)).toHaveLength(1);
    await typeIn(field(host, "Search"), "y");
    await key(field(host, "Search"), "Enter");
    await userEvent.click(within(form(host)).getByRole("button", { name: /Clear filters$/ }));
    expect(spy).not.toHaveBeenCalled();
  });

  it("rate-limited without the host's notice: one notice in the bar that every control points at", async () => {
    const host = await mount(<Host spy={vi.fn()} blockedReason={LIMITED} />);
    expect(within(host).getAllByText(LIMITED)).toHaveLength(1);
    const ids = new Set(
      within(form(host))
        .getAllByRole("combobox")
        .map((control) => control.getAttribute("aria-describedby")),
    );
    expect(ids.size).toBe(1);
  });

  it("a 422: each error under its field, linked and not live; focus to the first in the bar's order", async () => {
    const errors = {
      ip: "Enter one IP address, not a range.",
      to: "From must be earlier than To.",
    };
    const host = await mount(<Host spy={vi.fn()} errors={errors} />);
    const to = field(host, "To");
    const ip = field(host, "IP");
    expect(to).toHaveFocus();
    expect(to).toHaveAttribute("aria-invalid", "true");
    expect(describedTexts(to)).toContain(errors.to);
    expect(ip).toHaveAttribute("aria-invalid", "true");
    expect(describedTexts(ip)).toContain(errors.ip);
    for (const text of Object.values(errors)) {
      const line = within(form(host)).getByText(text);
      expect(line.closest("[aria-live], [role=status], [role=alert]")).toBeNull();
    }
  });

  it("a 422 that answers after mount moves focus to its first field, once per answer", async () => {
    let answer: (errors: AuditFilterBarProps["errors"]) => void = () => undefined;
    function Answering(): JSX.Element {
      const [errors, setErrors] = useState<AuditFilterBarProps["errors"]>(undefined);
      answer = setErrors;
      return <Host spy={vi.fn()} {...(errors === undefined ? {} : { errors })} />;
    }
    const host = await mount(<Answering />);
    expect(document.body).toHaveFocus();
    const errors = { ip: "Enter one IP address, not a range." };
    await act(async () => answer(errors));
    expect(field(host, "IP")).toHaveFocus();
    expect(field(host, "IP")).toHaveAttribute("aria-invalid", "true");
    // The same answer again (a stable re-render) moves nothing.
    await act(async () => field(host, "Search").focus());
    await act(async () => answer(errors));
    expect(field(host, "Search")).toHaveFocus();
  });

  it("a 422 for a set applied on leaving a field never pulls focus back from where the user moved on (A-12)", async () => {
    let answer: (errors: AuditFilterBarProps["errors"]) => void = () => undefined;
    function Answering(): JSX.Element {
      const [errors, setErrors] = useState<AuditFilterBarProps["errors"]>(undefined);
      answer = setErrors;
      return <Host spy={vi.fn()} {...(errors === undefined ? {} : { errors })} />;
    }
    const host = await mount(<Answering />);
    const ip = field(host, "IP");
    const search = field(host, "Search");
    await typeIn(ip, "100.84.12.0/24");
    // Tab from IP to Search: IP applies on leaving, and the user is typing in Search when the answer comes.
    await act(async () => ip.focus());
    await act(async () => search.focus());
    await typeIn(search, "cred");
    await act(async () => answer({ ip: "Enter one IP address, not a range." }));
    expect(search).toHaveFocus();
    expect(ip).toHaveAttribute("aria-invalid", "true");
    expect(describedTexts(ip)).toContain("Enter one IP address, not a range.");
  });

  it("a 422 for a set applied by Enter moves focus to the first field in error", async () => {
    let answer: (errors: AuditFilterBarProps["errors"]) => void = () => undefined;
    function Answering(): JSX.Element {
      const [errors, setErrors] = useState<AuditFilterBarProps["errors"]>(undefined);
      answer = setErrors;
      return <Host spy={vi.fn()} {...(errors === undefined ? {} : { errors })} />;
    }
    const host = await mount(<Answering />);
    const search = field(host, "Search");
    await typeIn(search, "credential");
    await act(async () => search.focus());
    await key(search, "Enter");
    await act(async () => answer({ to: "From must be earlier than To." }));
    expect(field(host, "To")).toHaveFocus();
  });

  it("a 422 for a day picked in the calendar moves focus to the first field in error", async () => {
    let answer: (errors: AuditFilterBarProps["errors"]) => void = () => undefined;
    function Answering(): JSX.Element {
      const [errors, setErrors] = useState<AuditFilterBarProps["errors"]>(undefined);
      answer = setErrors;
      return <Host spy={vi.fn()} {...(errors === undefined ? {} : { errors })} />;
    }
    const host = await mount(<Answering />);
    const [fromCalendar] = within(form(host)).getAllByRole("button", { name: /Choose date/ });
    await userEvent.click(fromCalendar as HTMLElement);
    const day = [
      ...document.querySelectorAll<HTMLButtonElement>(".cv-datepicker__cell button"),
    ].find((button) => !button.disabled);
    // The pick sends the set from the day's button, which the closing calendar then removes: not a move-on.
    await userEvent.click(day as HTMLButtonElement);
    await act(async () => answer({ to: "From must be earlier than To." }));
    expect(field(host, "To")).toHaveFocus();
  });

  it("has no serious or critical axe violation: set, own view and rate-limited", async () => {
    const host = await mount(
      <>
        <Host spy={vi.fn()} initial={{ action: ["flags.change"], severity: "error" }} />
        <Host spy={vi.fn()} view="own" />
        <Host spy={vi.fn()} blockedReason={LIMITED} />
      </>,
    );
    expect(await seriousViolations(host)).toEqual([]);
  });
});

describe("AuditFilterBar stories", () => {
  it.each(Object.entries(composeStories(stories)))("%s renders one bar", async (_name, Story) => {
    const host = await mount(<Story />);
    expect(host.querySelectorAll('[data-cmp="CMP-174"]')).toHaveLength(1);
  });

  // The storybook project runs each play in Chromium; here in jsdom too, so a wrong name fails without a browser.
  it("runs each story's play function", { timeout: 30_000 }, async () => {
    for (const [name, Story] of Object.entries(composeStories(stories))) {
      const canvasElement = document.body.appendChild(document.createElement("div"));
      await expect(Story.run({ canvasElement }), name).resolves.toBeUndefined();
    }
  });
});

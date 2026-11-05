/**
 * E13-S01 (#423) S4: CMP-242 SchemaForm and its draft. The closed subset renders by a static switch;
 * a hostile schema is one safe error in the first synchronous commit (the dialog-level test holds
 * the injected-clock bound, BQ-11 rider); prototype keys never reach a field or a param; values are
 * refused, never clamped or rounded (D02 D11).
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SETTINGS, UNSUPPORTED_PARAM } from "../../../src/features/indicators/copy";
import { parseParamsSchema, type NumberField } from "../../../src/features/indicators/model/schema";
import {
  checkDraft,
  draftOf,
  stepFrom,
  type Draft,
} from "../../../src/features/indicators/settings/draft";
import { SchemaForm } from "../../../src/features/indicators/settings/SchemaForm";
import { BOLLINGER, CVD, EMA } from "./fixtures";

const period = { type: "integer", title: "Period", minimum: 1, maximum: 5000, default: 21 };
const wrap = (properties: Record<string, unknown>) => ({
  type: "object",
  additionalProperties: false,
  properties,
});

function show(raw: unknown, draft?: Draft) {
  const schema = parseParamsSchema(raw);
  const fields = schema.ok ? schema.fields : [];
  const onChange = vi.fn();
  const onEnter = vi.fn();
  const used = draft ?? draftOf(fields, Object.create(null) as Record<string, never>);
  const view = render(
    <SchemaForm
      schema={schema}
      draft={used}
      errors={checkDraft(fields, used).errors}
      onChange={onChange}
      onEnter={onEnter}
    />,
  );
  return { ...view, onChange, onEnter };
}

describe("SchemaForm renders the closed subset", () => {
  it("test_schema_form_maps_each_kind_to_its_control", () => {
    show(
      wrap({
        n: period,
        mult: {
          type: "number",
          title: "Width",
          minimum: 0.1,
          maximum: 10,
          multipleOf: 0.1,
          default: 2,
        },
        anchor: {
          type: "string",
          title: "Reset anchor",
          enum: ["session", "utc_day"],
          default: "session",
        },
        filled: { type: "boolean", title: "Fill", default: false },
      }),
    );
    const n = screen.getByRole("spinbutton", { name: "Period" });
    expect(n).toHaveValue("21");
    expect(n).toHaveAttribute("aria-valuemin", "1");
    expect(n).toHaveAttribute("aria-valuemax", "5000");
    expect(screen.getByText("1–5000 bars")).toBeInTheDocument();
    expect(screen.getByText("0.1–10, step 0.1")).toBeInTheDocument();
    expect(screen.getByRole("combobox", { name: "Reset anchor" })).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: "Fill" })).toBeInTheDocument();
  });

  it("test_schema_form_unknown_type_is_the_deck_read_only_row", () => {
    show(wrap({ n: period, shape: { type: "object", title: "Shape", properties: {} } }));
    expect(screen.getByText(UNSUPPORTED_PARAM)).toBeInTheDocument();
    expect(screen.getAllByRole("spinbutton")).toHaveLength(1);
  });

  it("test_schema_form_no_params_says_so", () => {
    show(wrap({}));
    expect(screen.getByText(SETTINGS.noParams)).toBeInTheDocument();
  });
});

describe("a hostile schema is one safe error (SR-E13-09, BQ-11)", () => {
  const html = { ...period, title: "<img src=x onerror=alert(1)>" };
  const cases: [string, unknown][] = [
    ["$ref", wrap({ n: { $ref: "#/definitions/x" } })],
    ["pattern", wrap({ n: { type: "string", title: "Name", pattern: "(a+)+$", default: "a" } })],
    ["oneOf", wrap({ n: { oneOf: [period] } })],
    ["root oneOf", { ...wrap({ n: period }), oneOf: [] }],
    ["HTML title", wrap({ n: html })],
    [
      "65 properties",
      wrap(Object.fromEntries(Array.from({ length: 65 }, (_, i) => [`p${i}`, period]))),
    ],
    ["not an object", "<script>"],
  ];

  it.each(cases)("test_hostile_%s_renders_one_safe_error", (_name, raw) => {
    const { container } = show(raw);
    // In the first synchronous commit: no effect, timer or await stands between.
    expect(screen.getAllByText(SETTINGS.schemaRefused)).toHaveLength(1);
    expect(screen.queryByRole("spinbutton")).not.toBeInTheDocument();
    expect(container.querySelector("img, script")).toBeNull();
    expect(container.textContent).not.toContain("onerror");
  });

  it("test_prototype_keys_are_dropped_never_read", () => {
    const raw: unknown = JSON.parse(
      `{"type":"object","properties":{"__proto__":{"type":"integer","title":"Evil","minimum":1,"maximum":2,"default":1},"constructor":{"type":"boolean","title":"Ctor","default":true},"n":${JSON.stringify(period)}}}`,
    );
    show(raw);
    expect(screen.getAllByRole("spinbutton")).toHaveLength(1);
    expect(screen.queryByText("Evil")).not.toBeInTheDocument();
    expect(screen.queryByText("Ctor")).not.toBeInTheDocument();
    const schema = parseParamsSchema(raw);
    const fields = schema.ok ? schema.fields : [];
    const hostile = new Map<string, string | boolean>([
      ["n", "30"],
      ["__proto__", "7"],
    ]);
    const { params } = checkDraft(fields, hostile);
    expect(params).not.toBeNull();
    expect(Object.getPrototypeOf(params)).toBeNull();
    expect(Object.keys(params ?? {})).toEqual(["n"]);
    expect(({} as Record<string, unknown>)["polluted"]).toBeUndefined();
  });
});

describe("the draft refuses, never clamps (D02 D11)", () => {
  const boll = parseParamsSchema(BOLLINGER.params_schema);
  const fields = boll.ok ? boll.fields : [];
  const mult = fields[1] as NumberField;
  const draft = (n: string, m: string): Draft =>
    new Map([
      ["n", n],
      ["mult", m],
    ]);

  it("test_draft_reports_each_broken_keyword", () => {
    expect(checkDraft(fields, draft("20", "2")).params).toEqual({ n: 20, mult: 2 });
    expect([...checkDraft(fields, draft("0", "2.25")).errors]).toEqual([
      ["n", "minimum"],
      ["mult", "multipleOf"],
    ]);
    expect(checkDraft(fields, draft("1e3", "")).errors.get("n")).toBe("type");
    expect(checkDraft(fields, draft("2.5", "2")).errors.get("n")).toBe("type");
  });

  it("test_step_keys_land_on_the_grid_inside_the_bounds", () => {
    expect(stepFrom(mult, "2", 1)).toBe(2.1);
    expect(stepFrom(mult, "0.2", 1)).toBe(0.3);
    expect(stepFrom(mult, "2.25", 1)).toBe(2.3);
    expect(stepFrom(mult, "2.25", -1)).toBe(2.2);
    expect(stepFrom(mult, "9.5", 10)).toBe(10);
    expect(stepFrom(mult, "x", 1)).toBe(0.1);
    expect(stepFrom(mult, "x", -1)).toBe(10);
  });

  it("test_invalid_field_shows_the_deck_sentence_and_aria_invalid", () => {
    show(BOLLINGER.params_schema, draft("20", "2.25"));
    const field = screen.getByRole("spinbutton", { name: "Standard deviations" });
    expect(field).toHaveValue("2.25");
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(field).toHaveAccessibleDescription(
      "Standard deviations must be a multiple of 0.1. 0.1–10, step 0.1",
    );
  });

  it("test_keys_step_jump_and_enter", () => {
    const { onChange, onEnter } = show(EMA.params_schema);
    const n = screen.getByRole("spinbutton", { name: "Period" });
    for (const key of ["ArrowUp", "PageDown", "Home", "End", "Enter"])
      fireEvent.keyDown(n, { key });
    expect(onChange.mock.calls).toEqual([
      ["n", "22"],
      ["n", "11"],
      ["n", "1"],
      ["n", "5000"],
    ]);
    expect(onEnter).toHaveBeenCalledWith("n");
  });

  it("test_enum_options_render_as_text", () => {
    show(CVD.params_schema);
    const select = screen.getByRole("combobox", { name: "Reset anchor" });
    expect(within(select).getByText("session")).toBeInTheDocument();
  });
});

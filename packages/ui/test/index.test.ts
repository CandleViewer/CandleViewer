import { describe, expect, it } from "vitest";
import * as Atoms from "../src/index.js";
import { TOKEN_SCHEMA_VERSION, Placeholder } from "../src/index.js";
import type {
  ButtonProps,
  CardProps,
  CheckboxProps,
  DialogProps,
  FormFieldProps,
  FormSectionProps,
  IconButtonProps,
  NumericStepperInputProps,
  RadioGroupProps,
  SearchBoxProps,
  SegmentedControlProps,
  SelectProps,
  SliderProps,
  TabItem,
  TabsProps,
  TextInputProps,
  ToggleProps,
} from "../src/index.js";

describe("@candleviewer/ui public export surface", () => {
  it("exposes the token schema version", () => {
    expect(TOKEN_SCHEMA_VERSION).toBe(1);
  });

  it("exposes the Placeholder component as a function", () => {
    expect(typeof Placeholder).toBe("function");
  });
});

describe("@candleviewer/ui control atoms (E05-S01)", () => {
  it.each([
    ["Button", Atoms.Button],
    ["IconButton", Atoms.IconButton],
    ["SegmentedControl", Atoms.SegmentedControl],
    ["Toggle", Atoms.Toggle],
    ["Checkbox", Atoms.Checkbox],
    ["RadioGroup", Atoms.RadioGroup],
    ["TextInput", Atoms.TextInput],
    ["NumericStepperInput", Atoms.NumericStepperInput],
    ["Select", Atoms.Select],
    ["Slider", Atoms.Slider],
  ])("exports %s from the package entry as a component function", (_name, component) => {
    expect(typeof component).toBe("function");
  });

  it("exports each atom's props type (checked by the typechecker)", () => {
    const props:
      | [
          ButtonProps,
          IconButtonProps,
          SegmentedControlProps,
          ToggleProps,
          CheckboxProps,
          RadioGroupProps,
          TextInputProps,
          NumericStepperInputProps,
          SelectProps,
          SliderProps,
        ]
      | null = null;
    expect(props).toBeNull();
  });
});

describe("@candleviewer/ui molecules (E05-S03)", () => {
  it.each([
    ["Card", Atoms.Card],
    ["Dialog", Atoms.Dialog],
    ["FormField", Atoms.FormField],
    ["FormSection", Atoms.FormSection],
    ["SearchBox", Atoms.SearchBox],
    ["Tabs", Atoms.Tabs],
  ])("exports %s from the package entry as a component function", (_name, component) => {
    expect(typeof component).toBe("function");
  });

  it("exports each molecule's props type (checked by the typechecker)", () => {
    const props:
      | [
          CardProps,
          DialogProps,
          FormFieldProps,
          FormSectionProps,
          SearchBoxProps,
          TabsProps,
          TabItem,
        ]
      | null = null;
    expect(props).toBeNull();
  });
});

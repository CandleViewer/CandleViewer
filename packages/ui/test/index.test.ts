import { describe, expect, it } from "vitest";
import * as Atoms from "../src/index.js";
import { TOKEN_SCHEMA_VERSION, Placeholder } from "../src/index.js";
import type {
  ButtonProps,
  IconButtonProps,
  RadioGroupProps,
  SelectProps,
  SliderProps,
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
  // CMP-003 SegmentedControl, CMP-005 Checkbox and CMP-008 NumericStepperInput join this list
  // with their own PRs (#4757, #4738, #4761).
  it.each([
    ["Button", Atoms.Button],
    ["IconButton", Atoms.IconButton],
    ["Toggle", Atoms.Toggle],
    ["RadioGroup", Atoms.RadioGroup],
    ["TextInput", Atoms.TextInput],
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
          ToggleProps,
          RadioGroupProps,
          TextInputProps,
          SelectProps,
          SliderProps,
        ]
      | null = null;
    expect(props).toBeNull();
  });
});

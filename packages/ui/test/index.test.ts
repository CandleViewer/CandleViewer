import { describe, expect, it } from "vitest";
import * as Atoms from "../src/index.js";
import { TOKEN_SCHEMA_VERSION, Placeholder } from "../src/index.js";
import type {
  ButtonProps,
  CardProps,
  ColumnPickerProps,
  FileDropProps,
  FreshnessMarkerProps,
  TableRowContext,
  WatchlistGroupTabsProps,
  WatchlistRowProps,
  CheckboxProps,
  CommandPaletteProps,
  ConfirmDialogProps,
  DatePickerProps,
  DateRangePickerProps,
  DateRangeValue,
  DialogProps,
  DrawerProps,
  FormFieldProps,
  FormSectionProps,
  IconButtonProps,
  InfoPanelProps,
  MenuProps,
  NumericStepperInputProps,
  RadioGroupProps,
  SearchBoxProps,
  SegmentedControlProps,
  SelectProps,
  SliderProps,
  TabItem,
  TableProps,
  TabsProps,
  TextInputProps,
  ToastProps,
  ToastRegionProps,
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
    ["CommandPalette", Atoms.CommandPalette],
    ["ConfirmDialog", Atoms.ConfirmDialog],
    ["DatePicker", Atoms.DatePicker],
    ["DateRangePicker", Atoms.DateRangePicker],
    ["Dialog", Atoms.Dialog],
    ["Drawer", Atoms.Drawer],
    ["FormField", Atoms.FormField],
    ["FormSection", Atoms.FormSection],
    ["InfoPanel", Atoms.InfoPanel],
    ["Menu", Atoms.Menu],
    ["SearchBox", Atoms.SearchBox],
    ["Table", Atoms.Table],
    ["Tabs", Atoms.Tabs],
    ["Toast", Atoms.Toast],
    ["ToastRegion", Atoms.ToastRegion],
  ])("exports %s from the package entry as a component function", (_name, component) => {
    expect(typeof component).toBe("function");
  });

  it("exports each molecule's props type (checked by the typechecker)", () => {
    const props:
      | [
          CardProps,
          CommandPaletteProps,
          ConfirmDialogProps,
          DatePickerProps,
          DateRangePickerProps,
          DateRangeValue,
          DialogProps,
          DrawerProps,
          FormFieldProps,
          FormSectionProps,
          InfoPanelProps,
          MenuProps,
          SearchBoxProps,
          TableProps<unknown>,
          TabsProps,
          TabItem,
          ToastProps,
          ToastRegionProps,
        ]
      | null = null;
    expect(props).toBeNull();
  });
});

describe("@candleviewer/ui watchlist components (E08-S08)", () => {
  it.each([
    ["ColumnPicker", Atoms.ColumnPicker],
    ["FileDrop", Atoms.FileDrop],
    ["FreshnessMarker", Atoms.FreshnessMarker],
    ["WatchlistGroupTabs", Atoms.WatchlistGroupTabs],
    ["WatchlistRow", Atoms.WatchlistRow],
    ["watchlistColumns", Atoms.watchlistColumns],
  ])("exports %s from the package entry as a function", (_name, value) => {
    expect(typeof value).toBe("function");
  });

  it("exports each one's props type and CMP-049's row contract (checked by the typechecker)", () => {
    const props:
      | [
          ColumnPickerProps,
          FileDropProps,
          FreshnessMarkerProps,
          TableRowContext,
          WatchlistGroupTabsProps,
          WatchlistRowProps,
        ]
      | null = null;
    expect(props).toBeNull();
  });
});

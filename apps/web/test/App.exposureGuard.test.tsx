/**
 * E29-S07 (#1028): the keymap's new-exposure guard is installed by `App` itself (beside
 * `KeymapHost`), never by a UI slot, and uninstalled when the app goes.
 */
import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { resetSharedThemeStores } from "@candleviewer/ui";
import { App } from "../src/App";
import { EXPOSURE_NOT_READY, appExposureRefusal } from "../src/keymap/registry";

afterEach(() => {
  resetSharedThemeStores();
  localStorage.clear();
});

describe("App installs the keymap's new-exposure guard", () => {
  it("while the app is mounted the live guard answers, and unmounting puts back fail closed", async () => {
    expect(appExposureRefusal()).toBe(EXPOSURE_NOT_READY);
    const view = render(<App />);
    await screen.findByRole("main");
    // no WS client in this test: the live guard reads the link as down, never "not ready"
    expect(appExposureRefusal()).toBe(
      "Not connected — new orders off; cancel and close still work.",
    );
    view.unmount();
    expect(appExposureRefusal()).toBe(EXPOSURE_NOT_READY);
  });
});

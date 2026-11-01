/**
 * E29-S01 (#911) the CSV export's file (D-21, BQ-17): its name from the UTC time, and the browser
 * download (a Blob URL on an `<a download>`, clicked, removed and revoked). No request is made.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { exportFileName, saveCsv } from "../../../src/features/positions/exportFile";

/** jsdom's Blob has no `text()`: read it as a page would, through FileReader. */
function readBlob(blob: Blob | undefined): Promise<string> {
  return new Promise((resolve, reject) => {
    if (blob === undefined) return reject(new Error("no blob"));
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result));
    reader.onerror = () => reject(reader.error ?? new Error("unreadable"));
    reader.readAsText(blob);
  });
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("exportFileName (PROPOSED, D03's pattern)", () => {
  it("names the UTC time of the export to the second", () => {
    expect(exportFileName(new Date(Date.UTC(2026, 10, 1, 14, 5, 9, 750)))).toBe(
      "candleviewer-positions-20261101T140509Z.csv",
    );
  });
});

describe("saveCsv", () => {
  it("clicks one hidden download link with the CSV, removes it, then revokes its URL", async () => {
    vi.useFakeTimers();
    const create = vi.fn<(blob: Blob) => string>(() => "blob:positions");
    const revoke = vi.fn();
    // jsdom has no Blob URLs: the page's own `URL` takes the two for this test, then gives them back
    const target = (document.defaultView ?? window).URL;
    const saved = {
      createObjectURL: Object.getOwnPropertyDescriptor(target, "createObjectURL"),
      revokeObjectURL: Object.getOwnPropertyDescriptor(target, "revokeObjectURL"),
    };
    Object.assign(target, { createObjectURL: create, revokeObjectURL: revoke });
    const clicked: { href: string; download: string; hidden: boolean }[] = [];
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clicked.push({ href: this.href, download: this.download, hidden: this.hidden });
    });
    const fetchSpy = vi.fn();
    vi.stubGlobal("fetch", fetchSpy);
    saveCsv("positions.csv", "Account\r\nMain\r\n");
    expect(clicked).toEqual([{ href: "blob:positions", download: "positions.csv", hidden: true }]);
    expect(document.querySelector("a[download]")).toBeNull();
    const blob = create.mock.calls[0]?.[0];
    expect(blob?.type).toBe("text/csv;charset=utf-8");
    expect(revoke).not.toHaveBeenCalled();
    vi.advanceTimersByTime(0);
    expect(revoke).toHaveBeenCalledWith("blob:positions");
    vi.useRealTimers(); // jsdom's FileReader answers on a timer
    expect(await readBlob(blob)).toBe("Account\r\nMain\r\n");
    expect(fetchSpy).not.toHaveBeenCalled();
    click.mockRestore();
    for (const [name, descriptor] of Object.entries(saved)) {
      if (descriptor === undefined) Reflect.deleteProperty(target, name);
      else Object.defineProperty(target, name, descriptor);
    }
  });
});

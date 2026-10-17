// @vitest-environment jsdom
import { createHash } from "node:crypto";
import { runInNewContext } from "node:vm";
import { describe, expect, it } from "vitest";
import {
  DENSITIES,
  MOTION_OVERRIDES,
  THEME_PREPAINT_SCRIPT,
  THEME_PREPAINT_SCRIPT_SHA256,
  THEME_STORAGE_KEY,
  createThemeStore,
} from "../../src/theme/index.js";
import { mediaStub, memoryStorage, themeChanges } from "./helpers.js";

type Os = { dark: boolean; reduce: boolean };
const attrs = (root: HTMLElement): (string | null)[] =>
  ["theme", "density", "motion", "text-scale"].map((name) => root.getAttribute(`data-${name}`));

/** Runs the snippet as a browser would at the top of `<head>`: it sees only the document, storage and matchMedia. */
function runPrepaint(root: HTMLElement, raw: string | null, os?: Os): void {
  const storage = memoryStorage(raw === null ? {} : { [THEME_STORAGE_KEY]: raw });
  const matchMedia = os ? { matchMedia: mediaStub(os).matchMedia } : {};
  runInNewContext(THEME_PREPAINT_SCRIPT, {
    document: { documentElement: root },
    localStorage: storage,
    ...matchMedia,
  });
}

function storeAttrs(raw: string | null, os?: Os): (string | null)[] {
  const root = document.createElement("html");
  const storage = memoryStorage(raw === null ? {} : { [THEME_STORAGE_KEY]: raw });
  const media = os ? { matchMedia: mediaStub(os).matchMedia } : {};
  createThemeStore({ root, storage, ...media }).connect();
  return attrs(root);
}

describe("pre-paint snippet", () => {
  it("restores persisted light + comfortable before first paint; connecting the store changes nothing", () => {
    const saved = JSON.stringify({ baseTheme: "light", density: "comfortable" });
    const root = document.documentElement;
    runPrepaint(root, saved);
    expect(attrs(root)).toEqual(["light", "comfortable", "safe", "100"]);

    const observer = new MutationObserver(() => undefined);
    observer.observe(root, { attributes: true });
    const changes = themeChanges();
    const storage = memoryStorage({ [THEME_STORAGE_KEY]: saved });
    createThemeStore({ storage, matchMedia: mediaStub().matchMedia }).connect();
    expect(observer.takeRecords()).toEqual([]);
    expect(changes).toEqual([]);
    observer.disconnect();
  });

  it("resolves exactly like the store for every persisted theme, motion, density and scale", () => {
    const raws: (string | null)[] = [null, "{bad", "5", '"x"', "[1]", '{"textScale":"125"}'];
    const oses: Os[] = [true, false].flatMap((dark) =>
      [true, false].map((reduce) => ({ dark, reduce })),
    );
    for (const baseTheme of ["dark", "light", "neon"]) {
      for (const matchSystem of [true, false]) {
        for (const highContrast of [true, false]) {
          raws.push(JSON.stringify({ baseTheme, matchSystem, highContrast }));
        }
      }
    }
    for (const motionOverride of [...MOTION_OVERRIDES, "loud"]) {
      raws.push(JSON.stringify({ motionOverride }));
    }
    for (const density of [...DENSITIES, "huge"]) {
      for (const textScale of [100, 112, 125, 150, 99, "150"]) {
        raws.push(JSON.stringify({ density, textScale }));
      }
    }
    for (const raw of raws) {
      for (const os of [undefined, ...oses]) {
        const root = document.createElement("html");
        runPrepaint(root, raw, os);
        expect(attrs(root), `${raw} ${JSON.stringify(os)}`).toEqual(storeAttrs(raw, os));
      }
    }
  });

  it("never throws when storage access is denied", () => {
    const root = document.createElement("html");
    const denied = {
      getItem: () => {
        throw new Error("denied");
      },
    };
    runInNewContext(THEME_PREPAINT_SCRIPT, {
      document: { documentElement: root },
      localStorage: denied,
    });
    expect(attrs(root)).toEqual(["dark", "compact", "safe", "100"]);
  });

  it("pins its CSP hash and is safe to embed as the only inline script", () => {
    const hash = createHash("sha256").update(THEME_PREPAINT_SCRIPT).digest("base64");
    expect(hash).toBe(THEME_PREPAINT_SCRIPT_SHA256);
    expect(THEME_PREPAINT_SCRIPT).not.toMatch(/<\/script|<!--/i);
  });
});

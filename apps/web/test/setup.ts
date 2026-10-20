import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});

// #2712: vitest hands jsdom Node's BroadcastChannel, which would join every token holder of a run, across
// tests and files. Here the browser has none; a test that shares a token between tabs stubs its own.
Reflect.deleteProperty(globalThis, "BroadcastChannel");

import { act } from "react";
import { vi } from "vitest";

/** A `matchMedia` stub for the narrow query only: `set(true)` is a resize to 720 CSS px or less. */
export const narrowViewport = (initial: boolean): { set: (narrow: boolean) => Promise<void> } => {
  let narrow = initial;
  const listeners = new Set<() => void>();
  vi.stubGlobal("matchMedia", (query: string) => ({
    get matches() {
      return query.includes("max-width") && narrow;
    },
    media: query,
    addEventListener: (_type: string, listener: () => void) => void listeners.add(listener),
    removeEventListener: (_type: string, listener: () => void) => void listeners.delete(listener),
  }));
  return {
    set: async (next) => {
      narrow = next;
      await act(async () => listeners.forEach((listener) => listener()));
    },
  };
};

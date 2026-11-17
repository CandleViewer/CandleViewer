import { onTestFinished } from "vitest";

/** The part of jsdom's virtual console (vitest's `jsdom` global) that reports an error nobody handled. */
interface VirtualConsole {
  on(event: "jsdomError", listener: (error: Error) => void): unknown;
  off(event: "jsdomError", listener: (error: Error) => void): unknown;
}

/**
 * Counts `focusin` events and records uncaught errors until the test ends. A focus loop overflows the stack,
 * and its RangeError is raised so deep that jsdom often cannot dispatch it on `window`: it prints it on its
 * virtual console instead ("Uncaught [RangeError: …]"). Both are recorded, and a test bounds the count too.
 * An error that does reach `window` is marked handled, so the test's assertion reports it.
 */
export function watchFocus(): { readonly count: () => number; readonly errors: string[] } {
  let count = 0;
  const errors: string[] = [];
  const onFocusIn = (): void => {
    count += 1;
  };
  const onError = (event: ErrorEvent): void => {
    errors.push(event.message);
    event.preventDefault();
  };
  const onUncaught = (error: Error): void => {
    if (error.message.startsWith("Uncaught")) errors.push(error.message);
  };
  const { virtualConsole } = (
    globalThis as unknown as { jsdom: { virtualConsole: VirtualConsole } }
  ).jsdom;
  document.addEventListener("focusin", onFocusIn, true);
  window.addEventListener("error", onError);
  virtualConsole.on("jsdomError", onUncaught);
  onTestFinished(() => {
    document.removeEventListener("focusin", onFocusIn, true);
    window.removeEventListener("error", onError);
    virtualConsole.off("jsdomError", onUncaught);
  });
  return { count: () => count, errors };
}

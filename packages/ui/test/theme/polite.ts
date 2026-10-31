/** The shared polite live region's text after pending microtasks (a gated activation announces in one). */
export async function politeText(): Promise<string> {
  await Promise.resolve();
  return document.getElementById("cv-theme-live-region")?.textContent ?? "";
}

/** Empties the region between phases of one test (it is shared and outlives each mount). */
export function clearPolite(): void {
  const region = document.getElementById("cv-theme-live-region");
  if (region !== null) region.textContent = "";
}

/**
 * The one same-origin rule (ADR-0038 decision 3e): the SR-041 header, the credentials and the #2712 bearer
 * all go by it. A URL is resolved as `fetch` resolves it, against `document.baseURI`.
 */

function hrefOf(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  return input instanceof URL ? input.href : input.url;
}

/** `input` as a URL of this page's own origin, else `null`: another origin, an opaque one, or no URL. */
export function sameOriginUrl(input: RequestInfo | URL): URL | null {
  const { origin } = window.location;
  try {
    const url = new URL(hrefOf(input), document.baseURI);
    return origin !== "null" && url.origin === origin ? url : null;
  } catch {
    return null;
  }
}

/** True only for URLs on this page's own origin (relative URLs included). */
export const isSameOrigin = (input: RequestInfo | URL): boolean => sameOriginUrl(input) !== null;

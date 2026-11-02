import type { Plugin } from "vite";
import { buildCspPolicy } from "@candleviewer/config/csp-policy";

const CSP_META_RE = /<meta\s+http-equiv="Content-Security-Policy"[^>]*>/i;

/**
 * Writes the CSP `<meta>` into the built `index.html` from the shared policy builder (SR-112,
 * C-12.10, E43-T01). `apply: "build"`: `vite dev` (HMR needs an inline preamble) and Storybook carry
 * no policy and are outside the CSP assertion. A hand-written meta in the source page is refused,
 * so the build output can never drift from the builder.
 */
export function cspMetaPlugin(options: { readonly tailnetHost?: string } = {}): Plugin {
  return {
    name: "cv-csp-meta",
    apply: "build",
    transformIndexHtml: {
      order: "post",
      handler(html) {
        if (CSP_META_RE.test(html)) {
          throw new Error("index.html must not carry a CSP meta; cv-csp-meta injects it at build");
        }
        const policy = buildCspPolicy({
          surface: "meta",
          tailnetHost: options.tailnetHost ?? process.env["CV_CSP_TAILNET_HOST"] ?? null,
        });
        const tag = `<meta http-equiv="Content-Security-Policy" content="${policy}" />`;
        return html.replace("<head>", `<head>\n    ${tag}`);
      },
    },
  };
}

import { defineConfig, mergeConfig } from "vite";
import base from "../vite.config";

// E09-Q02 (#293) PR 2 (#2490): `vite preview` of the built SPA for the real-backend lane
// (`playwright.real.config.ts`). The SPA calls the same-origin `/api/v1/*` and opens `/api/v1/ws`,
// and the API serves its routes from the root, so the preview proxies `/api/v1` to the API with the
// prefix stripped, the WebSocket upgrade included. The browser sees one origin: the cookies the API
// sets (`cv_refresh` on `Path=/api/v1/auth`, `__Host-cv_csrf` on `/`) and its `Origin` checks see
// the preview's origin, which the lane lists in `CV_ALLOWED_ORIGINS`. Loopback only.
const api = new URL(process.env["CV_E2E_REAL_API"] ?? "http://127.0.0.1:8000");
if (api.protocol !== "http:" || !["127.0.0.1", "localhost"].includes(api.hostname)) {
  throw new Error("CV_E2E_REAL_API must be an http:// loopback origin");
}

export default mergeConfig(
  base,
  defineConfig({
    preview: {
      strictPort: true,
      proxy: {
        "/api/v1": {
          target: api.origin,
          ws: true,
          rewrite: (path: string) => path.replace(/^\/api\/v1(?=\/|$)/u, "") || "/",
        },
      },
    },
  }),
);

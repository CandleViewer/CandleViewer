// The Canvas 2D backend (E11-T05): DOM-free (C-2.16) like src/gl, below the host, the facade and
// the worker glue (.dependency-cruiser.js); src/core|layers|scene|model|viewport never import it.
export { Canvas2DBackend, MAX_BUCKETS } from "./backend.js";
export { asCtx2D, type Ctx2DLike } from "./ctx2d.js";

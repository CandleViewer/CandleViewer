// The WebGL2 backend (E11-S02): DOM-free (C-2.16), below the host, the facade and the worker glue
// (.dependency-cruiser.js); src/core|layers|scene|model never import it (26 §3.1).
export * from "./capability.js";
export * from "./context.js";
export * from "./gl-types.js";
export { GlRegistry, RESOURCE_KINDS, type RegistryStats, type ResourceKind } from "./registry.js";

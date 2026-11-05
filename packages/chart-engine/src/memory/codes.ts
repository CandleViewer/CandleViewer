// E11-S15's error codes (26 §11), in a leaf module like text/codes.ts so the main-thread protocol
// can re-export them (PR-2b) without pulling the governor into the host bundle. Both are
// recoverable: the pressure one once per worsening edge of the governor's state (§7), the clamp one
// once per chart when the drawing buffer is smaller than the backing store (F-12).
export const ENGINE_MEMORY_PRESSURE = "ENGINE_MEMORY_PRESSURE";
export const ENGINE_DRAWING_BUFFER_CLAMPED = "ENGINE_DRAWING_BUFFER_CLAMPED";

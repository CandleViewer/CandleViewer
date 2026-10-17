// Minimal typing for Vite's `import.meta.glob` (vite is only a transitive dependency of this package).
interface ImportMeta {
  glob(pattern: string, options: { eager: true }): Record<string, unknown>;
}

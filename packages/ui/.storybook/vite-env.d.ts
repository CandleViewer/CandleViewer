// Minimal typing for the two Vite features the package touches (vite is only a transitive dependency):
// `import.meta.glob` for the preview's token CSS and `import.meta.env.DEV` for development-only warnings.
// `env` is optional because plain Node and other bundlers do not provide it.
interface ImportMeta {
  glob(pattern: string, options: { eager: true }): Record<string, unknown>;
  readonly env?: { readonly DEV?: boolean };
}

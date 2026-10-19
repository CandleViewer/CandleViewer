// Minimal typing for the one Vite feature the package touches (vite is only a transitive dependency):
// `import.meta.env.DEV` for development-only warnings. `env` is optional because plain Node and other
// bundlers do not provide it. (The preview imports the token CSS by name, so no `import.meta.glob`.)
interface ImportMeta {
  readonly env?: { readonly DEV?: boolean };
}

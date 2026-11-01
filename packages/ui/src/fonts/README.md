# Design fonts

Self-hosted variable fonts for the design system (`docs/plan/16-design-system-brief.md` §2):
Inter (UI) and JetBrains Mono (numeric/mono), upright and italic, as WOFF2.

- `manifest.json` names the upstream release, source and SHA-256 of every file.
- `OFL-Inter.txt`, `OFL-JetBrainsMono.txt` are the licence texts (SIL OFL 1.1; CONSTITUTION.md §9 #14, v2.1.1).
- `BUILD.md` lists the re-vendoring commands. Do not hand-edit the binaries.

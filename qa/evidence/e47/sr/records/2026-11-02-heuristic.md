# Screen-reader pass record 2026-11-02 (heuristic)

**(heuristic) Not a human pass.** No screen reader was run and no build was started. Each row below was read from
source at the cited line, so it shows what the code is built to expose, not what was heard. It counts toward no
matrix row and no G2 pass.

```yaml
record_id: "2026-11-02-heuristic"
mode: heuristic
screen_reader: "none"
shell: "none (source read)"
os_build: ""
date: "2026-11-02"
tester: "agent (E47-T04 pre-stage)"
build_sha: c327ed438c01c5bab9247890dd00f5dce3717f97
fixture: "none"
script: XC
dry_run_by: ""
approved: pending
```

| Step                              | Result                   | What the source shows                                                                             |
| --------------------------------- | ------------------------ | ------------------------------------------------------------------------------------------------- |
| XC-01                             | (heuristic) code matches | The badge is `role="img"` named `Trading environment: {env}` (`TopBarEnvBadge.tsx:47`, `:64`).    |
| XC-03                             | (heuristic) code matches | `nav` labelled "Primary" (`AppShell.tsx:117`).                                                    |
| XC-06                             | (heuristic) code matches | A `role="status"` region labelled "System status" (`StatusBar.tsx:204`).                          |
| XC-07                             | (heuristic) code matches | Shell announcer has one polite and one assertive `aria-live` region, atomic (`announcer.tsx:87`). |
| XC-02, XC-04, XC-05               | not run                  | Needs a running build and the 2FA fixture; XC-04 is also E10-S03 pending.                         |
| CDC-_, FPI-_, DOM-_, RFE-_, RNE-* | unreachable: not built   | Surfaces are not mounted in the Electron build.                                                   |

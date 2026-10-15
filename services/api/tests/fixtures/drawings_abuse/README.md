# drawings_abuse

- `corpus.v1.json`: versioned hostile-text corpus for `/drawings` abuse tests (E14-X02, #474); source: hand-written
  public vectors (OWASP XSS filter-evasion cheat sheet, the 0xSobky "ultimate XSS polyglot" (HackVault wiki) and DOMPurify mXSS
  mutation-XSS examples, Unicode Trojan Source), 2026-10-15,
  no symbol/env/credentials, no redaction needed. Attack data: loaded
  only by `tests/drawings/test_drawings_abuse_*.py`; never ship or serve it. Bump the version for any change.
  The issue names `qa/security/corpus/drawings-text.json` as the shared path for E14-Q01/Q07; until that is
  decided, this file is the only copy and is NOT yet shared with them.

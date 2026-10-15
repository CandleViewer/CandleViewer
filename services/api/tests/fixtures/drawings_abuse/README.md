# drawings_abuse

- `corpus.v1.json`: versioned hostile-text corpus for `/drawings` abuse tests (E14-X02, #474); source: hand-written
  public XSS/Trojan-Source vectors, 2026-10-15, no symbol/env/credentials, no redaction needed. Attack data: loaded
  only by `tests/drawings/test_drawings_abuse_*.py`; never ship or serve it. Bump the version for any change.

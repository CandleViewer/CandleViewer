"""#843 (E29-K01): the demo order-path spike harness. Throwaway, on `spike/oms-demo-path`.

It measures the exchange's demo order path through the adapter as production composes it: M2
signs (the harness never holds a secret), M19 audits every borrow into a WAL of the harness's own,
and the real `TradingPort` and private stream run behind two recording seams (`recorder.py`).
`--offline` (the default) swaps only those seams for the recorded corpus (`offline.py`). Every
output is scrubbed before it is written (`scrub.py`, `outputs.py`). The runbook is `README.md`.
"""

# Design-QA ledger fixtures (E49-D01, #1330)

Synthetic, hand-written; no exchange or account data. `catalogue.md` is a five-screen trim of the
screens catalogue's heading shape; `register.json` is a five-screen stand-in for the E47-D02 register;
`findings.csv` is the finding ledger in the exporter's header. The five screen ledgers are the test
plan's cases: `complete.csv` passes; each other file breaks exactly one rule (`missing-row.csv`
E_MISSING, `bad-verdict.csv` E_VERDICT, `exception-without-owner.csv` E_EXCEPTION,
`findings-without-bug-key.csv` E_BUGKEY). Read by `scripts/design_qa_ledger_check.py`.

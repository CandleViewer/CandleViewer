"""#2893: the dev/test account fixture transport for the E27 fault-injection pack.

With `CV_ACCOUNT_FIXTURE=<scenario>`, a dev/test stack's exchange account traffic goes to a stub
that will answer from the account pack (`packages/fixtures/accounts`), for fabricated fixture keys
only. `wiring` is the only entry point (`build`, and the boot guard `guard_boot`), and
`candleviewer.account_fixture_wiring` is its only caller. Until the per-request guard and the
serving slices land, the stub refuses every request.
"""

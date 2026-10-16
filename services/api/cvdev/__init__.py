"""Dev-only backend code, a sibling of `candleviewer` (#2893 ruling 1).

Never packaged and never in an image: the wheel packages only `candleviewer`
(`services/api/pyproject.toml`) and `infra/images/Dockerfile.api` copies only that package, so a
release build cannot import anything here. A checkout reaches it through the editable install
that puts `services/api` on the import path (tests, a dev stack). Production code names this
package in exactly one place, `candleviewer.account_fixture_wiring`, which imports it lazily and
refuses boot when it is absent. Nothing here may import `candleviewer.secrets`.
"""

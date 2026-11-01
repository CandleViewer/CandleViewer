"""E12-X02 bars abuse suite (#452): `/market/bars`, `/market/klines` and the `bars.*` topic."""

import pytest

# `_oracle` is no `test_*` module, so pytest would not rewrite its asserts and a red check would
# print a bare `AssertionError` with no values (C-13.7). Register it before a test imports it.
pytest.register_assert_rewrite("tests.security.bars._oracle")

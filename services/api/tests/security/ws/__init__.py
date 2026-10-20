"""E17-X02 WS abuse suite (#415)."""

import pytest

# `_raw` is no `test_*` module, so pytest would not rewrite its asserts and a red pin would print
# a bare `AssertionError` with no values (C-13.7). Register it before the conftest imports it.
pytest.register_assert_rewrite("tests.security.ws._raw")

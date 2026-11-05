"""The session guard of #843's harness tests, reused: any socket connect or name lookup fails
the test, loopback included (C-13.5); structlog is reset after each test."""

from spike.oms_demo_path.tests.conftest import (  # noqa: F401 - pytest finds fixtures by name
    no_network,
    no_network_verdict,
    reset_structlog,
)

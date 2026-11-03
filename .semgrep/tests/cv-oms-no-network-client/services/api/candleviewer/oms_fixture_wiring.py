# Fixture for cv-oms-no-network-client in the OMS composition modules (`oms_*.py`), in a file with
# PEP 695 syntax (#3549): the lane's transport is a type only, never one the OMS builds.
import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import httpx  # ok: cv-oms-no-network-client

type Transport = "httpx.AsyncBaseTransport | None"


def lane_port[P](venue: P, transport: Transport = None) -> P:
    del transport
    return venue


def test_transport(handler):
    importlib.import_module("websockets")  # ruleid: cv-oms-no-network-client
    importlib.import_module("candleviewer.exchange.base")  # ok: cv-oms-no-network-client
    return httpx.MockTransport(handler)  # ruleid: cv-oms-no-network-client

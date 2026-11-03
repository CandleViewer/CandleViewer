# Fixture for cv-oms-no-network-client (E29-X02): network clients imported or built in an OMS
# module; the adapter's port, the adapter import M14 may make and a type-only import stay quiet.
from __future__ import annotations

import asyncio
import importlib
import typing
from typing import TYPE_CHECKING

import httpx  # ruleid: cv-oms-no-network-client
import aiohttp as http  # ruleid: cv-oms-no-network-client
from websockets import connect  # ruleid: cv-oms-no-network-client
import urllib.request  # ruleid: cv-oms-no-network-client
from urllib import request  # ruleid: cv-oms-no-network-client
import socket  # ruleid: cv-oms-no-network-client
from requests import Session  # ruleid: cv-oms-no-network-client
from http.client import HTTPSConnection  # ruleid: cv-oms-no-network-client

from candleviewer.exchange.base import TradingPort  # ok: cv-oms-no-network-client
from candleviewer.exchange.bybit import trading  # ok: cv-oms-no-network-client

if TYPE_CHECKING:
    from httpx import AsyncBaseTransport  # ok: cv-oms-no-network-client

if TYPE_CHECKING:  # ok: cv-oms-no-network-client
    from httpx import Client
else:
    Client = object

# the other branch of `if TYPE_CHECKING:` runs
if TYPE_CHECKING:  # ruleid: cv-oms-no-network-client
    import httpx as typed_httpx
else:
    import httpx as runtime_httpx

if typing.TYPE_CHECKING:  # ruleid: cv-oms-no-network-client
    from requests import Session as TypedSession
else:
    from requests import Session as RuntimeSession

if TYPE_CHECKING:  # ruleid: cv-oms-no-network-client
    import aiohttp as typed_aiohttp
elif Client is object:
    import websockets as runtime_websockets

if TYPE_CHECKING:  # ruleid: cv-oms-no-network-client
    pass
else:
    from urllib import request as runtime_request

if TYPE_CHECKING:  # ruleid: cv-oms-no-network-client
    pass
else:
    from http import client as runtime_client


async def send(port: TradingPort, loop, factory, transport: AsyncBaseTransport | None):
    async with httpx.AsyncClient(transport=transport) as client:  # ruleid: cv-oms-no-network-client
        await client.post("/v5/order/create")
    await asyncio.open_connection("venue", 443)  # ruleid: cv-oms-no-network-client
    await loop.create_connection(factory, "venue", 443)  # ruleid: cv-oms-no-network-client
    importlib.import_module("aiohttp")  # ruleid: cv-oms-no-network-client
    importlib.import_module("candleviewer.exchange.base")  # ok: cv-oms-no-network-client
    await port.place_order(None)  # ok: cv-oms-no-network-client
    return http, connect, request, socket, Session, HTTPSConnection, trading


class Lane:
    async def dial(self, factory, running):
        await asyncio.get_running_loop().create_connection(factory, "venue", 443, ssl=True)  # ruleid: cv-oms-no-network-client
        await self._loop.create_connection(factory, "venue", 443)  # ruleid: cv-oms-no-network-client
        await running.sock_connect(self._sock, ("venue", 443))  # ruleid: cv-oms-no-network-client
        self._loop.call_soon(factory)  # ok: cv-oms-no-network-client

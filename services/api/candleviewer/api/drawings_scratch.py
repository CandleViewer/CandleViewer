"""E14-X03 (#549) test-plan scratch: a drawing's owner read from the request body. Never merged."""

from __future__ import annotations

from typing import Any

from starlette.requests import Request


async def owner_from_the_body(request: Request) -> Any:
    data = await request.json()
    owner = data["owner"]
    return owner

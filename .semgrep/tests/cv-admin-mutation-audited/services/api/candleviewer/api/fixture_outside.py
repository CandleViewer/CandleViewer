"""Fixtures for cv-admin-mutation-audited: a class outside admin/ is out of its scope."""


class Router:
    async def replace(self, grants: dict[str, str]) -> None:  # ok: cv-admin-mutation-audited
        ...

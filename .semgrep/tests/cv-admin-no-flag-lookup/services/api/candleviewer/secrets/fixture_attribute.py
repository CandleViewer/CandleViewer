"""Fixtures for cv-admin-no-flag-lookup in secrets/: an attribute of a flag object (AC-ADM-14)."""


class Broker:
    def __init__(self, flag_state, kek) -> None:
        self.flag_state, self.kek = flag_state, kek

    def may_sign(self) -> bool:
        return not self.flag_state.engaged  # ruleid: cv-admin-no-flag-lookup

    def version(self) -> int:
        return self.kek.version  # ok: cv-admin-no-flag-lookup

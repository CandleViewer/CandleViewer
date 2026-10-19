"""Fixtures for cv-ws-no-adhoc-authz (E17-X02, SR-017).

Scanned only, never imported: each `ruleid` row must fire and each `ok` row must stay clean.
"""

# --- permissions
a1 = perm in principal.permissions  # ruleid: cv-ws-no-adhoc-authz
a2 = perm not in authz.principal.permissions  # ruleid: cv-ws-no-adhoc-authz
a3 = any(p in principal.permissions for p in perms)  # ruleid: cv-ws-no-adhoc-authz
a4 = need - principal.permissions  # ruleid: cv-ws-no-adhoc-authz
a5 = need <= principal.permissions  # ruleid: cv-ws-no-adhoc-authz
a6 = principal.permissions <= allowed  # ruleid: cv-ws-no-adhoc-authz
a7 = allowed >= principal.permissions  # ruleid: cv-ws-no-adhoc-authz
a8 = principal.permissions >= need  # ruleid: cv-ws-no-adhoc-authz
a9 = principal.permissions - need  # ruleid: cv-ws-no-adhoc-authz
a10 = need.issubset(principal.permissions)  # ruleid: cv-ws-no-adhoc-authz
a11 = need.issuperset(principal.permissions)  # ruleid: cv-ws-no-adhoc-authz
a12 = need.difference(principal.permissions)  # ruleid: cv-ws-no-adhoc-authz
a13 = principal.permissions.difference(need)  # ruleid: cv-ws-no-adhoc-authz
# --- roles
b1 = "owner" in principal.roles  # ruleid: cv-ws-no-adhoc-authz
b2 = "viewer" not in principal.roles  # ruleid: cv-ws-no-adhoc-authz
b3 = principal.roles.isdisjoint({"manager", "viewer"})  # ruleid: cv-ws-no-adhoc-authz
b4 = principal.roles.issubset({"manager", "viewer"})  # ruleid: cv-ws-no-adhoc-authz
b5 = principal.roles.issuperset({"manager"})  # ruleid: cv-ws-no-adhoc-authz
b6 = principal.roles.intersection({"owner"})  # ruleid: cv-ws-no-adhoc-authz
b7 = principal.roles & {"owner"}  # ruleid: cv-ws-no-adhoc-authz
b8 = principal.roles == {"owner"}  # ruleid: cv-ws-no-adhoc-authz
b9 = SCOPED_ROLES.isdisjoint(principal.roles)  # ruleid: cv-ws-no-adhoc-authz
b10 = {"owner"}.intersection(principal.roles)  # ruleid: cv-ws-no-adhoc-authz
b11 = principal.roles < allowed  # ruleid: cv-ws-no-adhoc-authz
b12 = principal.roles > allowed  # ruleid: cv-ws-no-adhoc-authz
b13 = allowed < principal.roles  # ruleid: cv-ws-no-adhoc-authz
b14 = allowed > principal.roles  # ruleid: cv-ws-no-adhoc-authz
b15 = any(r == "owner" for r in principal.roles)  # ruleid: cv-ws-no-adhoc-authz
b16 = all(r in allowed for r in principal.roles)  # ruleid: cv-ws-no-adhoc-authz
b17 = getattr(principal, "roles", frozenset())  # ruleid: cv-ws-no-adhoc-authz
# --- one role
c1 = principal.role == "owner"  # ruleid: cv-ws-no-adhoc-authz
c2 = principal.role != "owner"  # ruleid: cv-ws-no-adhoc-authz
c3 = "owner" == principal.role  # ruleid: cv-ws-no-adhoc-authz
c4 = "owner" != principal.role  # ruleid: cv-ws-no-adhoc-authz
c5 = principal.role in ("owner", "manager")  # ruleid: cv-ws-no-adhoc-authz
c6 = principal.role not in ("owner", "manager")  # ruleid: cv-ws-no-adhoc-authz
c7 = principal.role is None  # ruleid: cv-ws-no-adhoc-authz
c8 = principal.role is not None  # ruleid: cv-ws-no-adhoc-authz
# --- scopes
d1 = "orders:read" in principal.scopes  # ruleid: cv-ws-no-adhoc-authz
d2 = principal.scopes.isdisjoint({"orders:read"})  # ruleid: cv-ws-no-adhoc-authz
d3 = principal.scopes == {"orders:read"}  # ruleid: cv-ws-no-adhoc-authz
# --- account grants: a grant test or a grant lookup outside `decide()`
g1 = grant in principal.account_grants  # ruleid: cv-ws-no-adhoc-authz
g2 = principal.grant_for(account_id)  # ruleid: cv-ws-no-adhoc-authz

# --- fine: the RBAC helpers, a plain read, other attributes
e1 = isinstance(decide(principal, perm), Allow)  # ok: cv-ws-no-adhoc-authz
e2 = principal.is_owner  # ok: cv-ws-no-adhoc-authz
e3 = machine_refusal(principal, kind, entity) is None  # ok: cv-ws-no-adhoc-authz
e4 = {"roles": sorted(principal.roles), "user": principal.user_id}  # ok: cv-ws-no-adhoc-authz
e5 = principal.roles  # ok: cv-ws-no-adhoc-authz
e6 = len(principal.permissions)  # ok: cv-ws-no-adhoc-authz
e7 = account in sub.accounts  # ok: cv-ws-no-adhoc-authz
e8 = family.permission is not None  # ok: cv-ws-no-adhoc-authz
e9 = principal.user_id == user_id  # ok: cv-ws-no-adhoc-authz
e10 = {g.exchange_account_id for g in principal.account_grants if g.can_view}  # ok: cv-ws-no-adhoc-authz
# --- an allow-listed site: the marker on the line above, or on the line itself
# nosemgrep: cv-ws-no-adhoc-authz reason=fan-out owner=@CandleViewer/security review=2027-03-25
f1 = perm not in principal.permissions  # ok: cv-ws-no-adhoc-authz
f2 = principal.roles.isdisjoint({"viewer"})  # nosemgrep: cv-ws-no-adhoc-authz reason=x owner=@CandleViewer/security review=2027-03-25  # ok: cv-ws-no-adhoc-authz
# nosemgrep: some-other-rule reason=x owner=@CandleViewer/security review=2027-03-25
f3 = principal.roles.isdisjoint({"viewer"})  # ruleid: cv-ws-no-adhoc-authz

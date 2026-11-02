"""Every server-side builder of a generated response model, pinned to a test (#4237, BQ-06).

Each generated REST model refuses `null` on an optional member the contract does not let be
`null`, so a builder that validates a `None` there answers 500. A scan of `candleviewer/` finds
each call that builds, validates or constructs a model a response reaches and that holds such a
refusal, itself or in a model it holds; each is listed here with the test that drives it. A new
builder fails the scan until it is listed, with its test."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

from pydantic import BaseModel

from candleviewer.api._generated import openapi_models as api
from tests.contract._generated_contract import RESPONSE_MODELS, _models_in

_SERVICE = Path(__file__).resolve().parents[2]
_BUILD = {"model_validate", "model_validate_json", "model_construct"}

#: (module under `candleviewer/`, innermost function, model) -> (test file under `tests/`, test).
_BUILDERS: dict[tuple[str, str, str], tuple[str, str]] = {
    ("api/admin_backups.py", "backup_payload", "Backup"): (
        "unit/api/test_admin_backups_router.py",
        "test_payload_never_carries_encryption_ref_and_maps_location_and_error",
    ),
    ("api/admin_capacity.py", "set_subaccount_tier", "SubaccountCapacity"): (
        "contract/test_admin_tier_contract.py",
        "test_tier_is_committed_and_audited_before_capacity_is_read",
    ),
    ("api/admin_ops.py", "health_payload", "HealthReport"): (
        "unit/test_admin_payload_fixtures.py",
        "test_a_health_payload_has_the_report_keys_the_server_sends",
    ),
    ("api/admin_ops.py", "incident_payload", "Incident"): (
        "unit/api/test_admin_incidents_router.py",
        "test_a_stored_null_is_sent_as_null_and_a_dropped_title_is_left_out",
    ),
    ("api/admin_overview.py", "capacity_payload", "CapacityReport"): (
        "unit/admin/test_admin_routes.py",
        "test_tier_fields_are_omitted_unless_the_tier_was_read",
    ),
    ("api/admin_overview.py", "overview_payload", "AdminOverview"): (
        "unit/admin/test_admin_routes.py",
        "test_every_unwired_source_is_reported_unavailable_never_faked",
    ),
    ("api/admin_statecharts.py", "_detail", "StatechartMachineDetail"): (
        "unit/admin/test_statechart_detail.py",
        "test_a_kind_without_summary_keys_sends_none_and_an_unwired_timeline_says_so",
    ),
    ("api/admin_statecharts.py", "_status", "AdminSliceStatus"): (
        "unit/admin/test_statechart_inspector.py",
        "test_an_unreadable_store_adds_no_row",
    ),
    ("api/feature_flags.py", "_shown", "FeatureFlag"): (
        "unit/admin/test_flag_routes.py",
        "test_a_store_outage_lists_fail_closed_values_only",
    ),
    ("api/me.py", "get_me", "Me"): (
        "unit/api/test_me_router.py",
        "test_me_is_the_contract_shape_for_the_caller",
    ),
    ("api/order_cancel_all.py", "_result", "BulkAccountResult"): (
        "unit/api/test_order_cancel_all_route.py",
        "test_a_caller_with_no_trade_grant_naming_none_gets_200_with_no_results",
    ),
    ("api/order_cancel_all.py", "_result", "LegError"): (
        "unit/api/test_order_cancel_all_route.py",
        "test_a_retryable_account_error_says_so",
    ),
    ("api/order_cancel_all.py", "_result", "Result"): (
        "unit/api/test_order_cancel_all_route.py",
        "test_the_owners_empty_list_cancels_every_accounts_selected_orders",
    ),
    ("api/order_diagnostics.py", "_call", "ExchangeCallRecord"): (
        "unit/api/test_oms_reads_route.py",
        "test_diagnostics_serve_the_order_events_and_records_after_the_audit_row",
    ),
    ("api/profile_writes.py", "_schema", "AccountProfileInput"): (  # a request body: the 422
        "contract/test_generated_optionals_refuse_null.py",
        "test_null_is_a_value_error_at_the_member",
    ),
    ("api/user_settings_models.py", "effective", "Settings"): (
        "unit/api/test_user_settings_router.py",
        "test_get_settings_answers_the_callers_overrides_and_meta_names_them",
    ),
    ("api/users.py", "_grant_json", "AccountAccessGrant"): (  # `granted_by` is left out
        "unit/api/test_users_account_access_put.py",
        "test_a_kept_grant_whose_granter_is_gone_is_answered_without_granted_by",
    ),
    ("api/users.py", "representation", "User"): (
        "unit/api/test_user_admin_routes.py",
        "test_get_user_answers_the_user_and_an_etag",
    ),
}


def _refuses(model: type[BaseModel], seen: set[type[BaseModel]]) -> bool:
    """Whether `model`, a class it extends or a model it holds refuses `null` for a member."""
    seen.add(model)
    if any(name.endswith("__null_refused") for cls in model.__mro__ for name in vars(cls)):
        return True
    held = (m for f in model.model_fields.values() for m in _models_in(f.annotation))
    return any(_refuses(m, seen) for m in held if m not in seen)


def _built(call: ast.Call) -> str | None:
    """The generated model `call` builds: `api.X(...)` or `api.X.model_validate*(...)`."""
    func = call.func
    if isinstance(func, ast.Attribute) and func.attr in _BUILD:
        func = func.value
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        return func.attr if func.value.id == "api" else None
    return None


def _sites(node: ast.AST, where: str) -> Iterator[tuple[str, str]]:
    """(innermost function, model name) of each generated-model build under `node`."""
    for child in ast.iter_child_nodes(node):
        inner = child.name if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) else where
        if isinstance(child, ast.Call) and (name := _built(child)) is not None:
            yield where, name
        yield from _sites(child, inner)


#: Files that import a generated model by name: it only reads `model_fields`, never builds one.
_NAMED_IMPORT_OK = {"api/rules_crud.py"}
#: (module, model) -> why a bare `api.X` reference (not a call, annotation or fields read) is fine.
_BARE_REFS_OK: dict[tuple[str, str], str] = {}


def _is_refusing(name: str) -> bool:
    model = getattr(api, name, None)
    return name in RESPONSE_MODELS and isinstance(model, type) and _refuses(model, set())


def _import_violations(tree: ast.AST, rel: str) -> list[str]:
    """Imports of `openapi_models` that the `api.X(...)` scan cannot see."""
    bad: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            names = [(a.name, a.asname) for a in node.names]
            if (node.module or "").endswith("openapi_models"):
                if rel not in _NAMED_IMPORT_OK:
                    bad.append(f"{rel}:{node.lineno} imports from openapi_models")
            elif any(n == "openapi_models" and alias != "api" for n, alias in names):
                bad.append(f"{rel}:{node.lineno} aliases openapi_models other than `as api`")
        elif isinstance(node, ast.Import):
            if any(a.name.endswith("openapi_models") for a in node.names):
                bad.append(f"{rel}:{node.lineno} imports openapi_models")
    return bad


def _bare_refs(tree: ast.AST, rel: str) -> list[str]:
    """`api.X` of a refusing response model used other than as a call, annotation or fields read."""
    parents = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    bad: list[str] = []
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "api"
            and _is_refusing(node.attr)
        ):
            continue
        if (rel, node.attr) in _BARE_REFS_OK:
            continue
        parent = parents.get(node)
        if isinstance(parent, ast.Call) and parent.func is node:
            continue
        if isinstance(parent, ast.Attribute) and (
            parent.attr in _BUILD or parent.attr == "model_fields"
        ):
            continue
        child: ast.AST = node
        in_annotation = False
        while child in parents:
            up = parents[child]
            if getattr(up, "annotation", None) is child or getattr(up, "returns", None) is child:
                in_annotation = True
                break
            child = up
        if not in_annotation:
            bad.append(f"{rel}:{node.lineno} bare reference api.{node.attr}")
    return bad


def _scan() -> set[tuple[str, str, str]]:
    found: set[tuple[str, str, str]] = set()
    violations: list[str] = []
    root = _SERVICE / "candleviewer"
    for path in sorted(root.rglob("*.py")):
        if "_generated" in path.parts:
            continue
        rel = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        violations += _import_violations(tree, rel) + _bare_refs(tree, rel)
        for where, name in _sites(tree, "<module>"):
            if _is_refusing(name):
                found.add((rel, where, name))
    assert not violations, "\n".join(violations)
    return found


def test_every_response_builder_is_swept() -> None:
    """The scan finds exactly the listed builders: a new one is listed with its test first."""
    assert sorted(_scan()) == sorted(_BUILDERS)


#: Builders a test drives through the route or the model rather than by name: the text the
#: named test file must mention instead of the builder's name.
_DRIVEN_VIA = {
    "set_subaccount_tier": "/capacity/subaccount-tier",
    "get_me": '"/me"',
    "_status": "/admin/statecharts",
    "_shown": "FeatureFlag",
    "_schema": "AccountProfileInput",
    "_grant_json": "account-access",
}


def test_each_listed_builder_names_a_test_that_exists() -> None:
    for (_, builder, _model), (module, test) in _BUILDERS.items():
        tree = ast.parse((_SERVICE / "tests" / module).read_text(encoding="utf-8"))
        names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)}
        assert test in names, f"{module}::{test}"
        source = (_SERVICE / "tests" / module).read_text(encoding="utf-8")
        needle = _DRIVEN_VIA.get(builder, builder)
        assert needle in source, f"{module} never mentions {needle} ({builder})"

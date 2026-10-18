"""Synchronous arming preconditions (E35-S01).

Which mode changes are legal is NOT decided here: that is the B9 `rule_instance` chart
(`rules.lifecycle`). This module only enforces what must hold before an arm is recorded:
statecharts record, synchronous code enforces (C-2.21). Refusal
messages are user-facing prose (rendered verbatim in SCR-085, read by a screen reader).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from candleviewer.statechart.bindings.b09_rule_instance import (
    DEFAULT_MIN_SIMULATION_FIRES,
    DEFAULT_MIN_SIMULATION_HOURS,
    promotion_gate_met,
)

ORDERS_WRITE = "orders:write"
LIVE_ARM_PERMISSION = "rules:arm_live"  # ticket "rules.arm.live"; DB codes are domain:action


@dataclass(frozen=True, slots=True)
class Refusal:
    code: str
    status: int
    message: str
    #: The budget fields an Owner-only refusal names (#3232); the manager answers each one as
    #: an `errors` entry, as a save does.
    raised_limits: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ArmingFacts:
    """Everything the arming decision needs, gathered by the manager (never the client)."""

    has_valid_active_version: bool
    validation_errors: int
    open_safety_warnings: int
    simulated_on_ir_hash: bool
    simulation_fires: int
    simulation_hours: float
    environments: tuple[str, ...]
    sends_orders: bool
    has_flatten_all: bool
    perms: frozenset[str] = frozenset()
    unauthorised_accounts: tuple[str, ...] = ()
    step_up_fresh: bool = False
    flatten_all_acknowledged: bool = False
    owner_override_reason: str | None = None
    is_owner: bool = False
    #: Budget fields of the active version above their `RuleLimits` default (#3232, decision 5):
    #: arming it needs the arming actor to be the Owner, whoever saved it.
    limits_above_default: tuple[str, ...] = ()
    min_fires: int = DEFAULT_MIN_SIMULATION_FIRES
    min_hours: float = DEFAULT_MIN_SIMULATION_HOURS
    extra: dict[str, str] = field(default_factory=dict)


def check_arming(f: ArmingFacts) -> Refusal | None:
    """First failing precondition wins; order is stable so refusals are deterministic."""
    if not f.has_valid_active_version or f.validation_errors:
        return Refusal(
            "rule_invalid",
            422,
            "This rule's active version has validation errors. Fix them and save before arming.",
        )
    if f.open_safety_warnings:
        return Refusal(
            "safety_warning_open",
            422,
            "This rule has open safety warnings. Resolve them before arming.",
        )
    if not f.simulated_on_ir_hash:
        return Refusal(
            "simulation_required",
            422,
            "This rule has not completed a simulation on its current version. "
            "Run a simulation before arming.",
        )
    if not promotion_gate_met(f.simulation_fires, f.simulation_hours, f.min_fires, f.min_hours):
        if not (f.is_owner and f.owner_override_reason):
            return Refusal(
                "promotion_gate",
                422,
                f"Simulation needs {f.min_fires} fires or {f.min_hours:g} hours before arming. "
                "Only the Owner can override this, with a written reason.",
            )
    if f.limits_above_default and not f.is_owner:
        return Refusal(
            "forbidden",
            403,
            "Only the Owner can arm a rule whose action budget is above the default.",
            f.limits_above_default,
        )
    if f.sends_orders and not f.is_owner and ORDERS_WRITE not in f.perms:
        return Refusal(
            "orders_write_required",
            403,
            "You need the orders:write permission to arm a rule that places orders.",
        )
    if f.sends_orders and f.unauthorised_accounts:
        return Refusal(
            "orders_write_required",
            403,
            "You need orders:write on every account this rule trades. Missing: "
            + ", ".join(f.unauthorised_accounts)
            + ".",
        )
    if "live" in f.environments:
        if LIVE_ARM_PERMISSION not in f.perms:
            return Refusal(
                "permission_required",
                403,
                "Arming a live rule needs the rules:arm_live permission.",
            )
        if not f.step_up_fresh:
            return Refusal(
                "step_up_required", 403, "Re-enter your authenticator code to arm a live rule."
            )
    if f.has_flatten_all and not f.flatten_all_acknowledged:
        return Refusal(
            "acknowledgement_required",
            422,
            "This rule can flatten all positions. Acknowledge that before arming.",
        )
    return None

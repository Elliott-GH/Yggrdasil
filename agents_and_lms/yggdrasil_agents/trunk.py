"""Trunk layer: W_i context-decay math and air-gap privacy routing gate."""

from __future__ import annotations

import math
from typing import Literal

from pydantic import BaseModel, Field

from .local_engine import LocalEngine

RouteTarget = Literal["twigs_local", "leaves_cloud"]


class DecayParameters(BaseModel):
    """Parameters governing node context decay W_i(t) = W_0 * exp(-lambda * dt) + alpha * R_i."""

    decay_rate: float = Field(default=0.05, ge=0.0, description="Decay constant lambda (1/hr)")
    alpha: float = Field(default=0.15, ge=0.0, description="Resonance reactivation coefficient")
    prune_threshold: float = Field(default=0.10, ge=0.0, description="Weight below which node prunes")


class ContextNodeState(BaseModel):
    """State snapshot of a single Yggdrasil context node."""

    node_id: str
    label: str
    initial_weight: float = Field(default=1.0, ge=0.0)
    elapsed_hours: float = Field(default=0.0, ge=0.0)
    resonance_count: int = Field(default=0, ge=0)
    contains_personal_vault_data: bool = True
    summary: str = ""


class TrunkRoutingDecision(BaseModel):
    """Deterministic routing and vitality decision computed by TrunkRouter."""

    node_id: str
    weight: float = Field(ge=0.0)
    should_prune: bool
    route_target: RouteTarget
    air_gap_blocked: bool
    sanitized_summary: str | None = None


def compute_decay_weight(
    initial_weight: float,
    decay_rate: float,
    elapsed_hours: float,
    alpha: float,
    resonance_count: int,
) -> float:
    """Compute node priority weight W_i(t) = W_{i,0} * exp(-lambda_i * dt) + alpha * R_i."""
    if initial_weight < 0 or decay_rate < 0 or elapsed_hours < 0 or alpha < 0 or resonance_count < 0:
        raise ValueError("All decay formula inputs must be non-negative.")
    decayed_base = initial_weight * math.exp(-decay_rate * elapsed_hours)
    return decayed_base + (alpha * resonance_count)


class TrunkRouter:
    """Evaluates context vitality and enforces the air-gap gate before cloud dispatch."""

    def __init__(
        self,
        params: DecayParameters | None = None,
        engine: LocalEngine | None = None,
    ) -> None:
        self.params: DecayParameters = params or DecayParameters()
        self.engine: LocalEngine = engine or LocalEngine.get_shared()

    def evaluate_node(
        self,
        node: ContextNodeState,
        allow_cloud: bool = False,
    ) -> TrunkRoutingDecision:
        """Compute W_i weight and route strictly locally whenever personal vault taint exists."""
        weight = compute_decay_weight(
            initial_weight=node.initial_weight,
            decay_rate=self.params.decay_rate,
            elapsed_hours=node.elapsed_hours,
            alpha=self.params.alpha,
            resonance_count=node.resonance_count,
        )
        should_prune = weight < self.params.prune_threshold

        if node.contains_personal_vault_data or not allow_cloud:
            return TrunkRoutingDecision(
                node_id=node.node_id,
                weight=weight,
                should_prune=should_prune,
                route_target="twigs_local",
                air_gap_blocked=node.contains_personal_vault_data,
                sanitized_summary=None,
            )

        return TrunkRoutingDecision(
            node_id=node.node_id,
            weight=weight,
            should_prune=should_prune,
            route_target="leaves_cloud",
            air_gap_blocked=False,
            sanitized_summary=node.summary,
        )

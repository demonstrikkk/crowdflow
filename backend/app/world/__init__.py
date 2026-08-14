"""CrowdFlow world layer: unified external spatial graph + aggregate flow.

P0  unified spatial graph + venue<->external connectors
P1  OSM / Overpass ingestion + external graph normalization
P2  external demand model
P3  aggregate external world simulation (see world_sim.WorldSimulation)
P4  real rerouting (congestion-aware paths + closure reroutes)
"""
from .demand import DemandPlan, plan_demand, redistribute_gates
from .models import (
    AccessPoint,
    DemandSource,
    ExternalEdge,
    ExternalNode,
    WorldEdgeState,
    WorldGateState,
    WorldGraph,
    WorldPrediction,
    WorldProvenance,
    WorldSourceState,
    WorldState,
)
from .providers import DemoProvider, MapProvider, OSMProvider, resolve_world_graph
from .world_sim import WorldSimulation

__all__ = [
    "AccessPoint",
    "DemandPlan",
    "DemandSource",
    "DemoProvider",
    "ExternalEdge",
    "ExternalNode",
    "MapProvider",
    "OSMProvider",
    "WorldEdgeState",
    "WorldGateState",
    "WorldGraph",
    "WorldPrediction",
    "WorldProvenance",
    "WorldSimulation",
    "WorldSourceState",
    "WorldState",
    "plan_demand",
    "redistribute_gates",
    "resolve_world_graph",
]

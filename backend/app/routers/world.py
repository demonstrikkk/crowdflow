"""World layer endpoints: the unified external graph behind the live map.

The world graph is the spatial layer of the simulation — demand sources route
over external roads/footpaths to venue gates, and the venue drains back out to
outer sinks. The engine already steps it inside ``sim.world``; these endpoints
expose the static graph for rendering and the live state for status.
"""
from __future__ import annotations

import time
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, Query

from ..storage import storage
from ..world.models import WorldGraph, WorldState
from ..world.providers import resolve_world_graph

router = APIRouter()

_cache: Dict[str, WorldGraph] = {}
_last_fetch: Dict[str, float] = {}
LIVE_MIN_INTERVAL_S = 30.0


def _graph_for(venue_id: str) -> WorldGraph:
    venue = storage.get_venue(venue_id)
    if venue is None:
        raise HTTPException(status_code=404, detail=f"Venue '{venue_id}' not found")
    cached = _cache.get(venue_id)
    if cached is not None:
        return cached
    graph = resolve_world_graph(venue)
    _cache[venue_id] = graph
    return graph


@router.get("/graph", response_model=WorldGraph)
def get_world_graph(
    venue_id: str = Query(..., description="venue id to build the world graph for"),
):
    """The unified external graph for a venue (OSM when reachable, else demo)."""
    return _graph_for(venue_id)


@router.post("/refresh", response_model=WorldGraph)
def refresh_world_graph(
    venue_id: str = Query(..., description="venue id to refresh the world graph for"),
):
    """Force a live re-fetch of the world graph (OSM), falling back to demo.

    Re-fetches at most once per {LIVE_MIN_INTERVAL_S}s per venue.
    """
    venue = storage.get_venue(venue_id)
    if venue is None:
        raise HTTPException(status_code=404, detail=f"Venue '{venue_id}' not found")

    now = time.monotonic()
    last = _last_fetch.get(venue_id, 0.0)
    if now - last < LIVE_MIN_INTERVAL_S:
        return _cache.get(venue_id) or resolve_world_graph(venue)
    _last_fetch[venue_id] = now

    graph = resolve_world_graph(venue, force_live=True)
    _cache[venue_id] = graph
    return graph


@router.get("/status", response_model=WorldState)
def world_status(
    sim_id: str = Query(..., description="simulation id to read the world state from"),
):
    """Live world state (edges, gate queues, sources, predictions) for a sim."""
    from .simulation import _get_engine

    engine = _get_engine(sim_id)
    state = engine.state()
    if state.world is None:
        raise HTTPException(
            status_code=404,
            detail="This simulation has no world layer (engine built without one).",
        )
    return state.world

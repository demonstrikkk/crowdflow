"""External environment endpoints: the surrounding road network + live OSM."""
from __future__ import annotations

import time
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, Query

from ..engine.environment import (
    LIVE_MIN_INTERVAL_S,
    build_bundled_environment,
    fetch_live_environment,
    venue_location,
)
from ..models import ExternalEnvironment
from ..storage import storage

router = APIRouter()

_cache: Dict[str, ExternalEnvironment] = {}
_last_fetch: Dict[str, float] = {}


def _env_for(venue_id: str) -> ExternalEnvironment:
    venue = storage.get_venue(venue_id)
    if venue is None:
        raise HTTPException(status_code=404, detail=f"Venue '{venue_id}' not found")
    cached = _cache.get(venue_id)
    if cached is not None:
        return cached
    env = build_bundled_environment(venue)
    _cache[venue_id] = env
    return env


@router.get("", response_model=ExternalEnvironment)
def get_environment(
    venue_id: str = Query(..., description="venue id to build surroundings for"),
):
    """Surrounding road network for a venue (bundled offline data by default)."""
    return _env_for(venue_id)


@router.post("/refresh", response_model=ExternalEnvironment)
def refresh_environment(
    venue_id: str = Query(..., description="venue id to refresh surroundings for"),
):
    """Try to replace the bundled environment with live OpenStreetMap data.

    Falls back to bundled data with a note when OSM is unconfigured,
    unreachable, or returns nothing usable. Re-fetches at most once per
    {LIVE_MIN_INTERVAL_S}s per venue.
    """
    venue = storage.get_venue(venue_id)
    if venue is None:
        raise HTTPException(status_code=404, detail=f"Venue '{venue_id}' not found")

    now = time.monotonic()
    last = _last_fetch.get(venue_id, 0.0)
    if now - last < LIVE_MIN_INTERVAL_S:
        return _cache.get(venue_id) or build_bundled_environment(venue)
    _last_fetch[venue_id] = now

    env = build_bundled_environment(venue)
    loc = venue_location(venue)
    if loc is None:
        env.notes.append(
            "Live OSM requested but the venue has no lat/lon (set venue "
            "metadata.location or OSM_LAT/OSM_LON) — using bundled data."
        )
    else:
        live = fetch_live_environment(venue, loc[0], loc[1])
        if live is None:
            env.notes.append(
                "Live OSM fetch failed or returned nothing usable — using "
                "bundled data."
            )
        else:
            env = live
    _cache[venue_id] = env
    return env

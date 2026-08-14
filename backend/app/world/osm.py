"""OpenStreetMap / Overpass ingestion for the external world layer.

Only the relevant area around a venue is queried (never a whole city), with a
single bounded request and no retries — the caller (``providers.OSMProvider``)
falls back to the deterministic demo graph on any failure.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional

from ..models import WorldPosition

# Overpass endpoint(s); tried in order so one being down does not block the app.
ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

TIMEOUT_S = 12.0

# highway tag -> external edge kind
_HIGHWAY_KIND = {
    "motorway": "ROAD",
    "motorway_link": "ROAD",
    "trunk": "ROAD",
    "trunk_link": "ROAD",
    "primary": "ROAD",
    "primary_link": "ROAD",
    "secondary": "ROAD",
    "secondary_link": "ROAD",
    "tertiary": "ROAD",
    "tertiary_link": "ROAD",
    "unclassified": "ROAD",
    "residential": "ROAD",
    "service": "STREET",
    "living_street": "STREET",
    "footway": "FOOTPATH",
    "path": "FOOTPATH",
    "pedestrian": "FOOTPATH",
    "steps": "FOOTPATH",
    "bridleway": "FOOTPATH",
}

_WALK_HIGHWAYS = {
    "footway", "path", "pedestrian", "steps", "living_street", "bridleway", "service",
}

# walking speed on each kind (m/s) — conservative crowd approach speeds
_SPEED_MPS = {"ROAD": 1.3, "STREET": 1.3, "FOOTPATH": 1.2}

# heuristic pedestrian capacity (people/minute per metre of effective width);
# widths are not reliably tagged in OSM so capacities are marked "estimated".
_CAP_PER_M = 40.0


def _http_get(url: str, params: dict):
    """Thin httpx wrapper so tests can monkeypatch a single seam."""
    import httpx

    return httpx.get(url, params=params, timeout=TIMEOUT_S)


def overpass_query(
    ref_lat: float, ref_lon: float, span_m: float
) -> Optional[Dict]:
    """One bounded Overpass query for the area around the venue.

    Returns raw OSM JSON on success or None on any failure. No retries — the
    caller falls back to the demo graph.
    """
    dlat = span_m / 110540.0
    dlon = span_m / (111320.0 * math.cos(math.radians(ref_lat)))
    bbox = f"{ref_lat - dlat},{ref_lon - dlon},{ref_lat + dlat},{ref_lon + dlon}"

    query = f"""
    [out:json][timeout:{int(TIMEOUT_S)}];
    (
      way["highway"~"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|service|living_street|footway|path|pedestrian|steps)$"]({bbox});
      way["highway"="footway"]["footway"~"^(crossing|sidewalk)$"]({bbox});
      node["public_transport"~"^(station|stop_position)$"]({bbox});
      node["amenity"="parking"]({bbox});
      node["amenity"="bus_station"]({bbox});
      node["railway"="station"]({bbox});
      node["railway"="tram_stop"]({bbox});
      node["amenity"~"^(parking|bus_station)$"]({bbox});
      way["amenity"~"^(parking|bus_station)$"]({bbox});
    );
    out body;
    >;
    out skel qt;
    """

    last_error: Optional[Exception] = None
    for endpoint in ENDPOINTS:
        try:
            resp = _http_get(endpoint, {"data": query})
            resp.raise_for_status()
            data = resp.json()
            elements = data.get("elements", [])
            if any(e.get("type") == "way" for e in elements):
                return {"elements": elements, "endpoint": endpoint}
        except Exception as exc:  # noqa: BLE001 - any failure falls back
            last_error = exc
            continue
    if last_error is not None:
        import logging

        logging.getLogger("crowdflow.world.osm").warning(
            "Overpass fetch failed: %s", last_error
        )
    return None


def project(lat: float, lon: float, ref_lat: float, ref_lon: float) -> WorldPosition:
    """Equirectangular metres around the reference point (venue coord frame)."""
    m_per_deg_lat = 110540.0
    m_per_deg_lon = 111320.0 * math.cos(math.radians(ref_lat))
    return WorldPosition(
        x=round((lon - ref_lon) * m_per_deg_lon, 1),
        y=round(-(lat - ref_lat) * m_per_deg_lat, 1),
    )


def way_length_m(points: List[WorldPosition]) -> float:
    return sum(
        math.hypot(b.x - a.x, b.y - a.y) for a, b in zip(points[:-1], points[1:])
    )


def highway_kind(tags: Dict[str, str]) -> Optional[str]:
    hw = tags.get("highway", "")
    return _HIGHWAY_KIND.get(hw)


def is_walkable(kind: str, tags: Dict[str, str]) -> bool:
    hw = tags.get("highway", "")
    return kind in ("FOOTPATH", "STREET") or hw in _WALK_HIGHWAYS


def speed_for(kind: str) -> float:
    return _SPEED_MPS.get(kind, 1.2)


def capacity_estimate(length_m: float, kind: str, tags: Dict[str, str]) -> float:
    """People/minute heuristic. Never claimed to be measured — always 'estimated'."""
    width = 4.0
    if tags.get("lanes") and kind == "ROAD":
        try:
            width = max(4.0, float(tags["lanes"]) * 3.0)
        except ValueError:
            pass
    return max(60.0, round(_CAP_PER_M * width, 0))
"""Geographic-area cache for the external world layer.

Overpass must not be polled continuously. Raw OSM payloads and normalized
world graphs are cached on disk keyed by venue + provider + bbox hash, with a
configurable TTL (default 24h). Offline / expired data is reused with a note
in ``provenance`` instead of blocking the app.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any, Optional

logger = logging.getLogger("crowdflow.world.cache")

CACHE_DIR = os.getenv(
    "WORLD_CACHE_DIR",
    os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "data", "world_cache"),
)
TTL_S = int(os.getenv("WORLD_CACHE_TTL_S", str(24 * 3600)))

_cache_hits = 0
_cache_misses = 0


def _path(kind: str, venue_id: str, provider: str, bbox: dict) -> str:
    os.makedirs(CACHE_DIR, exist_ok=True)
    digest = hashlib.sha256(
        json.dumps(bbox, sort_keys=True).encode()
    ).hexdigest()[:12]
    safe = "".join(c for c in venue_id if c.isalnum())[:40] or "venue"
    return os.path.join(CACHE_DIR, f"{kind}_{safe}_{provider}_{digest}.json")


def _read(path: str) -> Optional[Any]:
    global _cache_hits, _cache_misses
    try:
        if not os.path.exists(path):
            _cache_misses += 1
            return None
        if time.time() - os.path.getmtime(path) > TTL_S:
            _cache_misses += 1
            return None
        with open(path, "r", encoding="utf-8") as fh:
            _cache_hits += 1
            return json.load(fh)
    except Exception as exc:  # noqa: BLE001 - cache must never break the app
        logger.warning("world cache read failed: %s", exc)
        return None


def _write(path: str, payload: Any) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
    except Exception as exc:  # noqa: BLE001
        logger.warning("world cache write failed: %s", exc)


def get_raw_osm(venue_id: str, provider: str, bbox: dict) -> Optional[dict]:
    return _read(_path("osm", venue_id, provider, bbox))


def put_raw_osm(venue_id: str, provider: str, bbox: dict, payload: dict) -> None:
    _write(_path("osm", venue_id, provider, bbox), payload)


def get_graph(venue_id: str, provider: str, bbox: dict) -> Optional[dict]:
    return _read(_path("graph", venue_id, provider, bbox))


def put_graph(venue_id: str, provider: str, bbox: dict, payload: dict) -> None:
    _write(_path("graph", venue_id, provider, bbox), payload)


def stats() -> dict:
    return {"hits": _cache_hits, "misses": _cache_misses, "dir": CACHE_DIR, "ttl_s": TTL_S}
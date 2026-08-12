"""SQLite persistence for venues and scenarios (brief: "Start with SQLite").

Venues and scenarios are stored as JSON documents in two tables and seeded
from `backend/data/` on first start so the demo works from a clean checkout.
Simulations stay in memory - they are short-lived runtime objects.

Venue documents are versioned::

    {"schema_version": 2, "venue": {...}, "spatial": {...}}

Legacy documents (a bare VenueModel) are still readable, so old seeds and
rows keep working.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

from .models import ScenarioModel, VenueDocument, VenueModel, VenueSpatialModel

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "crowdflow.db"


class Storage:
    def __init__(self, db_path: str = str(DEFAULT_DB)):
        self.db_path = db_path
        self._init_db()
        self._seed()

    # ------------------------------------------------------------------ #
    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS venues (id TEXT PRIMARY KEY, doc TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS scenarios (id TEXT PRIMARY KEY, doc TEXT NOT NULL)"
            )

    def _seed(self) -> None:
        if not DATA_DIR.exists():
            return
        venue_files = sorted(DATA_DIR.glob("venue_*.json"))
        scenario_files = sorted(DATA_DIR.glob("scenario_*.json"))
        with self._connect() as conn:
            for path in venue_files:
                doc = json.loads(path.read_text(encoding="utf-8"))
                vid = doc["venue"]["id"] if "venue" in doc else doc["id"]
                conn.execute(
                    "INSERT OR REPLACE INTO venues (id, doc) VALUES (?, ?)",
                    (vid, json.dumps(doc)),
                )
            for path in scenario_files:
                doc = json.loads(path.read_text(encoding="utf-8"))
                conn.execute(
                    "INSERT OR REPLACE INTO scenarios (id, doc) VALUES (?, ?)",
                    (doc["id"], json.dumps(doc)),
                )

    # ------------------------------------------------------------------ #
    #  Venues
    # ------------------------------------------------------------------ #
    @staticmethod
    def _unwrap_doc(raw: dict) -> dict:
        """Return the VenueModel payload whether the doc is v1 or v2."""
        return raw["venue"] if "venue" in raw else raw

    def list_venues(self) -> List[VenueModel]:
        with self._connect() as conn:
            rows = conn.execute("SELECT doc FROM venues ORDER BY id").fetchall()
        return [VenueModel.model_validate(self._unwrap_doc(json.loads(r["doc"]))) for r in rows]

    def get_venue(self, venue_id: str) -> Optional[VenueModel]:
        doc = self._raw_venue_doc(venue_id)
        if doc is None:
            return None
        return VenueModel.model_validate(self._unwrap_doc(doc))

    def _raw_venue_doc(self, venue_id: str) -> Optional[dict]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT doc FROM venues WHERE id = ?", (venue_id,)
            ).fetchone()
        return json.loads(row["doc"]) if row else None

    def get_venue_document(self, venue_id: str) -> Optional[VenueDocument]:
        """Return the full versioned venue document (venue + spatial), if any."""
        raw = self._raw_venue_doc(venue_id)
        if raw is None:
            return None
        if "venue" in raw:
            return VenueDocument.model_validate(raw)
        return VenueDocument(
            schema_version=1,
            venue=VenueModel.model_validate(raw),
            spatial=None,
        )

    def save_venue(self, venue: VenueModel) -> VenueModel:
        """Persist a VenueModel, preserving any existing spatial model."""
        existing = self._raw_venue_doc(venue.id)
        spatial = None
        if existing and "venue" in existing and existing.get("spatial"):
            spatial = VenueSpatialModel.model_validate(existing["spatial"])
        self.save_venue_document(venue, spatial)
        return venue

    def save_venue_document(
        self,
        venue: VenueModel,
        spatial: Optional[VenueSpatialModel] = None,
        canonical2d: Optional[Canonical2DModel] = None,
        architectural_scene: Optional[ArchitecturalScene] = None,
        report: Optional[ReconstructionReport] = None,
        reconstruction_version: Optional[str] = None,
    ) -> VenueDocument:
        """Persist a versioned venue document and return it."""
        if spatial is not None and spatial.venue_id != venue.id:
            spatial.venue_id = venue.id
        doc = VenueDocument(
            schema_version=2,
            venue=venue,
            spatial=spatial,
            canonical2d=canonical2d,
            architectural_scene=architectural_scene,
            report=report,
            reconstruction_version=reconstruction_version,
        )
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO venues (id, doc) VALUES (?, ?)",
                (venue.id, doc.model_dump_json()),
            )
        return doc

    def delete_venue(self, venue_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM venues WHERE id = ?", (venue_id,))
        return cur.rowcount > 0

    # ------------------------------------------------------------------ #
    #  Scenarios
    # ------------------------------------------------------------------ #
    def list_scenarios(self) -> List[ScenarioModel]:
        with self._connect() as conn:
            rows = conn.execute("SELECT doc FROM scenarios ORDER BY id").fetchall()
        return [ScenarioModel.model_validate(json.loads(r["doc"])) for r in rows]

    def get_scenario(self, scenario_id: str) -> Optional[ScenarioModel]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT doc FROM scenarios WHERE id = ?", (scenario_id,)
            ).fetchone()
        return ScenarioModel.model_validate(json.loads(row["doc"])) if row else None

    def save_scenario(self, scenario: ScenarioModel) -> ScenarioModel:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO scenarios (id, doc) VALUES (?, ?)",
                (scenario.id, scenario.model_dump_json()),
            )
        return scenario

    def delete_scenario(self, scenario_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM scenarios WHERE id = ?", (scenario_id,))
        return cur.rowcount > 0


storage = Storage()

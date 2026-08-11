"""SQLite persistence for venues and scenarios (brief: "Start with SQLite").

Venues and scenarios are stored as JSON documents in two tables and seeded
from `backend/data/` on first start so the demo works from a clean checkout.
Simulations stay in memory - they are short-lived runtime objects.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

from .models import ScenarioModel, VenueModel

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
                conn.execute(
                    "INSERT OR REPLACE INTO venues (id, doc) VALUES (?, ?)",
                    (doc["id"], json.dumps(doc)),
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
    def list_venues(self) -> List[VenueModel]:
        with self._connect() as conn:
            rows = conn.execute("SELECT doc FROM venues ORDER BY id").fetchall()
        return [VenueModel.model_validate(json.loads(r["doc"])) for r in rows]

    def get_venue(self, venue_id: str) -> Optional[VenueModel]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT doc FROM venues WHERE id = ?", (venue_id,)
            ).fetchone()
        return VenueModel.model_validate(json.loads(row["doc"])) if row else None

    def save_venue(self, venue: VenueModel) -> VenueModel:
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO venues (id, doc) VALUES (?, ?)",
                (venue.id, venue.model_dump_json()),
            )
        return venue

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

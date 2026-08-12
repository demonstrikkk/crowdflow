"""Reconstruction validation and quality gate (Phase 10)."""
from __future__ import annotations
from typing import List, Tuple
from ...models import VenueSpatialModel
from .profile import StadiumProfile


class ValidationResult:
    def __init__(self):
        self.passed = True
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def fail(self, msg: str):
        self.passed = False
        self.errors.append(msg)

    def warn(self, msg: str):
        self.warnings.append(msg)


def validate_profile(profile: StadiumProfile) -> ValidationResult:
    """Validate a StadiumProfile before building."""
    result = ValidationResult()
    if not profile.footprint_polygon or len(profile.footprint_polygon) < 3:
        result.fail("footprint_polygon must have at least 3 points")
    if not profile.field_polygon and not profile.field_center:
        result.warn("No field detected – procedural field placeholder will be used")
    if not profile.seating_bowls:
        result.warn("No seating bowls detected")
    if not profile.gates:
        result.warn("No gates detected – venue will have no entry points")
    return result


def validate_spatial(spatial: VenueSpatialModel, profile: StadiumProfile) -> ValidationResult:
    """Post-build structural consistency checks."""
    result = ValidationResult()
    level_ids = {lv.id for lv in spatial.levels}

    for struct in spatial.structures:
        if struct.level_id not in level_ids:
            result.fail(f"Structure {struct.id} references unknown level {struct.level_id}")

    for opening in spatial.openings:
        if opening.level_id not in level_ids:
            result.fail(f"Opening {opening.id} references unknown level {opening.level_id}")

    for path in spatial.paths:
        if path.level_id not in level_ids:
            result.fail(f"Path {path.id} references unknown level {path.level_id}")

    if not any(s.type == "FIELD" for s in spatial.structures):
        result.warn("No FIELD structure in spatial model")

    if not spatial.openings:
        result.warn("No openings (gates) in spatial model")

    return result


def check_architectural_consistency(spatial: VenueSpatialModel) -> List[str]:
    """Run spec rule checks (section 112) and return a list of violations."""
    violations = []
    level_ids = {lv.id for lv in spatial.levels}
    has_field = any(s.type == "FIELD" for s in spatial.structures)
    has_seating = any(s.type == "SEATING" for s in spatial.structures)
    has_concourse = any(s.type == "CONCOURSE" for s in spatial.structures)
    has_emergency = any(o.type == "EMERGENCY_EXIT" for o in spatial.openings)

    if has_seating and not has_field:
        violations.append("Seating present without a field")
    if has_seating and not has_concourse:
        violations.append("Seating present but no concourse circulation")
    if len(spatial.levels) > 1 and not any(
        s.type == "STAIR" for s in spatial.structures
    ):
        violations.append("Multiple levels but no vertical connections (stairs/ramps)")
    return violations

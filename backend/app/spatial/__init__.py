"""Spatial / architectural layer for CrowdFlow.

VenueSpatialModel is the physical-spatial counterpart of VenueModel. This
package owns coordinate conversion (blueprint pixels <-> venue metres) and the
derivation of a spatial model from a legacy navigation-only venue.
"""
from .legacy import derive_spatial_from_venue  # noqa: F401

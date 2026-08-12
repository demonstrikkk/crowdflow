from fastapi import APIRouter, HTTPException, Response, status
from typing import List

from ..models import (
    VenueDigitalTwin,
    VenueModel,
    VenueSpatialModel,
    digital_twin_to_document,
    document_to_digital_twin,
    validate_digital_twin,
)
from ..spatial import derive_spatial_from_venue
from ..storage import storage

router = APIRouter()


@router.get("/", response_model=List[VenueModel])
def get_venues():
    return storage.list_venues()


@router.get("/{venue_id}", response_model=VenueModel)
def get_venue(venue_id: str):
    venue = storage.get_venue(venue_id)
    if venue is None:
        raise HTTPException(status_code=404, detail="Venue not found")
    return venue


@router.post("/", response_model=VenueModel, status_code=status.HTTP_201_CREATED)
def create_venue(venue: VenueModel):
    if storage.get_venue(venue.id) is not None:
        raise HTTPException(status_code=409, detail=f"Venue '{venue.id}' already exists")
    return storage.save_venue(venue)


@router.put("/{venue_id}", response_model=VenueModel)
def update_venue(venue_id: str, venue: VenueModel):
    if storage.get_venue(venue_id) is None:
        raise HTTPException(status_code=404, detail="Venue not found")
    venue.id = venue_id
    return storage.save_venue(venue)


@router.delete("/{venue_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_venue(venue_id: str):
    if not storage.delete_venue(venue_id):
        raise HTTPException(status_code=404, detail="Venue not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
#  Spatial (architectural) model
# --------------------------------------------------------------------------- #
@router.get("/{venue_id}/spatial", response_model=VenueSpatialModel)
def get_venue_spatial(venue_id: str):
    """Return the venue's VenueSpatialModel, or derive one on demand."""
    doc = storage.get_venue_document(venue_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Venue not found")
    if doc.spatial is not None:
        return doc.spatial
    spatial = derive_spatial_from_venue(doc.venue)
    storage.save_venue_document(doc.venue, spatial)
    return spatial


@router.put("/{venue_id}/spatial", response_model=VenueSpatialModel)
def save_venue_spatial(venue_id: str, spatial: VenueSpatialModel):
    """Replace the venue's spatial model."""
    venue = storage.get_venue(venue_id)
    if venue is None:
        raise HTTPException(status_code=404, detail="Venue not found")
    spatial.venue_id = venue_id
    storage.save_venue_document(venue, spatial)
    return spatial


@router.post("/{venue_id}/spatial/generate", response_model=VenueSpatialModel)
def generate_venue_spatial(venue_id: str):
    """Derive a spatial model from the navigation-only VenueModel."""
    venue = storage.get_venue(venue_id)
    if venue is None:
        raise HTTPException(status_code=404, detail="Venue not found")
    spatial = derive_spatial_from_venue(venue)
    storage.save_venue_document(venue, spatial)
    return spatial


# --------------------------------------------------------------------------- #
#  Digital twin (canonical semantic model + navigation graph + validation)
# --------------------------------------------------------------------------- #
@router.get("/{venue_id}/twin", response_model=VenueDigitalTwin)
def get_venue_twin(venue_id: str):
    """Return the canonical, validated digital twin of a venue.

    The twin is a pure projection of the persisted VenueDocument: its geometry,
    navigation graph and validation report are derived deterministically and the
    model itself never depends on a renderer.
    """
    doc = storage.get_venue_document(venue_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Venue not found")
    return document_to_digital_twin(doc)


@router.put("/{venue_id}/twin", response_model=VenueDigitalTwin)
def save_venue_twin(venue_id: str, twin: VenueDigitalTwin):
    """Persist an edited digital twin.

    The twin is converted back into a VenueDocument, the navigation graph is
    regenerated from the edited geometry, then the canonical twin (with fresh
    validation) is returned so the UI can re-render and re-validate in one round
    trip. The semantic model remains the single source of truth.
    """
    if storage.get_venue_document(venue_id) is None:
        raise HTTPException(status_code=404, detail="Venue not found")

    twin.venue_id = venue_id
    doc = digital_twin_to_document(twin)
    storage.save_venue_document(doc.venue, doc.spatial)

    final = document_to_digital_twin(doc)
    final.validation = validate_digital_twin(final)
    return final

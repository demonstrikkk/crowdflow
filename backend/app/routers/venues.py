from fastapi import APIRouter, HTTPException, Response, status
from typing import List

from ..models import VenueModel
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

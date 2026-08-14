import type { VenueModel } from './types';

// --------------------------------------------------------------------------- //
//  Geographic projection for the map workspace.
//
//  The backend venue + environment live in a local meter coordinate system
//  (x 0..venue.width, y 0..venue.height; environment extends beyond via bbox).
//  Leaflet needs lat/lng. We anchor the venue centre to a real-world
//  latitude/longitude and scale meters to degrees (approx. at the anchor
//  latitude), so the stadium + surrounding road network render on real tiles.
// --------------------------------------------------------------------------- //

export interface GeoAnchor {
  lat: number;
  lng: number;
  name: string;
}

export const DEFAULT_ANCHOR: GeoAnchor = {
  lat: 51.5386,
  lng: -0.0166,
  name: 'London Stadium, Queen Elizabeth Olympic Park',
};

// meters → degrees (good enough for a few-km extent at these latitudes)
const DEG_PER_M_LAT = 1 / 111_320;
function degPerMlng(lat: number): number {
  return 1 / (111_320 * Math.cos((lat * Math.PI) / 180));
}

export class GeoProjector {
  private anchor: GeoAnchor;
  private originLat: number;
  private originLng: number;

  constructor(anchor: GeoAnchor, venue: { width: number; height: number }) {
    this.anchor = anchor;
    // The anchor is the venue centre (venue.width/2, venue.height/2) in local
    // space (x grows east, y grows "down" = south on the map).
    const cx = venue.width / 2;
    const cy = venue.height / 2;
    const kLat = DEG_PER_M_LAT;
    const kLng = degPerMlng(anchor.lat);
    // Back out the local-space origin's lat/lng.
    this.originLat = anchor.lat + cy * kLat;
    this.originLng = anchor.lng - cx * kLng;
  }

  /** local venue (x, y) → Leaflet [lat, lng]. x east, y south. */
  toLatLng(x: number, y: number): [number, number] {
    const kLat = DEG_PER_M_LAT;
    const kLng = degPerMlng(this.anchor.lat);
    return [this.originLat - y * kLat, this.originLng + x * kLng];
  }

  venueCenter(): [number, number] {
    return [this.anchor.lat, this.anchor.lng];
  }

  /** metres per degree of longitude at the anchor (for circle radius sizing). */
  metersToDegLat(m: number): number {
    return m * DEG_PER_M_LAT;
  }

  metersToDegLng(m: number): number {
    return m * degPerMlng(this.anchor.lat);
  }
}

export function venueGeoFootprint(
  projector: GeoProjector,
  venue: { width: number; height: number },
): [number, number][] {
  return [
    projector.toLatLng(0, 0),
    projector.toLatLng(venue.width, 0),
    projector.toLatLng(venue.width, venue.height),
    projector.toLatLng(0, venue.height),
  ];
}

// convenience for environment bbox extent (roads can be far outside venue)
export function envBoundsExtent(
  projector: GeoProjector,
  bbox: { min_x: number; min_y: number; max_x: number; max_y: number },
): [number, number][] {
  return [
    projector.toLatLng(bbox.min_x, bbox.min_y),
    projector.toLatLng(bbox.max_x, bbox.min_y),
    projector.toLatLng(bbox.max_x, bbox.max_y),
    projector.toLatLng(bbox.min_x, bbox.max_y),
  ];
}

export const STADIUM_LABEL_FN = (v: VenueModel) => v.name.replace(/\?/g, '–');
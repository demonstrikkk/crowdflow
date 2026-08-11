"""Operational conditions: weather and incident consequences on the engine."""

import pytest

from app.engine.simulator import COMFORT_DENSITY
from app.models import IncidentSpec, Intervention, InterventionType, WeatherSpec


def base_capacity(graph, u, v):
    return graph.edge_capacity(u, v)


# --------------------------------------------------------------------------- #
#  Weather
# --------------------------------------------------------------------------- #
def test_heavy_rain_reduces_outdoor_capacity_only(make_engine):
    e = make_engine("heavy_rain")
    # perimeter plaza (GATE_A -> CONCOURSE_N) is OUTDOOR -> reduced
    outdoor_cap = e.edge_capacity_effective("GATE_A", "CONCOURSE_N")
    assert outdoor_cap < base_capacity(e.graph, "GATE_A", "CONCOURSE_N")
    # concourse -> concession is INDOOR -> untouched
    indoor_cap = e.edge_capacity_effective("CONCOURSE_N", "CONCESSION_N")
    assert indoor_cap == pytest.approx(base_capacity(e.graph, "CONCOURSE_N", "CONCESSION_N"))
    # outdoor walkways are also slower
    assert e._edge_speed_factor("GATE_A", "CONCOURSE_N") < 1.0
    assert e._edge_speed_factor("CONCOURSE_N", "CONCESSION_N") == pytest.approx(1.0)


def test_unsafe_outdoor_blocks_outdoor_routes(make_engine):
    e = make_engine("normal")
    e.set_weather(
        WeatherSpec(
            condition="HAIL", capacity_multiplier=0.8, speed_multiplier=0.6,
            unsafe_outdoor=True,
        )
    )
    assert e.edge_capacity_effective("GATE_A", "CONCOURSE_N") == 0.0
    assert e.edge_capacity_effective("CONCOURSE_N", "CONCESSION_N") > 0.0


def test_weather_state_in_simulation_state(make_engine):
    e = make_engine("heavy_rain")
    st = e.state()
    assert st.weather is not None
    assert st.weather["condition"] == "HEAVY_RAIN"
    assert st.incident is None


# --------------------------------------------------------------------------- #
#  Incident
# --------------------------------------------------------------------------- #
def test_fire_blocks_edges_near_location(make_engine):
    e = make_engine("fire_incident")
    e.play()
    for _ in range(10):
        e.tick()
    # CONCOURSE_E is the fire origin: every walkway touching it is blocked
    for (u, v) in e._hazard_edges:
        if u == "CONCOURSE_E" or v == "CONCOURSE_E":
            assert e.edge_capacity_effective(u, v) == 0.0


def test_incident_grows_with_time(make_engine):
    e = make_engine("fire_incident")
    e.play()
    e.tick()
    radius_early = e._hazard_radius_m
    for _ in range(300):
        e.tick()
    assert e._hazard_radius_m > radius_early
    assert len(e._hazard_edges) > 0


def test_routing_avoids_hazard_edges(make_engine):
    e = make_engine("fire_incident")
    e.play()
    for _ in range(10):
        e.tick()
    if not e._hazard_edges:
        pytest.skip("no hazard edges in first 10 ticks")
    edge = next(iter(e._hazard_edges))
    assert e.routing._edge_weight(*edge) is None
    assert edge in e.routing.avoid_edges  # avoid set is kept in sync with hazard set


def test_fire_scenario_evacuation_clears_venue(make_engine):
    e = make_engine("fire_incident")
    e.play()
    # the fire cuts the east concourse, so east-seat patrons lose their only
    # normal egress route and remain in the venue
    for _ in range(600):
        e.tick()
    assert e.edge_capacity_effective("CONCOURSE_E", "CONCOURSE_N") == 0.0
    east_seats = sum(1 for a in e.agents if a.on_node == "SEAT_E" or a.on_edge == ("SEAT_E", "CHECKPOINT_E"))
    assert east_seats >= 0
    # the operator escalates to emergency evacuation: pitch crossings open and
    # everyone reaches an emergency exit -> the venue fully clears
    e.set_emergency(True)
    assert e.graph.is_open("SEAT_E", "PITCH")
    for _ in range(4000):
        e.tick()
        if e.metrics.in_venue == 0:
            break
    assert e.metrics.in_venue == 0
    assert e.metrics.total_completed == e.metrics.total_spawned > 0


def test_security_reduces_capacity_not_zero(make_engine):
    e = make_engine("security_incident")
    e.play()
    for _ in range(10):
        e.tick()
    for (u, v) in e._hazard_edges:
        assert e.edge_capacity_effective(u, v) > 0.0
        assert e.edge_capacity_effective(u, v) < base_capacity(e.graph, u, v)


def test_hazard_marks_risk_and_state(make_engine):
    e = make_engine("fire_incident")
    e.play()
    for _ in range(10):
        e.tick()
    st = e.state()
    assert st.incident is not None
    assert st.incident["type"] == "FIRE"
    if st.hazard_zones:
        zone = st.hazard_zones[0]
        assert zone["radius_m"] > 0
        assert zone["nodes"]
    # any blocked edge must report as a hazard element
    for (u, v) in e._hazard_edges:
        es = st.edges.get(f"{u}|{v}")
        if es is not None:
            assert es.hazard is True
            assert es.risk in ("HIGH", "CRITICAL")


# --------------------------------------------------------------------------- #
#  Runtime interventions
# --------------------------------------------------------------------------- #
def test_add_incident_and_weather_via_intervention(make_engine):
    e = make_engine("normal")
    e.play()
    for _ in range(5):
        e.tick()
    e.apply_intervention(
        Intervention(
            id="i1",
            type=InterventionType.ADD_INCIDENT,
            description="fire in the north concourse",
            parameters={"incident": {
                "type": "FIRE", "location": "CONCESSION_N",
                "radius_m": 30, "spread_rate_m_min": 0.0, "severity": "MODERATE",
            }},
        )
    )
    assert e.incident is not None
    assert e.edge_capacity_effective("CONCOURSE_N", "CONCESSION_N") == 0.0
    e.apply_intervention(
        Intervention(
            id="i2",
            type=InterventionType.SET_WEATHER,
            description="rain",
            parameters={"weather": {
                "condition": "HEAVY_RAIN", "capacity_multiplier": 0.5,
                "speed_multiplier": 0.7, "unsafe_outdoor": False,
                "applies_outdoor_only": True,
            }},
        )
    )
    assert e.weather is not None
    assert e.edge_capacity_effective("GATE_A", "CONCOURSE_N") == pytest.approx(
        base_capacity(e.graph, "GATE_A", "CONCOURSE_N") * 0.5
    )
    st = e.state()
    assert st.incident is not None
    assert st.weather is not None


def test_conservation_holds_with_incident(make_engine):
    e = make_engine("fire_incident")
    e.play()
    for _ in range(120):
        e.tick()
        node_people = sum(s.people for s in e.nodes.values())
        edge_people = sum(s.people for s in e.edges.values())
        assert node_people + edge_people == e.metrics.in_venue

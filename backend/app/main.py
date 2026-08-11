from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import ai, blueprint, environment, scenarios, simulation, venues, vision
from .storage import storage

app = FastAPI(
    title="CrowdFlow Optimiser API",
    description=(
        "Predictive crowd safety & flow optimisation: simulate crowds on a venue "
        "graph, forecast bottlenecks, recommend rerouting interventions and run "
        "counterfactual comparisons - with optional Hugging Face crowd sensing."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(venues.router, prefix="/api/venues", tags=["venues"])
app.include_router(scenarios.router, prefix="/api/scenarios", tags=["scenarios"])
app.include_router(simulation.router, prefix="/api/simulation", tags=["simulation"])
app.include_router(vision.router, prefix="/api", tags=["vision"])
app.include_router(environment.router, prefix="/api/environment", tags=["environment"])
app.include_router(ai.router, tags=["ai"])
app.include_router(blueprint.router, prefix="/api/blueprint", tags=["blueprint"])


@app.get("/", tags=["system"])
def root():
    return {
        "status": "operational",
        "system": "CROWD_FLOW_OPTIMISER",
        "docs": "/docs",
    }


@app.get("/api/health", tags=["system"])
def health():
    venues = storage.list_venues()
    scenarios = storage.list_scenarios()
    from .ai.factory import provider_status

    ai = provider_status()
    return {
        "status": "ok",
        "venues_loaded": len(venues),
        "scenarios_loaded": len(scenarios),
        "hf_model": "configured via HF_API_TOKEN" if __import__("os").getenv("HF_API_TOKEN") else "not configured (crowd sensing disabled)",
        "ai_provider": ai.get("provider"),
        "ai_model": ai.get("model"),
        "ai_configured": ai.get("configured", False),
    }


@app.get("/api/venue", tags=["system"])
def default_venue():
    """Default demo venue (used by the ready-to-paste contract)."""
    venue = storage.get_venue("unity_arena")
    if venue is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="No default venue seeded")
    return venue

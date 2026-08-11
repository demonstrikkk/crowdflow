from fastapi import APIRouter, HTTPException, Response, status
from typing import List

from ..models import ScenarioModel
from ..storage import storage

router = APIRouter()


@router.get("/", response_model=List[ScenarioModel])
def get_scenarios():
    return storage.list_scenarios()


@router.get("/{scenario_id}", response_model=ScenarioModel)
def get_scenario(scenario_id: str):
    scenario = storage.get_scenario(scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    return scenario


@router.post("/", response_model=ScenarioModel, status_code=status.HTTP_201_CREATED)
def create_scenario(scenario: ScenarioModel):
    if storage.get_scenario(scenario.id) is not None:
        raise HTTPException(status_code=409, detail=f"Scenario '{scenario.id}' already exists")
    return storage.save_scenario(scenario)


@router.put("/{scenario_id}", response_model=ScenarioModel)
def update_scenario(scenario_id: str, scenario: ScenarioModel):
    if storage.get_scenario(scenario_id) is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    scenario.id = scenario_id
    return storage.save_scenario(scenario)


@router.delete("/{scenario_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_scenario(scenario_id: str):
    if storage.get_scenario(scenario_id) is None:
        raise HTTPException(status_code=404, detail="Scenario not found")
    storage.delete_scenario(scenario_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

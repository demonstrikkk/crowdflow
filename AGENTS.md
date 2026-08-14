# CrowdFlow Working Rules

## Definition of Done

Never claim that a product capability is implemented merely because:
- a backend function exists
- an API endpoint exists
- a component exists
- a state field exists
- a simulation method exists
- a test passes
- an AI service exists
- a route exists
- code imports successfully

A capability is ONLY considered implemented when the COMPLETE USER-FACING PATH works.

For every major feature, verify:

1. USER TRIGGER
2. FRONTEND ACTION
3. API / STATE TRANSITION
4. BACKEND LOGIC
5. REAL RESULT
6. RESULT RETURNED TO FRONTEND
7. UI STATE UPDATED
8. VISIBLE RESULT
9. USER CAN UNDERSTAND THE RESULT

Chain:

```
USER → UI → API / EVENT → BACKEND → REAL COMPUTATION → STATE UPDATE → STREAM / RESPONSE → FRONTEND STATE → RENDERER → USER
```

If any link is missing, the feature is NOT DONE.

Do not report "implemented" when only the backend or code path exists.

### CrowdFlow-specific gates

- **DYNAMIC REROUTING** is not done until I can visibly trigger congestion and observe agents/groups actually changing routes.
- **WHAT-IF** is not done until I can trigger an intervention and visually observe a genuine counterfactual simulation.
- **AI** is not done until the UI sends a real user request/context to the AI, the AI produces structured output based on actual CrowdFlow state, and the resulting recommendation can be executed against the simulation.
- **PREDICTION** is not done until the UI shows a future state derived from actual simulation state.
- **OPTIMIZATION** is not done until candidate interventions are actually simulated and compared.
- **DIGITAL TWIN** is not done merely because Three.js renders geometry. It must represent the operational venue and visibly connect to the simulation.
- **CROWD SIMULATION** is not done merely because agents exist. They must visibly move, respond to the environment, and respond to interventions.

Whenever I claim a feature is complete, I provide the exact USER ACTION that triggers it and the exact VISIBLE RESULT that proves it.

If I cannot demonstrate the result through the running application, I classify it as:
**PARTIAL / BACKEND-ONLY / NOT INTEGRATED**.

Never call it complete.

## Proving features (not reporting them)

Do not answer "what features exist" by listing code. DEMONSTRATE the P0 user journey from a fresh application launch:

1. Start the event.
2. Show the living digital twin.
3. Show crowd movement.
4. Create/observe congestion.
5. Show prediction.
6. Select bottleneck.
7. Ask AI why.
8. Ask AI for intervention.
9. Run actual What-If.
10. Compare baseline vs counterfactual.
11. Apply the intervention.
12. Observe actual crowd rerouting.
13. Show improved flow.

For every step, identify: exact UI action, exact backend/API/event involved, exact state change, exact visible result.

If a step cannot be demonstrated from the running UI, it is NOT complete. Find the first broken link in the user-facing chain and fix it.

## Visual verification

`docs/visual-verification.md` defines the capture → review → fix loop. The Builder (text-only) must not claim visual verification; only the `crowdflow-visual-reviewer` (vision model) issues visual verdicts.
